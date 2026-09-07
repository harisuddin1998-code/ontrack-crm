# src/web/inventory.py
"""
Inventory Routes - Device stock synced from SJ_MIS gs_objects, cross-linked
with the Installation and REDO modules by IMEI.
"""
from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from src.web import inventory_bp
from src.extensions import db
from src.models.inventory import InventoryDevice
from src.services.inventory_service import InventoryService
from src.utils.decorators import role_required
from src.utils.logging import get_logger

logger = get_logger(__name__)


@inventory_bp.route('/dashboard')
@login_required
@role_required('installation', 'redo_technician', 'inventory', 'admin', 'manager', 'executive')
def dashboard():
    """Inventory dashboard - all GPS devices synced from SJ_MIS, their
    assignment/install status, and cross-referenced install history."""
    from src.services.technician_service import TechnicianService

    service = InventoryService()

    status_filter = request.args.get('status', '').strip()
    search = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 50

    query = InventoryDevice.query
    if status_filter:
        query = query.filter(InventoryDevice.status == status_filter)
    if search:
        pattern = f"%{search}%"
        query = query.filter(db.or_(
            InventoryDevice.imei.ilike(pattern),
            InventoryDevice.sim_number.ilike(pattern),
            InventoryDevice.device_name.ilike(pattern),
            InventoryDevice.plate_number.ilike(pattern),
        ))

    total = query.count()
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    devices = query.order_by(InventoryDevice.imei).offset((page - 1) * per_page).limit(per_page).all()

    # Batch-fetch linked records for the visible page instead of querying
    # per-row, so a page of devices doesn't fire 2x N extra queries.
    imeis = [d.imei for d in devices]
    linked = _batch_linked_records(imeis)

    stats = service.get_dashboard_stats()
    technicians = TechnicianService.get_roster()

    return render_template('inventory/dashboard.html',
                         devices=devices,
                         linked=linked,
                         stats=stats,
                         technicians=technicians,
                         status_filter=status_filter,
                         search=search,
                         page=page,
                         total_pages=total_pages,
                         total=total,
                         per_page=per_page)


def _batch_linked_records(imeis):
    """Cross-reference a batch of IMEIs against PurchaseOrder/RedoActivity in
    two queries total, rather than InventoryService.get_linked_records()'s
    two-queries-per-device (fine for a single detail lookup, too slow for a
    list page)."""
    from src.models.purchase_order import PurchaseOrder
    from src.models.redo import RedoActivity

    if not imeis:
        return {}

    result = {imei: {'po': None, 'redo': None} for imei in imeis}

    for po in PurchaseOrder.query.filter(PurchaseOrder.imei_no.in_(imeis)).all():
        if po.imei_no in result:
            result[po.imei_no]['po'] = po

    for redo in RedoActivity.query.filter(
        db.or_(RedoActivity.imei_no.in_(imeis), RedoActivity.new_device.in_(imeis))
    ).all():
        key = redo.imei_no if redo.imei_no in result else redo.new_device
        if key in result:
            result[key]['redo'] = redo

    return result


@inventory_bp.route('/sync', methods=['POST'])
@login_required
@role_required('inventory', 'admin')
def sync():
    """Admin-triggered pull of the device catalog from SJ_MIS gs_objects."""
    service = InventoryService()
    result = service.sync_from_sj_mis()
    if result.get('error'):
        flash('Inventory sync failed - could not reach SJ_MIS. Check server connectivity.', 'danger')
    else:
        flash(f"Inventory synced: {result['new']} new, {result['updated']} updated.", 'success')
    return redirect(url_for('inventory.dashboard'))


@inventory_bp.route('/<int:device_id>/assign', methods=['POST'])
@login_required
@role_required('inventory', 'admin')
def assign(device_id):
    """Issue a device to a technician's field stock."""
    from src.models.technician import Technician

    device = InventoryDevice.query.get_or_404(device_id)
    technician_id = request.form.get('technician_id')
    if not technician_id:
        flash('No technician selected.', 'danger')
        return redirect(url_for('inventory.dashboard'))

    tech = Technician.query.get(int(technician_id))
    if not tech:
        flash('Technician not found.', 'danger')
        return redirect(url_for('inventory.dashboard'))

    device.assign_to(tech.id, current_user.id)
    flash(f"Device {device.imei} assigned to {tech.name}.", 'success')
    return redirect(url_for('inventory.dashboard'))


@inventory_bp.route('/<int:device_id>/unassign', methods=['POST'])
@login_required
@role_required('inventory', 'admin')
def unassign(device_id):
    """Return a device to general stock."""
    device = InventoryDevice.query.get_or_404(device_id)
    device.unassign()
    flash(f"Device {device.imei} returned to stock.", 'success')
    return redirect(url_for('inventory.dashboard'))


