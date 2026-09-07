# src/web/sales.py
"""
Sales Routes - Dashboard and PO management
"""
from typing import Any, Dict

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from src.web import sales_bp
from src.services import POService, UserService, CityService
from src.services.vehicle_service import VehicleModelService
from src.forms.po_forms import POCreationForm
from src.utils.decorators import role_required
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _sees_every_po() -> bool:
    """Whether this user's Sales Dashboard covers the whole order book.

    Only the Administrator and the Installation team do. Everyone else sees
    the orders they raised and nothing else - a PO created by Sales Person A
    is never visible to Sales Person B, including through a filter they might
    put on the query string themselves.

    Stated once, here, because the list, the kanban counts above it and the
    salesperson picker all have to agree about it. Two of them agreeing and
    one not is how a count leaks the size of a pipeline whose records are
    correctly hidden.
    """
    return current_user.is_admin() or current_user.is_installation() or current_user.is_executive()


@sales_bp.route('/dashboard')
@login_required
@role_required('sales', 'admin', 'installation', 'executive')
def dashboard():
    """Sales dashboard - a PO created by Sales Person A is never visible to
    Sales Person B; only Administrator and the Installation team see/manage
    every PO regardless of who created it.

    Searching by salesperson is the Administrator's alone: for anyone else
    the answer is already fixed to themselves, so the control would be a
    choice with one option - and for a sales person, a way to ask about
    somebody else's book.
    """
    po_service = POService()

    # Get filters
    search = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    city_filter = request.args.get('city', '')
    sales_person_filter = (request.args.get('sales_person') or '').strip()

    # Build filters
    filters: Dict[str, Any] = {}
    if status_filter:
        filters['status'] = status_filter
    if city_filter:
        filters['city'] = city_filter

    if _sees_every_po():
        # The salesperson filter is read from the query string only for those
        # who may narrow it; for anyone else the scope below overrides it, so
        # a hand-typed `?sales_person=` cannot widen or redirect the view.
        if current_user.is_admin() and sales_person_filter.isdigit():
            filters['sales_person_id'] = int(sales_person_filter)
        logger.info(f"{current_user.username} ({current_user.role}) viewing all POs")
    else:
        sales_person_filter = ''
        filters['sales_person_id'] = current_user.id
        logger.info(f"User {current_user.username} viewing their own POs")

    # Get orders
    result = po_service.get_pos(filters=filters, search=search)
    orders = result['items']

    # Kanban counts. Deliberately computed over the whole pipeline in view
    # rather than the filtered page below - a "Completed 12" card that drops
    # to 0 the moment you click it tells you nothing.
    card_stats = _po_card_stats(sales_person_filter)

    # Get cities for filter
    city_service = CityService()
    cities = city_service.get_all_cities()

    # Get sales users for admin filter
    sales_users = []
    if current_user.is_admin():
        sales_users = UserService().get_sales_users()

    return render_template('sales/dashboard.html',
                         orders=orders,
                         cities=cities,
                         sales_users=sales_users,
                         card_stats=card_stats,
                         search=search,
                         status_filter=status_filter,
                         city_filter=city_filter,
                         sales_person_filter=sales_person_filter)


def _po_card_stats(sales_person_filter: str = '') -> dict:
    """Purchase order counts for the dashboard's kanban cards.

    Scoped exactly like the list below them (see `_sees_every_po`), and
    narrowed to the same salesperson when the Administrator has picked one -
    otherwise the cards would count the whole book while the table beneath
    them showed one person's.

    Counted in SQL rather than through `POService.get_pos`, which paginates
    at 20 - a count taken from a page is a count of that page.
    """
    from datetime import datetime
    from src.models.purchase_order import PurchaseOrder

    def scoped():
        query = PurchaseOrder.query
        if not _sees_every_po():
            return query.filter(PurchaseOrder.sales_person_id == current_user.id)
        if current_user.is_admin() and sales_person_filter.isdigit():
            return query.filter(PurchaseOrder.sales_person_id == int(sales_person_filter))
        return query

    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    return {
        'total': scoped().count(),
        'pending': scoped().filter(PurchaseOrder.status == 'PENDING').count(),
        'in_progress': scoped().filter(PurchaseOrder.status == 'IN_PROGRESS').count(),
        'completed': scoped().filter(PurchaseOrder.status == 'COMPLETED').count(),
        'today': scoped().filter(PurchaseOrder.created_at >= midnight).count(),
    }


