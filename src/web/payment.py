# src/web/payment.py
"""
Payment Recovery Routes
"""
from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from src.web import payment_bp
from src.extensions import db
from src.services import PaymentRecoveryService, POService
from src.forms.payment_forms import PaymentForm
from src.utils.decorators import role_required
from src.utils.logging import get_logger

logger = get_logger(__name__)


@payment_bp.route('/dashboard')
@login_required
@role_required('payment_recovery', 'admin', 'executive')
def dashboard():
    """Installation Payment Recovery dashboard. AMC/monitoring charges are
    shown here only as a billed reference figure - once a PO completes, its
    AMC obligation is transferred into Annual Recovery (see
    POService._transfer_amc_to_annual_recovery), which is what actually
    loops the follow-up every year, so it's flagged as transferred here
    rather than tracked twice."""
    from src.models.annual_recovery import AnnualRecoveryVehicle

    payment_service = PaymentRecoveryService()

    stats = payment_service.get_dashboard_stats()
    recent_payments = payment_service.get_recent(10)

    transferred_reg_nos = {r[0] for r in db.session.query(AnnualRecoveryVehicle.reg_no).all() if r[0]}

    return render_template('payment/dashboard.html',
                         stats=stats,
                         payments=recent_payments,
                         transferred_reg_nos=transferred_reg_nos)


@payment_bp.route('/list')
@login_required
@role_required('payment_recovery', 'admin', 'executive')
def payment_list():
    """List payments"""
    payment_service = PaymentRecoveryService()
    
    status = request.args.get('status', '')
    search = request.args.get('search', '')
    
    filters = {}
    if status:
        filters['payment_status'] = status
    
    result = payment_service.get_payments(filters=filters, search=search)
    
    return render_template('payment/list.html',
                         payments=result['items'],
                         total=result['total'],
                         status=status,
                         search=search)


@payment_bp.route('/<int:payment_id>', methods=['GET', 'POST'])
@login_required
@role_required('payment_recovery', 'admin')
def payment_detail(payment_id):
    """View/Update payment detail"""
    payment_service = PaymentRecoveryService()
    payment = payment_service.get_by_id(payment_id)
    
    if not payment:
        flash('Payment record not found', 'danger')
        return redirect(url_for('payment.dashboard'))
    
    form = PaymentForm()

    if form.validate_on_submit() and request.form.get('action') == 'add_payment':
        from src.services.payment_proof_service import save_payment_proof

        method = form.payment_method.data
        proof_file = request.files.get('proof_file')
        if method == 'ONLINE' and not (proof_file and proof_file.filename):
            flash('Proof of payment is required for online payments.', 'danger')
            return redirect(url_for('payment.payment_detail', payment_id=payment_id))

        amount = form.amount.data
        if amount is None:
            flash('Amount is required.', 'danger')
            return redirect(url_for('payment.payment_detail', payment_id=payment_id))

        try:
            proof_path = save_payment_proof(proof_file, 'installation', payment_id)
            reference = form.transaction_id.data if method == 'ONLINE' else (form.cheque_number.data if method == 'CHEQUE' else None)
            payment_service.add_payment(
                payment_id=payment_id,
                amount=amount,
                user_id=current_user.id,
                notes=form.notes.data,
                payment_method=method,
                proof_of_payment_path=proof_path,
                reference=reference,
            )
            flash(f'Payment of PKR {amount:,.2f} recorded!', 'success')
            return redirect(url_for('payment.payment_detail', payment_id=payment_id))
        except ValueError as e:
            flash(str(e), 'danger')
        except Exception as e:
            flash(str(e), 'danger')
    
    # Get payment history
    history = payment_service.get_payment_history(payment_id)
    
    return render_template('payment/detail.html',
                         payment=payment,
                         form=form,
                         history=history)


