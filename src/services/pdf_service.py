# src/services/pdf_service.py
"""
PDF Service - Generate PDF documents
"""
import os
from typing import Optional, Dict, Any, List
from datetime import datetime, date, timedelta
from flask import current_app

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    print("ReportLab not installed. PDF generation will be limited.")

from src.utils.timezone import get_current_time, get_current_date, format_pkt_time
from src.utils.logging import get_logger

logger = get_logger(__name__)


def find_wkhtmltopdf() -> Optional[str]:
    """The wkhtmltopdf binary, whether or not it is on PATH.

    It is the renderer for both documents - it draws the HTML templates,
    which is where the layout and the branding live. Without it the code
    falls back to ReportLab, which produces a correct but plain document, so
    a PATH that happens not to include it silently downgrades every invoice
    and certificate the CRM issues.

    The Windows installer does not add itself to PATH, so PATH alone is not a
    reliable test. WKHTMLTOPDF_PATH in config wins, then PATH, then the
    standard install locations.
    """
    import shutil

    configured = current_app.config.get('WKHTMLTOPDF_PATH')
    if configured and os.path.exists(configured):
        return configured

    on_path = shutil.which('wkhtmltopdf')
    if on_path:
        return on_path

    for candidate in (
        os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'),
                     'wkhtmltopdf', 'bin', 'wkhtmltopdf.exe'),
        os.path.join(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
                     'wkhtmltopdf', 'bin', 'wkhtmltopdf.exe'),
        '/usr/local/bin/wkhtmltopdf',
        '/usr/bin/wkhtmltopdf',
    ):
        if os.path.exists(candidate):
            return candidate

    logger.warning('wkhtmltopdf not found - documents will render via the '
                   'plain ReportLab fallback')
    return None


def _brand_mark() -> Optional[str]:
    """Absolute path to the logo the documents should print.

    `logo.png` is the trimmed, transparent mark. The PDFs used to load
    `logo.jpeg`, which is a 1024x1024 square with a white plate baked into it -
    on a document that is why the mark sat in a visible white box, off-centre
    from the text beside it. The JPEG stays as a fallback only.
    """
    static_folder = current_app.static_folder or ''
    for name in ('logo.png', 'logo.jpeg'):
        candidate = os.path.join(static_folder, 'images', name)
        if os.path.exists(candidate):
            return candidate
    return None


def _brand_mark_size(path: str, width: float) -> tuple:
    """(width, height) for the mark at a given width, keeping its proportions.

    ReportLab takes both dimensions and will happily distort an image to fit
    them; the fixed 140x40 the invoice asked for squashed a 590x471 mark to a
    third of its height. Read the real ratio and derive the height from it.
    """
    try:
        from reportlab.lib.utils import ImageReader
        source_w, source_h = ImageReader(path).getSize()
        if source_w:
            return width, width * (source_h / source_w)
    except Exception as err:                          # noqa: BLE001
        logger.warning(f'Could not measure the brand mark: {err}')
    return width, width * 0.8


