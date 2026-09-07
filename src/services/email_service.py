# src/services/email_service.py
"""
Email Service - Email sending and management
"""
from typing import Optional, List, Dict, Any, Tuple, Union, cast
from flask import current_app
from flask_mail import Message

from src.extensions import mail
from src.config import get_config
from src.utils.logging import get_logger

logger = get_logger(__name__)


# Senior management, and only senior management.
#
# The month-end report pack is restricted to this list. It carries commercial
# and staff-performance detail that the wider operational list
# (`EmailService.default_recipients`, which includes CS and other shared
# mailboxes) must not receive.
#
# This is now the *seed and fallback*: the live list is managed from
# Settings -> Report Recipients and stored in `report_recipients`. These
# addresses populate that table the first time it is opened, and are used
# directly if the table is ever unavailable - a month-end run must never
# quietly go to nobody.
SENIOR_MANAGEMENT_RECIPIENTS = [
    'alister@on-tracking.com',
    'shaan@on-tracking.com',
    'sharoon@on-tracking.com',
    'musarrat@on-tracking.com',
]


class EmailService:
    """Service for sending emails"""

    def __init__(self):
        self.config = get_config()
        # Operational distribution - installation completion notices and the
        # like. Wider than the restricted list above on purpose.
        self.default_recipients = [
            'Sharoon@on-tracking.com',
            'shaan@on-tracking.com',
            'alister@on-tracking.com',
            'cs@on-tracking.com',
            'Salman@on-tracking.com',
            'cr@on-tracking.com',
            'sunita@on-tracking.com'
        ]
        self.senior_management_recipients = list(SENIOR_MANAGEMENT_RECIPIENTS)

    @staticmethod
    def report_recipients() -> List[str]:
        """The live management distribution.

        Read from the table an administrator maintains in Settings. Falls
        back to the built-in list if the table is empty or unreachable -
        losing the recipients is not a reason to send a month-end pack to an
        empty address list, and a silent no-send is the failure nobody
        notices until the report is missed.
        """
        try:
            from src.models.report_recipient import ReportRecipient
            addresses = ReportRecipient.active_emails()
            if addresses:
                return addresses
            logger.warning('No active report recipients configured - '
                           'falling back to the built-in management list')
        except Exception as err:                       # noqa: BLE001
            logger.warning(f'Could not read report recipients ({err}) - '
                           'falling back to the built-in management list')
        return list(SENIOR_MANAGEMENT_RECIPIENTS)

    def send_restricted_report(self, subject: str, html_body: str,
                               attachments: Optional[List[Dict[str, str]]] = None) -> bool:
        """Send one of the management-only reports.

        A separate method rather than a recipients argument at each call
        site, so the restriction is applied in one place and cannot be
        widened by a caller passing the wrong list.
        """
        return self.send_email(
            subject=subject,
            recipients=self.report_recipients(),
            html_body=html_body,
            attachments=attachments,
        )


    def send_email(self, subject: str, recipients: List[str],
                   html_body: str, text_body: Optional[str] = None,
                   sender: Optional[str] = None,
                   attachments: Optional[List[Dict[str, str]]] = None) -> bool:
        """
        Send an email

        Args:
            subject: Email subject
            recipients: List of recipient emails
            html_body: HTML content
            text_body: Plain text content (optional)
            sender: Sender email (defaults to MAIL_DEFAULT_SENDER)
            attachments: Optional list of {'filename', 'filepath', 'content_type'} dicts

        Returns:
            True if sent successfully, False otherwise
        """
        if not recipients:
            logger.warning("No recipients provided for email")
            return False

        try:
            msg = Message(
                subject=subject,
                recipients=cast(List[Union[str, Tuple[str, str]]], recipients),
                html=html_body,
                body=text_body,
                sender=sender or self.config.MAIL_DEFAULT_SENDER
            )
            for att in (attachments or []):
                with open(att['filepath'], 'rb') as f:
                    msg.attach(att['filename'], att.get('content_type', 'application/octet-stream'), f.read())
            mail.send(msg)
            logger.info(f"✅ Email sent to {len(recipients)} recipients: {subject}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to send email: {e}")
            return False
    
    def send_completion_email(self, po) -> bool:
        """
        Send installation completion email with beautiful template
        This is called ONLY when installer marks PO as COMPLETED
        """
        from src.models.user import User
        
        recipients = self.default_recipients.copy()
        
        # Get sales person name
        sales_person = User.query.get(po.sales_person_id) if po.sales_person_id else None
        sales_person_name = sales_person.name if sales_person else (sales_person.username if sales_person else 'N/A')
        
        subject = f"VEHICLE ACTIVITY NOTIFICATION - INSTALLATION COMPLETED - {po.po_number} - {po.owner_name}"
        
        # Beautiful HTML email template
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Installation Completed</title>
<style>
    body {{
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        margin: 0;
        padding: 20px;
        background-color: #f5f7fa;
    }}
    .email-container {{
        max-width: 650px;
        margin: 0 auto;
        background: #ffffff;
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }}
    .header {{
        background: linear-gradient(135deg, #f8fafc 0%, #ffffff 100%);
        padding: 20px 25px;
        text-align: center;
        border-bottom: 3px solid #15b3da;
    }}
    .logo-text {{
        font-size: 20px;
        font-weight: bold;
        color: #0f2b5e;
        letter-spacing: 1px;
    }}
    .company-sub {{
        font-size: 11px;
        color: #15b3da;
        margin-top: 5px;
        letter-spacing: 0.5px;
    }}
    .title-section {{
        background: #f8fafc;
        padding: 12px 25px;
        text-align: center;
        border-bottom: 1px solid #e2e8f0;
    }}
    .title-section h2 {{
        margin: 0;
        color: #0f172a;
        font-size: 16px;
        font-weight: 600;
    }}
    .title-section h3 {{
        margin: 3px 0 0;
        color: #15b3da;
        font-size: 13px;
        font-weight: normal;
    }}
    .po-header {{
        background: #f1f5f9;
        padding: 10px 25px;
        text-align: center;
        border-bottom: 1px solid #e2e8f0;
    }}
    .po-number {{
        font-weight: bold;
        color: #0f172a;
        font-size: 14px;
    }}
    .status {{
        display: inline-block;
        background: #10b981;
        color: white;
        padding: 3px 12px;
        border-radius: 20px;
        font-size: 10px;
        font-weight: bold;
        margin-left: 10px;
    }}
    .content {{
        padding: 20px 25px;
    }}
    .info-table {{
        width: 100%;
        border-collapse: collapse;
    }}
    .info-table tr {{
        border-bottom: 1px solid #e2e8f0;
    }}
    .info-table td {{
        padding: 10px 8px;
        font-size: 13px;
    }}
    .info-table td:first-child {{
        font-weight: 700;
        color: #1e293b;
        width: 35%;
        background-color: #f8fafc;
    }}
    .info-table td:last-child {{
        color: #334155;
    }}
    .footer {{
        background: #f8fafc;
        padding: 12px 25px;
        text-align: center;
        font-size: 10px;
        color: #64748b;
        border-top: 1px solid #e2e8f0;
    }}
    .footer a {{
        color: #15b3da;
        text-decoration: none;
    }}
    @media (max-width: 600px) {{
        .info-table td {{
            display: block;
            width: 100%;
        }}
        .info-table td:first-child {{
            border-bottom: none;
            padding-bottom: 4px;
        }}
    }}
</style>
</head>
<body>
<div class="email-container">
    <div class="header">
        <div class="logo-text">ON TRACK PRIVATE LIMITED</div>
        <div class="company-sub">Vehicle Tracking Management System</div>
    </div>
    <div class="title-section">
        <h2>VEHICLE ACTIVITY NOTIFICATION</h2>
        <h3>INSTALLATION COMPLETED</h3>
    </div>
    <div class="po-header">
        <span class="po-number">{po.po_number}</span>
        <span class="status">COMPLETED</span>
    </div>
    <div class="content">
        <table class="info-table">
            <tr><td style="background:#f8fafc; font-weight:700;">INSTALLATION</td><td>{po.scheduled_date.strftime('%d/%m/%Y') if po.scheduled_date else 'N/A'}</td></tr>
            <tr><td style="background:#f8fafc; font-weight:700;">CLIENT</td><td><strong>{po.owner_name}</strong></td></tr>
            <tr><td style="background:#f8fafc; font-weight:700;">CLIENT CONTACT</td><td>{po.owner_contact}</td></tr>
            <tr><td style="background:#f8fafc; font-weight:700;">SALESPERSON</td><td>{sales_person_name}</td></tr>
            <tr><td style="background:#f8fafc; font-weight:700;">DEVICE ID</td><td>{po.imei_no or 'N/A'}</td></tr>
            <tr><td style="background:#f8fafc; font-weight:700;">SIM NUMBER</td><td>{po.sim_no or 'N/A'}</td></tr>
            <tr><td style="background:#f8fafc; font-weight:700;">REG#</td><td>{po.reg_no}</td></tr>
            <tr><td style="background:#f8fafc; font-weight:700;">ENGINE</td><td>{po.engine_number}</td></tr>
            <tr><td style="background:#f8fafc; font-weight:700;">CHASSIS</td><td>{po.chassis_number}</td></tr>
            <tr><td style="background:#f8fafc; font-weight:700;">MANUFACTURER / BRAND</td><td>{po.vehicle_make}/{po.vehicle_model}</td></tr>
            <tr><td style="background:#f8fafc; font-weight:700;">YEAR / MODEL &amp; COLOR</td><td>{po.vehicle_year}/{po.vehicle_color}</td></tr>
            <tr><td style="background:#f8fafc; font-weight:700;">TRANSMISSION / POWER CC</td><td>{po.transmission or 'N/A'}/{po.power_cc or 'N/A'}</td></tr>
            <tr><td style="background:#f8fafc; font-weight:700;">TECH</td><td>{po.technician_assigned or 'N/A'}</td></tr>
            <tr><td style="background:#f8fafc; font-weight:700;">TESTED BY</td><td>{po.tested_by or 'N/A'}</td></tr>
            <tr><td style="background:#f8fafc; font-weight:700;">CITY</td><td>{po.city or 'N/A'}</td></tr>
            <tr><td style="background:#f8fafc; font-weight:700;">DEVICE LOCATION</td><td>{po.device_location or 'N/A'}</td></tr>
            <tr><td style="background:#f8fafc; font-weight:700;">REMARKS</td><td>{po.remarks or 'N/A'}</td></tr>
        </table>
    </div>
    <div class="footer">
        <p>This is an automated notification from the <strong>On Track Vehicle Management System</strong>.</p>
        <p>© 2026 On Track Private Limited | <a href="mailto:cs@on-tracking.com">cs@on-tracking.com</a></p>
    </div>
</div>
</body>
</html>
"""
        
        return self.send_email(subject, recipients, html_body)
    
    def send_security_completion_email(self, briefing) -> bool:
        """Send security briefing completion email - includes every client
        detail captured during the briefing (contact/emergency info,
        installation/device details, and the security checklist), not just
        a summary, so this email can stand alone as the full record.

        Goes to the same distribution as the installation completion email
        (`send_completion_email`) - the briefing closes out the installation
        those recipients were already told about, so splitting the two lists
        would leave people holding half a record."""
        po = briefing.purchase_order
        recipients = self.default_recipients.copy()

        subject = f"SECURITY BRIEFING COMPLETED - {po.po_number} - {briefing.registration_no} - {briefing.customer_name}"

        def row(label, value):
            display = value if value not in (None, '') else 'N/A'
            return f'<div class="detail-row"><span class="label">{label}:</span> {display}</div>'

        yes_no = lambda v: 'Yes' if v else 'No'

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Security Briefing Completed</title>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #004080; color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 20px; }}
                .section-title {{ margin: 20px 0 8px 0; color: #004080; font-size: 14px; text-transform: uppercase; border-bottom: 2px solid #004080; padding-bottom: 4px; }}
                .detail-row {{ padding: 8px 0; border-bottom: 1px solid #eee; }}
                .label {{ font-weight: bold; width: 180px; display: inline-block; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>ON TRACK PRIVATE LIMITED</h2>
                    <h3>Security Briefing Completed</h3>
                </div>
                <div class="content">
                    <div class="section-title">Purchase Order</div>
                    {row('PO Number', po.po_number)}
                    {row('Status', 'COMPLETED')}
                    {row('Briefed By', briefing.briefed_by)}
                    {row('Completed At', briefing.completed_at.strftime('%d/%m/%Y %H:%M') if briefing.completed_at else None)}

                    <div class="section-title">Vehicle</div>
                    {row('Registration', briefing.registration_no)}
                    {row('Make / Model', f"{briefing.make or ''} {briefing.model or ''}".strip())}
                    {row('Year / Color', f"{briefing.year or ''} {briefing.color or ''}".strip())}
                    {row('Chassis No', briefing.chassis_no)}
                    {row('Engine No', briefing.engine_no)}

                    <div class="section-title">Client Details</div>
                    {row('Customer Name', briefing.customer_name)}
                    {row('Phone', briefing.phone)}
                    {row('Segment', briefing.segment)}
                    {row('CNIC', briefing.cnic)}
                    {row('Address', briefing.address)}
                    {row('Father Name', briefing.father_name)}
                    {row('Mother Name', briefing.mother_name)}
                    {row('Secondary User', briefing.secondary_user_name)}
                    {row('Secondary User Phone', briefing.secondary_user_phone)}
                    {row('Emergency Contact', briefing.emergency_user_name)}
                    {row('Emergency Phone', briefing.emergency_user_phone)}

                    <div class="section-title">Installation & Device</div>
                    {row('Technician', briefing.technician_name)}
                    {row('Device Location', briefing.device_location)}
                    {row('IMEI', briefing.imei_no)}
                    {row('SIM', briefing.sim_no)}
                    {row('Device Serial No', briefing.device_serial_no)}
                    {row('SIM Network', briefing.sim_network)}
                    {row('Accessories Installed', briefing.accessories_installed)}
                    {row('Fence', briefing.fence)}
                    {row('Password 1', briefing.password_1)}
                    {row('Password 2', briefing.password_2)}

                    <div class="section-title">Security Checklist</div>
                    {row('Security Training Completed', yes_no(briefing.security_training_completed))}
                    {row('Customer Demonstration Given', yes_no(briefing.customer_demonstration))}
                    {row('Services Explained', yes_no(briefing.services_explained))}
                    {row('Customer Acknowledgement', yes_no(briefing.acknowledgement))}
                    {row('Officer Notes', briefing.officer_notes)}

                    <hr>
                    <p style="color: #666; font-size: 12px;">This is an automated notification containing the complete security briefing record.</p>
                    <p style="color: #999; font-size: 11px; text-align: center; margin-top: 18px;">
                        CRAFTED WITH PRECISION BY ORIGINS SOLUTIONS FOR ON TRACK PRIVATE LIMITED &copy; 2026
                    </p>
                </div>
            </div>
        </body>
        </html>
        """

        return self.send_email(subject, recipients, html_body)
    
    def send_po_created_email(self, po) -> bool:
        """Send PO created notification email (Optional - can be disabled)"""
        # For now, let's NOT send PO created emails - only completion emails
        # This keeps the flow clean: Sales creates PO → Installer handles it
        logger.info(f"PO created email skipped for {po.po_number} - only completion emails are sent")
        return True
    
    def send_password_reset_email(self, user, token: str) -> bool:
        """Send password reset email"""
        reset_link = f"{current_app.config.get('BASE_URL', 'http://localhost:5000')}/auth/reset-password?token={token}"
        
        subject = "Password Reset Request - ON TRACK"
        
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Password Reset</title>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #004080; color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 20px; }}
                .button {{ display: inline-block; padding: 12px 24px; background: #28a745; color: white; text-decoration: none; border-radius: 4px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>ON TRACK Private Limited</h2>
                    <h3>Password Reset Request</h3>
                </div>
                <div class="content">
                    <p>Hello {user.name or user.username},</p>
                    <p>We received a request to reset your password. Click the button below to create a new password:</p>
                    <p style="text-align: center; margin: 30px 0;">
                        <a href="{reset_link}" class="button">Reset Password</a>
                    </p>
                    <p>If you didn't request this, please ignore this email.</p>
                    <p>This link will expire in 24 hours.</p>
                    <hr>
                    <p style="color: #666; font-size: 12px;">This is an automated notification. Do not reply to this email.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return self.send_email(subject, [user.email], html_body)

    def send_redo_completion_email(self, redo) -> bool:
        """Notify the operational list that a REDO has been completed.

        Carries every field on the REDO entry form, grouped the way the form
        groups them, so the notice is a complete record of the visit and the
        reader does not have to open the CRM to find out what was done. The
        device-replacement block appears only when a device or SIM was
        actually swapped - six rows of "N/A" on the ordinary REDO buried the
        rows that matter.
        """
        recipients = self.default_recipients.copy()
        cust_name = redo.customer_name or 'N/A'
        redo_id = redo.redo_number or f"REDO-{redo.id}"
        activity = redo.activity_type or 'REDO'

        subject = f"Vehicle Activity - {cust_name} - {activity} - ID: {redo_id}"

        def fmt_date(value, fmt='%d/%m/%Y'):
            return value.strftime(fmt) if value else 'N/A'

        sched_date = fmt_date(redo.scheduled_date)
        completed_at = fmt_date(redo.completed_at, '%d/%m/%Y %H:%M')

        def row(label, value):
            return (f'<tr><td class="label">{label}</td>'
                    f'<td>{value if value not in (None, "") else "N/A"}</td></tr>')

        def strong(value):
            return f'<strong>{value}</strong>' if value else 'N/A'

        activity_rows = ''.join([
            row('ACTIVITY TYPE', strong(activity)),
            row('SCHEDULED DATE', sched_date),
            row('COMPLETED ON', strong(completed_at)),
            row('RESOLUTION STATUS', strong(redo.resolution_status)),
        ])

        customer_rows = ''.join([
            row('CLIENT NAME', strong(redo.customer_name)),
            row('CLIENT CONTACT', redo.customer_contact),
            row('SALES PERSON', strong(redo.sale_person)),
            row('ARRANGED BY', strong(redo.arranged_by)),
        ])

        vehicle_rows = ''.join([
            row('REGISTRATION #', strong(redo.registration_no)),
            row('MANUFACTURER / BRAND', f"{redo.make or 'N/A'} / {redo.model or 'N/A'}"),
            row('YEAR / MODEL & COLOR', f"{redo.year or 'N/A'} / {redo.color or 'N/A'}"),
            row('CHASSIS #', redo.chassis_no),
            row('ENGINE #', redo.engine_no),
            row('CITY', redo.city),
            row('VEHICLE LOCATION', redo.vehicle_location),
        ])

        device_rows = ''.join([
            row('DEVICE ID (IMEI)', strong(redo.imei_no)),
            row('SIM NUMBER', redo.sim_no),
            row('DEVICE TYPE', redo.device_type),
            row('DEVICE LOCATION', redo.device_location),
        ])

        # Only a real swap gets the replacement block.
        swapped = any([redo.new_device, redo.new_sim, redo.old_imei_no,
                       redo.old_sim_no, redo.device_change_reason])
        if swapped:
            replacement_block = f"""
        <div class="section-title">Device Replacement</div>
        <table class="info-table">
            {row('REASON FOR CHANGE', strong(redo.device_change_reason))}
            {row('PREVIOUS IMEI', redo.old_imei_no)}
            {row('PREVIOUS SIM', redo.old_sim_no)}
            {row('NEW DEVICE (IMEI)', strong(redo.new_device))}
            {row('NEW SIM', redo.new_sim)}
        </table>"""
        else:
            replacement_block = """
        <div class="section-title">Device Replacement</div>
        <div class="none-note">No device or SIM replacement was recorded for this activity.</div>"""

        service_rows = ''.join([
            row('TECHNICIAN', strong(redo.technician)),
            row('TESTING BY', redo.tested_by),
            row('TRANSFER INSTALLATION', redo.transfer_installation),
            row('TRANSFER CHARGES', redo.transfer_charges),
            row('FUEL COMPENSATED', redo.fuel),
        ])

        html_body = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>{subject}</title>
<style>
    body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f6f9; padding: 20px; color: #1e293b; margin: 0; }}
    .email-container {{ max-width: 650px; margin: 0 auto; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.06); }}
    .header {{ background: linear-gradient(135deg, #004080, #002b55); padding: 22px; text-align: center; color: #ffffff; }}
    .logo-text {{ font-size: 20px; font-weight: 800; letter-spacing: 1px; margin-bottom: 4px; }}
    .company-sub {{ font-size: 12px; opacity: 0.85; text-transform: uppercase; letter-spacing: 0.5px; }}
    .title-section {{ background: #6B8DD6; color: #ffffff; text-align: center; padding: 12px; font-weight: 700; font-size: 15px; letter-spacing: 0.5px; }}
    .po-header {{ display: flex; justify-content: space-between; padding: 12px 20px; background: #f8fafc; border-bottom: 1px solid #e2e8f0; font-size: 13px; }}
    .po-number {{ font-weight: 700; color: #004080; }}
    .status {{ font-weight: 700; color: #16a34a; background: #dcfce7; padding: 2px 8px; border-radius: 4px; }}
    .content {{ padding: 20px; }}
    .section-title {{ font-weight: 700; font-size: 12px; color: #004080; text-transform: uppercase; letter-spacing: 0.6px; margin: 18px 0 6px 0; padding-bottom: 4px; border-bottom: 2px solid #e2e8f0; }}
    .section-title:first-child {{ margin-top: 0; }}
    .info-table {{ width: 100%; border-collapse: collapse; margin-bottom: 4px; font-size: 13px; }}
    .info-table td {{ padding: 8px 12px; border-bottom: 1px solid #f1f5f9; }}
    .info-table td.label {{ font-weight: 700; width: 38%; color: #475569; background: #f8fafc; text-transform: uppercase; font-size: 11px; letter-spacing: 0.5px; }}
    .none-note {{ font-size: 12px; color: #64748b; font-style: italic; padding: 10px 12px; background: #f8fafc; border: 1px dashed #e2e8f0; border-radius: 6px; }}
    .remarks-box {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px; font-size: 13px; color: #334155; line-height: 1.5; margin-top: 6px; }}
    .footer {{ text-align: center; padding: 15px 20px; font-size: 11px; color: #94a3b8; border-top: 1px solid #f1f5f9; background: #fafafa; }}
    .footer a {{ color: #004080; text-decoration: none; }}
</style>
</head>
<body>
<div class="email-container">
    <div class="header">
        <div class="logo-text">ON TRACK PRIVATE LIMITED</div>
        <div class="company-sub">Vehicle Tracking Management System</div>
    </div>
    <div class="title-section">
        VEHICLE ACTIVITY NOTIFICATION &mdash; {activity}
    </div>
    <div class="po-header">
        <span class="po-number">RECORD ID: {redo_id}</span>
        <span class="status">COMPLETED</span>
    </div>
    <div class="content">
        <div class="section-title">Activity</div>
        <table class="info-table">{activity_rows}</table>

        <div class="section-title">Customer</div>
        <table class="info-table">{customer_rows}</table>

        <div class="section-title">Vehicle</div>
        <table class="info-table">{vehicle_rows}</table>

        <div class="section-title">Device</div>
        <table class="info-table">{device_rows}</table>
{replacement_block}

        <div class="section-title">Service</div>
        <table class="info-table">{service_rows}</table>

        <div class="section-title">Remarks &amp; Work Summary</div>
        <div class="remarks-box">
            {redo.remarks or redo.completion_notes or 'Service completed successfully.'}
        </div>
    </div>
    <div class="footer">
        <p>This is an automated notification from the <strong>On Track Vehicle Management System</strong>.</p>
        <p>&copy; 2026 On Track Private Limited | <a href="mailto:cs@on-tracking.com">cs@on-tracking.com</a></p>
    </div>
</div>
</body>
</html>"""

        return self.send_email(subject, recipients, html_body)
