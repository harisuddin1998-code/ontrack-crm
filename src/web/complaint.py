# src/web/complaint.py
"""
Complaint Management Routes
"""
from datetime import datetime
from typing import Any, Dict, Optional

from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from src.web import complaint_bp
from src.services.complaint_service import ComplaintService
from src.services.technician_service import TechnicianService
from src.services.vehicle_search_service import VehicleSearchService
from src.forms.complaint_forms import ComplaintForm, ComplaintResolveForm
from src.utils.decorators import role_required
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _sync_values(stats: Dict[str, Any], complaints=None) -> Dict[str, str]:
    """Complaint figures formatted for the live-sync loop.

    Same arrangement as the admin dashboard: one map, rendered into the page
    by Jinja and written back into it by the 120-second refresh, so a
    refreshed count is produced by exactly the code that produced the one on
    the page.

    Passing `complaints` adds a per-ticket status entry. That is what makes a
    Complaint Manager moving a ticket to RESOLVED show up on the raiser's
    wallboard without them reloading anything.
    """
    from src.utils.formatting import format_count

    values = {
        'c_total': format_count(stats.get('total', 0)),
        'c_open': format_count(stats.get('open', 0)),
        'c_in_progress': format_count(stats.get('in_progress', 0)),
        'c_resolved': format_count(stats.get('resolved', 0)),
        'c_critical': format_count(stats.get('critical', 0)),
    }
    for c in (complaints or []):
        values[f'ticket_{c.id}_status'] = c.status
        values[f'ticket_{c.id}_resolution'] = c.resolution_notes or '—'
        values[f'ticket_{c.id}_resolved_at'] = (
            c.resolved_at.strftime('%d %b %Y %H:%M') if c.resolved_at else '—')
    return values


def _parse_date(raw: Optional[str]):
    """A date from the search form, or None if it was left blank or typed
    into by hand as something that isn't a date. A malformed date must not
    500 the board - it simply doesn't narrow anything."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw.strip(), '%Y-%m-%d').date()
    except ValueError:
        return None


def _search_criteria() -> Dict[str, Any]:
    """What the user typed into the ticket search, off the query string.

    Read in one place so the board, its paging links and its stat cards all
    agree on what the current search is.
    """
    return {
        'ticket_no': (request.args.get('ticket_no') or '').strip(),
        'reg_no': (request.args.get('reg_no') or '').strip(),
        'contact': (request.args.get('contact') or '').strip(),
        'date_from': _parse_date(request.args.get('date_from')),
        'date_to': _parse_date(request.args.get('date_to')),
    }


@complaint_bp.route('/')
@login_required
@role_required('complaint_manager', 'admin', 'executive')
def dashboard():
    """Complaints wallboard - a searchable list of every ticket.

    Administrators and Complaint Managers both land here and both see every
    complaint - one query, no role branch, so the two roles cannot end up
    looking at different sets of tickets.

    One list, not a board: a ticket is worked from its number, its vehicle or
    the customer's phone, and those are things you search for, not things you
    spot by scanning three columns of cards.
    """
    complaint_service = ComplaintService()
    complaint_service.auto_seed_sample_complaints()

    status = request.args.get('status', '')
    severity = request.args.get('severity', '')
    page = request.args.get('page', 1, type=int)
    per_page = 20

    filters: Dict[str, Any] = {}
    if status:
        filters['status'] = status
    if severity:
        filters['severity'] = severity

    criteria = _search_criteria()
    result = complaint_service.get_complaints(
        filters=filters, page=page, per_page=per_page, criteria=criteria)
    stats = complaint_service.get_dashboard_stats()

    total = result['total']
    total_pages = max(1, (total + per_page - 1) // per_page)

    # Everything needed to rebuild this exact search on another page or
    # behind a stat card, so paging never silently drops what was typed.
    query_state = {
        'ticket_no': criteria['ticket_no'],
        'reg_no': criteria['reg_no'],
        'contact': criteria['contact'],
        'date_from': request.args.get('date_from', ''),
        'date_to': request.args.get('date_to', ''),
    }
    is_searching = any(query_state.values())

    return render_template(
        'complaints/dashboard.html',
        complaints=result['items'],
        stats=stats,
        sync=_sync_values(stats, result['items']),
        status=status,
        severity=severity,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        query_state=query_state,
        is_searching=is_searching,
        total=total
    )


@complaint_bp.route('/my')
@login_required
def my_complaints():
    """One user's own complaints, and nothing else.

    Deliberately not the manager wallboard with a filter bolted on: the
    scoping is the query (`get_user_complaints`), not something the template
    applies, so there is no arrangement of parameters that widens it. Anyone
    who can log a complaint can reach this page - it is their record of what
    they reported and what came of it.
    """
    complaint_service = ComplaintService()
    complaints = complaint_service.get_user_complaints(current_user.id)
    stats = complaint_service.get_dashboard_stats(user_id=current_user.id)

    status = (request.args.get('status') or '').strip().upper()
    if status:
        complaints = [c for c in complaints if c.status == status]

    return render_template(
        'complaints/my_dashboard.html',
        complaints=complaints,
        stats=stats,
        sync=_sync_values(stats, complaints),
        status=status,
    )


@complaint_bp.route('/my/api/sync')
@login_required
def api_my_sync():
    """Live values for one user's own complaint wallboard."""
    complaint_service = ComplaintService()
    complaints = complaint_service.get_user_complaints(current_user.id)
    stats = complaint_service.get_dashboard_stats(user_id=current_user.id)
    return jsonify({'success': True, 'values': _sync_values(stats, complaints)})


