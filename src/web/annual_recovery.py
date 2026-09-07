# src/web/annual_recovery.py
"""
Annual Recovery Blueprint & API Routes
Handles annual vehicle tracking device monitoring, recovery payments, follow-ups, and sheet management.
"""
from datetime import datetime
from flask import Blueprint, render_template, jsonify, request, flash, redirect, url_for
from flask_login import login_required, current_user
import pandas as pd

from src.extensions import db
from src.models.user import User
from src.utils.decorators import role_required
from src.utils.logging import get_logger
from src.models.annual_recovery import (
    AnnualRecoveryClient,
    AnnualRecoveryVehicle,
    AnnualRecoveryFollowup,
    AnnualRecoveryHistory,
    AnnualRecoveryAuditLog
)

annual_recovery_bp = Blueprint('annual_recovery', __name__)

logger = get_logger(__name__)


def _send_lost_vehicles_for_removal(vehicles, user_id=None) -> int:
    """Put every written-off vehicle onto the Removal wallboard.

    Used by the sheet import; `mark_lost` does the same for one vehicle at a
    time. A vehicle whose flag cannot be raised is logged and stepped over
    rather than taking the rest of the batch down with it - the write-offs
    themselves are already committed by this point.
    """
    from src.services.removal_service import RemovalService

    removal_service = RemovalService()
    sent = 0
    for vehicle in vehicles:
        try:
            if removal_service.flag_amc_lost_vehicle(vehicle, user_id):
                sent += 1
        except Exception as e:
            logger.error(f"Could not raise a removal for LOST vehicle "
                         f"{getattr(vehicle, 'reg_no', '?')}: {e}")
    return sent


def log_recovery_audit(action: str, details: str = ''):
    """Helper to log audit events for Annual Recovery module"""
    try:
        user_str = current_user.username if hasattr(current_user, 'username') else 'System'
        ip_addr = request.remote_addr or ''
        audit = AnnualRecoveryAuditLog(
            user=user_str,
            action=action,
            details=details,
            ip_address=ip_addr
        )
        db.session.add(audit)
        db.session.commit()
    except Exception as e:
        db.session.rollback()


# Admin and manager supervise the whole module - every sheet, plus uploading
# and assigning them. A recovery officer only ever works the sheets assigned to
# them. Assignment is stored per vehicle (assign_sheet stamps every vehicle in a
# sheet), so scoping on assigned_to is what makes "only the sheets assigned to
# me" true for the stat cards, the client list, the sheet dropdown and every
# per-vehicle action alike - not just for the list the officer happens to see.
SHEET_SUPERVISOR_ROLES = ['admin', 'manager', 'executive']


def is_sheet_supervisor() -> bool:
    """True when the signed-in user administers all sheets, not just their own."""
    return current_user.is_authenticated and current_user.has_any_role(SHEET_SUPERVISOR_ROLES)


def scope_vehicles(query):
    """Restrict a vehicle query to the sheets the signed-in user may see."""
    if is_sheet_supervisor():
        return query
    return query.filter(AnnualRecoveryVehicle.assigned_to == current_user.id)


def visible_sheet_names() -> list:
    """Distinct sheet names the signed-in user may see, in name order."""
    query = db.session.query(AnnualRecoveryVehicle.sheet_name).distinct()
    if not is_sheet_supervisor():
        query = query.filter(AnnualRecoveryVehicle.assigned_to == current_user.id)
    return sorted({row[0] for row in query.all() if row[0]})


def can_access_vehicle(vehicle) -> bool:
    """A recovery officer may only act on vehicles from their own sheets.

    Hiding a vehicle from the list is not access control on its own - every
    per-vehicle route takes an id from the client and must check it too.
    """
    return is_sheet_supervisor() or vehicle.assigned_to == current_user.id


def vehicle_access_denied():
    """Uniform refusal for a vehicle outside the user's assigned sheets."""
    return jsonify({
        'success': False,
        'message': 'That vehicle belongs to a sheet that is not assigned to you.'
    }), 403


@annual_recovery_bp.route('/')
@login_required
@role_required('recovery_officer', 'admin', 'manager', 'executive')
def dashboard():
    """Render Annual Recovery Dashboard UI"""
    can_manage_sheets = current_user.is_admin() or current_user.is_manager()
    # The user list only drives the assignment picker and the "Assigned User"
    # filter, both of which are supervisor-only.
    users = User.query.all() if is_sheet_supervisor() else []
    return render_template('annual_recovery/dashboard.html',
                           users=users,
                           can_manage_sheets=can_manage_sheets)