@payment_bp.route('/<int:payment_id>/update-status', methods=['POST'])
@login_required
@role_required('payment_recovery', 'admin')
def update_status(payment_id):
    """Update payment status"""
    payment_service = PaymentRecoveryService()
    status = request.form.get('status')
    
    try:
        payment = payment_service.update_status(payment_id, status)
        flash(f'Payment status updated to {status}', 'success')
    except Exception as e:
        flash(str(e), 'danger')
    
    return redirect(url_for('payment.payment_detail', payment_id=payment_id))


@payment_bp.route('/<int:payment_id>/follow-up', methods=['POST'])
@login_required
@role_required('payment_recovery', 'admin')
def follow_up(payment_id):
    """Schedule follow-up"""
    payment_service = PaymentRecoveryService()
    next_follow_up = request.form.get('next_follow_up')

    try:
        payment = payment_service.schedule_follow_up(payment_id, next_follow_up)
        flash('Follow-up scheduled successfully', 'success')
    except Exception as e:
        flash(str(e), 'danger')

    return redirect(url_for('payment.payment_detail', payment_id=payment_id))


# ============================================
# DEVICE RECOVERY - device replacement charges
# (Power Issue / Device Damage / Device Missing), auto-created from REDO
# activities - a separate ledger from the PO payment recovery above.
#
# Reachable by its own `device_recovery` role as well as by an Installation
# Recovery officer, so this screen can be granted on its own (Additional Views
# on the user form) without also handing over the PO payment ledger above.
# Every route in this section shares one list, so a new route cannot silently
# be added with narrower or wider access than its neighbours.
# ============================================

DEVICE_RECOVERY_ROLES = ('device_recovery', 'payment_recovery', 'admin', 'manager')


def _restricted_to_own_charges(user) -> bool:
    """True when this user may only touch charges assigned to them.

    Shares the service's definition so the per-charge checks below and the list
    the user is shown can never disagree about who owns what.
    """
    from src.services.installation_recovery_service import InstallationRecoveryService
    return (InstallationRecoveryService.works_device_recovery(user)
            and not InstallationRecoveryService.is_supervisor(user))


@payment_bp.route('/installation-recovery')
@login_required
@role_required(*DEVICE_RECOVERY_ROLES, 'executive')
def installation_recovery_dashboard():
    """Device Recovery dashboard - three layers/tabs (Power Issue / Device
    Damage / Device Missing), each with the same functionality (follow-ups,
    payment recording). Officer's own list (or all, for admin/manager),
    with status + reason filters."""
    from src.services.installation_recovery_service import InstallationRecoveryService, TRIGGERING_REASONS

    service = InstallationRecoveryService()
    reason = request.args.get('reason', '').strip()
    charges = _installation_recovery_filtered_charges()
    stats = service.get_dashboard_stats(current_user, reason=reason or None)
    reason_counts = service.get_reason_counts(current_user)
    # Only supervisors can reassign, so only they need the roster to pick from.
    officers = (service.get_officers()
                if InstallationRecoveryService.is_supervisor(current_user) else [])

    return render_template('payment/installation_recovery.html',
                         charges=charges,
                         stats=stats,
                         officers=officers,
                         reason_choices=TRIGGERING_REASONS,
                         reason_counts=reason_counts,
                         reason=reason,
                         status=request.args.get('status', '').strip(),
                         search=request.args.get('search', '').strip())


def _installation_recovery_filtered_charges():
    """Shared filter logic for the dashboard view and both export routes,
    so what you see on screen is exactly what downloads."""
    from src.services.installation_recovery_service import InstallationRecoveryService
    service = InstallationRecoveryService()
    status = request.args.get('status', '').strip()
    reason = request.args.get('reason', '').strip()
    search = request.args.get('search', '').strip()
    charges = service.get_charges_for_view(current_user, status=status or None, reason=reason or None)
    if search:
        s = search.lower()
        charges = [c for c in charges if c.redo_activity and (
            s in (c.redo_activity.registration_no or '').lower()
            or s in (c.redo_activity.customer_name or '').lower()
        )]
    return charges


