# src/web/redo.py
"""
REDO Activity and Non-Reporting Vehicle Routes
"""
from datetime import datetime
from typing import Any, Dict
from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from types import SimpleNamespace

from src.web import redo_bp
from src.extensions import db
from src.services import RedoService, NonReportingService
from src.forms.redo_forms import RedoForm, NonReportingConversationForm
from src.utils.decorators import role_required
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _attach_sales_persons(activities) -> None:
    """Stamp each activity with the salesperson from its vehicle's PO.

    The salesperson belongs to the order that sold the vehicle, not to the
    service visit, so the wallboard reads it back from PurchaseOrder rather
    than trusting whatever was typed on the REDO. Resolved in one query over
    the registration numbers on screen - a per-row lookup would be one query
    per row on a board that regularly shows hundreds.

    A REDO's own `sale_person` is the fallback: rows created before the form
    pulled the name from the PO still have it, and the external data source
    has no PO at all.
    """
    from sqlalchemy import func
    from src.models.purchase_order import PurchaseOrder

    reg_nos = {(getattr(act, 'registration_no', '') or '').strip().upper()
               for act in activities}
    reg_nos.discard('')
    if not reg_nos:
        return

    # Read in batches: showing completed work puts every REDO ever raised on
    # the board, and one IN clause with that many registrations runs into the
    # database's bind-parameter ceiling.
    BATCH = 500
    registrations = sorted(reg_nos)

    # Ascending id, so a later order overwrites an earlier one and the newest
    # PO per registration is the one left standing - a vehicle re-sold to a
    # new owner belongs to the current order, not the original one.
    by_reg = {}
    for start in range(0, len(registrations), BATCH):
        batch = registrations[start:start + BATCH]
        for po in (PurchaseOrder.query
                   .filter(func.upper(PurchaseOrder.reg_no).in_(batch))
                   .order_by(PurchaseOrder.id.asc())
                   .all()):
            name = ''
            if po.sales_person:
                name = po.sales_person.name or po.sales_person.username or ''
            name = name or (po.arranged_by_sales_person or '')
            if name:
                by_reg[(po.reg_no or '').strip().upper()] = name

    for act in activities:
        reg = (getattr(act, 'registration_no', '') or '').strip().upper()
        setattr(act, 'sale_person',
                by_reg.get(reg) or getattr(act, 'sale_person', None) or '')