@annual_recovery_bp.route('/api/stats', methods=['GET'])
@login_required
@role_required('recovery_officer', 'admin', 'manager', 'executive')
def get_stats():
    """Get high level summary stats for dashboard cards. Honours the same
    `sheet` filter as the clients list, so selecting a sheet in the dashboard's
    Sheet Name dropdown re-scopes the stat cards to that sheet instead of
    always showing all-sheet totals. For a recovery officer every figure here
    covers only their own assigned sheets."""
    sheet_filter = request.args.get('sheet', '').strip()

    v_query = scope_vehicles(AnnualRecoveryVehicle.query)
    if sheet_filter:
        v_query = v_query.filter(AnnualRecoveryVehicle.sheet_name == sheet_filter)
    vehicles = v_query.all()

    vehicles_count = len(vehicles)
    # Clients are counted from the visible vehicle set whenever that set is a
    # subset of everything - a chosen sheet, or an officer's own sheets - so the
    # card matches what the list below it actually shows.
    if sheet_filter or not is_sheet_supervisor():
        clients_count = len({v.client_id for v in vehicles})
    else:
        clients_count = AnnualRecoveryClient.query.count()

    total_amc = sum(v.amc_charges or 0.0 for v in vehicles)
    total_recovered = sum(v.recovered_amount or 0.0 for v in vehicles)
    total_lost = sum(v.amc_charges or 0.0 for v in vehicles if v.status == 'LOST')
    total_outstanding = total_amc - total_recovered - total_lost

    recovered_vehicles = sum(1 for v in vehicles if v.status == 'RECOVERED')
    pending_vehicles = sum(1 for v in vehicles if v.status == 'PENDING')
    followup_vehicles = sum(1 for v in vehicles if v.status == 'FOLLOWUP')
    lost_vehicles = sum(1 for v in vehicles if v.status == 'LOST')

    # Every sheet the user may see, ignoring the current selection - this
    # populates the dropdown itself, so it must not shrink to just the
    # currently-selected sheet. It is still scoped by assignment: an officer's
    # dropdown must not name sheets they have no access to.
    sheets = visible_sheet_names()

    return jsonify({
        'totalClients': clients_count,
        'totalVehicles': vehicles_count,
        'totalAmcCharges': total_amc,
        'totalRecovered': total_recovered,
        'totalOutstanding': max(0.0, total_outstanding),
        'totalLost': total_lost,
        'recoveredVehicles': recovered_vehicles,
        'pendingVehicles': pending_vehicles,
        'followupVehicles': followup_vehicles,
        'lostVehicles': lost_vehicles,
        'sheets': sheets
    })


@annual_recovery_bp.route('/api/clients', methods=['GET'])
@login_required
@role_required('recovery_officer', 'admin', 'manager', 'executive')
def get_clients():
    """Fetch clients with associated vehicles, filtered by sheet, status, assigned user, search text.

    A recovery officer only ever gets vehicles from their own assigned sheets;
    the request's own filters can narrow that further but never widen it.
    """
    sheet_filter = request.args.get('sheet', '').strip()
    status_filter = request.args.get('status', '').strip().upper()
    assigned_filter = request.args.get('assigned', '').strip()
    search_filter = request.args.get('search', '').strip().lower()

    # Base vehicle query, scoped to what this user is allowed to see
    v_query = scope_vehicles(AnnualRecoveryVehicle.query)

    if sheet_filter:
        v_query = v_query.filter(AnnualRecoveryVehicle.sheet_name == sheet_filter)
    if status_filter:
        v_query = v_query.filter(AnnualRecoveryVehicle.status == status_filter)
    if assigned_filter:
        if assigned_filter == 'unassigned':
            v_query = v_query.filter(AnnualRecoveryVehicle.assigned_to == None)
        elif assigned_filter.isdigit():
            v_query = v_query.filter(AnnualRecoveryVehicle.assigned_to == int(assigned_filter))

    filtered_vehicles = v_query.all()
    filtered_v_map = {v.client_id: [] for v in filtered_vehicles}
    for v in filtered_vehicles:
        filtered_v_map[v.client_id].append(v)

    if not filtered_v_map:
        return jsonify([])

    clients = AnnualRecoveryClient.query.filter(AnnualRecoveryClient.id.in_(list(filtered_v_map.keys()))).all()
    result = []

    for client in clients:
        c_vehicles = filtered_v_map.get(client.id, [])
        if search_filter:
            c_name = (client.name or '').lower()
            c_cell = (client.cell1 or '').lower()
            matching_v = [v for v in c_vehicles if search_filter in (v.reg_no or '').lower() or search_filter in (v.remarks or '').lower()]
            if search_filter not in c_name and search_filter not in c_cell and not matching_v:
                continue

        # Described over the vehicles this user is actually being shown, so
        # the totals in the card header are the total of the rows under it.
        # Passing them in also stops the client's whole vehicle list being
        # serialised and then thrown away on every card.
        result.append(client.to_dict(c_vehicles))

    return jsonify(result)


