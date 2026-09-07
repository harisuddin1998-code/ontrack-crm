# src/web/removal.py
"""
Removal and Transfer Activity Routes - Complete with Wallboard
"""
from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime

from src.web import removal_bp
from src.services import RemovalService
from src.services.technician_service import TechnicianService
from src.forms.removal_forms import TransferForm, RetainedForm, FlagVehicleForm
from src.utils.decorators import role_required
from src.utils.logging import get_logger

logger = get_logger(__name__)


@removal_bp.route('/dashboard')
@login_required
@role_required('removal', 'admin', 'executive')
def dashboard():
    """Removal Wallboard - Shows all pending and active removals"""
    removal_service = RemovalService()
    
    # Get all flagged vehicles (pending and in progress)
    flagged_result = removal_service.get_flagged_vehicles(
        filters={'status': ['PENDING', 'IN_PROGRESS']},
        page=1, 
        per_page=50
    )
    flagged_vehicles = flagged_result['items']
    flagged_count = flagged_result['total']
    
    # Get all transfers and retained for overview
    stats = removal_service.get_dashboard_stats()
    
    # Get recent completed
    completed_flags = removal_service.get_flagged_vehicles(
        filters={'status': 'COMPLETED'},
        page=1,
        per_page=10
    )
    
    # Get returned count
    returned_count = removal_service.get_returned_count()
    
    return render_template('removal/dashboard.html',
                         flagged_vehicles=flagged_vehicles,
                         flagged_count=flagged_count,
                         stats=stats,
                         completed_flags=completed_flags['items'],
                         returned_count=returned_count)


@removal_bp.route('/flag', methods=['GET', 'POST'])
@login_required
@role_required('removal', 'admin')
def flag_vehicle():
    """Flag a vehicle for removal - Anyone can assign"""
    form = FlagVehicleForm()
    
    if form.validate_on_submit():
        removal_service = RemovalService()
        
        try:
            data = {
                'registration_no': form.registration_no.data.upper() if form.registration_no.data else '',
                'make': form.make.data.upper() if form.make.data else None,
                'model': form.model.data.upper() if form.model.data else None,
                'year': form.year.data,
                'color': form.color.data.upper() if form.color.data else None,
                'chassis_no': form.chassis_no.data.upper() if form.chassis_no.data else None,
                'engine_no': form.engine_no.data.upper() if form.engine_no.data else None,
                'customer_name': form.customer_name.data.upper() if form.customer_name.data else None,
                'customer_contact': form.customer_contact.data,
                'imei_no': form.imei_no.data,
                'sim_no': form.sim_no.data,
                'device_location': form.device_location.data.upper() if form.device_location.data else None,
                'flag_type': form.flag_type.data,
                'priority': form.priority.data,
                'flag_reason': form.flag_reason.data,
            }
            
            flag = removal_service.flag_vehicle(data, current_user.id)
            
            # Flash message with popup notification
            flash(f'🚨 Vehicle {flag.registration_no} flagged for {flag.flag_type}!', 'success')
            
            # Log the action
            logger.info(f"Vehicle {flag.registration_no} flagged by {current_user.username}")
            
            return redirect(url_for('removal.dashboard'))
        except ValueError as e:
            flash(str(e), 'danger')
        except Exception as e:
            flash(f'Error flagging vehicle: {str(e)}', 'danger')
            logger.error(f"Flag vehicle error: {e}")
    
    if form.errors:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{field}: {error}', 'danger')
    
    return render_template('removal/flag_vehicle.html', form=form)


@removal_bp.route('/flagged')
@login_required
@role_required('removal', 'admin')
def flagged_vehicles():
    """List all flagged vehicles"""
    removal_service = RemovalService()
    
    search = request.args.get('search', '')
    flag_type = request.args.get('flag_type', '')
    status = request.args.get('status', '')
    
    filters = {}
    if flag_type:
        filters['flag_type'] = flag_type
    if status:
        filters['status'] = status
    
    result = removal_service.get_flagged_vehicles(filters=filters, search=search)
    
    return render_template('removal/flagged_vehicles.html',
                         flags=result['items'],
                         total=result['total'],
                         search=search,
                         flag_type=flag_type,
                         status=status)


@removal_bp.route('/flag/<int:flag_id>')
@login_required
@role_required('removal', 'admin')
def flag_detail(flag_id):
    """View flag details"""
    removal_service = RemovalService()
    flag = removal_service.get_flag(flag_id)
    
    if not flag:
        flash('Flag not found', 'danger')
        return redirect(url_for('removal.flagged_vehicles'))
    
    technicians = TechnicianService.get_roster()
    return render_template('removal/flag_detail.html', flag=flag, technicians=technicians)