@redo_bp.route('/')
@redo_bp.route('/dashboard')
@login_required
@role_required('redo_technician', 'admin', 'executive')
def dashboard():
    """REDO dashboard with aging buckets, SLA escalation, corporate tab & external DB integration"""
    from datetime import datetime
    redo_service = RedoService()
    
    # Determine data source - use external DB if available
    use_external_db = request.args.get('source', 'internal') == 'external'
    
    if use_external_db:
        # Fetch from external SJ_MIS database
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 100, type=int)
        external_result = redo_service.get_external_redo_data(page=page, per_page=per_page)
        
        activities = []
        for item in external_result.get('items', []):
            # Create a SimpleNamespace object to mimic RedoActivity
            act = SimpleNamespace(
                id=item.get('ir_id'),
                registration_no=item.get('registration_no'),
                customer_name=item.get('customer_name'),
                customer_contact=item.get('customer_contact'),
                engine_no=item.get('engine_no'),
                chassis_no=item.get('chassis_no'),
                imei_no=item.get('imei_no'),
                sim_no=item.get('sim_no'),
                device_location=item.get('device_location'),
                age_hours=item.get('age_hours'),
                sla_exceeded=item.get('sla_exceeded', False),
                status='PENDING',  # External data is always pending
                priority='NORMAL',
                created_at=item.get('dt_server') or item.get('dt_tracker'),
                assigned_to=None,
                assigned_to_user=None,
                assigned_by=None,
                assigned_by_user=None,
                assigned_at=None,
                completed_by=None,
                completed_by_user=None,
                completed_at=None,
                rework_completed_date=None,
                completion_notes=None,
                rework_reason=None,
                issue_description=None,
                previous_installation_notes=None,
                make='N/A',
                model='N/A',
                year=None,
                color=None,
                technician=item.get('technician', 'Unassigned'),
                source='external_db'
            )
            activities.append(act)
        
        stats = {
            'total': external_result.get('total', 0),
            'this_month': external_result.get('total', 0),
            'pending': len(activities),
            'in_progress': 0,
            'completed': 0,
            'cancelled': 0,
            'pending_verification': 0,
        }

    else:
        # Use internal database
        show_completed = request.args.get('show_completed', 'false') == 'true'

        # Both NR Team and administrators view all active activities across the board
        if show_completed:
            activities = redo_service.get_all()
        else:
            activities = redo_service.get_active_activities()


        stats = redo_service.get_dashboard_stats()

        now = datetime.now()

        for act in activities:
            # Calculate age in hours (still used to highlight SLA-breaching rows in the list)
            created = act.created_at or now
            age_hours = (now - created).total_seconds() / 3600.0
            act.age_hours = round(age_hours, 1)
            act.sla_exceeded = (age_hours > 24.0 and act.status != 'COMPLETED')

    # Aging since technician assignment - shown on the Wallboard list as hours
    # while pending, switching to days once the REDO has been outstanding
    # more than 24 hours. Completed REDOs don't keep aging.
    now = datetime.now()
    for act in activities:
        if getattr(act, 'status', None) == 'COMPLETED':
            setattr(act, 'aging_display', 'Completed')
            # Finished work has stopped aging, so it sorts below everything
            # still outstanding rather than by however long it once took.
            setattr(act, 'aging_hours', -1.0)
            continue
        ref_time = getattr(act, 'assigned_at', None) or getattr(act, 'created_at', None) or now
        hours = max(0.0, (now - ref_time).total_seconds() / 3600.0)
        setattr(act, 'aging_hours', hours)
        if hours <= 24:
            setattr(act, 'aging_display', f"{round(hours, 1)} hrs")
        else:
            days = int(hours // 24)
            setattr(act, 'aging_display', f"{days} day{'s' if days != 1 else ''}")

    # The wallboard is one linear list, not three status columns, so this
    # ordering is the only thing putting urgent work in front of whoever is
    # reading it. Breached SLAs first, then longest-waiting first inside each
    # group: a job outstanding six days outranks one raised this morning, and
    # newest-first buried exactly the rows that needed attention.
    #
    # Sorted on the same figure the Aging column prints - measured from
    # assignment, not from creation - so the order visibly explains itself.
    # Ranking by one clock and displaying another reads as no order at all.
    activities.sort(key=lambda act: (
        0 if getattr(act, 'sla_exceeded', False) else 1,
        -getattr(act, 'aging_hours', 0.0),
    ))

    # SLA/TAT aging buckets - mirror the Non-Reporting System Dashboard exactly
    # (same source, same bucket definitions) rather than computing a second,
    # independent aging metric from REDO activity age. A REDO's real urgency
    # comes from how long its vehicle has been offline, not how long the
    # activity record itself has existed.
    nr_service = NonReportingService()
    bucket_counts = {'24 Hours': 0, '25-36 Hours': 0, '37-48 Hours': 0, '48+ Hours': 0}
    for v in nr_service.get_all_confirmed():
        b = v.get_aging_bucket()
        if b in bucket_counts:
            bucket_counts[b] += 1

    # A status card on the wallboard filters both the kanban board and the
    # list below it. Applied here rather than in each query above so it works
    # the same for the internal and the external data source.
    status_filter = (request.args.get('status') or '').strip().upper()
    if status_filter:
        activities = [a for a in activities
                      if (getattr(a, 'status', '') or '').upper() == status_filter]

    # `created=today` is the standalone "raised today" view. The admin
    # dashboard's REDO cards now carry the board's timeframe as `since`
    # instead, but this stays a valid filter. Same reasoning as the status
    # filter above, and applied in the same place so it works for both data
    # sources.
    created_filter = (request.args.get('created') or '').strip().lower()
    if created_filter == 'today':
        today = datetime.now().date()
        # The external source hands back created_at as whatever the remote
        # column held, which is not always a datetime - hence the hasattr.
        activities = [a for a in activities
                      if hasattr(getattr(a, 'created_at', None), 'date')
                      and a.created_at.date() == today]

    # `since=YYYY-MM-DD` and `aging=` back the REDO Turnaround cards on the
    # Administration and Executive dashboards. Both measure from creation and
    # ignore completed work, exactly as those cards counted - a card that says
    # 7 has to land on 7 rows, or it is not a link to its own figure.
    since_filter = (request.args.get('since') or '').strip()
    if since_filter:
        try:
            since_dt = datetime.strptime(since_filter, '%Y-%m-%d')
            activities = [a for a in activities
                          if hasattr(getattr(a, 'created_at', None), 'date')
                          and a.created_at >= since_dt]
        except ValueError:
            pass  # a malformed date filters nothing rather than everything

    aging_filter = (request.args.get('aging') or '').strip().lower()
    # (lower bound exclusive, upper bound inclusive) in hours since creation
    AGING_BANDS = {'over24': (24.0, 36.0), 'over36': (36.0, 48.0),
                   'breached': (48.0, None)}
    if aging_filter in AGING_BANDS:
        low, high = AGING_BANDS[aging_filter]

        def _in_band(act):
            if (getattr(act, 'status', '') or '').upper() in ('COMPLETED', 'CANCELLED'):
                return False
            created = getattr(act, 'created_at', None)
            if created is None or not hasattr(created, 'date'):
                return False
            hours = (now - created).total_seconds() / 3600.0
            return hours > low and (high is None or hours <= high)

        activities = [a for a in activities if _in_band(a)]

    # Search filter on Wallboard (registration, customer, technician, redo number, city, imei)
    search = (request.args.get('search') or '').strip()
    if search:
        search_lower = search.lower()
        activities = [
            a for a in activities
            if search_lower in (getattr(a, 'registration_no', '') or '').lower()
            or search_lower in (getattr(a, 'customer_name', '') or '').lower()
            or search_lower in (getattr(a, 'technician', '') or '').lower()
            or search_lower in (getattr(a, 'redo_number', '') or '').lower()
            or search_lower in (getattr(a, 'city', '') or '').lower()
            or search_lower in (getattr(a, 'imei_no', '') or '').lower()
            or search_lower in (getattr(a, 'issue_description', '') or '').lower()
        ]

    # Follow-up reminders and summary metrics for the Follow-Up Module
    from src.models.gps import NonReportingVehicle
    today_date = datetime.now().date()
    followup_q = NonReportingVehicle.query.filter(
        db.or_(
            NonReportingVehicle.status == 'FOLLOW_UP',
            db.and_(
                NonReportingVehicle.contact_outcome.isnot(None),
                NonReportingVehicle.contact_outcome != '',
                NonReportingVehicle.contact_outcome != 'Technician Assigned',
                NonReportingVehicle.status.in_(['FOLLOW_UP', 'PENDING', 'ESCALATED'])
            )
        )
    )
    all_followups = followup_q.all()
    due_today_count = sum(1 for v in all_followups if v.next_followup_date == today_date or v.scheduled_date == today_date)
    overdue_count = sum(
        1 for v in all_followups
        if (v.next_followup_date and v.next_followup_date < today_date)
        or (v.scheduled_date and v.scheduled_date < today_date)
    )
    followup_stats = {
        'due_today': due_today_count,
        'overdue': overdue_count,
        'total': len(all_followups)
    }

    _attach_sales_persons(activities)

    return render_template('redo/dashboard.html',
                         activities=activities,
                         stats=stats,
                         bucket_counts=bucket_counts,
                         status_filter=status_filter,
                         created_filter=created_filter,
                         search=search,
                         followup_stats=followup_stats,
                         use_external_db=use_external_db)


@redo_bp.route('/new', methods=['GET', 'POST'])
@redo_bp.route('/create', methods=['GET', 'POST'])
@login_required
@role_required('redo_technician', 'admin')
def new():
    """Create new REDO activity with full control specifications and auto REDO ID"""
    from src.models.user import User
    from src.models.redo import RedoActivity
    
    form = RedoForm()
    
    # Auto-populate Arranged By (ADMIN if admin role, else user name) & Testing By
    if request.method == 'GET':
        if current_user.role == 'admin':
            form.arranged_by.data = 'ADMIN'
        else:
            form.arranged_by.data = current_user.name or current_user.username
        form.tested_by.data = current_user.name or current_user.username

        # Scheduling a REDO from the Non-Reporting dashboard passes the
        # vehicle's reg no through - prefill it here; the page's own
        # vehicle-lookup JS pulls the rest of the vehicle/customer data
        # automatically on load once this field has a value.
        prefill_reg_no = request.args.get('reg_no', '').strip()
        if prefill_reg_no:
            form.registration_no.data = prefill_reg_no.upper()
    
    # Populate technician choices from the Technician Management roster
    # only - no User accounts, no seed/placeholder data.
    from src.services.technician_service import TechnicianService
    technicians = TechnicianService.get_roster()
    form.technician.choices = [('', '-- Select Technician --')] + [(t.name, t.name) for t in technicians]
    
    redo_service = RedoService()
    
    if request.method == 'POST' and form.validate():
        try:
            # The technician field is a free-text name (matching the dropdown
            # label) - resolve it to the actual user so the activity shows up
            # on that technician's own dashboard, which filters strictly by
            # the assigned_to foreign key.
            assigned_technician = None
            if form.technician.data:
                assigned_technician = User.query.filter(
                    db.or_(User.name == form.technician.data, User.username == form.technician.data),
                    User.role == 'redo_technician'
                ).first()

            # Device swap (missing device / power issue scenarios): when a
            # New Device or New SIM is entered, the vehicle's current
            # IMEI/SIM becomes the recorded "old" value and the new one
            # takes over as the active IMEI/SIM - simple before/after
            # snapshot, not a full historical chain.
            imei_no = form.imei_no.data
            sim_no = form.sim_no.data
            old_imei_no = form.old_imei_no.data
            old_sim_no = form.old_sim_no.data
            if form.new_device.data:
                old_imei_no = form.imei_no.data
                imei_no = form.new_device.data
            if form.new_sim.data:
                old_sim_no = form.sim_no.data
                sim_no = form.new_sim.data

            data = {
                'activity_type': form.activity_type.data,
                'scheduled_date': form.scheduled_date.data,
                'customer_name': form.customer_name.data,
                'customer_contact': form.customer_contact.data,
                'sale_person': form.sale_person.data,
                'arranged_by': form.arranged_by.data or ('ADMIN' if current_user.role == 'admin' else (current_user.name or current_user.username)),
                'registration_no': (form.registration_no.data or '').strip().upper(),
                'make': form.make.data,
                'model': form.model.data,
                'year': form.year.data,
                'color': form.color.data,
                'chassis_no': form.chassis_no.data,
                'engine_no': form.engine_no.data,
                'imei_no': imei_no,
                'sim_no': sim_no,
                'device_type': form.device_type.data,
                'device_location': form.device_location.data,
                'old_imei_no': old_imei_no,
                'old_sim_no': old_sim_no,
                'new_device': form.new_device.data,
                'new_sim': form.new_sim.data,
                'device_change_reason': form.device_change_reason.data or None,
                'transfer_installation': form.transfer_installation.data,
                'transfer_charges': form.transfer_charges.data,
                'city': form.city.data,
                'vehicle_location': form.vehicle_location.data,
                'technician': form.technician.data,
                'assigned_to': assigned_technician.id if assigned_technician else None,
                'tested_by': form.tested_by.data or (current_user.name or current_user.username),
                'fuel': form.fuel.data,
                'resolution_status': form.resolution_status.data,
                'remarks': form.remarks.data,
            }
            
            # If status marked completed, set status to COMPLETED
            if data['resolution_status'] == 'Completed':
                data['status'] = 'COMPLETED'
                data['completed_at'] = datetime.now()
            
            redo = redo_service.create_redo(data, current_user.id)

            # Keep Inventory in sync: if the IMEI or the New Device swapped
            # in here matches a known inventory unit, flip it to INSTALLED
            # so the device catalog reflects where it actually ended up.
            from src.services.inventory_service import InventoryService
            inventory_service = InventoryService()
            inventory_service.mark_installed_if_known(redo.imei_no, redo.registration_no)
            inventory_service.mark_installed_if_known(redo.new_device, redo.registration_no)

            # A device_change_reason of Power Issue / Device Damage / Water
            # Damage / Device Missing creates an Installation Recovery
            # charge automatically - no separate step for the officer.
            from src.services.installation_recovery_service import InstallationRecoveryService
            InstallationRecoveryService().create_charge_if_applicable(redo, current_user.id)

            # If marked complete, send email
            if redo.status == 'COMPLETED':
                redo_service.complete_redo(redo.id, current_user.id, redo.remarks)  # type: ignore[arg-type]

            # Scheduling a REDO is the resolution step for a non-reporting
            # vehicle - reflect that back on its Non-Reporting record so it
            # shows as "Technician In Progress" there instead of still
            # sitting in "Pending Follow-up".
            from src.models.gps import NonReportingVehicle
            nr_vehicle = NonReportingVehicle.query.filter_by(registration_no=redo.registration_no).first()
            if nr_vehicle and nr_vehicle.status == 'PENDING':
                nr_vehicle.status = 'IN_PROGRESS'
                db.session.commit()

            flash(f'REDO Record {redo.redo_number} created successfully for vehicle {redo.registration_no}!', 'success')
            return redirect(url_for('redo.new'))
        except Exception as e:
            logger.error(f"Error creating REDO entry: {e}")
            flash(f'Error creating REDO record: {e}', 'danger')

    auto_redo_number = RedoActivity.generate_redo_number()
    recent_redos = redo_service.get_recent(limit=15)
    
    from src.models.installation_recovery import RECOVERY_AMOUNT_BY_REASON
    return render_template('redo/redo_form.html', form=form, auto_redo_number=auto_redo_number,
                         recent_redos=recent_redos, recovery_amount_map=RECOVERY_AMOUNT_BY_REASON)


@redo_bp.route('/api/vehicle-lookup', methods=['GET'])
@login_required
def vehicle_lookup():
    """Auto-pull vehicle data and REDO history from DB when Reg No or the
    customer's cell/contact number is typed or selected. Pulls across
    reporting AND non-reporting vehicles - any vehicle on record, regardless
    of current GPS reporting status, is eligible to be found."""
    from src.models.redo import RedoActivity
    from src.services import VehicleSearchService

    reg_no = request.args.get('reg_no', '').strip()
    contact_raw = request.args.get('contact', '').strip()

    service = VehicleSearchService()
    record = service.lookup_by_reg_no(reg_no) if reg_no else service.lookup_by_contact(contact_raw)

    if not record:
        return jsonify({'found': False})

    previous_redos = RedoActivity.query.filter(
        RedoActivity.registration_no.ilike(f"%{record['registration_no']}%")
    ).order_by(RedoActivity.created_at.desc()).all()

    return jsonify({
        'found': True,
        'registration_no': record['registration_no'],
        'customer_name': record['customer_name'],
        'customer_contact': record['customer_contact'],
        'manufacturer': record['manufacturer'],
        'brand': record['brand'],
        'model_year': record['model_year'],
        'color': record['color'],
        'transmission': record['transmission'],
        'power_cc': record['power_cc'],
        'chassis_no': record['chassis_no'],
        'engine_no': record['engine_no'],
        'imei_no': record['imei_no'],
        'sim_no': record['sim_no'],
        'device_location': record['unit_location'],
        'city': record['city'],
        # Straight off the vehicle's Purchase Order - the REDO form shows it
        # rather than asking the technician to pick a name.
        'sale_person': record['sale_person'],
        'po_id': record['po_id'],
        'po_number': record['po_number'],
        'is_reporting': record['is_reporting'],
        'reporting_status': record['reporting_status'],
        'last_service_by': record['last_service_by'],
        'previous_redo_count': len(previous_redos),
        'previous_redos': [
            {
                'redo_number': r.redo_number or f'REDO-{r.id}',
                'date': r.created_at.strftime('%d/%m/%Y'),
                'activity_type': r.activity_type or 'REDO',
                'technician': r.technician or (r.assigned_to_user.name if r.assigned_to_user else 'Unassigned'),
                'status': r.status,
                'remarks': r.remarks or r.completion_notes or ''
            } for r in previous_redos
        ]
    })


@redo_bp.route('/api/technician-info/<name>', methods=['GET'])
@login_required
def technician_info(name):
    """Get the technician's real GPS location, read off the tracker installed
    on their assigned motorbike (TechnicianBike.imei -> CurrentLocation), not
    a name match on the unrelated User model."""
    name_clean = name.strip()
    from src.models.technician import Technician

    technician = Technician.query.filter(Technician.name.ilike(name_clean)).first()
    if not technician:
        return jsonify({'name': name_clean, 'location_info': 'Technician not found'})

    bike = technician.bike
    if not bike:
        return jsonify({
            'name': name_clean,
            'location_info': f"{technician.name}: no bike/GPS tracker assigned"
        })

    location = bike.get_current_location()
    if not location or location.get('latitude') is None:
        return jsonify({
            'name': name_clean,
            'location_info': f"{technician.name}'s Bike ({bike.bike_registration}): GPS location not available"
        })

    address = location.get('address') or f"{location['latitude']}, {location['longitude']}"
    updated_str = ''
    if location.get('last_updated'):
        try:
            updated_str = f" (Updated {datetime.fromisoformat(location['last_updated']).strftime('%H:%M')})"
        except ValueError:
            pass
    # Plain address text for auto-filling the Vehicle Location field - no
    # technician/bike/status wrapper, just where the bike physically is.
    address_text = f"{address}{updated_str}"
    status_str = ' - Active' if location.get('is_active') else ' - Offline'
    location_str = f"{technician.name}'s Bike ({bike.bike_registration}): {address_text}{status_str}"

    return jsonify({
        'name': name_clean,
        'location_info': location_str,
        'vehicle_location_text': address_text,
        'latitude': location.get('latitude'),
        'longitude': location.get('longitude'),
    })


# What a history search may be run against. A whitelist rather than
# `hasattr(RedoActivity, search_by)`, which accepted any attribute name on the
# model - including ones that are not columns and blow up on .ilike().
REDO_HISTORY_SEARCH_FIELDS = [
    ('registration_no', 'Registration No.'),
    ('customer_name', 'Customer Name'),
    ('customer_contact', 'Contact Number'),
    ('redo_number', 'REDO ID'),
    ('imei_no', 'IMEI No.'),
    ('technician', 'Technician'),
    ('sale_person', 'Sales Person'),
]

REDO_HISTORY_LIMIT = 200


@redo_bp.route('/records', methods=['GET'])
@login_required
@role_required('redo_technician', 'admin', 'executive')
def redo_records():
    """Historical REDO activity - a read-only record of work already done.

    Deliberately its own page and not the entry form. Both were rendering
    `redo_form.html`, so the History action and the Perform-activity action on
    the wallboard opened the same screen, and the history was a footnote under
    a blank form that invited a new entry nobody had asked for.
    """
    from src.models.redo import RedoActivity

    search_by = request.args.get('search_by', 'registration_no')
    valid_fields = [name for name, _ in REDO_HISTORY_SEARCH_FIELDS]
    if search_by not in valid_fields:
        search_by = 'registration_no'
    search_term = request.args.get('search_term', '').strip()

    from src.services.redo_service import DEVICE_RECOVERY_REASONS

    query = RedoActivity.query.filter(
        db.or_(
            RedoActivity.device_change_reason.is_(None),
            RedoActivity.device_change_reason.notin_(DEVICE_RECOVERY_REASONS)
        )
    )
    if search_term:
        query = query.filter(getattr(RedoActivity, search_by).ilike(f"%{search_term}%"))

    records = (query.order_by(RedoActivity.created_at.desc())
               .limit(REDO_HISTORY_LIMIT).all())
    _attach_sales_persons(records)

    return render_template('redo/redo_history.html',
                           records=records,
                           search_by=search_by,
                           search_term=search_term,
                           search_fields=REDO_HISTORY_SEARCH_FIELDS,
                           result_limit=REDO_HISTORY_LIMIT)


@redo_bp.route('/<int:redo_id>/assign', methods=['POST'])
@login_required
@role_required('admin')
def assign(redo_id):
    """Assign REDO to technician"""
    redo_service = RedoService()
    technician_id = request.form.get('technician_id')
    if not technician_id:
        flash('No technician selected', 'danger')
        return redirect(url_for('redo.dashboard'))
    
    try:
        redo = redo_service.assign_technician(redo_id, int(technician_id), current_user.id)
        assigned_name = redo.assigned_to_user.name if (redo and redo.assigned_to_user) else 'Technician'
        flash(f'REDO assigned to {assigned_name}', 'success')
    except Exception as e:
        flash(str(e), 'danger')
    
    return redirect(url_for('redo.dashboard'))


@redo_bp.route('/<int:redo_id>/update', methods=['POST'])
@login_required
@role_required('redo_technician', 'admin')
def update(redo_id):
    """Update a REDO's status. Completing one sends the completion email.

    Ends on the wallboard, which is where the status just changed. It used to
    redirect to `redo.create_redo_entry`, an endpoint that does not exist -
    so marking a REDO done completed the record and sent the email, then
    raised a BuildError and showed the technician a 500 page. The work had
    gone through; only the page saying so had not.
    """
    redo_service = RedoService()
    status = request.form.get('status')
    notes = request.form.get('completion_notes', '')

    try:
        if status == 'COMPLETED':
            redo_service.complete_redo(redo_id, current_user.id, notes)
            flash('REDO completed - the completion email has been sent.', 'success')
        elif status:
            redo_service.update_status(redo_id, status)
            flash(f'REDO status updated to {status}', 'success')
    except Exception as e:
        logger.error(f"Could not update REDO {redo_id}: {e}")
        flash(str(e), 'danger')

    return redirect(url_for('redo.dashboard'))


# Non-Reporting Vehicles
@redo_bp.route('/non-reporting')
@login_required
@role_required('redo_technician', 'admin', 'executive')
def non_reporting_dashboard():
    """Non-reporting vehicle dashboard with hour-based buckets, pagination, and auto-sync"""
    nr_service = NonReportingService()
    
    source = request.args.get('source', 'internal')
    do_sync = request.args.get('sync', '0') == '1'
    status = request.args.get('status', '')
    search = request.args.get('search', '')
    bucket = request.args.get('bucket', '')
    page = request.args.get('page', 1, type=int)
    per_page = 25

    use_external_db = (source == 'external') or do_sync

    if use_external_db:
        try:
            sync_res = nr_service.sync_non_reporting_vehicles()
            if do_sync:
                flash(f'Live Data Sync Complete! New: {sync_res.get("new", 0)}, Updated: {sync_res.get("updated", 0)}, Removed (reconnected): {sync_res.get("removed", 0)}.', 'success')
        except Exception as e:
            logger.error(f"Error pulling live data: {e}")
            flash(f'Warning: Unable to sync live data ({e}). Showing cached data.', 'warning')
    
    filters = {}
    if status:
        filters['status'] = status

    # Aging buckets aren't evenly spread across pages (e.g. "48+ Hours" can be
    # the vast majority of records while "24 Hours" is a handful) - filtering
    # by bucket has to happen against the full matching set before pagination,
    # otherwise a bucket's vehicles can be entirely absent from page 1 and the
    # page appears empty even though the bucket count tile shows a real total.
    all_confirmed = nr_service.get_all_confirmed(filters=filters, search=search)

    bucket_counts = {'24 Hours': 0, '25-36 Hours': 0, '37-48 Hours': 0, '48+ Hours': 0}
    for v in all_confirmed:
        b = v.get_aging_bucket()
        if b in bucket_counts:
            bucket_counts[b] += 1

    if bucket:
        bucket_items = [v for v in all_confirmed if v.get_aging_bucket() == bucket]
        total = len(bucket_items)
        start = (page - 1) * per_page
        filtered_items = bucket_items[start:start + per_page]
    else:
        result = nr_service.get_vehicles(filters=filters, page=page, per_page=per_page, search=search)
        filtered_items = result['items']
        total = result['total']

    stats = nr_service.get_dashboard_stats()
    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template('redo/non_reporting_dashboard.html',
                         vehicles=filtered_items,
                         total=total,
                         stats=stats,
                         status=status,
                         search=search,
                         bucket=bucket,
                         bucket_counts=bucket_counts,
                         use_external_db=use_external_db,
                         source=source,
                         page=page,
                         per_page=per_page,
                         total_pages=total_pages)


@redo_bp.route('/non-reporting/corporate')
@login_required
@role_required('redo_technician', 'admin', 'executive')
def corporate_non_reporting_dashboard():
    """Corporate Non-Reporting Dashboard - the same aging-bucket/SLA
    monitoring as the main Non-Reporting dashboard, scoped to vehicles
    belonging to corporate clients (5+ vehicle fleets in SJ_MIS). The fleet
    roster is synced separately (see DBSyncService.sync_corporate_fleet) and
    cached in CorporateVehicle, since re-deriving fleet size from the full
    Vehicles table on every page load would be far too slow."""
    from src.models.corporate import CorporateVehicle
    from src.services.db_sync_service import DBSyncService

    nr_service = NonReportingService()

    do_sync = request.args.get('sync', '0') == '1'
    if do_sync:
        result = DBSyncService().sync_corporate_fleet()
        if result.get('error'):
            flash('Corporate fleet roster sync failed - could not reach SJ_MIS.', 'danger')
        else:
            flash(f"Corporate fleet roster synced: {result['clients']} clients, {result['vehicles']} vehicles.", 'success')

    roster = CorporateVehicle.query.all()
    if not roster:
        # First-ever visit - build the roster once automatically rather than
        # showing an empty page with no explanation.
        DBSyncService().sync_corporate_fleet()
        roster = CorporateVehicle.query.all()

    roster_map = {c.registration_no: c for c in roster}
    total_corporate_clients = len({c.client_id for c in roster})
    roster_synced_at = roster[0].synced_at if roster else None

    status = request.args.get('status', '')
    search = request.args.get('search', '')
    bucket = request.args.get('bucket', '')
    page = request.args.get('page', 1, type=int)
    clients_per_page = 10

    filters = {}
    if status:
        filters['status'] = status

    all_confirmed = nr_service.get_all_confirmed(filters=filters, search=search)
    all_corporate = [v for v in all_confirmed if v.registration_no in roster_map]

    bucket_counts = {'24 Hours': 0, '25-36 Hours': 0, '37-48 Hours': 0, '48+ Hours': 0}
    for v in all_corporate:
        b = v.get_aging_bucket()
        if b in bucket_counts:
            bucket_counts[b] += 1

    items = [v for v in all_corporate if v.get_aging_bucket() == bucket] if bucket else all_corporate
    total = len(items)

    # Club every client's non-reporting vehicles under one header instead of
    # an undifferentiated flat list - each corporate account should read as
    # one fleet, not N unrelated rows.
    groups_by_client: Dict[str, Dict[str, Any]] = {}
    for v in items:
        corp = roster_map.get(v.registration_no)
        client_id = corp.client_id if corp else 'UNKNOWN'
        group = groups_by_client.setdefault(client_id, {
            'client_id': client_id,
            'client_name': corp.client_name if corp else 'Unknown Client',
            'fleet_size': corp.fleet_size if corp else None,
            'vehicles': [],
        })
        group['vehicles'].append(v)

    client_groups = sorted(groups_by_client.values(), key=lambda g: len(g['vehicles']), reverse=True)
    total_clients_matched = len(client_groups)
    total_pages = max(1, (total_clients_matched + clients_per_page - 1) // clients_per_page)
    start = (page - 1) * clients_per_page
    page_groups = client_groups[start:start + clients_per_page]

    return render_template('redo/corporate_non_reporting_dashboard.html',
                         client_groups=page_groups,
                         roster_map=roster_map,
                         total=total,
                         total_clients_matched=total_clients_matched,
                         total_corporate_clients=total_corporate_clients,
                         roster_synced_at=roster_synced_at,
                         status=status,
                         search=search,
                         bucket=bucket,
                         bucket_counts=bucket_counts,
                         page=page,
                         per_page=clients_per_page,
                         total_pages=total_pages)


def _followup_conversations(outcome_filter: str, search: str, date_range=None, limit=500):
    """The follow-up conversations behind both the report and its download.

    One query for both, so the file always contains exactly what the screen
    that launched it was showing.
    """
    from src.models.gps import NonReportingConversation, NonReportingVehicle
    from src.utils.date_ranges import apply_range

    query = NonReportingConversation.query.join(
        NonReportingVehicle, NonReportingConversation.vehicle_id == NonReportingVehicle.id
    )
    if outcome_filter:
        query = query.filter(NonReportingVehicle.contact_outcome == outcome_filter)
    if search:
        pattern = f"%{search}%"
        query = query.filter(db.or_(
            NonReportingVehicle.registration_no.ilike(pattern),
            NonReportingVehicle.customer_name.ilike(pattern),
        ))
    if date_range:
        query = apply_range(query, NonReportingConversation.conversation_date, date_range)

    query = query.order_by(NonReportingConversation.conversation_date.desc())
    return query.limit(limit).all() if limit else query.all()


def _redo_scheduler_names(conversations):
    """Map registration number -> who scheduled that vehicle's REDO.

    Resolved in one pass rather than per row: the report renders up to 500
    conversations and most of them concern the same handful of vehicles.
    `assigned_by` is the signed-in user at the moment the REDO was raised, so
    it names the scheduler, not the technician it was handed to.
    """
    from src.models.redo import RedoActivity

    reg_nos = {c.vehicle.registration_no for c in conversations
               if c.vehicle and c.vehicle.registration_no}
    if not reg_nos:
        return {}

    scheduled = {}
    redos = (RedoActivity.query
             .filter(RedoActivity.registration_no.in_(reg_nos))
             .order_by(RedoActivity.created_at.asc())
             .all())
    for redo in redos:
        who = None
        if redo.assigned_by_user:
            who = redo.assigned_by_user.name or redo.assigned_by_user.username
        who = who or redo.arranged_by
        # Later REDOs overwrite earlier ones - the newest scheduling of a
        # vehicle is the one a follow-up call is about.
        scheduled[redo.registration_no] = {
            'scheduled_by': who,
            'redo_number': redo.redo_number,
            'technician': redo.technician,
        }
    return scheduled


@redo_bp.route('/reports/followup')
@login_required
@role_required('redo_technician', 'admin', 'executive')
def followup_report():
    """REDO Follow-up Report: full vehicle + conversation history for
    non-reporting follow-up calls, summarized by recorded contact outcome.

    Shows who scheduled each vehicle's REDO - the report exists to chase
    follow-ups, and the first question asked of a row is whose it was.
    """
    from sqlalchemy import func
    from src.models.gps import NonReportingVehicle
    from src.utils.date_ranges import parse_range

    outcome_filter = request.args.get('outcome', '').strip()
    search = request.args.get('search', '').strip()
    date_range = parse_range(request.args, default_to_current_month=False)

    conversations = _followup_conversations(outcome_filter, search, date_range)
    scheduled_by = _redo_scheduler_names(conversations)

    outcome_summary = {c: 0 for c in CONTACT_OUTCOME_CHOICES}
    outcome_summary['Not Yet Contacted'] = 0
    for outcome, count in db.session.query(
        NonReportingVehicle.contact_outcome, func.count(NonReportingVehicle.id)
    ).group_by(NonReportingVehicle.contact_outcome).all():
        key = outcome if outcome in outcome_summary else 'Not Yet Contacted'
        outcome_summary[key] += count

    return render_template('redo/followup_report.html',
                         conversations=conversations,
                         scheduled_by=scheduled_by,
                         outcome_summary=outcome_summary,
                         outcome_choices=CONTACT_OUTCOME_CHOICES,
                         outcome_filter=outcome_filter,
                         search=search,
                         date_range=date_range)


@redo_bp.route('/reports/followup/export')
@login_required
@role_required('redo_technician', 'admin', 'executive')
def followup_report_export():
    """Download the REDO Follow-up Report, filters and all."""
    import os
    from flask import send_file
    from src.services.mis_export_service import MISExportService
    from src.utils.date_ranges import parse_range

    conversations = _followup_conversations(
        request.args.get('outcome', '').strip(),
        request.args.get('search', '').strip(),
        parse_range(request.args, default_to_current_month=False),
        limit=None)

    filepath = MISExportService().generate_followup_excel(conversations)
    return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))