@annual_recovery_bp.route('/api/recover', methods=['POST'])
@login_required
@role_required('recovery_officer', 'admin', 'manager')
def recover_amount():
    """Record recovery payment for a vehicle. Accepts multipart form data
    (not JSON) since Online Payment requires a proof-of-payment upload -
    the same Payment Recording flow Installation Recovery uses (see
    src.services.payment_proof_service)."""
    from src.services.payment_proof_service import save_payment_proof

    data = request.form
    vehicle_id = data.get('vehicleId')
    if not vehicle_id:
        return jsonify({'success': False, 'message': 'Vehicle ID required'}), 400

    vehicle = AnnualRecoveryVehicle.query.get_or_404(vehicle_id)
    if not can_access_vehicle(vehicle):
        return vehicle_access_denied()

    amount = float(data.get('amount') or 0.0)
    payment_method = data.get('paymentMethod', 'Cash Payment')
    if payment_method not in ('Online Payment', 'Cash Payment', 'Cheque'):
        return jsonify({'success': False, 'message': 'Invalid payment method.'}), 400
    cheque_status = data.get('chequeStatus', '')
    reference_no = data.get('referenceNo', '')
    notes = data.get('notes', '')
    # Date and time, in Pakistan time. A date alone cannot distinguish two
    # payments taken against the same vehicle on the same day, which is
    # exactly when someone needs to tell them apart. `created_at` carries the
    # same stamp; this column is the one the ledger and the exports read.
    from src.utils.timezone import get_current_time
    payment_date = data.get('paymentDate') or get_current_time().strftime('%Y-%m-%d %H:%M')
    force_full = data.get('forceFullyRecovered', 'false').lower() == 'true'

    proof_file = request.files.get('proofFile')
    if payment_method == 'Online Payment' and not (proof_file and proof_file.filename):
        return jsonify({'success': False, 'message': 'Proof of payment is required for online payments.'}), 400
    try:
        proof_path = save_payment_proof(proof_file, 'amc', vehicle_id)
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    remaining = (vehicle.amc_charges or 0.0) - (vehicle.recovered_amount or 0.0)

    if force_full:
        vehicle.recovered_amount = vehicle.amc_charges
        vehicle.status = 'RECOVERED'
    else:
        if amount > remaining + 0.01:
            return jsonify({'success': False, 'message': f'Amount ({amount}) exceeds remaining balance ({remaining})'}), 400
        vehicle.recovered_amount = (vehicle.recovered_amount or 0.0) + amount
        if vehicle.recovered_amount >= (vehicle.amc_charges or 0.0) - 0.01:
            vehicle.status = 'RECOVERED'
            vehicle.recovered_amount = vehicle.amc_charges

    # Update Client total_recovered
    client = AnnualRecoveryClient.query.get(vehicle.client_id)
    if client:
        client.total_recovered = sum(v.recovered_amount or 0.0 for v in client.vehicles)

    # Save recovery history record (immutable once created)
    history = AnnualRecoveryHistory(
        client_id=vehicle.client_id,
        vehicle_id=vehicle.id,
        amount=amount,
        payment_date=payment_date,
        reference_no=reference_no,
        payment_method=payment_method,
        cheque_status=cheque_status if payment_method == 'Cheque' else '',
        proof_of_payment_path=proof_path,
        notes=notes,
        is_locked=True
    )
    db.session.add(history)
    db.session.commit()

    log_recovery_audit('RECOVERY_RECORDED', f"Vehicle {vehicle.reg_no}: Amount {amount}, Method {payment_method}")
    return jsonify({'success': True, 'message': f'Recovery of PKR {amount:,.2f} recorded successfully for {vehicle.reg_no}'})


@annual_recovery_bp.route('/api/followup', methods=['POST'])
@login_required
@role_required('recovery_officer', 'admin', 'manager')
def add_followup():
    """Add follow-up note and next follow-up date for a vehicle"""
    data = request.json or {}
    vehicle_id = data.get('vehicleId')
    note = data.get('note', '').strip()
    next_date = data.get('nextDate', '').strip()

    if not vehicle_id or not note:
        return jsonify({'success': False, 'message': 'Vehicle ID and note are required'}), 400

    vehicle = AnnualRecoveryVehicle.query.get_or_404(vehicle_id)
    if not can_access_vehicle(vehicle):
        return vehicle_access_denied()

    user_name = current_user.name or current_user.username if hasattr(current_user, 'username') else 'System'
    followup = AnnualRecoveryFollowup(
        client_id=vehicle.client_id,
        vehicle_id=vehicle.id,
        note=note,
        next_date=next_date,
        created_by=user_name
    )
    db.session.add(followup)

    if vehicle.status not in ['RECOVERED', 'LOST']:
        vehicle.status = 'FOLLOWUP'

    db.session.commit()
    log_recovery_audit('FOLLOWUP_ADDED', f"Vehicle {vehicle.reg_no}: {note[:40]}")
    return jsonify({'success': True, 'followup': followup.to_dict()})