@payment_bp.route('/installation-recovery/export/excel')
@login_required
@role_required(*DEVICE_RECOVERY_ROLES, 'executive')
def installation_recovery_export_excel():
    import os
    from flask import send_file
    from src.services.mis_export_service import MISExportService

    charges = _installation_recovery_filtered_charges()
    filepath = MISExportService().generate_installation_recovery_excel(charges)
    return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))


@payment_bp.route('/installation-recovery/export/pdf')
@login_required
@role_required(*DEVICE_RECOVERY_ROLES, 'executive')
def installation_recovery_export_pdf():
    import os
    from flask import send_file, abort
    from src.services.pdf_service import PDFService

    charges = _installation_recovery_filtered_charges()
    filepath = PDFService().generate_installation_recovery_report_pdf(charges)
    if not filepath:
        abort(500)
    return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))


@payment_bp.route('/installation-recovery/<int:charge_id>/contacted', methods=['POST'])
@login_required
@role_required(*DEVICE_RECOVERY_ROLES)
def installation_recovery_contacted(charge_id):
    from src.services.installation_recovery_service import InstallationRecoveryService
    InstallationRecoveryService().mark_contacted(charge_id, request.form.get('notes'))
    flash('Marked as contacted.', 'success')
    return redirect(url_for('payment.installation_recovery_dashboard'))


@payment_bp.route('/installation-recovery/<int:charge_id>/lost', methods=['POST'])
@login_required
@role_required('admin', 'manager')
def installation_recovery_mark_lost(charge_id):
    reason = request.form.get('reason', '').strip()
    if not reason:
        flash('A reason is required to mark a charge as lost.', 'danger')
        return redirect(url_for('payment.installation_recovery_dashboard'))
    from src.services.installation_recovery_service import InstallationRecoveryService
    InstallationRecoveryService().mark_lost(charge_id, reason)
    flash('Charge marked as lost.', 'success')
    return redirect(url_for('payment.installation_recovery_dashboard'))


@payment_bp.route('/installation-recovery/<int:charge_id>/assign', methods=['POST'])
@login_required
@role_required('admin', 'manager')
def installation_recovery_assign(charge_id):
    """Hand a charge to a different Device Recovery officer.

    Supervisors only: an officer moving charges off their own list would be
    marking their own homework, and moving one onto someone else's is a
    workload decision.
    """
    from src.services.installation_recovery_service import InstallationRecoveryService

    raw = (request.form.get('officer_id') or '').strip()
    officer_id = None
    if raw:
        if not raw.isdigit():
            flash('Please choose an officer from the list.', 'danger')
            return redirect(url_for('payment.installation_recovery_dashboard'))
        officer_id = int(raw)

    charge = InstallationRecoveryService().reassign_charge(charge_id, officer_id,
                                                           actor=current_user)
    if charge is None:
        flash('Could not reassign that charge - check the officer still works '
              'Device Recovery and is active.', 'danger')
    else:
        who = charge.assigned_officer.name if charge.assigned_officer else 'nobody'
        flash(f'Charge reassigned to {who}.', 'success')
    return redirect(url_for('payment.installation_recovery_dashboard'))


@payment_bp.route('/installation-recovery/<int:charge_id>/contacts')
@login_required
@role_required(*DEVICE_RECOVERY_ROLES, 'executive')
def installation_recovery_contacts(charge_id):
    """Everything the follow-up form needs to know before the officer dials.

    Kept separate from the details endpoint, which also loads the full
    conversation history: this one opens every time someone records a call,
    and all it needs is who to ring, on what, and what happened last time.
    """
    from src.models.installation_recovery import InstallationRecoveryCharge
    from src.services.contact_book_service import ContactBookService
    from src.services.installation_recovery_service import InstallationRecoveryService

    charge = InstallationRecoveryCharge.query.get_or_404(charge_id)
    if _restricted_to_own_charges(current_user):
        if charge.assigned_officer_id != current_user.id:
            return jsonify({'success': False, 'message': 'Not your assigned charge.'}), 403

    activity = charge.redo_activity
    book = (ContactBookService().for_registration(activity.registration_no)
            if activity and activity.registration_no
            else {'numbers': [], 'names': []})

    entry = InstallationRecoveryService().followup_summaries([charge]).get(charge.id)
    last = entry['last'] if entry else None

    return jsonify({
        'success': True,
        'registration_no': activity.registration_no if activity else None,
        'customer_name': activity.customer_name if activity else None,
        'reason': charge.reason,
        'amount': charge.amount,
        'status': charge.status,
        'contacts': book['numbers'],
        'names': book['names'],
        'attempts': entry['count'] if entry else 0,
        'last_attempt': {
            'date': last.conversation_date.strftime('%d/%m/%Y %H:%M')
                    if last and last.conversation_date else None,
            'channel': ('WhatsApp' if last.conversation_type == 'WHATSAPP'
                        else 'Phone Call') if last else None,
            'number': last.contact_number if last else None,
            'summary': last.summary if last else None,
        } if last else None,
        'callback_due': (entry['next_due'].strftime('%d/%m/%Y')
                         if entry and entry['next_due'] else None),
    })