DEVICE_CHANGE_REASONS = ['Power Issue', 'Device Damage', 'Device Missing']


def _device_change_query(reason_filter: str, search: str, date_range=None):
    """The device-change query behind both the report and its download."""
    from src.models.redo import RedoActivity
    from src.utils.date_ranges import apply_range

    is_device_change = db.or_(
        db.and_(RedoActivity.new_device.isnot(None), RedoActivity.new_device != ''),
        db.and_(RedoActivity.new_sim.isnot(None), RedoActivity.new_sim != ''),
    )

    query = RedoActivity.query.filter(is_device_change)
    if reason_filter == 'Device Damage':
        query = query.filter(RedoActivity.device_change_reason.in_(['Device Damage', 'Device Burnt', 'Water Damage']))
    elif reason_filter:
        query = query.filter(RedoActivity.device_change_reason == reason_filter)
    if search:
        pattern = f"%{search}%"
        query = query.filter(db.or_(
            RedoActivity.registration_no.ilike(pattern),
            RedoActivity.customer_name.ilike(pattern),
        ))
    if date_range:
        query = apply_range(query, RedoActivity.created_at, date_range)
    return query.order_by(RedoActivity.created_at.desc())


@redo_bp.route('/reports/device-changes')
@login_required
@role_required('redo_technician', 'admin', 'executive')
def device_change_report():
    """Device Change Report: complete details of every REDO activity where
    a device was swapped (New Device/New SIM populated), summarized by the
    recorded change reason - Power Issue, Device Damage, or Device Missing.
    Historical rows saved under retired labels ("Device Burnt", "Water
    Damage") are normalized into the Device Damage bucket for both the
    summary counts and the reason filter, since they're the same condition.

    Viewable date-wise and downloadable; also emailed to senior management
    on the 1st of each month for the month just ended.
    """
    from src.models.redo import RedoActivity
    from src.models.installation_recovery import normalize_device_change_reason
    from src.utils.date_ranges import apply_range, parse_range

    from sqlalchemy import func

    reason_filter = request.args.get('reason', '').strip()
    search = request.args.get('search', '').strip()
    date_range = parse_range(request.args, default_to_current_month=False)

    changes = _device_change_query(reason_filter, search, date_range).limit(500).all()

    is_device_change = db.or_(
        db.and_(RedoActivity.new_device.isnot(None), RedoActivity.new_device != ''),
        db.and_(RedoActivity.new_sim.isnot(None), RedoActivity.new_sim != ''),
    )

    # The summary counts follow the same period as the table - a headline
    # that counts all time above a table showing one month is a trap.
    summary_query = apply_range(
        db.session.query(RedoActivity.device_change_reason, func.count(RedoActivity.id))
        .filter(is_device_change),
        RedoActivity.created_at, date_range)

    reason_summary = {r: 0 for r in DEVICE_CHANGE_REASONS}
    reason_summary['Not Specified'] = 0
    for reason, count in summary_query.group_by(RedoActivity.device_change_reason).all():
        normalized = normalize_device_change_reason(reason)
        key = normalized if normalized in reason_summary else 'Not Specified'
        reason_summary[key] += count

    return render_template('redo/device_change_report.html',
                         changes=changes,
                         reason_summary=reason_summary,
                         reason_choices=DEVICE_CHANGE_REASONS,
                         reason_filter=reason_filter,
                         search=search,
                         date_range=date_range)