@annual_recovery_bp.route('/api/mark-lost', methods=['POST'])
@login_required
@role_required('recovery_officer', 'admin', 'manager')
def mark_lost():
    """Mark a vehicle status as LOST, and send it for removal.

    Writing the money off is only half the decision - the device is still
    fitted to a vehicle nobody is billing for, so the same action puts the
    vehicle on the Removal wallboard with the reason it got there.
    """
    from src.services.removal_service import RemovalService

    data = request.json or {}
    vehicle_id = data.get('vehicleId')
    vehicle = AnnualRecoveryVehicle.query.get_or_404(vehicle_id)
    if not can_access_vehicle(vehicle):
        return vehicle_access_denied()

    old_status = vehicle.status
    vehicle.status = 'LOST'

    client = AnnualRecoveryClient.query.get(vehicle.client_id)
    if client:
        client.total_lost = sum(v.amc_charges or 0.0 for v in client.vehicles if v.status == 'LOST')

    db.session.commit()
    log_recovery_audit('MARKED_LOST', f"Vehicle {vehicle.reg_no}: {old_status} -> LOST")

    # The write-off stands whatever happens here: a removal that could not be
    # raised is worth reporting, not worth undoing the officer's decision for.
    message = f'Vehicle {vehicle.reg_no} marked as LOST'
    try:
        flag = RemovalService().flag_amc_lost_vehicle(vehicle, current_user.id)
        if flag:
            message += ' and sent to the Removal dashboard for device recovery'
            log_recovery_audit('SENT_FOR_REMOVAL',
                               f"Vehicle {vehicle.reg_no}: removal flag #{flag.id} raised")
    except Exception as e:
        logger.error(f"Could not raise a removal for LOST vehicle {vehicle.reg_no}: {e}")
        message += ' (it could not be sent to Removal - please flag it there manually)'

    return jsonify({'success': True, 'message': message})


@annual_recovery_bp.route('/api/followups/<int:vehicle_id>', methods=['GET'])
@login_required
@role_required('recovery_officer', 'admin', 'manager', 'executive')
def get_followups(vehicle_id):
    """Get follow-up history for a vehicle"""
    vehicle = AnnualRecoveryVehicle.query.get_or_404(vehicle_id)
    if not can_access_vehicle(vehicle):
        return vehicle_access_denied()

    followups = AnnualRecoveryFollowup.query.filter_by(vehicle_id=vehicle_id).order_by(AnnualRecoveryFollowup.created_at.desc()).all()
    return jsonify([f.to_dict() for f in followups])


@annual_recovery_bp.route('/api/history/<int:vehicle_id>', methods=['GET'])
@login_required
@role_required('recovery_officer', 'admin', 'manager', 'executive')
def get_history(vehicle_id):
    """Get recovery payment history for a vehicle"""
    vehicle = AnnualRecoveryVehicle.query.get_or_404(vehicle_id)
    if not can_access_vehicle(vehicle):
        return vehicle_access_denied()

    history = AnnualRecoveryHistory.query.filter_by(vehicle_id=vehicle_id).order_by(AnnualRecoveryHistory.created_at.desc()).all()
    return jsonify([h.to_dict() for h in history])


@annual_recovery_bp.route('/api/sheets', methods=['GET'])
@login_required
@role_required('recovery_officer', 'admin', 'manager', 'executive')
def get_sheets():
    """Get list of distinct sheet names and their assigned users, restricted to
    the sheets the signed-in user may see."""
    s_query = db.session.query(AnnualRecoveryVehicle.sheet_name, AnnualRecoveryVehicle.assigned_to).distinct()
    if not is_sheet_supervisor():
        s_query = s_query.filter(AnnualRecoveryVehicle.assigned_to == current_user.id)
    sheets = s_query.all()
    result = []
    seen = set()
    for sheet_name, assigned_to in sheets:
        if sheet_name and sheet_name not in seen:
            seen.add(sheet_name)
            user_name = None
            if assigned_to:
                user = User.query.get(assigned_to)
                if user:
                    user_name = user.name or user.username
            count = scope_vehicles(AnnualRecoveryVehicle.query).filter_by(sheet_name=sheet_name).count()
            result.append({
                'sheet_name': sheet_name,
                'assigned_to': assigned_to,
                'assigned_to_name': user_name,
                'vehicle_count': count
            })
    return jsonify(sorted(result, key=lambda x: x['sheet_name']))


@annual_recovery_bp.route('/api/assign-sheet', methods=['POST'])
@login_required
@role_required('admin', 'manager')
def assign_sheet():
    """Assign all vehicles in a sheet to a user.

    Supervisor-only: deciding who works which sheet is the supervising job, and
    an officer who could assign could hand themselves any sheet in the system.
    """
    data = request.json or {}
    sheet_name = data.get('sheet_name')
    user_id = data.get('user_id')

    if not sheet_name or user_id is None:
        return jsonify({'success': False, 'message': 'Sheet name and user ID are required'}), 400

    target_user_id = int(user_id) if str(user_id).isdigit() and int(user_id) > 0 else None

    vehicles = AnnualRecoveryVehicle.query.filter_by(sheet_name=sheet_name).all()
    if not vehicles:
        return jsonify({'success': False, 'message': 'No vehicles found in sheet'}), 404

    for v in vehicles:
        v.assigned_to = target_user_id

    db.session.commit()

    user_label = 'Unassigned'
    if target_user_id:
        user = User.query.get(target_user_id)
        if user:
            user_label = user.name or user.username

    log_recovery_audit('SHEET_ASSIGNED', f"Sheet '{sheet_name}' ({len(vehicles)} vehicles) assigned to {user_label}")
    return jsonify({'success': True, 'message': f"Sheet '{sheet_name}' assigned to {user_label}"})