@payment_bp.route('/installation-recovery/<int:charge_id>/details')
@login_required
@role_required(*DEVICE_RECOVERY_ROLES, 'executive')
def installation_recovery_charge_details(charge_id):
    """JSON detail view for the Details action - charge info plus its full
    follow-up call/WhatsApp history, so an officer can see every past
    interaction on this charge without leaving the dashboard."""
    from src.models.installation_recovery import InstallationRecoveryCharge, InstallationRecoveryFollowup

    charge = InstallationRecoveryCharge.query.get_or_404(charge_id)
    if _restricted_to_own_charges(current_user):
        if charge.assigned_officer_id != current_user.id:
            return jsonify({'success': False, 'message': 'Not your assigned charge.'}), 403

    followups = InstallationRecoveryFollowup.query.filter_by(charge_id=charge_id) \
        .order_by(InstallationRecoveryFollowup.conversation_date.desc()).all()

    activity = charge.redo_activity
    # Every number on record for the vehicle, not just the one copied onto
    # the REDO activity - an officer looking at a charge that will not
    # answer needs the alternatives without leaving the modal.
    from src.services.contact_book_service import ContactBookService
    book = (ContactBookService().for_registration(activity.registration_no)
            if activity and activity.registration_no
            else {'numbers': [], 'names': []})
    return jsonify({
        'success': True,
        'charge': {
            'registration_no': activity.registration_no if activity else None,
            'customer_name': activity.customer_name if activity else None,
            'customer_contact': activity.customer_contact if activity else None,
            'reason': charge.reason,
            'amount': charge.amount,
            'status': charge.status,
            'assigned_officer_name': charge.assigned_officer.name if charge.assigned_officer else 'Unassigned',
            'payment_method': charge.payment_method,
            'payment_reference': charge.payment_reference,
            'has_proof': bool(charge.proof_of_payment_path),
            'proof_url': url_for('payment.installation_recovery_proof', charge_id=charge.id) if charge.proof_of_payment_path else None,
            'recovered_at': charge.recovered_at.strftime('%d/%m/%Y %H:%M') if charge.recovered_at else None,
            'notes': charge.notes,
            'created_at': charge.created_at.strftime('%d/%m/%Y %H:%M') if charge.created_at else None,
        },
        'contacts': book['numbers'],
        'contact_names': book['names'],
        'followups': [{
            'date': f.conversation_date.strftime('%d/%m/%Y %H:%M') if f.conversation_date else None,
            'channel': 'WhatsApp' if f.conversation_type == 'WHATSAPP' else 'Phone Call',
            'direction': f.direction,
            'contact_person': f.contact_person,
            'contact_number': f.contact_number,
            'summary': f.summary,
            'action_taken': f.action_taken,
            'follow_up_date': f.follow_up_date.strftime('%d/%m/%Y') if f.follow_up_date else None,
            'recorded_by_name': f.recorded_by_name,
        } for f in followups],
    })