@complaint_bp.route('/api/sync')
@login_required
@role_required('complaint_manager', 'admin', 'executive')
def api_sync():
    """Live values for the Complaint Manager / Administrator wallboard.

    Both roles poll this one endpoint, which is what keeps their boards in
    step with each other and with the user's.
    """
    complaint_service = ComplaintService()
    stats = complaint_service.get_dashboard_stats()
    return jsonify({'success': True,
                    'values': _sync_values(stats, complaint_service.get_all())})


def _registry_state() -> Dict[str, Any]:
    """How much of the fleet the search can currently see.

    The form searches a local dump of SJ_MIS's master roster, so "no results"
    has two very different causes - the vehicle is not on the roster, or the
    dump has never been taken. Saying how many vehicles are searchable, and
    when the copy was made, tells the two apart at a glance.
    """
    from src.models.vehicle_registry import VehicleRegistryEntry

    latest = VehicleRegistryEntry.query.order_by(
        VehicleRegistryEntry.synced_at.desc()).first()
    return {
        'registry_count': VehicleRegistryEntry.query.count(),
        'registry_synced_at': latest.synced_at if latest else None,
        'can_sync_registry': current_user.is_admin() or current_user.is_manager(),
    }


@complaint_bp.route('/vehicles/sync', methods=['POST'])
@login_required
@role_required('admin', 'manager')
def sync_vehicle_registry():
    """Re-take the local dump of SJ_MIS's master vehicle roster.

    It refreshes itself nightly; this is for the case where a vehicle was
    added to SJ_MIS today and somebody needs to log a complaint against it
    now.
    """
    from src.services.db_sync_service import DBSyncService

    result = DBSyncService().sync_vehicle_registry()
    if result.get('error'):
        flash('Vehicle list refresh failed - could not reach SJ_MIS.', 'danger')
    else:
        flash(f"Vehicle list refreshed: {result['new']} new, "
              f"{result['updated']} updated.", 'success')
    return redirect(url_for('complaint.new'))