@removal_bp.route('/flag/<int:flag_id>/assign', methods=['POST'])
@login_required
@role_required('removal', 'admin')
def flag_assign(flag_id):
    """Assign a flagged vehicle to a technician"""
    removal_service = RemovalService()
    technician_id = request.form.get('technician_id')
    
    if not technician_id:
        flash('Please select a technician', 'danger')
        return redirect(url_for('removal.flag_detail', flag_id=flag_id))
    
    try:
        flag = removal_service.assign_flag(flag_id, int(technician_id))
        if flag:
            flash(f'Flag assigned to technician!', 'success')
            logger.info(f"Flag {flag_id} assigned to technician {technician_id}")
        else:
            flash('Flag not found', 'danger')
    except Exception as e:
        flash(f'Error assigning flag: {str(e)}', 'danger')
    
    return redirect(url_for('removal.dashboard'))


@removal_bp.route('/flag/<int:flag_id>/complete', methods=['POST'])
@login_required
@role_required('removal', 'admin')
def flag_complete(flag_id):
    """Complete a flagged vehicle"""
    removal_service = RemovalService()
    notes = request.form.get('completion_notes', '')
    
    try:
        flag = removal_service.complete_flag(flag_id, current_user.id, notes)
        if flag:
            flash(f'✅ Flag for {flag.registration_no} completed!', 'success')
            logger.info(f"Flag {flag_id} completed by {current_user.username}")
        else:
            flash('Flag not found', 'danger')
    except Exception as e:
        flash(f'Error completing flag: {str(e)}', 'danger')
    
    return redirect(url_for('removal.dashboard'))