@payment_bp.route('/installation-recovery/<int:charge_id>/record-payment', methods=['POST'])
@login_required
@role_required(*DEVICE_RECOVERY_ROLES)
def installation_recovery_record_payment(charge_id):
    """Payment Recording for a device-recovery charge - same method +
    proof-of-payment rules as the PO payment flow and AMC recovery."""
    from src.services.installation_recovery_service import InstallationRecoveryService
    from src.services.payment_proof_service import save_payment_proof

    method = request.form.get('payment_method', '')
    if method not in ('ONLINE', 'CASH', 'CHEQUE'):
        flash('Invalid payment method.', 'danger')
        return redirect(url_for('payment.installation_recovery_dashboard'))

    proof_file = request.files.get('proof_file')
    if method == 'ONLINE' and not (proof_file and proof_file.filename):
        flash('Proof of payment is required for online payments.', 'danger')
        return redirect(url_for('payment.installation_recovery_dashboard'))

    try:
        proof_path = save_payment_proof(proof_file, 'installation', charge_id)
    except ValueError as e:
        flash(str(e), 'danger')
        return redirect(url_for('payment.installation_recovery_dashboard'))

    reference = request.form.get('reference', '').strip() or None
    InstallationRecoveryService().record_payment(charge_id, method, reference, proof_path,
                                                  request.form.get('notes'))
    flash('Payment recorded.', 'success')
    return redirect(url_for('payment.installation_recovery_dashboard'))


