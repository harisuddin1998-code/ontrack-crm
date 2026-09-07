# src/web/live_amc.py
"""
Live AMC Routes - daily anniversary-based AMC recovery assignment dashboard.
"""
import calendar
from datetime import date

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from src.web import live_amc_bp
from src.models.amc_database_assignment import AmcDatabaseAssignment
from src.models.amc_recovery_record import AmcRecoveryRecord
from src.models.live_amc import LiveAmcAssignment
from src.services.amc_database_recovery_service import AmcDatabaseRecoveryService
from src.services.live_amc_service import LiveAmcService
from src.utils.decorators import role_required
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _safe_date(year: int, month: int, day: int) -> date:
    """Clamp an out-of-range day (e.g. day=31 picked, then month changed to
    February) to the last real day of that month instead of raising."""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


@live_amc_bp.route('/dashboard')
@login_required
@role_required('recovery_officer', 'admin', 'manager', 'executive')
def dashboard():
    """Live AMC dashboard - browse any year/month's anniversary calendar,
    drill into a specific day's due vehicles. Today's list is generated
    (round-robin across recovery officers) on first view each day; past
    days show whatever was actually generated at the time; future days
    only show a preview count, since assignment happens live, daily."""
    service = LiveAmcService()
    today = date.today()

    year = request.args.get('year', today.year, type=int)
    month = request.args.get('month', today.month, type=int)
    day = request.args.get('day', today.day if (year, month) == (today.year, today.month) else 1, type=int)
    target_date = _safe_date(year, month, day)

    month_matrix = service.get_month_matrix(year, month)

    assignments = []
    preview_count = None
    if target_date == today:
        service.get_or_create_assignments(target_date, current_user.id)
        assignments = service.get_assignments_for_view(target_date, current_user)
    elif target_date < today:
        assignments = service.get_assignments_for_view(target_date, current_user)
    else:
        preview_count = len(service.get_matching_vehicles(target_date.day, target_date.month))

    officers = service.get_recovery_officers()

    return render_template('live_amc/dashboard.html',
                         year=year,
                         month=month,
                         day=day,
                         target_date=target_date,
                         today=today,
                         month_matrix=month_matrix,
                         assignments=assignments,
                         preview_count=preview_count,
                         officers=officers,
                         month_name=calendar.month_name[month],
                         calendar_month_names=list(calendar.month_name))


@live_amc_bp.route('/generate', methods=['POST'])
@login_required
@role_required('admin', 'manager')
def generate():
    """Manually (re-)trigger round-robin generation for a given date -
    mainly for today, but also usable to catch up a missed day."""
    service = LiveAmcService()
    date_str = request.form.get('date', '')
    try:
        y, m, d = (int(p) for p in date_str.split('-'))
        target_date = _safe_date(y, m, d)
    except (ValueError, TypeError):
        target_date = date.today()

    assignments = service.get_or_create_assignments(target_date, current_user.id)
    if assignments:
        flash(f"Generated {len(assignments)} AMC follow-up assignment(s) for {target_date.strftime('%d %B %Y')}.", 'success')
    else:
        flash(f"No vehicles have an AMC anniversary on {target_date.strftime('%d %B')}.", 'info')

    return redirect(url_for('live_amc.dashboard', year=target_date.year, month=target_date.month, day=target_date.day))


@live_amc_bp.route('/<int:assignment_id>/update', methods=['POST'])
@login_required
@role_required('recovery_officer', 'admin', 'manager')
def update_assignment(assignment_id):
    """Update an assignment's daily work status/remarks. Officers may only
    touch their own assignments; admin/manager can touch any."""
    assignment = LiveAmcAssignment.query.get_or_404(assignment_id)

    if current_user.is_recovery_officer() and not current_user.is_admin() and not current_user.is_manager():
        if assignment.assigned_officer_id != current_user.id:
            flash('You can only update your own assigned vehicles.', 'danger')
            return redirect(url_for('live_amc.dashboard'))

    work_status = request.form.get('work_status')
    remarks = request.form.get('remarks')
    service = LiveAmcService()
    service.update_assignment(assignment_id, work_status=work_status, remarks=remarks)
    flash('Updated.', 'success')

    d = assignment.due_date
    return redirect(url_for('live_amc.dashboard', year=d.year, month=d.month, day=d.day))


@live_amc_bp.route('/database-recoveries')
@login_required
@role_required('recovery_officer', 'admin', 'manager', 'executive')
def database_recoveries():
    """AMC Recoveries - Database Method: the daily follow-up list.

    Same anniversary rule as the Sheet Method above, applied to SJ_MIS's own
    AMCInfo payment ledger instead of the imported spreadsheet. The vehicles
    due on the chosen date are clubbed by customer and round-robined across
    the Recovery Officers; each officer sees the customers that are theirs
    and nobody else's.

    Any date can be opened, and any date up to today can be generated - the
    anniversary rule does not depend on when the question is asked, so a day
    that went by unworked can still be reconstructed and followed up. Future
    dates show a count only: who is on shift next month is not knowable now.
    """
    service = AmcDatabaseRecoveryService()
    today = date.today()

    year = request.args.get('year', today.year, type=int)
    month = request.args.get('month', today.month, type=int)
    day = request.args.get('day', today.day if (year, month) == (today.year, today.month) else 1, type=int)
    target_date = _safe_date(year, month, day)

    month_matrix = service.get_month_matrix(year, month)
    officers = service.get_recovery_officers()

    assignments = []
    preview_count = None
    if target_date <= today:
        # Today generates itself on first view; a past date is only
        # generated when somebody asks for it, so opening an old day to look
        # at it does not invent a distribution that never happened.
        if target_date == today:
            service.get_or_create_assignments(target_date, current_user.id)
        assignments = service.get_assignments_for_view(target_date, current_user)
    else:
        preview_count = service.count_due(target_date.day, target_date.month)

    customers = service.group_by_customer(assignments)
    summary = service.day_summary(assignments)

    ledger_row = AmcRecoveryRecord.query.order_by(AmcRecoveryRecord.synced_at.desc()).first()

    return render_template('live_amc/database_recoveries.html',
                         year=year,
                         month=month,
                         day=day,
                         target_date=target_date,
                         today=today,
                         month_matrix=month_matrix,
                         customers=customers,
                         summary=summary,
                         preview_count=preview_count,
                         officers=officers,
                         can_generate=current_user.is_admin() or current_user.is_manager(),
                         ledger_size=AmcRecoveryRecord.query.count(),
                         ledger_synced_at=ledger_row.synced_at if ledger_row else None,
                         work_statuses=AmcDatabaseAssignment.WORK_STATUSES,
                         month_name=calendar.month_name[month],
                         calendar_month_names=list(calendar.month_name))