@redo_bp.route('/reports/device-changes/export')
@login_required
@role_required('redo_technician', 'admin', 'executive')
def device_change_report_export():
    """Download the Device Change Report for the current filters/period."""
    import os
    from flask import send_file
    from src.services.mis_export_service import MISExportService
    from src.utils.date_ranges import parse_range

    changes = _device_change_query(
        request.args.get('reason', '').strip(),
        request.args.get('search', '').strip(),
        parse_range(request.args, default_to_current_month=False)).all()

    filepath = MISExportService().generate_device_change_excel(changes=changes)
    return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))


@redo_bp.route('/reports/technician-performance')
@login_required
@role_required('redo_technician', 'admin', 'executive')
def technician_performance_report():
    """Technician Performance wallboard.

    Covers every activity a technician can be assigned - Installations,
    REDOs, Removals and Removal Transfers - across every status: Completed,
    Pending, In Progress, Cancelled, and Total Assigned. Reconciling the four
    tables (which each identify their technician differently) is
    TechnicianActivityService's job, and the MIS page and the monthly
    management email read the exact same rows.
    """
    from src.services.technician_activity_service import (
        ACTIVITY_TYPES, STATUSES, TechnicianActivityService)
    from src.utils.date_ranges import parse_range

    date_range = parse_range(request.args, default_to_current_month=False)

    service = TechnicianActivityService()
    rows = service.wallboard_rows(date_range)

    return render_template('redo/technician_performance_report.html',
                         rows=rows,
                         totals=service.totals(rows),
                         activity_types=ACTIVITY_TYPES,
                         statuses=STATUSES,
                         date_range=date_range)