@payment_bp.route('/installation-recovery/import-excel', methods=['POST'])
@login_required
@role_required(*DEVICE_RECOVERY_ROLES)
def installation_recovery_import_excel():
    """Bulk import Device Missing / Power Issue records from Excel, creating
    an Installation Recovery charge for every row. The sheet has no
    DEVICE_CHANGE_REASON column - one uploaded file is entirely Device
    Missing or entirely Power Issue, selected once in the upload form and
    applied to every row. Reads columns by HEADER NAME, not position - a
    reordered column fails loudly per-row instead of silently corrupting
    data. Every row is validated independently and reported; nothing fails
    silently."""
    import pandas as pd
    from src.models.redo import RedoActivity
    from src.services.installation_recovery_service import InstallationRecoveryService

    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'success': False, 'message': 'No file provided'}), 400

    reason = request.form.get('reason', '').strip()
    if reason not in ('Device Missing', 'Power Issue'):
        return jsonify({'success': False, 'message': 'A reason (Device Missing or Power Issue) is required for this file'}), 400

    try:
        df = pd.read_excel(file.stream)
    except Exception as e:
        return jsonify({'success': False, 'message': f'Could not read the file: {e}'}), 400

    df.columns = [f"{c}".strip().upper() for c in df.columns]

    def cell(row, col):
        val = row.get(col)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        text = str(val).strip()
        return text or None

    def cell_date(row, col):
        val = row.get(col)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None, None
        try:
            return pd.to_datetime(val).date(), None
        except Exception:
            return None, f"{col} '{val}' could not be parsed as a date"

    def cell_datetime(row, col):
        val = row.get(col)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None, None
        try:
            return pd.to_datetime(val).to_pydatetime(), None
        except Exception:
            return None, f"{col} '{val}' could not be parsed as a date/time"

    service = InstallationRecoveryService()
    imported = 0
    skipped = 0
    errors = []

    for pos, (_idx, row) in enumerate(df.iterrows()):
        row_num = pos + 2  # header is row 1, pandas position is 0-based

        reg_no = cell(row, 'REGISTRATION_NO')
        customer_name = cell(row, 'CUSTOMER_NAME')
        if not reg_no:
            errors.append({'row': row_num, 'reason': 'Missing REGISTRATION_NO'})
            skipped += 1
            continue
        if not customer_name:
            errors.append({'row': row_num, 'reason': 'Missing CUSTOMER_NAME'})
            skipped += 1
            continue

        row_error = None
        scheduled_date, err = cell_date(row, 'SCHEDULED_DATE')
        row_error = row_error or err
        created_at, err2 = cell_datetime(row, 'CREATED_AT')
        row_error = row_error or err2
        if row_error:
            errors.append({'row': row_num, 'reason': row_error})
            skipped += 1
            continue

        rates_raw = cell(row, 'RATES')
        if rates_raw:
            try:
                float(rates_raw)
            except ValueError:
                errors.append({'row': row_num, 'reason': f"RATES '{rates_raw}' is not numeric"})
                skipped += 1
                continue

        existing = RedoActivity.query.filter_by(registration_no=reg_no, device_change_reason=reason)
        if scheduled_date:
            existing = existing.filter(RedoActivity.scheduled_date == scheduled_date)
        existing = existing.first()
        if existing:
            errors.append({'row': row_num, 'reason': f"Duplicate - REDO {existing.redo_number or existing.id} already exists for this registration/reason"})
            skipped += 1
            continue

        activity_kwargs = dict(
            redo_number=RedoActivity.generate_redo_number(),
            activity_type='REDO',
            scheduled_date=scheduled_date,
            rates=rates_raw,
            customer_name=customer_name,
            customer_contact=cell(row, 'CUSTOMER_CONTACT'),
            sale_person=cell(row, 'SALE_PERSON'),
            registration_no=reg_no,
            make=cell(row, 'MAKE'),
            model=cell(row, 'MODEL'),
            year=cell(row, 'YEAR'),
            color=cell(row, 'COLOR'),
            chassis_no=cell(row, 'CHASSIS_NO'),
            engine_no=cell(row, 'ENGINE_NO'),
            device_type=cell(row, 'DEVICE_TYPE'),
            device_location=cell(row, 'DEVICE_LOCATION'),
            old_imei_no=cell(row, 'OLD_IMEI_NO'),
            old_sim_no=cell(row, 'OLD_SIM_NO'),
            new_device=cell(row, 'NEW_DEVICE'),
            new_sim=cell(row, 'NEW_SIM'),
            device_change_reason=reason,
            transfer_installation='No',
            city=cell(row, 'CITY'),
            vehicle_location=cell(row, 'LAST LOCATION'),
            technician=cell(row, 'TECHNICIAN_ASSIGNED'),
            tested_by=cell(row, 'TESTED_BY'),
            remarks=cell(row, 'REMARKS'),
            resolution_status=cell(row, 'RESOLUTION_STATUS') or 'Pending',
            status='PENDING',
            created_by=current_user.id,
        )
        if created_at:
            activity_kwargs['created_at'] = created_at

        activity = RedoActivity(**activity_kwargs)
        db.session.add(activity)
        db.session.flush()  # assign activity.id before charge creation, without committing yet

        service.create_charge_if_applicable(activity, current_user.id)
        imported += 1

    db.session.commit()
    logger.info(f"Installation Recovery Excel import ({reason}): {imported} imported, {skipped} skipped by {current_user.username}")

    return jsonify({'success': True, 'imported': imported, 'skipped': skipped, 'errors': errors,
                    'message': f"{imported} imported, {skipped} skipped"})


@payment_bp.route('/installation-recovery/<int:charge_id>/followup', methods=['POST'])
@login_required
@role_required(*DEVICE_RECOVERY_ROLES)
def installation_recovery_add_followup(charge_id):
    """Log a call/WhatsApp follow-up against a device recovery charge -
    officers may only log against their own assigned charges."""
    from datetime import datetime as dt
    from src.services.installation_recovery_service import InstallationRecoveryService
    from src.models.installation_recovery import InstallationRecoveryCharge

    charge = InstallationRecoveryCharge.query.get_or_404(charge_id)
    if _restricted_to_own_charges(current_user):
        if charge.assigned_officer_id != current_user.id:
            flash('You can only log follow-ups for your own assigned charges.', 'danger')
            return redirect(url_for('payment.installation_recovery_dashboard'))

    summary = request.form.get('summary', '').strip()
    if not summary:
        flash('A summary is required to log a follow-up.', 'danger')
        return redirect(url_for('payment.installation_recovery_dashboard'))

    follow_up_date_str = request.form.get('follow_up_date', '').strip()
    follow_up_date = None
    if follow_up_date_str:
        try:
            follow_up_date = dt.strptime(follow_up_date_str, '%Y-%m-%d').date()
        except ValueError:
            follow_up_date = None

    InstallationRecoveryService().add_followup(charge_id, {
        'conversation_type': request.form.get('conversation_type', 'PHONE_CALL'),
        'direction': request.form.get('direction', 'OUT'),
        'contact_person': request.form.get('contact_person', '').strip() or None,
        'contact_number': request.form.get('contact_number', '').strip() or None,
        'summary': summary,
        'action_taken': request.form.get('action_taken', '').strip() or None,
        'follow_up_date': follow_up_date,
    }, current_user)

    flash('Follow-up logged.', 'success')
    return redirect(url_for('payment.installation_recovery_dashboard'))