class PDFService:
    """Service for generating PDF documents"""
    
    def __init__(self):
        upload_setting = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        if not os.path.isabs(upload_setting):
            # Resolve relative upload folder relative to project root
            project_root = os.path.abspath(os.path.join(current_app.root_path, '..'))
            self.upload_folder = os.path.abspath(os.path.join(project_root, upload_setting))
        else:
            self.upload_folder = os.path.abspath(upload_setting)
            
        self.pdf_folder = os.path.join(self.upload_folder, 'pdf')
        os.makedirs(self.pdf_folder, exist_ok=True)

        self.certificate_folder = os.path.join(self.upload_folder, 'certificates')
        os.makedirs(self.certificate_folder, exist_ok=True)
    
    def generate_invoice_pdf(self, invoice_id: int) -> Optional[str]:
        """
        Generate fuel reimbursement invoice PDF with logo and proper formatting
        """
        try:
            from flask import render_template
            from src.models.technician import FuelReimbursementInvoice, TechnicianTrip
            from src.services.technician_service import PetrolRateService
            
            invoice = FuelReimbursementInvoice.query.get(invoice_id)
            if not invoice:
                logger.error(f"Invoice {invoice_id} not found")
                return None
            
            tech = invoice.technician
            if not tech:
                logger.error(f"Technician not found for invoice {invoice_id}")
                return None
            
            # Get trips
            trips = TechnicianTrip.query.filter(
                TechnicianTrip.technician_id == tech.id,
                TechnicianTrip.start_time >= invoice.start_date,
                TechnicianTrip.start_time <= invoice.end_date + timedelta(days=1),
                TechnicianTrip.status == 'COMPLETED'
            ).order_by(TechnicianTrip.start_time).all()
            
            # Get bike efficiency
            bike = tech.bike_assignment
            efficiency = bike.fuel_efficiency if bike and bike.fuel_efficiency > 0 else 35.0
            petrol_rate = PetrolRateService.get_current_rate()
            
            # Helper for float conversion
            def safe_float(val):
                if not val:
                    return 0.0
                try:
                    clean = ''.join(c for c in str(val) if c.isdigit() or c == '.')
                    return float(clean) if clean else 0.0
                except Exception:
                    return 0.0

            items = []
            total_dist = 0.0
            total_fuel = 0.0
            total_cost = 0.0
            total_customer = 0.0
            
            for i, trip in enumerate(trips, 1):
                po = trip.purchase_order
                dist = trip.distance_km or 0.0
                fuel_used = round(dist / efficiency, 2) if dist > 0 else 0.0
                rate = trip.petrol_rate_at_time or petrol_rate
                cost = round(fuel_used * rate, 2) if dist > 0 else 0.0
                customer = safe_float(po.fuel) if po else 0.0
                date_str = trip.start_time.strftime('%d/%m/%Y') if trip.start_time else '-'
                
                from_loc = trip.start_address or (f"Site {chr(64 + i)}" if i > 1 else "Home Base")
                to_loc = trip.end_address or (po.vehicle_availability_location if po and po.vehicle_availability_location else po.city if po and po.city else f"Site {chr(64 + i)}")

                
                items.append({
                    'num': i,
                    'date': date_str,
                    'from_loc': from_loc,
                    'to_loc': to_loc,
                    'dist': dist,
                    'fuel': fuel_used,
                    'cost': cost,
                    'customer': customer
                })
                
                total_dist += dist
                total_fuel += fuel_used
                total_cost += cost
                total_customer += customer
            
            # Non-fuel items claimed on this invoice - mobile top-offs,
            # relays, sundries. Added after the fuel side is floored at zero
            # so a customer's over-provision of fuel cannot swallow them.
            expenses = list(invoice.expenses or [])
            total_expenses = round(sum(e.amount or 0.0 for e in expenses), 2)
            fuel_payable = max(0.0, total_cost - total_customer)
            net_payable = round(fuel_payable + total_expenses, 2)
            filepath = os.path.abspath(os.path.join(self.pdf_folder, f"invoice_{invoice.id}.pdf"))
            
            logo_url = _brand_mark()

            # Try HTML -> wkhtmltopdf (pdfkit) rendering
            rendered_html = render_template(
                'pdf/fuel_invoice.html',
                invoice=invoice,
                tech=tech,
                bike=bike,
                efficiency=efficiency,
                items=items,
                total_dist=total_dist,
                total_fuel=total_fuel,
                total_cost=total_cost,
                total_customer=total_customer,
                expenses=expenses,
                total_expenses=total_expenses,
                fuel_payable=fuel_payable,
                net_payable=net_payable,
                logo_path=logo_url
            )
            
            pdfkit_rendered = False
            wkhtmltopdf_cmd = find_wkhtmltopdf()
            
            if wkhtmltopdf_cmd:
                try:
                    import pdfkit
                    options = {
                        'page-size': 'A4',
                        'margin-top': '10mm',
                        'margin-right': '10mm',
                        'margin-bottom': '10mm',
                        'margin-left': '10mm',
                        'encoding': "UTF-8",
                        'enable-local-file-access': None
                    }
                    config = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_cmd)
                    pdfkit.from_string(rendered_html, filepath, options=options, configuration=config)
                    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                        pdfkit_rendered = True
                        logger.info(f"PDF generated via pdfkit: {filepath}")
                except Exception as pk_err:
                    logger.warning(f"pdfkit execution failed ({pk_err}), falling back to ReportLab")
                    if os.path.exists(filepath):
                        try:
                            os.remove(filepath)
                        except Exception:
                            pass

            if not pdfkit_rendered and REPORTLAB_AVAILABLE:
                # Clean up empty file if exists
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except Exception:
                        pass
                        
                from reportlab.platypus import Image as RLImage
                doc = SimpleDocTemplate(filepath, pagesize=A4)
                styles = getSampleStyleSheet()
                story: List[Any] = []
                
                # Add logo if exists, at its own proportions
                if logo_url and os.path.exists(logo_url):
                    try:
                        mark_w, mark_h = _brand_mark_size(logo_url, 120)
                        story.append(RLImage(logo_url, width=mark_w, height=mark_h))
                        story.append(Spacer(1, 10))
                    except Exception as img_err:
                        logger.warning(f"Could not load logo in ReportLab: {img_err}")
                
                story.append(Paragraph("ON TRACK PRIVATE LIMITED", styles['Title']))
                story.append(Paragraph("Fuel Reimbursement Invoice", styles['Heading2']))
                story.append(Spacer(1, 10))
                story.append(Paragraph(f"<b>Invoice #:</b> {invoice.invoice_number}", styles['Normal']))
                story.append(Paragraph(f"<b>Technician:</b> {tech.name}", styles['Normal']))
                start_fmt = invoice.start_date.strftime('%d/%m/%Y') if invoice.start_date else '-'
                end_fmt = invoice.end_date.strftime('%d/%m/%Y') if invoice.end_date else '-'
                story.append(Paragraph(f"<b>Period:</b> {start_fmt} to {end_fmt}", styles['Normal']))
                story.append(Paragraph(f"<b>Fuel Efficiency:</b> {efficiency} km/L", styles['Normal']))
                story.append(Spacer(1, 12))
                
                table_data: List[List[Any]] = [['#', 'Date', 'From', 'To', 'Dist(km)', 'Fuel(L)', 'Fuel Cost', 'Customer Fuel']]
                for item in items:
                    table_data.append([
                        str(item['num']), item['date'], item['from_loc'], item['to_loc'],
                        f"{item['dist']:.2f}", f"{item['fuel']:.2f}",
                        f"PKR {item['cost']:.2f}", f"PKR {item['customer']:.2f}"
                    ])
                table_data.append([
                    'TOTALS', '', '', '',
                    f"{total_dist:,.2f}", f"{total_fuel:,.2f}",
                    f"PKR {total_cost:,.2f}", f"PKR {total_customer:,.2f}"
                ])

                t = Table(table_data)
                t.setStyle(TableStyle([
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#5478C0')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ]))
                story.append(t)
                story.append(Spacer(1, 14))

                # Additional expenses, itemised - they are part of what is
                # owed, so the fallback PDF must show them too rather than
                # folding them silently into the net figure.
                if expenses:
                    story.append(Paragraph("Additional Expenses", styles['Heading3']))
                    expense_data: List[List[Any]] = [['Item', 'Description', 'Amount']]
                    for expense in expenses:
                        expense_data.append([
                            expense.label,
                            expense.description or '-',
                            f"PKR {(expense.amount or 0.0):,.2f}",
                        ])
                    expense_data.append(['TOTAL', '', f"PKR {total_expenses:,.2f}"])
                    et = Table(expense_data, colWidths=[110, 280, 100])
                    et.setStyle(TableStyle([
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#8A7DC4')),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
                    ]))
                    story.append(et)
                    story.append(Spacer(1, 14))

                summary_data: List[List[Any]] = [
                    ['Total Fuel Cost', f"PKR {total_cost:,.2f}"],
                    ['Customer Fuel Deduction', f"- PKR {total_customer:,.2f}"],
                    ['Fuel Payable', f"PKR {fuel_payable:,.2f}"],
                    ['Additional Expenses', f"PKR {total_expenses:,.2f}"],
                    ['NET AMOUNT PAYABLE', f"PKR {net_payable:,.2f}"],
                ]
                st = Table(summary_data, colWidths=[220, 130], hAlign='RIGHT')
                st.setStyle(TableStyle([
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#DDE3F0')),
                    ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                    ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#EEF2FB')),
                    ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                    ('TEXTCOLOR', (0, -1), (-1, -1), colors.HexColor('#4A6AB5')),
                ]))
                story.append(st)
                story.append(Spacer(1, 20))
                story.append(Paragraph(
                    "CRAFTED WITH PRECISION BY ORIGINS SOLUTIONS FOR "
                    "ON TRACK PRIVATE LIMITED &copy; 2026", styles['Italic']))
                doc.build(story)
                logger.info(f"PDF generated via ReportLab: {filepath}")
            
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                return filepath
            else:
                logger.error(f"PDF file missing or empty after generation attempt: {filepath}")
                return None
                
        except Exception as e:
            logger.error(f"Error generating PDF: {e}", exc_info=True)
            return None
    
    def generate_custom_report_pdf(self, data: Dict[str, Any], title: str) -> Optional[str]:
        """
        Generate a custom report PDF
        
        Args:
            data: Report data
            title: Report title
            
        Returns:
            str: Path to generated PDF file
        """
        if not REPORTLAB_AVAILABLE:
            logger.error("ReportLab not available")
            return None
        
        try:
            filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            filepath = os.path.join(self.pdf_folder, filename)
            doc = SimpleDocTemplate(filepath, pagesize=A4)
            styles = getSampleStyleSheet()
            
            story: List[Any] = []
            story.append(Paragraph(title, styles['Title']))
            story.append(Spacer(1, 12))
            
            # Add summary
            if 'summary' in data:
                story.append(Paragraph("Summary", styles['Heading2']))
                for key, value in data['summary'].items():
                    if not isinstance(value, dict):
                        story.append(Paragraph(f"{key.replace('_', ' ').title()}: {value}", styles['Normal']))
            
            story.append(Spacer(1, 12))
            doc.build(story)
            
            logger.info(f"PDF generated: {filepath}")
            return filepath
            
        except Exception as e:
            logger.error(f"Error generating custom PDF: {e}")
            return None

    # ---------- AMC / Annual Recovery invoice ----------

    @staticmethod
    def customer_code(name: str) -> str:
        """Four-character customer code for an invoice number.

        Letters and digits only, upper case, padded with X so the code is
        always four characters wide and the invoice number keeps a fixed
        shape - a number that changes length between customers cannot be
        read down a column or matched by eye against a bank statement.
        """
        cleaned = ''.join(ch for ch in (name or '') if ch.isalnum()).upper()
        return (cleaned[:4] or 'CUST').ljust(4, 'X')

    @staticmethod
    def amc_invoice_number(client_name: str, now=None) -> str:
        """AMC_ONT_<CUST>_<YYYYMMDD-HHMMSS>, unique in the ledger.

        Carries the date and time it was raised, so an invoice can be placed
        in the day's work without opening it, and the customer code, so a
        customer's invoices sort together.

        Uniqueness is confirmed against the ledger rather than assumed: two
        invoices raised for the same customer inside the same second would
        otherwise collide, and `amc_invoices.invoice_number` is a unique
        column - the second write would fail rather than renumber itself.
        """
        from src.models.amc_invoice import AmcInvoice

        stamp = (now or get_current_time()).strftime('%Y%m%d-%H%M%S')
        base = f"AMC_ONT_{PDFService.customer_code(client_name)}_{stamp}"

        candidate = base
        suffix = 1
        while AmcInvoice.query.filter_by(invoice_number=candidate).first() is not None:
            suffix += 1
            candidate = f"{base}-{suffix}"
        return candidate

    @staticmethod
    def _amc_validity(installation_date: str, installation_year: str) -> str:
        """One year from installation, ending the day before the anniversary.

        Same convention as the Tracker Certificate. The date arrives as text
        from the imported sheets, so anything unparseable degrades to the
        installation year, and then to a dash - an invoice may not invent a
        validity period it cannot derive.
        """
        raw = (installation_date or '').strip()
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d', '%d-%b-%Y', '%d %b %Y'):
            try:
                start = datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
            return (PDFService._add_years(start, 1) - timedelta(days=1)).strftime('%Y-%m-%d')

        year = (installation_year or '').strip()
        if year.isdigit() and len(year) == 4:
            return str(int(year) + 1)
        return '-'

    @staticmethod
    def _amount_in_words(amount: float) -> str:
        """PKR figure written out, as an invoice is expected to state it."""
        units = ('Zero', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven',
                 'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve', 'Thirteen',
                 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen',
                 'Nineteen')
        tens = ('', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty',
                'Seventy', 'Eighty', 'Ninety')

        def under_thousand(n: int) -> str:
            if n < 20:
                return units[n]
            if n < 100:
                return tens[n // 10] + (' ' + units[n % 10] if n % 10 else '')
            return units[n // 100] + ' Hundred' + (
                ' ' + under_thousand(n % 100) if n % 100 else '')

        # Split rather than round: the words sit beside the figure, and
        # "Seven Thousand Five Hundred One" against a printed 7,500.50 reads
        # as a discrepancy on a document a customer is being asked to pay.
        total_paisa = int(round(amount * 100))
        rupees, paisa = divmod(total_paisa, 100)

        if rupees == 0 and paisa == 0:
            return 'Zero Rupees Only'

        # Pakistani numbering: crore, lakh, thousand, hundred.
        parts = []
        remainder = rupees
        for divisor, label in ((10000000, 'Crore'), (100000, 'Lakh'), (1000, 'Thousand')):
            if remainder >= divisor:
                parts.append(under_thousand(remainder // divisor) + ' ' + label)
                remainder %= divisor
        if remainder:
            parts.append(under_thousand(remainder))

        words = (' '.join(parts) + ' Rupees') if parts else 'Zero Rupees'
        if paisa:
            words += ' and ' + under_thousand(paisa) + ' Paisa'
        return words + ' Only'

    def _amc_invoice_items(self, vehicles: List[Any]) -> List[Dict[str, Any]]:
        """One printable line per vehicle, in the invoice's column order.

        A vehicle whose AMC charge was never filled in on the imported sheet
        bills as zero, not as a guess - an invoice must not quote a figure the
        company has not actually set.
        """
        return [{
            'reg_no': (v.reg_no or '').strip().upper() or 'N/A',
            'installation_date': (v.installation_date or '').strip() or '-',
            'validity': self._amc_validity(v.installation_date, v.installation_year),
            'amount': f"{(v.amc_charges or 0.0):,.2f}",
        } for v in vehicles]

    def _render_amc_invoice(self, filepath: str, context: Dict[str, Any]) -> Optional[str]:
        """Draw the invoice HTML to `filepath` with wkhtmltopdf.

        No ReportLab fallback here, unlike the older documents: the whole point
        of this invoice is the branded layout, and a plain table of numbers
        going out to a customer under the company's name is worse than a clear
        failure the officer can act on.
        """
        from flask import render_template

        wkhtmltopdf_cmd = find_wkhtmltopdf()
        if not wkhtmltopdf_cmd:
            logger.error('Cannot generate the AMC invoice: wkhtmltopdf is not '
                         'installed or is not on PATH (set WKHTMLTOPDF_PATH).')
            return None

        rendered_html = render_template('pdf/amc_invoice.html', **context)

        try:
            import pdfkit
            # Real page margins. These were 0mm, copied from the Tracker
            # Certificate - which is correct there, because that document
            # draws its own inset frame and positions itself inside the
            # sheet. The invoice has no frame, so a zero margin ran the
            # masthead, the table borders and the footer into the paper's
            # edge and outside most printers' printable area.
            #
            # wkhtmltopdf sets the page box from these options; an @page
            # rule in the stylesheet does not reach it.
            options = {
                'page-size': 'A4',
                'margin-top': '16mm',
                'margin-right': '14mm',
                'margin-bottom': '16mm',
                'margin-left': '14mm',
                'encoding': 'UTF-8',
                # Smart shrinking rescales the page to fit its width, which
                # quietly changes what a CSS millimetre is worth - the layout
                # is sized to the sheet and has to stay that way.
                'disable-smart-shrinking': None,
                'dpi': 96,
                'enable-local-file-access': None,
            }
            config = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_cmd)
            pdfkit.from_string(rendered_html, filepath, options=options, configuration=config)
        except Exception as err:                          # noqa: BLE001
            logger.error(f'AMC invoice rendering failed: {err}', exc_info=True)
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except OSError:
                    pass
            return None

        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            logger.info(f'AMC invoice generated: {filepath}')
            return filepath
        logger.error(f'AMC invoice file missing or empty after generation: {filepath}')
        return None

    def _build_amc_invoice(self, client, vehicles: List[Any], basis: str,
                           filename: str, vehicle=None, override_amount=None,
                           discount_reason: str = '', user_id=None) -> Optional[Dict[str, Any]]:
        """Raise an AMC invoice: record it, then draw it.

        Vehicle-wise and customer-wise differ only in which vehicles are on the
        invoice and what it is called; everything the customer reads is built
        the same way, so the two can never disagree about a total.

        `override_amount` is what the officer chose to bill, which may be less
        than the balance - settling a fleet below its outstanding is ordinary
        commercial practice. The shortfall is recorded as a discount against
        the officer rather than lost with the download, and the customer's copy
        shows the amount they are actually being asked to pay.

        Returns the ledger row and the file, or None. The row is committed
        only once the document has actually been drawn: the dashboard counts
        invoices generated, so a row written for a PDF that failed to render
        would report an invoice the customer never received, and the officer's
        retry would report a second one. Nothing is consumed by abandoning the
        attempt - the number is derived at write time, not drawn from a
        sequence.
        """
        from src.extensions import db
        from src.models.amc_invoice import AmcInvoice

        if not vehicles:
            logger.error('Refusing to generate an AMC invoice with no vehicles on it')
            return None

        total_charges = sum(v.amc_charges or 0.0 for v in vehicles)
        total_received = sum(v.recovered_amount or 0.0 for v in vehicles)
        # Never a negative demand: an overpaid book owes nothing, it does not
        # owe less than nothing.
        outstanding = max(0.0, total_charges - total_received)

        # An override above the balance is not a discount and is not billed -
        # the customer owes what they owe.
        if override_amount is None:
            invoiced = outstanding
        else:
            invoiced = max(0.0, min(float(override_amount), outstanding))
        discount = round(max(0.0, outstanding - invoiced), 2)

        client_name = (client.name or '').strip().upper() if client else 'N/A'
        sheets = sorted({(v.sheet_name or '').strip() for v in vehicles} - {''})

        record = AmcInvoice(
            invoice_number=self.amc_invoice_number(client_name),
            basis=basis,
            client_id=client.id if client else None,
            vehicle_id=vehicle.id if vehicle is not None else None,
            client_name=client_name,
            vehicle_count=len(vehicles),
            sheet_names=', '.join(sheets)[:300],
            total_charges=round(total_charges, 2),
            total_received=round(total_received, 2),
            outstanding_amount=round(outstanding, 2),
            invoiced_amount=round(invoiced, 2),
            discount_amount=discount,
            discount_reason=(discount_reason or '').strip()[:300],
            generated_by=user_id,
        )
        context = {
            'invoice_number': record.invoice_number,
            'invoice_date': get_current_date().strftime('%d %b %Y'),
            'basis_label': record.basis_label,
            'client_name': client_name,
            'client_contact': (client.cell1 or '').strip() if client else '',
            'sheet_name': ', '.join(sheets),
            'items': self._amc_invoice_items(vehicles),
            'total_charges': f'{total_charges:,.2f}',
            'total_received': f'{total_received:,.2f}',
            'outstanding': f'{outstanding:,.2f}',
            'discount': f'{discount:,.2f}',
            'has_discount': discount > 0,
            'balance_due': f'{invoiced:,.2f}',
            'amount_in_words': self._amount_in_words(invoiced),
            'logo_path': _brand_mark(),
        }

        filepath = os.path.abspath(os.path.join(self.pdf_folder, filename))
        rendered = self._render_amc_invoice(filepath, context)
        if not rendered:
            # Nothing was written, so there is nothing to roll back - but say
            # so, since the officer is about to be told the invoice failed.
            logger.error(f'AMC invoice {record.invoice_number} was not recorded: '
                         f'the document could not be rendered')
            return None

        db.session.add(record)
        db.session.commit()
        return {'invoice': record, 'filepath': rendered}

    def generate_amc_invoice_pdf(self, vehicle_id: int, override_amount=None,
                                 discount_reason: str = '',
                                 user_id=None) -> Optional[Dict[str, Any]]:
        """Vehicle-wise AMC invoice - one vehicle, one demand."""
        try:
            from src.models.amc_invoice import AmcInvoice
            from src.models.annual_recovery import AnnualRecoveryVehicle

            vehicle = AnnualRecoveryVehicle.query.get(vehicle_id)
            if not vehicle:
                logger.error(f'Vehicle {vehicle_id} not found for AMC invoice')
                return None

            reg = ''.join(ch for ch in (vehicle.reg_no or '') if ch.isalnum()).upper()
            return self._build_amc_invoice(
                client=vehicle.client,
                vehicles=[vehicle],
                vehicle=vehicle,
                basis=AmcInvoice.BASIS_VEHICLE,
                filename=f"AMC_INVOICE_{reg or ('V' + str(vehicle.id))}.pdf",
                override_amount=override_amount,
                discount_reason=discount_reason,
                user_id=user_id,
            )
        except Exception as e:
            logger.error(f'Error generating vehicle AMC invoice {vehicle_id}: {e}',
                         exc_info=True)
            return None

    def generate_amc_client_invoice_pdf(self, client_id: int,
                                        vehicles: Optional[List[Any]] = None,
                                        override_amount=None,
                                        discount_reason: str = '',
                                        user_id=None) -> Optional[Dict[str, Any]]:
        """Customer-wise AMC invoice - every billable vehicle on one demand.

        `vehicles` is the set the caller may actually see. A recovery officer
        works assigned sheets only, so the invoice they raise must cover those
        vehicles and no others - passing the scoped list in keeps that decision
        with the caller that already made it, rather than re-deriving it here.
        """
        try:
            from src.models.amc_invoice import AmcInvoice
            from src.models.annual_recovery import AnnualRecoveryClient, AnnualRecoveryVehicle

            client = AnnualRecoveryClient.query.get(client_id)
            if not client:
                logger.error(f'Client {client_id} not found for AMC invoice')
                return None

            if vehicles is None:
                vehicles = (AnnualRecoveryVehicle.query
                            .filter_by(client_id=client_id)
                            .order_by(AnnualRecoveryVehicle.reg_no.asc()).all())

            # Written-off vehicles are not billed - the money was given up on,
            # and re-demanding it is exactly the kind of error that costs a
            # customer relationship.
            billable = [v for v in vehicles if (v.status or '').upper() != 'LOST']

            safe_name = ''.join(ch for ch in (client.name or '') if ch.isalnum())[:40].upper()
            return self._build_amc_invoice(
                client=client,
                vehicles=billable,
                basis=AmcInvoice.BASIS_CUSTOMER,
                filename=f"AMC_INVOICE_{safe_name or ('C' + str(client.id))}.pdf",
                override_amount=override_amount,
                discount_reason=discount_reason,
                user_id=user_id,
            )
        except Exception as e:
            logger.error(f'Error generating customer AMC invoice {client_id}: {e}',
                         exc_info=True)
            return None

    def generate_installation_recovery_report_pdf(self, charges: List[Any]) -> Optional[str]:
        """Installation Recovery follow-up report - same column set as the
        report page's Excel export, same letterhead/table style as the AMC
        invoice PDF above, so it matches the visual language already
        established rather than inventing a new house style."""
        if not REPORTLAB_AVAILABLE:
            return None
        try:
            filename = f"installation_recovery_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            filepath = os.path.join(self.pdf_folder, filename)
            doc = SimpleDocTemplate(filepath, pagesize=A4)
            styles = getSampleStyleSheet()

            story: List[Any] = []
            story.append(Paragraph("ON TRACK PRIVATE LIMITED", styles['Title']))
            story.append(Paragraph("Installation Recovery Report", styles['Heading2']))
            story.append(Paragraph(f"Generated {format_pkt_time(get_current_time())}", styles['Normal']))
            story.append(Spacer(1, 15))

            table_data = [['Reg No', 'Customer', 'Reason', 'Amount', 'Status', 'Officer']]
            for c in charges:
                table_data.append([
                    c.redo_activity.registration_no if c.redo_activity else '-',
                    c.redo_activity.customer_name if c.redo_activity else '-',
                    c.reason,
                    f"PKR {c.amount:,.0f}",
                    c.status,
                    c.assigned_officer.name if c.assigned_officer else 'Unassigned',
                ])

            t = Table(table_data, repeatRows=1)
            t.setStyle(TableStyle([
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0056b3')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
            ]))
            story.append(t)
            doc.build(story)
            return filepath
        except Exception as e:
            logger.error(f"Error generating Installation Recovery report PDF: {e}")
            return None

    def generate_installation_recovery_followup_pdf(self, followups: List[Any]) -> Optional[str]:
        """Installation Recovery Follow-up Report - call/WhatsApp history per
        device recovery charge, same letterhead/table style as the charge-
        list report PDF above."""
        if not REPORTLAB_AVAILABLE:
            return None
        try:
            filename = f"installation_recovery_followup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            filepath = os.path.join(self.pdf_folder, filename)
            doc = SimpleDocTemplate(filepath, pagesize=A4)
            styles = getSampleStyleSheet()

            story: List[Any] = []
            story.append(Paragraph("ON TRACK PRIVATE LIMITED", styles['Title']))
            story.append(Paragraph("Installation Recovery Follow-up Report", styles['Heading2']))
            story.append(Paragraph(f"Generated {format_pkt_time(get_current_time())}", styles['Normal']))
            story.append(Spacer(1, 15))

            table_data = [['Date', 'Reg No', 'Customer', 'Reason', 'Channel', 'Summary', 'Status', 'By']]
            for f in followups:
                charge = f.charge
                activity = charge.redo_activity if charge else None
                table_data.append([
                    f.conversation_date.strftime('%d/%m/%Y') if f.conversation_date else '-',
                    activity.registration_no if activity else '-',
                    activity.customer_name if activity else '-',
                    charge.reason if charge else '-',
                    'WhatsApp' if f.conversation_type == 'WHATSAPP' else 'Phone Call',
                    (f.summary or '-')[:80],
                    charge.status if charge else '-',
                    f.recorded_by_name or '-',
                ])

            t = Table(table_data, repeatRows=1)
            t.setStyle(TableStyle([
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0056b3')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 7),
            ]))
            story.append(t)
            doc.build(story)
            return filepath
        except Exception as e:
            logger.error(f"Error generating Installation Recovery follow-up report PDF: {e}")
            return None

    # ---------- tracker certificate: shared between the PDF and the Excel ----------

    @staticmethod
    def _certificate_filename(po, extension: str) -> str:
        """REGISTRATIONNUMBER_TRACKER_CERTIFICATE.<ext>.

        The certificate is filed and forwarded per vehicle, so the vehicle has
        to be readable in the filename - the file used to be saved as the bare
        registration, which says nothing about what the document is once it
        has left the CRM. Non-alphanumerics are dropped because the name
        travels through email and Windows file shares.
        """
        reg = ''.join(ch for ch in (po.reg_no or '') if ch.isalnum()).upper()
        return f"{reg or ('PO' + str(po.id))}_TRACKER_CERTIFICATE.{extension}"

    @staticmethod
    def _certificate_fields(po) -> List[Any]:
        """The certificate's particulars, in the order they are printed.

        Built once and used by both output formats: the PDF and the Excel copy
        are the same certificate, and a field added to one has to appear in the
        other. All of it comes off the PO and its security briefing (CNIC and
        address) - nothing here is typed by hand.
        """
        from src.models.security import SecurityBriefingData

        briefing = SecurityBriefingData.query.filter_by(po_id=po.id).first()

        # The installation date is when the installation-completion email went
        # out, per company convention - not today, and not whenever the PO row
        # was last touched for some unrelated reason.
        install_dt = po.completion_email_sent_at or po.updated_at or get_current_time()
        install_date = install_dt.date() if hasattr(install_dt, 'date') else install_dt
        # Validity runs a year from installation, ending the day before the
        # anniversary.
        validity_date = PDFService._add_years(install_date, 1) - timedelta(days=1)

        return [
            ('CUSTOMER NAME', po.owner_name or 'N/A'),
            ('CNIC', briefing.cnic if briefing and briefing.cnic else ''),
            ('CONTACT NO.', po.owner_contact or 'N/A'),
            ('ADDRESS', briefing.address if briefing and briefing.address else ''),
            ('INSURED BY', ''),
            ('MANUFACTURER', ' / '.join(p for p in [po.vehicle_make, po.vehicle_color] if p) or 'N/A'),
            ('YEAR / MODEL', po.vehicle_year or 'N/A'),
            ('REG NO.', (po.reg_no or '').strip() or 'N/A'),
            ('CHASSIS NO.', po.chassis_number or 'N/A'),
            ('ENGINE NO.', po.engine_number or 'N/A'),
            ('DATE OF INSTALLATION', install_date.strftime('%Y-%m-%d')),
            ('CERTIFICATE VALIDITY', validity_date.strftime('%Y-%m-%d')),
            ('COMPANY NO.', po.owner_contact or 'N/A'),
        ]

    def generate_tracker_certificate_excel(self, po_id: int) -> Optional[str]:
        """The same Tracker Certificate as a spreadsheet.

        Offered alongside the PDF because the certificate is sometimes
        forwarded to insurers who want the particulars as data rather than as
        a printed page. Same fields, same filename stem, same folder - only
        the format differs.
        """
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
            from src.models.purchase_order import PurchaseOrder

            po = PurchaseOrder.query.get(po_id)
            if not po:
                logger.error(f"PO {po_id} not found for tracker certificate")
                return None

            fields = self._certificate_fields(po)
            filepath = os.path.abspath(os.path.join(
                self.certificate_folder, self._certificate_filename(po, 'xlsx')))

            workbook = Workbook()
            sheet = workbook.active
            sheet.title = 'Tracker Certificate'

            heading = Font(bold=True, size=14, color='FFFFFF')
            banner = PatternFill('solid', fgColor='3B5599')
            label_font = Font(bold=True, size=10)
            label_fill = PatternFill('solid', fgColor='F4F7FD')
            edge = Side(style='thin', color='C6CFE4')
            box = Border(left=edge, right=edge, top=edge, bottom=edge)

            sheet['A1'] = 'ONTRACK (PVT.) LIMITED'
            sheet['A1'].font = heading
            sheet['A1'].fill = banner
            sheet['A1'].alignment = Alignment(horizontal='center')
            sheet.merge_cells('A1:B1')

            sheet['A2'] = 'TRACKER CERTIFICATE'
            sheet['A2'].font = Font(bold=True, size=12)
            sheet['A2'].alignment = Alignment(horizontal='center')
            sheet.merge_cells('A2:B2')

            row = 4
            for label, value in fields:
                sheet.cell(row=row, column=1, value=label).font = label_font
                sheet.cell(row=row, column=1).fill = label_fill
                sheet.cell(row=row, column=1).border = box
                sheet.cell(row=row, column=2, value=value).border = box
                row += 1

            row += 1
            statement = sheet.cell(
                row=row, column=1,
                value='This is to certify that OnTrack Vehicle Tracking System has been '
                      'installed in the vehicle with the specifications above.')
            statement.font = Font(bold=True, size=10)
            statement.alignment = Alignment(wrap_text=True, vertical='center')
            sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
            sheet.row_dimensions[row].height = 30

            row += 1
            sheet.cell(row=row, column=1,
                       value=f"Date of Issue: {get_current_date().strftime('%d-%b-%y')}")
            sheet.cell(row=row, column=2, value='Issued By: Ontrack (Pvt.) Limited')

            row += 1
            sheet.cell(row=row, column=1,
                       value='This is a computer generated document and does not '
                             'require a signature.').font = Font(italic=True, size=9)
            sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)

            sheet.column_dimensions['A'].width = 26
            sheet.column_dimensions['B'].width = 46

            workbook.save(filepath)
            logger.info(f"Tracker certificate spreadsheet generated: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Error generating tracker certificate spreadsheet for "
                         f"PO {po_id}: {e}", exc_info=True)
            return None

    def generate_tracker_certificate(self, po_id: int) -> Optional[str]:
        """
        Generate the Tracker Installation Certificate for a completed PO.
        All data is pulled from the PO record (and its linked security
        briefing, for CNIC/address) - nothing is entered manually. The
        installation date is the moment the installation-completion email
        was sent (completion_email_sent_at), not today's date, per company
        convention. Certificate validity runs one year from installation,
        ending the day before the anniversary. The PDF is saved under the
        vehicle's registration number.
        """
        try:
            from flask import render_template
            from reportlab.lib.units import mm
            from reportlab.platypus import Image as RLImage
            from src.models.purchase_order import PurchaseOrder

            po = PurchaseOrder.query.get(po_id)
            if not po:
                logger.error(f"PO {po_id} not found for tracker certificate")
                return None

            fields = self._certificate_fields(po)
            generated_date_str = get_current_date().strftime('%d-%b-%y')
            filepath = os.path.abspath(os.path.join(
                self.certificate_folder, self._certificate_filename(po, 'pdf')))

            logo_path = _brand_mark()

            # Try HTML -> wkhtmltopdf (pdfkit) rendering first
            rendered_html = render_template(
                'pdf/tracker_certificate.html',
                fields=fields,
                generated_date=generated_date_str,
                logo_path=logo_path
            )

            pdfkit_rendered = False
            wkhtmltopdf_cmd = find_wkhtmltopdf()
            if wkhtmltopdf_cmd:
                try:
                    import pdfkit
                    # No page margin: the certificate draws its own frame and
                    # positions it, so a margin here would inset the border
                    # twice and leave it floating in the middle of the sheet.
                    #
                    # Smart shrinking is off because it rescales the whole
                    # page to fit the width, which quietly changes what a
                    # CSS millimetre is worth - the frame was sized to the
                    # sheet in mm and came out three quarters of the height.
                    options = {
                        'page-size': 'A4',
                        'margin-top': '0mm',
                        'margin-right': '0mm',
                        'margin-bottom': '0mm',
                        'margin-left': '0mm',
                        'encoding': "UTF-8",
                        'disable-smart-shrinking': None,
                        'dpi': 96,
                        'enable-local-file-access': None
                    }
                    config = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_cmd)
                    pdfkit.from_string(rendered_html, filepath, options=options, configuration=config)
                    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                        pdfkit_rendered = True
                        logger.info(f"Tracker certificate generated via pdfkit: {filepath}")
                except Exception as pk_err:
                    logger.warning(f"pdfkit execution failed ({pk_err}), falling back to ReportLab")
                    if os.path.exists(filepath):
                        try:
                            os.remove(filepath)
                        except Exception:
                            pass

            if not pdfkit_rendered and REPORTLAB_AVAILABLE:
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except Exception:
                        pass

                doc = SimpleDocTemplate(filepath, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
                styles = getSampleStyleSheet()
                story: List[Any] = []

                logo_cell: Any = ''
                if logo_path and os.path.exists(logo_path):
                    try:
                        cell_w, cell_h = _brand_mark_size(logo_path, 110)
                        logo_cell = RLImage(logo_path, width=cell_w, height=cell_h)
                    except Exception as img_err:
                        logger.warning(f"Could not load logo in ReportLab: {img_err}")

                company_lines = [
                    '<b>Ontrack (Pvt.) Limited</b>',
                    'Address: C-25 Office # 1, 3rd Floor Old Sunset,',
                    'UAN: 0311-1345070 / Phone: 021-36100246',
                    'WhatsApp: 0311-1345070',
                    'Email: info@on-tracking.com',
                    'Website: www.on-tracking.com',
                    f"Date: {generated_date_str}",
                ]
                company_para = Paragraph(
                    '<br/>'.join(company_lines),
                    ParagraphStyle('company', parent=styles['Normal'], alignment=1, fontSize=9, leading=12)
                )

                header_table = Table([[logo_cell, company_para]], colWidths=[130, 340])
                header_table.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('ALIGN', (0, 0), (0, 0), 'LEFT'),
                    ('ALIGN', (1, 0), (1, 0), 'CENTER'),
                ]))
                story.append(header_table)
                story.append(Spacer(1, 14))

                title_table = Table([['TRACKER CERTIFICATE']], colWidths=[470])
                title_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#5478C0')),
                    ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
                    ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 13),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('TOPPADDING', (0, 0), (-1, -1), 8),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ]))
                story.append(title_table)
                story.append(Spacer(1, 4))

                particulars_table = Table([['PARTICULARS']], colWidths=[470])
                particulars_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, -1), colors.black),
                    ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
                    ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 12),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('TOPPADDING', (0, 0), (-1, -1), 6),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ]))
                story.append(particulars_table)

                fields_table_data = [[label, value] for label, value in fields]
                fields_table = Table(fields_table_data, colWidths=[180, 290])
                fields_table.setStyle(TableStyle([
                    ('GRID', (0, 0), (-1, -1), 0.75, colors.grey),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('ALIGN', (0, 0), (0, -1), 'CENTER'),
                    ('ALIGN', (1, 0), (1, -1), 'CENTER'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('TOPPADDING', (0, 0), (-1, -1), 6),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ]))
                story.append(fields_table)
                story.append(Spacer(1, 20))

                story.append(Paragraph(
                    "This is to certify that OnTrack Vehicle Tracking System has been "
                    "installed in the vehicle with the specifications above.",
                    ParagraphStyle('cert_note', parent=styles['Normal'], alignment=1,
                                   fontSize=10, fontName='Helvetica-Bold')
                ))
                story.append(Spacer(1, 10))
                story.append(Paragraph(
                    f"Date of Issue: {generated_date_str} &nbsp;&nbsp;|&nbsp;&nbsp; "
                    "Issued By: Ontrack (Pvt.) Limited",
                    ParagraphStyle('cert_issue', parent=styles['Normal'], alignment=1, fontSize=9)
                ))
                story.append(Paragraph(
                    "This is a computer generated document and does not require a signature.",
                    ParagraphStyle('cert_note2', parent=styles['Normal'], alignment=1, fontSize=9)
                ))

                doc.build(story)
                logger.info(f"Tracker certificate generated via ReportLab: {filepath}")

            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                return filepath
            logger.error(f"Tracker certificate file missing or empty after generation: {filepath}")
            return None
        except Exception as e:
            logger.error(f"Error generating tracker certificate for PO {po_id}: {e}", exc_info=True)
            return None

    @staticmethod
    def _add_years(d: date, years: int) -> date:
        """Add whole years to a date, clamping Feb 29 -> Feb 28 on non-leap targets"""
        try:
            return d.replace(year=d.year + years)
        except ValueError:
            return d.replace(year=d.year + years, day=28)