@redo_bp.route('/non-reporting/sync')
@login_required
@role_required('redo_technician', 'admin')
def non_reporting_sync():
    """Sync non-reporting vehicles from external SJ_MIS DB (IRData, Vehicles, Clients, gs_objects)"""
    nr_service = NonReportingService()
    
    try:
        result = nr_service.sync_non_reporting_vehicles()
        flash(f'✅ Live SJ_MIS DB Sync complete! New vehicles: {result["new"]}, Updated: {result["updated"]}', 'success')
    except Exception as e:
        flash(f'❌ Sync error: {str(e)}', 'danger')
    
    next_url = request.args.get('next')
    if next_url:
        return redirect(next_url)
    return redirect(url_for('redo.non_reporting_dashboard', source='external'))



# Contact outcomes selectable on the follow-up form. 'Technician Assigned' is
# the only one that (a) enables the technician dropdown and (b) auto-creates
# a REDO Activity. The rest map back to the underlying PENDING/IN_PROGRESS/
# ESCALATED workflow status so the Non-Reporting dashboard's existing bucket
# and stat-tile filters keep working unchanged.
CONTACT_OUTCOME_CHOICES = [
    'Follow-up Required',
    'No Answer',
    'Technician Assigned',
    'Phone Switched Off',
    'Vehicle Out of City',
    'Client Requested Removal',
]
CONTACT_OUTCOME_TO_STATUS = {
    'Follow-up Required': 'FOLLOW_UP',
    'No Answer': 'FOLLOW_UP',
    'Technician Assigned': 'IN_PROGRESS',
    'Phone Switched Off': 'FOLLOW_UP',
    'Vehicle Out of City': 'FOLLOW_UP',
    'Client Requested Removal': 'ESCALATED',
}