@annual_recovery_bp.route('/api/audit-logs', methods=['GET'])
@login_required
@role_required('admin', 'manager')
def get_audit_logs():
    """Get audit logs for annual recovery actions.

    Supervisor-only: the log spans every sheet, naming clients and vehicles an
    officer is not assigned - it would be a way around the sheet scoping.
    """
    logs = AnnualRecoveryAuditLog.query.order_by(AnnualRecoveryAuditLog.created_at.desc()).limit(150).all()
    return jsonify([l.to_dict() for l in logs])


# Accepted spreadsheet header names per field, tried in order. Matching is done
# on a normalised form (lowercased, punctuation/whitespace stripped) so
# "Amc charges ", "AMC_Charges_PKR" and "amc charges" all resolve alike.
COLUMN_ALIASES = {
    'name':          ['name', 'clientname', 'customername', 'client', 'customer', 'ownername'],
    'cell1':         ['cell1', 'cell', 'cellno', 'cellnumber', 'contact', 'contactno',
                      'contactnumber', 'phone', 'phoneno', 'mobile', 'mobileno'],
    'reg_no':        ['regno', 'registrationno', 'registrationnumber', 'registration',
                      'vehicleno', 'vehiclenumber', 'vehicleregno', 'reg'],
    'install_date':  ['installationdate', 'installdate', 'dateofinstallation',
                      'installedon', 'installation'],
    'employee_name': ['employeename', 'employee', 'salesperson', 'salesagent',
                      'arrangedby', 'staff'],
    'amc_charges':   ['amccharges', 'amccharge', 'amcchargespkr', 'amcamount', 'amc',
                      'charges', 'charge', 'amount'],
    # 'address' is last: only used as remarks when the sheet has no real remarks
    # column, so an address is preserved rather than silently dropped.
    'remarks':       ['remarks', 'remark', 'notes', 'note', 'comments', 'comment',
                      'status', 'address'],
}

# Column positions the importer used before header matching existed. Kept as a
# fallback for sheets whose headers cannot be recognised, so previously working
# uploads behave exactly as they did.
LEGACY_POSITIONS = {
    'name': 0, 'cell1': 1, 'reg_no': 2, 'install_date': 4,
    'employee_name': 5, 'amc_charges': 6, 'remarks': 7,
}


def _normalise_header(value) -> str:
    """Reduce a header to comparable form: lowercase alphanumerics only."""
    return ''.join(ch for ch in str(value).lower() if ch.isalnum())


def _resolve_columns(cols: list) -> dict:
    """Map each canonical field to an actual spreadsheet column by header name.

    Returns {field: column_or_None}. Falls back to the historical fixed column
    positions when the sheet's headers are unrecognisable, so this never
    regresses an upload that used to work.
    """
    normalised = {}
    for col in cols:
        key = _normalise_header(col)
        # First column wins on duplicate headers, matching pandas' left-to-right read.
        normalised.setdefault(key, col)

    resolved = {}
    claimed = set()
    for field, aliases in COLUMN_ALIASES.items():
        match = None
        for alias in aliases:
            col = normalised.get(alias)
            if col is not None and col not in claimed:
                match = col
                break
        if match is not None:
            claimed.add(match)
        resolved[field] = match

    # Name and registration are the two fields a row is meaningless without. If
    # headers didn't yield them, this sheet isn't header-labelled the way we
    # expect - revert to legacy positional reading for the whole sheet.
    if resolved['name'] is None or resolved['reg_no'] is None:
        return {field: (cols[i] if i < len(cols) else None)
                for field, i in LEGACY_POSITIONS.items()}
    return resolved


def _cell_text(row, col) -> str:
    """Trimmed text for a cell, '' when the column is absent or empty."""
    if col is None:
        return ''
    value = row.get(col)
    if value is None or pd.isna(value):
        return ''
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.strftime('%Y-%m-%d')
    text = str(value).strip()
    # Excel/pandas render whole numbers read as floats with a trailing ".0",
    # which would corrupt phone numbers and registrations.
    if text.endswith('.0') and text[:-2].isdigit():
        text = text[:-2]
    return text


# Remarks wording that means the client has actually paid. "UNPAID" and "NOT
# PAID" contain "PAID" as a substring, so they are excluded first - otherwise an
# unpaid vehicle would import as recovered.
NOT_PAID_MARKERS = ('UNPAID', 'UN PAID', 'NOT PAID', 'NON PAID', 'NO PAYMENT')
PAID_MARKERS = ('RECOVERED', 'PAID', 'RECEIVED')


def _is_paid(remarks: str) -> bool:
    """True when the remarks say this AMC was actually collected."""
    text = (remarks or '').upper()
    if any(marker in text for marker in NOT_PAID_MARKERS):
        return False
    return any(marker in text for marker in PAID_MARKERS)


def _status_from_remarks(remarks: str) -> str:
    """Map a sheet's free-text remarks onto a recovery status."""
    text = (remarks or '').upper()
    if _is_paid(text):
        return 'RECOVERED'
    if 'LOST' in text:
        return 'LOST'
    if 'FOLLOWUP' in text or 'FOLLOW UP' in text:
        return 'FOLLOWUP'
    return 'PENDING'