@removal_bp.route('/flag/<int:flag_id>/process', methods=['GET', 'POST'])
@login_required
@role_required('removal', 'admin')
def process_flag(flag_id):
    """Process a flagged vehicle - combined assign/complete/cancel"""
    removal_service = RemovalService()
    flag = removal_service.get_flag(flag_id)
    
    if not flag:
        flash('Flag not found', 'danger')
        return redirect(url_for('removal.dashboard'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        technician_id = request.form.get('technician_id')
        notes = request.form.get('completion_notes', '')
        
        try:
            if action == 'IN_PROGRESS' and technician_id:
                removal_service.assign_flag(flag_id, int(technician_id))
                flash(f'Flag for {flag.registration_no} assigned and in progress!', 'success')
            elif action == 'COMPLETE':
                removal_service.complete_flag(flag_id, current_user.id, notes)
                flash(f'Flag for {flag.registration_no} completed!', 'success')
            elif action == 'CANCELLED':
                removal_service.update_flag_status(flag_id, 'CANCELLED')
                flash(f'Flag for {flag.registration_no} cancelled.', 'info')
            else:
                flash('Please select a valid action.', 'warning')
                return redirect(url_for('removal.process_flag', flag_id=flag_id))
        except Exception as e:
            flash(f'Error processing flag: {str(e)}', 'danger')
            logger.error(f"Flag process error: {e}")
        
        return redirect(url_for('removal.dashboard'))
    
    technicians = TechnicianService.get_roster()
    return render_template('removal/flag_process.html', flag=flag, technicians=technicians)


# ============================================
# TRANSFER ACTIVITIES
# ============================================

@removal_bp.route('/transfer')
@login_required
@role_required('removal', 'admin', 'executive')
def transfer_dashboard():
    """Transfer activity dashboard"""
    removal_service = RemovalService()
    
    status = request.args.get('status', '')
    search = request.args.get('search', '')
    
    filters = {}
    if status:
        filters['status'] = status
    
    if current_user.is_removal():
        filters['assigned_to'] = current_user.id
    
    result = removal_service.get_transfers(filters=filters, search=search)
    
    return render_template('removal/transfer_dashboard.html',
                         activities=result['items'],
                         total=result['total'],
                         status=status,
                         search=search)


@removal_bp.route('/transfer/new', methods=['GET', 'POST'])
@login_required
@role_required('removal', 'admin')
def transfer_new():
    """Create new transfer activity"""
    form = TransferForm()
    
    if form.validate_on_submit():
        removal_service = RemovalService()
        
        data = {
            'old_registration_no': form.old_registration_no.data.upper() if form.old_registration_no.data else '',
            'old_make': form.old_make.data.upper() if form.old_make.data else None,
            'old_model': form.old_model.data.upper() if form.old_model.data else None,
            'old_year': form.old_year.data,
            'old_color': form.old_color.data.upper() if form.old_color.data else None,
            'old_chassis_no': form.old_chassis_no.data.upper() if form.old_chassis_no.data else None,
            'old_engine_no': form.old_engine_no.data.upper() if form.old_engine_no.data else None,
            'old_customer_name': form.old_customer_name.data.upper() if form.old_customer_name.data else None,
            'old_customer_contact': form.old_customer_contact.data,
            'old_imei_no': form.old_imei_no.data,
            'old_sim_no': form.old_sim_no.data,
            'old_device_location': form.old_device_location.data.upper() if form.old_device_location.data else None,
            'new_registration_no': form.new_registration_no.data.upper() if form.new_registration_no.data else '',
            'new_make': form.new_make.data.upper() if form.new_make.data else None,
            'new_model': form.new_model.data.upper() if form.new_model.data else None,
            'new_year': form.new_year.data,
            'new_color': form.new_color.data.upper() if form.new_color.data else None,
            'new_chassis_no': form.new_chassis_no.data.upper() if form.new_chassis_no.data else None,
            'new_engine_no': form.new_engine_no.data.upper() if form.new_engine_no.data else None,
            'new_customer_name': form.new_customer_name.data.upper() if form.new_customer_name.data else None,
            'new_customer_contact': form.new_customer_contact.data,
            'transfer_reason': form.transfer_reason.data,
            'device_transferred_date': form.device_transferred_date.data,
        }
        
        try:
            transfer = removal_service.create_transfer(data, current_user.id)
            flash(f'Transfer created for {transfer.old_registration_no} -> {transfer.new_registration_no}', 'success')
            return redirect(url_for('removal.transfer_dashboard'))
        except Exception as e:
            flash(f'Error creating transfer: {str(e)}', 'danger')
            logger.error(f"Transfer creation error: {e}")
    
    if form.errors:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{field}: {error}', 'danger')
    
    return render_template('removal/transfer_new.html', form=form)


@removal_bp.route('/transfer/<int:transfer_id>', methods=['GET', 'POST'])
@login_required
@role_required('removal', 'admin')
def transfer_update(transfer_id):
    """Update transfer activity"""
    removal_service = RemovalService()
    transfer = removal_service.get_transfer(transfer_id)
    
    if not transfer:
        flash('Transfer not found', 'danger')
        return redirect(url_for('removal.transfer_dashboard'))
    
    if current_user.is_removal() and transfer.assigned_to != current_user.id:
        flash('You are not assigned to this transfer', 'danger')
        return redirect(url_for('removal.transfer_dashboard'))
    
    if request.method == 'POST':
        status = request.form.get('status')
        notes = request.form.get('completion_notes', '')

        if not status:
            flash('Status is required', 'danger')
            return redirect(url_for('removal.transfer_dashboard'))

        try:
            if status == 'COMPLETED':
                transfer = removal_service.complete_transfer(transfer_id, current_user.id, notes)
                flash('Transfer completed!', 'success')
            else:
                transfer = removal_service.update_transfer_status(transfer_id, status)
                flash(f'Transfer status updated to {status}', 'success')
            return redirect(url_for('removal.transfer_dashboard'))
        except Exception as e:
            flash(f'Error updating transfer: {str(e)}', 'danger')
    
    technicians = TechnicianService.get_roster()
    return render_template('removal/transfer_update.html',
                         transfer=transfer,
                         technicians=technicians)


@removal_bp.route('/transfer/<int:transfer_id>/assign', methods=['POST'])
@login_required
@role_required('admin')
def transfer_assign(transfer_id):
    """Assign transfer to technician"""
    removal_service = RemovalService()
    technician_id = request.form.get('technician_id')

    if not technician_id:
        flash('No technician selected', 'warning')
        return redirect(url_for('removal.transfer_dashboard'))

    try:
        transfer = removal_service.assign_transfer(transfer_id, int(technician_id), current_user.id)
        assigned_name = transfer.technician.name if (transfer and transfer.technician) else 'Technician'
        flash(f'Transfer assigned to {assigned_name}', 'success')
    except Exception as e:
        flash(f'Error assigning transfer: {str(e)}', 'danger')
    
    return redirect(url_for('removal.transfer_dashboard'))


# ============================================
# RETAINED ACTIVITIES
# ============================================

@removal_bp.route('/retained')
@login_required
@role_required('removal', 'admin', 'executive')
def retained_dashboard():
    """Retained activity dashboard"""
    removal_service = RemovalService()
    
    status = request.args.get('status', '')
    search = request.args.get('search', '')
    
    filters = {}
    if status:
        filters['status'] = status
    
    if current_user.is_removal():
        filters['assigned_to'] = current_user.id
    
    result = removal_service.get_retained(filters=filters, search=search)
    
    return render_template('removal/retained_dashboard.html',
                         activities=result['items'],
                         total=result['total'],
                         status=status,
                         search=search)


@removal_bp.route('/retained/new', methods=['GET', 'POST'])
@login_required
@role_required('removal', 'admin')
def retained_new():
    """Create new retained activity"""
    form = RetainedForm()
    
    if form.validate_on_submit():
        removal_service = RemovalService()
        
        try:
            data = {
                'registration_no': form.registration_no.data.upper() if form.registration_no.data else '',
                'make': form.make.data.upper() if form.make.data else None,
                'model': form.model.data.upper() if form.model.data else None,
                'year': form.year.data,
                'color': form.color.data.upper() if form.color.data else None,
                'chassis_no': form.chassis_no.data.upper() if form.chassis_no.data else None,
                'engine_no': form.engine_no.data.upper() if form.engine_no.data else None,
                'customer_name': form.customer_name.data.upper() if form.customer_name.data else None,
                'customer_contact': form.customer_contact.data,
                'imei_no': form.imei_no.data,
                'sim_no': form.sim_no.data,
                'device_location': form.device_location.data.upper() if form.device_location.data else None,
                'removal_reason': form.removal_reason.data,
                'removal_date': form.removal_date.data,
                'removal_type': form.removal_type.data,
                'device_returned': form.device_returned.data,
                'return_date': form.return_date.data,
                'device_condition': form.device_condition.data,
                'retained_by': form.retained_by.data,
                'storage_location': form.storage_location.data.upper() if form.storage_location.data else None,
            }
            
            retained = removal_service.create_retained(data, current_user.id)
            flash(f'Retained activity created for {retained.registration_no}', 'success')
            return redirect(url_for('removal.retained_dashboard'))
        except Exception as e:
            flash(f'Error creating retained activity: {str(e)}', 'danger')
            logger.error(f"Retained creation error: {e}")
    
    if form.errors:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{field}: {error}', 'danger')
    
    return render_template('removal/retained_new.html', form=form)


@removal_bp.route('/retained/<int:retained_id>', methods=['GET', 'POST'])
@login_required
@role_required('removal', 'admin')
def retained_update(retained_id):
    """Update retained activity"""
    removal_service = RemovalService()
    retained = removal_service.get_retained_by_id(retained_id)
    
    if not retained:
        flash('Retained activity not found', 'danger')
        return redirect(url_for('removal.retained_dashboard'))
    
    if current_user.is_removal() and retained.assigned_to != current_user.id:
        flash('You are not assigned to this activity', 'danger')
        return redirect(url_for('removal.retained_dashboard'))
    
    if request.method == 'POST':
        status = request.form.get('status')
        notes = request.form.get('completion_notes', '')

        if not status:
            flash('Status is required', 'danger')
            return redirect(url_for('removal.retained_dashboard'))

        try:
            if status == 'COMPLETED':
                retained = removal_service.complete_retained(retained_id, current_user.id, notes)
                flash('Retained activity completed!', 'success')
            else:
                retained = removal_service.update_retained_status(retained_id, status)
                flash(f'Status updated to {status}', 'success')
            return redirect(url_for('removal.retained_dashboard'))
        except Exception as e:
            flash(f'Error updating retained activity: {str(e)}', 'danger')
    
    technicians = TechnicianService.get_roster()
    return render_template('removal/retained_update.html',
                         retained=retained,
                         technicians=technicians)


@removal_bp.route('/retained/<int:retained_id>/assign', methods=['POST'])
@login_required
@role_required('admin')
def retained_assign(retained_id):
    """Assign retained activity to technician"""
    removal_service = RemovalService()
    technician_id = request.form.get('technician_id')

    if not technician_id:
        flash('No technician selected', 'warning')
        return redirect(url_for('removal.retained_dashboard'))

    try:
        retained = removal_service.assign_retained(retained_id, int(technician_id), current_user.id)
        assigned_name = retained.technician.name if (retained and retained.technician) else 'Technician'
        flash(f'Activity assigned to {assigned_name}', 'success')
    except Exception as e:
        flash(f'Error assigning retained activity: {str(e)}', 'danger')
    
    return redirect(url_for('removal.retained_dashboard'))