@redo_bp.route('/non-reporting/<int:vehicle_id>', methods=['GET', 'POST'])
@login_required
@role_required('redo_technician', 'admin', 'executive')
def non_reporting_detail(vehicle_id):
    """Non-reporting vehicle detail with REDO activity history, last conversation context, and follow-up logging"""
    nr_service = NonReportingService()
    vehicle = nr_service.get_by_id(vehicle_id)

    if not vehicle:
        flash('Vehicle not found', 'danger')
        return redirect(url_for('redo.non_reporting_dashboard'))

    form = NonReportingConversationForm()

    if request.method == 'POST':
        if current_user.is_executive():
            flash('Executives have read-only access to vehicle follow-up records.', 'warning')
            return redirect(url_for('redo.non_reporting_detail', vehicle_id=vehicle_id))
        # Create follow-up conversation or update status
        try:
            summary = request.form.get('summary', '')
            contact_person = request.form.get('contact_person', vehicle.customer_name or 'N/A')
            contact_number = request.form.get('contact_number', vehicle.customer_contact or 'N/A')
            conv_type = request.form.get('conversation_type', 'PHONE_CALL')
            direction = request.form.get('direction', 'OUTBOUND')
            action_taken = request.form.get('action_taken', '')
            follow_up_date_str = request.form.get('follow_up_date', '')
            technician_name = request.form.get('technician_name', '').strip()
            contact_outcome = request.form.get('contact_outcome', '').strip()

            follow_up_date = None
            if follow_up_date_str:
                try:
                    follow_up_date = datetime.strptime(follow_up_date_str, '%Y-%m-%d').date()
                except ValueError:
                    pass

            # The conversation is recorded regardless of whether a technician
            # ends up assigned - contact attempts (No Answer, Phone Switched
            # Off, etc.) are still meaningful history even with no assignment.
            if summary:
                kwargs = {
                    'vehicle_id': vehicle_id,
                    'conversation_type': conv_type,
                    'direction': direction,
                    'contact_person': contact_person,
                    'contact_number': contact_number,
                    'summary': summary,
                    'action_taken': action_taken,
                    'follow_up_required': bool(follow_up_date),
                    'user_id': current_user.id
                }
                if follow_up_date is not None:
                    kwargs['follow_up_date'] = follow_up_date

                nr_service.add_conversation(**kwargs)

            # Workflow logic:
            # 1. If technician is assigned, create REDO activity -> shows in Activities section
            # 2. If technician is NOT assigned, stays in the state of Follow-Up
            if contact_outcome == 'Technician Assigned' and technician_name:
                vehicle.contact_outcome = contact_outcome
                vehicle.status = 'IN_PROGRESS'
                if follow_up_date:
                    vehicle.scheduled_date = follow_up_date
                    vehicle.next_followup_date = follow_up_date
                vehicle.last_contact_date = datetime.now()
                db.session.commit()

                from src.services.vehicle_search_service import VehicleSearchService
                from src.models.user import User

                pulled = VehicleSearchService().lookup_by_reg_no(vehicle.registration_no) or {}
                assigned_user = User.query.filter(
                    db.or_(User.name == technician_name, User.username == technician_name)
                ).first()
                assigned_to_id = assigned_user.id if assigned_user else None

                redo_data = {
                    'activity_type': 'REDO',
                    'registration_no': vehicle.registration_no,
                    'customer_name': pulled.get('customer_name') or vehicle.customer_name,
                    'customer_contact': pulled.get('customer_contact') or contact_number,
                    'make': pulled.get('manufacturer') or vehicle.make,
                    'model': pulled.get('brand') or vehicle.model,
                    'year': pulled.get('model_year') or vehicle.vehicle_year,
                    'color': pulled.get('color') or vehicle.vehicle_color,
                    'chassis_no': pulled.get('chassis_no') or vehicle.chassis_no,
                    'engine_no': pulled.get('engine_no') or vehicle.engine_no,
                    'imei_no': pulled.get('imei_no') or vehicle.imei_no,
                    'sim_no': pulled.get('sim_no') or vehicle.sim_no,
                    'device_location': pulled.get('unit_location') or vehicle.unit_location or vehicle.device_location,
                    'city': pulled.get('city') or vehicle.city,
                    'technician': technician_name,
                    'assigned_to': assigned_to_id,
                    'assigned_by': current_user.id,
                    'assigned_at': datetime.now(),
                    'scheduled_date': follow_up_date,
                    'arranged_by': current_user.name or current_user.username,
                    'tested_by': current_user.name or current_user.username,
                    'issue_description': summary or vehicle.issue_summary or f"Assigned to technician {technician_name} for REDO inspection",
                    'resolution_status': 'Pending',
                }
                redo_service = RedoService()
                redo = redo_service.create_redo(redo_data, current_user.id)
                flash(f'✅ Follow-up saved and REDO {redo.redo_number} scheduled for technician {technician_name}! Visible in Activities section.', 'success')
            else:
                # Stays in state of Follow-Up (no REDO activity created)
                vehicle.contact_outcome = contact_outcome or 'Follow-up Required'
                vehicle.status = 'FOLLOW_UP'
                if follow_up_date:
                    vehicle.next_followup_date = follow_up_date
                    vehicle.scheduled_date = follow_up_date
                vehicle.last_contact_date = datetime.now()
                db.session.commit()
                scheduled_str = f" scheduled for {follow_up_date.strftime('%d/%m/%Y')}" if follow_up_date else ""
                flash(f'✅ Follow-up saved in Follow-Up state{scheduled_str}. Awaiting technician assignment.', 'info')

            return redirect(url_for('redo.non_reporting_detail', vehicle_id=vehicle_id))
        except Exception as e:
            logger.error(f"Error saving non-reporting follow-up: {e}")
            flash(f'❌ Error saving follow-up: {str(e)}', 'danger')

    # Activity Monitoring History: Query all REDO activities performed on this vehicle
    from src.models.redo import RedoActivity
    search_pattern = f"%{vehicle.registration_no.strip()}%"
    redo_activities = RedoActivity.query.filter(
        db.or_(
            RedoActivity.registration_no.ilike(search_pattern),
            RedoActivity.registration_no == vehicle.registration_no
        )
    ).order_by(RedoActivity.created_at.desc()).all()

    redo_count = len(redo_activities)
    redo_dates = [r.created_at.strftime('%d/%m/%Y %H:%M') for r in redo_activities if r.created_at]

    # Real technician roster: ONLY actual technicians' names, no other users
    from src.services.technician_service import TechnicianService
    technicians = TechnicianService.get_roster()
    conversations = nr_service.get_conversations(vehicle_id)
    last_conversation = conversations[0] if conversations else None

    return render_template('redo/non_reporting_detail.html',
                         vehicle=vehicle,
                         form=form,
                         contact_outcome_choices=CONTACT_OUTCOME_CHOICES,
                         conversations=conversations,
                         last_conversation=last_conversation,
                         redo_activities=redo_activities,
                         redo_count=redo_count,
                         redo_dates=redo_dates,
                         technicians=technicians)