def _cell_amount(row, col) -> float:
    """Numeric value for a cell, tolerating currency symbols and separators."""
    if col is None:
        return 0.0
    value = row.get(col)
    if value is None or pd.isna(value):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = ''.join(ch for ch in str(value) if ch.isdigit() or ch in '.-')
    try:
        return float(cleaned) if cleaned not in ('', '.', '-') else 0.0
    except ValueError:
        return 0.0


@annual_recovery_bp.route('/api/upload-excel', methods=['POST'])
@login_required
@role_required('admin', 'manager')
def upload_excel():
    """Bulk import Excel sheets into Annual Recovery module.

    Supervisor-only: bringing new sheets into the system is a supervising job,
    and imported vehicles start unassigned - an officer cannot upload work for
    themselves.

    Columns are matched by header name rather than by fixed position, so a
    sheet's column order no longer has to match an implicit layout - a file
    missing a column, or ordering them differently, imports correctly instead
    of silently shifting values into the wrong fields.

    Payment is carried across too. The sheets record collection as wording in
    the remarks ("PAID") rather than as a figure, so a row saying PAID imports
    with its AMC recorded as recovered - previously it was labelled RECOVERED
    while still showing the full amount outstanding.

    Repeated registrations inside one sheet are merged rather than dropped: the
    operators log a follow-up payment as a second line, so
    "9,000 PENDING" + "7,000 PAID" is one vehicle charged 9,000, recovered
    7,000, outstanding 2,000 - and marked RECOVERED even though a balance
    remains, because the recovery itself did happen.
    """
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file uploaded'}), 400
    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({'success': False, 'message': 'No file selected'}), 400

    try:
        excel_file = pd.ExcelFile(file.stream)
        sheets = excel_file.sheet_names
        total_added = 0

        skipped_incomplete = 0
        skipped_duplicate = 0

        merged_rows = 0
        recorded_payments = 0

        # Vehicles the sheet has already written off. Collected as they are
        # read and flagged for removal after the commit, not during it.
        imported_lost = []

        # Stamped on every payment record this run creates, so an import can be
        # identified - and reversed - later. The sheets carry no payment date,
        # so the honest date is the day the figure entered the system.
        imported_at = datetime.now()
        import_date = imported_at.strftime('%Y-%m-%d')
        import_stamp = imported_at.strftime('%Y-%m-%d %H:%M:%S')
        import_reference = f"IMPORT-{imported_at.strftime('%Y%m%d-%H%M%S')}"
        source_name = file.filename or 'uploaded file'

        for sheet_name in sheets:
            file.stream.seek(0)
            df = pd.read_excel(file.stream, sheet_name=sheet_name)
            colmap = _resolve_columns(df.columns.tolist())

            # Pass 1: read the sheet, collapsing repeated registrations into one
            # record per vehicle. Order is preserved so the first line for a
            # vehicle supplies its client details.
            records: dict = {}
            for idx, row in df.iterrows():
                try:
                    name = _cell_text(row, colmap['name']).upper()
                    cell1 = _cell_text(row, colmap['cell1']).upper()
                    reg_no = _cell_text(row, colmap['reg_no']).upper()
                    install_date = _cell_text(row, colmap['install_date'])
                    employee_name = _cell_text(row, colmap['employee_name']).upper()
                    amc_charges = _cell_amount(row, colmap['amc_charges'])
                    remarks = _cell_text(row, colmap['remarks']).upper()

                    # A blank cell read through pandas can arrive as the literal
                    # text "NAN"/"NONE"; such a row identifies no vehicle.
                    if reg_no in ('NAN', 'NONE'):
                        reg_no = ''
                    if not name or not reg_no:
                        skipped_incomplete += 1
                        continue

                    paid = _is_paid(remarks)
                    existing = records.get(reg_no)
                    if existing is None:
                        records[reg_no] = {
                            'name': name, 'cell1': cell1, 'employee_name': employee_name,
                            'install_date': install_date, 'amc_charges': amc_charges,
                            # Each collected line is kept separately so it can
                            # become its own payment record below.
                            'paid_lines': [amc_charges] if paid else [],
                            'remarks': remarks, 'paid': paid,
                        }
                        continue

                    # A repeat line for the same vehicle. The AMC owed is the
                    # largest charge seen - a follow-up payment line often
                    # carries only the amount collected, which is smaller.
                    merged_rows += 1
                    existing['amc_charges'] = max(existing['amc_charges'], amc_charges)
                    if paid:
                        existing['paid_lines'].append(amc_charges)
                        existing['paid'] = True
                        if remarks:
                            existing['remarks'] = remarks
                    if not existing['install_date']:
                        existing['install_date'] = install_date
                except Exception:
                    continue

            # Pass 2: write the merged records.
            for reg_no, rec in records.items():
                try:
                    if AnnualRecoveryVehicle.query.filter_by(reg_no=reg_no).first():
                        skipped_duplicate += 1
                        continue

                    amc_charges = rec['amc_charges']
                    # Allocate each collected line against the charge, in order,
                    # stopping at the amount owed. A plain "RECOVERED" line
                    # carries the full AMC (the sheets record collection as
                    # wording, not a figure); the same payment typed twice
                    # cannot recover more than is owed.
                    payments = []
                    remaining = amc_charges
                    for line_amount in rec['paid_lines']:
                        take = min(line_amount, remaining)
                        if take <= 0:
                            break
                        payments.append(take)
                        remaining -= take
                    recovered = sum(payments)
                    status = 'RECOVERED' if rec['paid'] else _status_from_remarks(rec['remarks'])

                    client = AnnualRecoveryClient.query.filter_by(
                        name=rec['name'], cell1=rec['cell1']).first()
                    if not client:
                        client = AnnualRecoveryClient(name=rec['name'], cell1=rec['cell1'],
                                                      employee_name=rec['employee_name'])
                        db.session.add(client)
                        db.session.flush()

                    vehicle = AnnualRecoveryVehicle(
                        client_id=client.id,
                        reg_no=reg_no,
                        installation_date=rec['install_date'],
                        amc_charges=amc_charges,
                        recovered_amount=recovered,
                        remarks=rec['remarks'],
                        status=status,
                        sheet_name=sheet_name
                    )
                    db.session.add(vehicle)
                    db.session.flush()

                    # Give every recovered amount a payment record, so the money
                    # has something behind it in the vehicle's history instead of
                    # appearing from nowhere. These are marked Imported and left
                    # unlocked: unlike a payment taken through the Record
                    # Recovery screen, there is no receipt, date or reference
                    # behind them - they are the sheet's own wording - so they
                    # must stay correctable if a row turns out to be wrong.
                    for payment_amount in payments:
                        db.session.add(AnnualRecoveryHistory(
                            client_id=client.id,
                            vehicle_id=vehicle.id,
                            amount=payment_amount,
                            payment_date=import_date,
                            reference_no=import_reference,
                            payment_method='Imported',
                            notes=(f'Imported from {source_name} (sheet "{sheet_name}") '
                                   f'on {import_stamp}. Recorded from the sheet remark '
                                   f'"{rec["remarks"]}" - no receipt on file.'),
                            is_locked=False,
                        ))
                        recorded_payments += 1

                    client.total_amc_charges = (client.total_amc_charges or 0.0) + amc_charges
                    client.total_recovered = (client.total_recovered or 0.0) + recovered
                    if status == 'LOST':
                        client.total_lost = (client.total_lost or 0.0) + amc_charges
                        # A sheet arriving with a vehicle already written off
                        # means the same thing as writing one off by hand: the
                        # device is still fitted and has to come back. Held
                        # until after the commit below, since the flag records
                        # figures this vehicle has only just been given.
                        imported_lost.append(vehicle)

                    total_added += 1
                except Exception:
                    continue

        db.session.commit()

        sent_for_removal = _send_lost_vehicles_for_removal(
            imported_lost, getattr(current_user, 'id', None))

        # Report what was left out as well as what went in - a silent skip is
        # how a mis-shaped sheet used to look identical to a clean import.
        notes = []
        if recorded_payments:
            notes.append(f'{recorded_payments} payment record(s) created, reference {import_reference}')
        if sent_for_removal:
            notes.append(f'{sent_for_removal} LOST vehicle(s) sent to the Removal dashboard')
        if merged_rows:
            notes.append(f'{merged_rows} repeat line(s) merged as payments')
        if skipped_duplicate:
            notes.append(f'{skipped_duplicate} skipped (registration already on file)')
        if skipped_incomplete:
            notes.append(f'{skipped_incomplete} skipped (missing name or registration)')
        message = f'Successfully imported {total_added} vehicles!'
        if notes:
            message += ' ' + '; '.join(notes) + '.'

        log_recovery_audit(
            'EXCEL_UPLOAD',
            f"Uploaded Excel file with {total_added} vehicles across {len(sheets)} sheets"
            + (f" ({'; '.join(notes)})" if notes else '')
        )
        return jsonify({
            'success': True,
            'count': total_added,
            'mergedRows': merged_rows,
            'recordedPayments': recorded_payments,
            'importReference': import_reference,
            'skippedDuplicate': skipped_duplicate,
            'skippedIncomplete': skipped_incomplete,
            'message': message,
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


INVOICE_FAILED_MESSAGE = (
    'Unable to generate the AMC invoice. The PDF renderer (wkhtmltopdf) may '
    'not be installed on this server - check the application log.'
)


def _requested_override(outstanding: float):
    """The amount the officer chose to bill, and why, off the form.

    Returns (override, reason, error). `override` is None when the officer
    did not override, which bills the full balance.

    An override above the outstanding is refused rather than clamped: it
    means the officer typed the wrong figure, and quietly billing something
    other than what they entered is how a wrong invoice reaches a customer
    with nobody having seen it.
    """
    raw = (request.form.get('override_amount') or '').strip()
    reason = (request.form.get('discount_reason') or '').strip()

    if not raw:
        return None, '', None

    try:
        amount = float(raw.replace(',', ''))
    except ValueError:
        return None, reason, 'Enter the invoice amount as a number.'

    if amount < 0:
        return None, reason, 'The invoice amount cannot be negative.'
    if amount > outstanding + 0.01:
        return None, reason, (f'The invoice amount cannot be more than the '
                              f'outstanding balance of PKR {outstanding:,.2f}.')

    # A concession has to be accounted for. Requiring the reason at the point
    # the discount is granted is the only moment anyone still knows it.
    if amount < outstanding - 0.01 and not reason:
        return None, reason, ('Give a reason for billing below the outstanding '
                              'balance - it is recorded against the discount.')

    return amount, reason, None


def _vehicle_outstanding(vehicles) -> float:
    """What a set of vehicles owes: charges less receipts, never below zero."""
    charges = sum(v.amc_charges or 0.0 for v in vehicles)
    received = sum(v.recovered_amount or 0.0 for v in vehicles)
    return max(0.0, charges - received)


@annual_recovery_bp.route('/invoice/vehicle/<int:vehicle_id>/pdf', methods=['GET', 'POST'])
@login_required
@role_required('recovery_officer', 'admin', 'manager', 'executive')
def amc_invoice_pdf(vehicle_id):
    """Vehicle-wise AMC invoice - one vehicle's annual monitoring charge.

    POST carries the amount override; GET bills the full balance, which keeps
    a plain link to this route working.
    """
    import os
    from flask import send_file
    from src.services.pdf_service import PDFService

    vehicle = AnnualRecoveryVehicle.query.get_or_404(vehicle_id)
    if not can_access_vehicle(vehicle):
        flash('That vehicle belongs to a sheet that is not assigned to you.', 'danger')
        return redirect(url_for('annual_recovery.dashboard'))

    override, reason, error = _requested_override(_vehicle_outstanding([vehicle]))
    if error:
        flash(error, 'danger')
        return redirect(url_for('annual_recovery.dashboard'))

    result = PDFService().generate_amc_invoice_pdf(
        vehicle_id, override_amount=override, discount_reason=reason,
        user_id=current_user.id)

    if result and os.path.exists(result['filepath']):
        record = result['invoice']
        log_recovery_audit(
            'INVOICE_GENERATED',
            f'{record.invoice_number}: vehicle-wise AMC invoice for '
            f'{vehicle.reg_no} - billed PKR {record.invoiced_amount:,.2f} '
            f'of PKR {record.outstanding_amount:,.2f} outstanding'
            + (f', discount PKR {record.discount_amount:,.2f} ({record.discount_reason})'
               if record.is_discounted else ''))
        return send_file(result['filepath'], as_attachment=True,
                         download_name=os.path.basename(result['filepath']))

    flash(INVOICE_FAILED_MESSAGE, 'danger')
    return redirect(url_for('annual_recovery.dashboard'))


@annual_recovery_bp.route('/invoice/client/<int:client_id>/pdf', methods=['GET', 'POST'])
@login_required
@role_required('recovery_officer', 'admin', 'manager', 'executive')
def amc_client_invoice_pdf(client_id):
    """Customer-wise AMC invoice - every vehicle the caller may bill, on one
    demand.

    The vehicle set is scoped before it reaches the renderer: a recovery
    officer invoices the sheets assigned to them, so a client whose fleet
    spans several sheets must not be billed for the ones they cannot see.
    """
    import os
    from flask import send_file
    from src.services.pdf_service import PDFService

    client = AnnualRecoveryClient.query.get_or_404(client_id)
    vehicles = scope_vehicles(
        AnnualRecoveryVehicle.query.filter_by(client_id=client_id)
    ).order_by(AnnualRecoveryVehicle.reg_no.asc()).all()

    if not vehicles:
        flash('This customer has no vehicles on the sheets assigned to you.', 'warning')
        return redirect(url_for('annual_recovery.dashboard'))

    # Written-off vehicles are not billed, so a customer whose whole fleet is
    # written off has nothing to invoice. Said plainly here rather than left to
    # the generic failure below, which talks about the PDF renderer and would
    # send the officer looking for a fault that does not exist.
    billable = [v for v in vehicles if (v.status or '').upper() != 'LOST']
    if not billable:
        flash('Every vehicle for this customer is marked LOST, so there is '
              'nothing to invoice.', 'warning')
        return redirect(url_for('annual_recovery.dashboard'))

    override, reason, error = _requested_override(_vehicle_outstanding(billable))
    if error:
        flash(error, 'danger')
        return redirect(url_for('annual_recovery.dashboard'))

    result = PDFService().generate_amc_client_invoice_pdf(
        client_id, vehicles=vehicles, override_amount=override,
        discount_reason=reason, user_id=current_user.id)

    if result and os.path.exists(result['filepath']):
        record = result['invoice']
        log_recovery_audit(
            'INVOICE_GENERATED',
            f'{record.invoice_number}: customer-wise AMC invoice for '
            f'{client.name} ({record.vehicle_count} vehicles) - billed '
            f'PKR {record.invoiced_amount:,.2f} of '
            f'PKR {record.outstanding_amount:,.2f} outstanding'
            + (f', discount PKR {record.discount_amount:,.2f} ({record.discount_reason})'
               if record.is_discounted else ''))
        return send_file(result['filepath'], as_attachment=True,
                         download_name=os.path.basename(result['filepath']))

    flash(INVOICE_FAILED_MESSAGE, 'danger')
    return redirect(url_for('annual_recovery.dashboard'))