@complaint_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    """Log a new complaint ticket"""
    form = ComplaintForm()

    # The roster from Technician Management, and nothing else - a ticket can
    # only be given to a technician who actually exists and is still active.
    form.technician_id.choices = [(0, '-- Unassigned --')] + [
        (t.id, t.name) for t in TechnicianService.get_roster()]

    if form.validate_on_submit():
        complaint_service = ComplaintService()
        try:
            technician_id = form.technician_id.data if form.technician_id.data and form.technician_id.data > 0 else None
            data = {
                'customer_name': form.customer_name.data,
                'customer_contact': form.customer_contact.data,
                'reg_no': (form.reg_no.data or '').upper(),
                'city': form.city.data,
                'vehicle_location': (form.vehicle_location.data or '').upper() if form.vehicle_location.data else None,
                'complaint_type': form.complaint_type.data,
                'severity': form.severity.data,
                'description': form.description.data,
                'technician_id': technician_id
            }
            complaint = complaint_service.create_complaint(data, current_user.id)
            flash(f'✅ Complaint Ticket {complaint.ticket_no} logged successfully!', 'success')
            # Managers go to the board they work from; everyone else goes to
            # their own record of what they have reported, where they can
            # watch this ticket through to resolution. Landing back on an
            # empty form told them nothing about the one they just filed.
            if current_user.is_admin() or current_user.is_complaint_manager() or current_user.is_executive():
                return redirect(url_for('complaint.dashboard'))
            return redirect(url_for('complaint.my_complaints'))
        except Exception as e:
            flash(f'❌ Error logging complaint: {str(e)}', 'danger')

    return render_template('complaints/form.html', form=form,
                           title='Log New Complaint', **_registry_state())


@complaint_bp.route('/<int:complaint_id>', methods=['GET', 'POST'])
@login_required
@role_required('complaint_manager', 'admin', 'executive')
def detail(complaint_id):
    """View complaint ticket details & resolve"""
    complaint_service = ComplaintService()
    complaint = complaint_service.get_by_id(complaint_id)

    if not complaint:
        flash('Complaint ticket not found', 'danger')
        return redirect(url_for('complaint.dashboard'))

    form = ComplaintResolveForm(obj=complaint)
    technicians = TechnicianService.get_roster()

    if request.method == 'POST' and form.validate_on_submit():
        try:
            if form.status.data == 'RESOLVED':
                complaint_service.resolve_complaint(complaint_id, current_user.id, form.resolution_notes.data)
                flash(f'✅ Ticket {complaint.ticket_no} resolved successfully!', 'success')
            else:
                complaint_service.update_complaint(complaint_id, {
                    'status': form.status.data,
                    'resolution_notes': form.resolution_notes.data
                })
                flash(f'Ticket {complaint.ticket_no} updated to {form.status.data}', 'info')
            return redirect(url_for('complaint.detail', complaint_id=complaint_id))
        except Exception as e:
            flash(f'❌ Update error: {str(e)}', 'danger')

    return render_template(
        'complaints/detail.html',
        complaint=complaint,
        form=form,
        technicians=technicians
    )


@complaint_bp.route('/<int:complaint_id>/assign', methods=['POST'])
@login_required
@role_required('complaint_manager', 'admin', 'executive')
def assign(complaint_id):
    """Assign a complaint to a technician from Technician Management."""
    complaint_service = ComplaintService()
    tech_id = request.form.get('technician_id', type=int)

    if not tech_id:
        flash('No technician selected', 'warning')
        return redirect(url_for('complaint.detail', complaint_id=complaint_id))

    # Checked against the roster rather than trusted from the form: the
    # dropdown only offers active technicians, and a posted id has to mean
    # the same thing.
    technician = next((t for t in TechnicianService.get_roster() if t.id == tech_id), None)
    if technician is None:
        flash('That technician is not on the active roster.', 'warning')
        return redirect(url_for('complaint.detail', complaint_id=complaint_id))

    try:
        complaint = complaint_service.assign_complaint(complaint_id, tech_id)
        flash(f'✅ Ticket {complaint.ticket_no} assigned to {technician.name}!', 'success')
    except Exception as e:
        flash(f'❌ Assignment error: {str(e)}', 'danger')

    return redirect(url_for('complaint.detail', complaint_id=complaint_id))


@complaint_bp.route('/api/stats')
@login_required
@role_required('complaint_manager', 'admin', 'executive')
def api_stats():
    """API endpoint for complaint metrics"""
    complaint_service = ComplaintService()
    return jsonify({'success': True, 'stats': complaint_service.get_dashboard_stats()})


@complaint_bp.route('/api/vehicle-search')
@login_required
def api_vehicle_search():
    """Live multi-field vehicle & customer search for the complaint form -
    matches reg no, phone/cell number, IMEI, or SIM, case-insensitively,
    across reporting AND non-reporting vehicles alike."""
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify({'results': []})

    results = VehicleSearchService().search(query)
    return jsonify({'results': results})