@live_amc_bp.route('/database-recoveries/generate', methods=['POST'])
@login_required
@role_required('admin', 'manager')
def database_generate():
    """Pull the ledger from SJ_MIS and build a date's follow-up list.

    Works for today and for any past date, which is the point: a day nobody
    generated at the time is not lost, because the anniversary rule can be
    applied to it afterwards and produce exactly the same list.

    `regenerate` redistributes a day that already has a list. It discards the
    outcomes recorded against that day, so it is a separate button rather
    than what the ordinary one quietly does.
    """
    service = AmcDatabaseRecoveryService()

    date_str = request.form.get('date', '')
    try:
        y, m, d = (int(part) for part in date_str.split('-'))
        target_date = _safe_date(y, m, d)
    except (ValueError, TypeError):
        target_date = date.today()

    if target_date > date.today():
        flash('That date has not happened yet - AMC follow-ups are distributed '
              'on the day, not booked in advance.', 'warning')
        return redirect(url_for('live_amc.database_recoveries',
                                year=target_date.year, month=target_date.month,
                                day=target_date.day))

    regenerate = request.form.get('regenerate') == '1'
    if not service.get_recovery_officers():
        flash('No active Recovery Officers are configured, so the day cannot be '
              'distributed. Assign the AMC / Annual Recovery Officer role first.', 'warning')

    result = service.run_daily(target_date=target_date, sync_first=True)
    if regenerate:
        service.get_or_create_assignments(target_date, current_user.id, regenerate=True)
        result['assignments'] = len(service.get_assignments_for_view(target_date, current_user))

    synced = result.get('synced_records')
    if synced is None:
        flash('Could not reach SJ_MIS - the list was built from the ledger already on file.', 'warning')

    if result['assignments']:
        flash(f"{result['assignments']} AMC follow-up(s) ready for "
              f"{target_date.strftime('%d %B %Y')}.", 'success')
    else:
        flash(f"No vehicle has an AMC anniversary on {target_date.strftime('%d %B')}.", 'info')

    return redirect(url_for('live_amc.database_recoveries',
                            year=target_date.year, month=target_date.month,
                            day=target_date.day))


@live_amc_bp.route('/database-recoveries/<int:assignment_id>/update', methods=['POST'])
@login_required
@role_required('recovery_officer', 'admin', 'manager')
def database_update_assignment(assignment_id):
    """Record the outcome of one vehicle's follow-up.

    An officer may only touch their own; admin and manager may touch any.
    """
    assignment = AmcDatabaseAssignment.query.get_or_404(assignment_id)

    if current_user.is_recovery_officer() and not (current_user.is_admin() or current_user.is_manager()):
        if assignment.assigned_officer_id != current_user.id:
            flash('That customer was assigned to another officer.', 'danger')
            return redirect(url_for('live_amc.database_recoveries'))

    AmcDatabaseRecoveryService().update_assignment(
        assignment_id,
        work_status=request.form.get('work_status'),
        remarks=request.form.get('remarks'))
    flash('Follow-up recorded.', 'success')

    d = assignment.due_date
    return redirect(url_for('live_amc.database_recoveries',
                            year=d.year, month=d.month, day=d.day))


@live_amc_bp.route('/database-recoveries/customer/update', methods=['POST'])
@login_required
@role_required('recovery_officer', 'admin', 'manager')
def database_update_customer():
    """Record one outcome against every vehicle a customer had due that day.

    The vehicles are clubbed because it is one call; closing them out is one
    action for the same reason.
    """
    service = AmcDatabaseRecoveryService()

    try:
        y, m, d = (int(part) for part in request.form.get('date', '').split('-'))
        due_date = _safe_date(y, m, d)
    except (ValueError, TypeError):
        flash('Could not tell which day that was for.', 'danger')
        return redirect(url_for('live_amc.database_recoveries'))

    client_key = (request.form.get('client_key') or '').strip()
    if not client_key:
        flash('Could not tell which customer that was for.', 'danger')
        return redirect(url_for('live_amc.database_recoveries',
                                year=due_date.year, month=due_date.month, day=due_date.day))

    updated = service.update_customer(
        due_date, client_key,
        work_status=request.form.get('work_status'),
        remarks=request.form.get('remarks'),
        current_user=current_user)

    if updated:
        flash(f'Follow-up recorded against {updated} vehicle(s).', 'success')
    else:
        flash('Nothing to record - those vehicles are not yours to close out.', 'warning')

    return redirect(url_for('live_amc.database_recoveries',
                            year=due_date.year, month=due_date.month, day=due_date.day))