@sales_bp.route('/new', methods=['GET', 'POST'])
@login_required
@role_required('sales', 'admin')
def new_po():
    """Create new purchase order"""
    form = POCreationForm()
    form = populate_form_choices(form)
    # Handed to the form so picking a make narrows the model list in the
    # browser - see templates/_make_model_filter.html.
    make_model_map = VehicleModelService().get_make_model_map()

    if form.validate_on_submit():
        po_service = POService()
        
        # Determine sales person
        if current_user.is_sales():
            sales_person_id = current_user.id
        else:
            sales_person_id = form.sales_person_id.data
        
        # Validate sales_person_id
        if not sales_person_id:
            flash('Please select a sales person', 'danger')
            return render_template('sales/new_po.html', form=form, make_model_map=make_model_map)
        
        data = {
            'owner_name': form.owner_name.data.upper() if form.owner_name.data else '',
            'owner_contact': form.owner_contact.data,
            'contact_person_driver': form.contact_person_driver.data.upper() if form.contact_person_driver.data else None,
            'reg_no': form.reg_no.data.upper() if form.reg_no.data else '',
            'vehicle_make': form.vehicle_make.data.upper() if form.vehicle_make.data else '',
            'vehicle_model': form.vehicle_model.data.upper() if form.vehicle_model.data else '',
            # Vehicle year/color, engine/chassis numbers aren't collected on
            # this simplified creation form - the installer fills these in
            # when they update the PO (see installation.update_po).
            'vehicle_year': 'PENDING',
            'vehicle_color': 'PENDING',
            'engine_number': 'PENDING',
            'chassis_number': 'PENDING',
            'sales_person_id': int(sales_person_id),
            'city': None,
            'vehicle_availability_location': form.vehicle_availability_location.data.upper() if form.vehicle_availability_location.data else '',
            'existing_customer_name': form.existing_customer_name.data.upper() if form.existing_customer_name.data else None,
            'existing_vehicle_number': form.existing_vehicle_number.data.upper() if form.existing_vehicle_number.data else None,
            # Not collected on this simplified creation form - set during
            # installation scheduling instead.
            'scheduled_date': None,
            'rates': form.rates.data or 0.0,
            'amc': form.amc.data or 0.0,
        }
        
        try:
            po = po_service.create_po(data, current_user.id)
            flash(f'Purchase Order {po.po_number} created successfully!', 'success')
            return redirect(url_for('sales.dashboard'))
        except Exception as e:
            flash(f'Error creating PO: {str(e)}', 'danger')
    
    return render_template('sales/new_po.html', form=form, make_model_map=make_model_map)


@sales_bp.route('/pos/<int:po_id>')
@login_required
@role_required('sales', 'admin', 'installation', 'executive')
def po_detail(po_id):
    """View PO details - Sales can only see their own POs; Admin and
    Installation can view (and, via their own module, update) any PO."""
    po_service = POService()
    po = po_service.get_po(po_id)
    
    if not po:
        flash('PO not found', 'danger')
        return redirect(url_for('sales.dashboard'))
    
    # ✅ SALES: Can only view their own POs
    if current_user.is_sales() and po.sales_person_id != current_user.id:
        flash('You do not have permission to view this PO', 'danger')
        return redirect(url_for('sales.dashboard'))

    return render_template('sales/po_detail.html', po=po)


@sales_bp.route('/pos/<int:po_id>/certificate')
@login_required
@role_required('sales', 'admin', 'installation', 'executive')
def po_certificate(po_id):
    """Download the Tracker Certificate for a completed PO.

    `?format=excel` returns the same certificate as a spreadsheet - some
    insurers want the particulars as data rather than as a printed page.
    Either way the file is named REGISTRATION_TRACKER_CERTIFICATE, so it is
    identifiable once it has left the CRM.
    """
    import os
    from flask import send_file
    from src.services.pdf_service import PDFService

    po_service = POService()
    po = po_service.get_po(po_id)

    if not po:
        flash('PO not found', 'danger')
        return redirect(url_for('sales.dashboard'))

    if current_user.is_sales() and po.sales_person_id != current_user.id:
        flash('You do not have permission to view this PO', 'danger')
        return redirect(url_for('sales.dashboard'))

    if po.status != 'COMPLETED':
        flash('Tracker Certificate can only be generated once the installation is completed', 'warning')
        return redirect(url_for('sales.po_detail', po_id=po_id))

    # Anything other than an explicit excel request is the PDF - an unknown
    # value must not produce a file nobody asked for.
    as_excel = (request.args.get('format') or '').strip().lower() == 'excel'

    pdf_service = PDFService()
    filepath = (pdf_service.generate_tracker_certificate_excel(po_id) if as_excel
                else pdf_service.generate_tracker_certificate(po_id))

    if filepath and os.path.exists(filepath):
        return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))

    flash('Unable to generate Tracker Certificate', 'danger')
    return redirect(url_for('sales.po_detail', po_id=po_id))


def populate_form_choices(form):
    """Populate form choices"""
    from src.services.vehicle_service import (
        VehicleMakeService, VehicleModelService, VehicleYearService,
        VehicleColorService, CityService
    )
    from src.services.user_service import UserService
    
    if hasattr(form, 'vehicle_make'):
        form.vehicle_make.choices = [('', 'Select Make')] + [(m.name, m.name) for m in VehicleMakeService().get_all_makes()]
    if hasattr(form, 'vehicle_model'):
        form.vehicle_model.choices = [('', 'Select Model')] + [(m.name, m.name) for m in VehicleModelService().get_all()]
    if hasattr(form, 'vehicle_year'):
        form.vehicle_year.choices = [('', 'Select Year')] + VehicleYearService().get_year_choices()
    if hasattr(form, 'vehicle_color'):
        form.vehicle_color.choices = [('', 'Select Color')] + [(c.name, c.name) for c in VehicleColorService().get_all_colors()]
    if hasattr(form, 'city'):
        form.city.choices = [('', 'Select City')] + [(c.name, c.name) for c in CityService().get_all_cities()]
    if hasattr(form, 'sales_person_id'):
        form.sales_person_id.choices = [('', 'Select Sales Person')] + [(u.id, u.name or u.username) for u in UserService().get_sales_users()]
    
    return form