@payment_bp.route('/installation-recovery/followup-report')
@login_required
@role_required(*DEVICE_RECOVERY_ROLES)
def installation_recovery_followup_report():
    """Installation Recovery Follow-up Report: full call/WhatsApp history per
    device recovery charge - the same shape as the REDO Follow-up Report."""
    from src.services.installation_recovery_service import InstallationRecoveryService
    from src.models.installation_recovery import InstallationRecoveryCharge

    status_filter = request.args.get('status', '').strip()
    search = request.args.get('search', '').strip()

    service = InstallationRecoveryService()
    followups = service.get_followups_for_report(current_user, status=status_filter or None, search=search or None)

    charges = service.get_charges_for_view(current_user)
    status_summary = {
        InstallationRecoveryCharge.STATUS_PENDING: 0,
        InstallationRecoveryCharge.STATUS_CONTACTED: 0,
        InstallationRecoveryCharge.STATUS_RECOVERED: 0,
        InstallationRecoveryCharge.STATUS_LOST: 0,
    }
    for c in charges:
        if c.status in status_summary:
            status_summary[c.status] += 1

    return render_template('payment/installation_recovery_followup_report.html',
                         followups=followups,
                         status_summary=status_summary,
                         status_filter=status_filter,
                         search=search)


def _installation_recovery_followups_for_export():
    from src.services.installation_recovery_service import InstallationRecoveryService
    status_filter = request.args.get('status', '').strip()
    search = request.args.get('search', '').strip()
    return InstallationRecoveryService().get_followups_for_report(
        current_user, status=status_filter or None, search=search or None)


@payment_bp.route('/installation-recovery/followup-report/export/excel')
@login_required
@role_required(*DEVICE_RECOVERY_ROLES, 'executive')
def installation_recovery_followup_export_excel():
    import os
    from flask import send_file
    from src.services.mis_export_service import MISExportService

    followups = _installation_recovery_followups_for_export()
    filepath = MISExportService().generate_installation_recovery_followup_excel(followups)
    return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))


@payment_bp.route('/installation-recovery/followup-report/export/pdf')
@login_required
@role_required(*DEVICE_RECOVERY_ROLES, 'executive')
def installation_recovery_followup_export_pdf():
    import os
    from flask import send_file, abort
    from src.services.pdf_service import PDFService

    followups = _installation_recovery_followups_for_export()
    filepath = PDFService().generate_installation_recovery_followup_pdf(followups)
    if not filepath:
        abort(500)
    return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))


@payment_bp.route('/installation-recovery/<int:charge_id>/proof')
@login_required
@role_required(*DEVICE_RECOVERY_ROLES, 'executive')
def installation_recovery_proof(charge_id):
    """Serve a charge's proof-of-payment image - scoped to Payment
    Recovery officers/admin/manager, not a public static mount, since
    these are financial documents."""
    import os
    from flask import send_from_directory, abort
    from src.models.installation_recovery import InstallationRecoveryCharge
    from src.services.payment_proof_service import resolve_proof_path

    charge = InstallationRecoveryCharge.query.get_or_404(charge_id)
    if not charge.proof_of_payment_path:
        abort(404)
    full_path = resolve_proof_path(charge.proof_of_payment_path)
    return send_from_directory(os.path.dirname(full_path), os.path.basename(full_path))