@redo_bp.route('/followups')
@redo_bp.route('/follow-ups')
@login_required
@role_required('redo_technician', 'admin', 'executive')
def followups():
    """Follow-Up Module: Manage vehicles in follow-up state, reminders (due today, overdue, upcoming) and easy access."""
    from src.models.gps import NonReportingVehicle, NonReportingConversation
    from datetime import datetime

    today_date = datetime.now().date()
    tab = (request.args.get('tab') or 'all').strip().lower()
    search = (request.args.get('search') or '').strip()
    outcome_filter = (request.args.get('outcome') or '').strip()

    # Base query: vehicles in follow-up state or non-assigned vehicles with contact history
    query = NonReportingVehicle.query.filter(
        db.or_(
            NonReportingVehicle.status == 'FOLLOW_UP',
            db.and_(
                NonReportingVehicle.contact_outcome.isnot(None),
                NonReportingVehicle.contact_outcome != '',
                NonReportingVehicle.contact_outcome != 'Technician Assigned',
                NonReportingVehicle.status.in_(['FOLLOW_UP', 'PENDING', 'ESCALATED'])
            )
        )
    )

    # Compute total reminder counts before tab filtering
    all_followups = query.all()
    due_today_count = sum(
        1 for v in all_followups
        if v.next_followup_date == today_date or v.scheduled_date == today_date
    )
    overdue_count = sum(
        1 for v in all_followups
        if (v.next_followup_date and v.next_followup_date < today_date)
        or (v.scheduled_date and v.scheduled_date < today_date)
    )
    upcoming_count = sum(
        1 for v in all_followups
        if (v.next_followup_date and v.next_followup_date > today_date)
        or (v.scheduled_date and v.scheduled_date > today_date)
    )
    total_count = len(all_followups)

    reminder_counts = {
        'due_today': due_today_count,
        'overdue': overdue_count,
        'upcoming': upcoming_count,
        'total': total_count
    }

    # Apply tab filter
    if tab == 'due_today':
        query = query.filter(
            db.or_(
                NonReportingVehicle.next_followup_date == today_date,
                NonReportingVehicle.scheduled_date == today_date
            )
        )
    elif tab == 'overdue':
        query = query.filter(
            db.or_(
                db.and_(NonReportingVehicle.next_followup_date.isnot(None), NonReportingVehicle.next_followup_date < today_date),
                db.and_(NonReportingVehicle.scheduled_date.isnot(None), NonReportingVehicle.scheduled_date < today_date)
            )
        )
    elif tab == 'upcoming':
        query = query.filter(
            db.or_(
                db.and_(NonReportingVehicle.next_followup_date.isnot(None), NonReportingVehicle.next_followup_date > today_date),
                db.and_(NonReportingVehicle.scheduled_date.isnot(None), NonReportingVehicle.scheduled_date > today_date)
            )
        )

    # Search filter
    if search:
        p = f"%{search}%"
        query = query.filter(
            db.or_(
                NonReportingVehicle.registration_no.ilike(p),
                NonReportingVehicle.customer_name.ilike(p),
                NonReportingVehicle.customer_contact.ilike(p),
                NonReportingVehicle.emergency_mobile.ilike(p),
                NonReportingVehicle.city.ilike(p),
                NonReportingVehicle.imei_no.ilike(p)
            )
        )

    # Outcome filter
    if outcome_filter:
        query = query.filter(NonReportingVehicle.contact_outcome == outcome_filter)

    # Order by follow-up date ascending (nulls last)
    query = query.order_by(
        NonReportingVehicle.next_followup_date.asc().nullslast(),
        NonReportingVehicle.last_contact_date.desc().nullslast()
    )

    page = request.args.get('page', 1, type=int)
    per_page = 25
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    vehicles = pagination.items

    # Fetch last conversation for each vehicle
    vehicle_ids = [v.id for v in vehicles]
    last_conversations = {}
    if vehicle_ids:
        convs = NonReportingConversation.query.filter(
            NonReportingConversation.vehicle_id.in_(vehicle_ids)
        ).order_by(NonReportingConversation.conversation_date.desc()).all()
        for c in convs:
            if c.vehicle_id not in last_conversations:
                last_conversations[c.vehicle_id] = c

    return render_template(
        'redo/followups.html',
        vehicles=vehicles,
        pagination=pagination,
        reminder_counts=reminder_counts,
        last_conversations=last_conversations,
        tab=tab,
        search=search,
        outcome_filter=outcome_filter,
        outcome_choices=CONTACT_OUTCOME_CHOICES,
        today_date=today_date
    )