@inventory_bp.route('/api/technician-devices/<name>')
@login_required
def technician_devices(name):
    """AJAX endpoint for the REDO/Installation forms: once a technician is
    selected, return only the IMEIs actually assigned to them - not the
    entire inventory catalog."""
    service = InventoryService()
    devices = service.get_technician_devices(name)
    return jsonify({
        'devices': [
            {'imei': d.imei, 'sim_number': d.sim_number, 'device_name': d.device_name}
            for d in devices
        ]
    })


@inventory_bp.route('/stock')
@login_required
@role_required('admin', 'manager', 'inventory', 'executive')
def stock():
    """Stock & Accessories - non-device consumables (tape, relays, sensors,
    converters, etc.) and old stock issue, plus a per-technician daily
    issuance log. Separate tab from the GPS device stock above, since
    these are bulk consumables with no SJ_MIS source - entered manually
    each month, mirroring the report the Inventory Manager shares."""
    from datetime import date as date_cls
    from src.services.technician_service import TechnicianService
    from src.models.inventory import InventoryStockItem

    service = InventoryService()

    period = request.args.get('period', date_cls.today().strftime('%Y-%m'))
    issue_date_str = request.args.get('issue_date', date_cls.today().isoformat())
    try:
        issue_date = date_cls.fromisoformat(issue_date_str)
    except ValueError:
        issue_date = date_cls.today()

    items = service.get_stock_items(period)

    # `short=1` backs the admin dashboard's Stock Shortages card. That card
    # counts items whose remaining stock has gone negative, so clicking it
    # has to show those rows and not the full stock sheet.
    short_only = request.args.get('short') in ('1', 'true', 'yes')
    if short_only:
        items = [i for i in items if i.get_remaining() < 0]

    accessories = [i for i in items if i.category == InventoryStockItem.CATEGORY_ACCESSORY]
    old_stock = [i for i in items if i.category == InventoryStockItem.CATEGORY_OLD_STOCK]

    technicians = TechnicianService.get_roster()
    issuances = service.get_technician_issuances(issue_date)

    return render_template('inventory/stock.html',
                         period=period,
                         issue_date=issue_date,
                         accessories=accessories,
                         old_stock=old_stock,
                         short_only=short_only,
                         technicians=technicians,
                         issuances=issuances)


@inventory_bp.route('/stock/item', methods=['POST'])
@login_required
@role_required('admin', 'manager', 'inventory')
def stock_item_upsert():
    """Add or correct one stock item's Received/Issued figures for a period."""
    from src.models.inventory import InventoryStockItem

    name = (request.form.get('name') or '').strip()
    category = request.form.get('category', InventoryStockItem.CATEGORY_ACCESSORY)
    period = (request.form.get('period') or '').strip()
    try:
        total_received = float(request.form.get('total_received') or 0)
        total_issued = float(request.form.get('total_issued') or 0)
    except ValueError:
        flash('Received/Issued must be numbers.', 'danger')
        return redirect(url_for('inventory.stock', period=period))

    if not name or not period:
        flash('Item name and period are required.', 'danger')
        return redirect(url_for('inventory.stock', period=period))

    InventoryService().upsert_stock_item(name, category, period, total_received, total_issued)
    flash(f"{name} updated for {period}.", 'success')
    return redirect(url_for('inventory.stock', period=period))


@inventory_bp.route('/stock/item/<int:item_id>/delete', methods=['POST'])
@login_required
@role_required('admin', 'manager', 'inventory')
def stock_item_delete(item_id):
    """Remove a stock item row (e.g. entered under the wrong period/name)."""
    period = request.form.get('period', '')
    InventoryService().delete_stock_item(item_id)
    flash('Stock item removed.', 'success')
    return redirect(url_for('inventory.stock', period=period))


@inventory_bp.route('/stock/issuance', methods=['POST'])
@login_required
@role_required('admin', 'manager', 'inventory')
def stock_issuance_upsert():
    """Record how many accessory units a technician was issued on a given
    day. The technician dropdown/list this posts against is always built
    from the live Technician table (see the stock() view), so newly added
    or removed technicians are reflected automatically."""
    from datetime import date as date_cls

    technician_id = request.form.get('technician_id', type=int)
    issue_date_str = request.form.get('issue_date', '')
    try:
        quantity = float(request.form.get('quantity') or 0)
        issue_date = date_cls.fromisoformat(issue_date_str)
    except ValueError:
        flash('Invalid quantity or date.', 'danger')
        return redirect(url_for('inventory.stock'))

    if not technician_id:
        flash('No technician selected.', 'danger')
        return redirect(url_for('inventory.stock', issue_date=issue_date_str))

    InventoryService().upsert_technician_issuance(technician_id, issue_date, quantity)
    flash('Issuance recorded.', 'success')
    return redirect(url_for('inventory.stock', issue_date=issue_date_str))
