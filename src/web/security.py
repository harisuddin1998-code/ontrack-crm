# src/web/security.py
"""
Security Briefing Routes
"""
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from src.web import security_bp
from src.services import SecurityBriefingService, POService
from src.forms.security_forms import SecurityBriefingForm
from src.utils.decorators import role_required
from src.utils.logging import get_logger

logger = get_logger(__name__)


@security_bp.route('/dashboard')
@login_required
@role_required('security', 'admin', 'executive')
def dashboard():
    """Security briefing wallboard.

    Briefings arrive here on their own: completing an installation sends the
    completion email and creates the briefing in the same step, so there is
    nothing to sync by hand. The "New from Installations" tab is that
    inbox - briefings raised by an installation and not yet dealt with.
    """
    from src.models.security import SecurityBriefingData

    briefing_service = SecurityBriefingService()
    stats = briefing_service.get_dashboard_stats()

    # Kanban cards drive this: each one is a tab, and clicking it shows only
    # that category. `tab` and the card the user clicked are the same thing.
    tab = (request.args.get('tab') or 'new').lower()

    query = SecurityBriefingData.query
    if tab == 'pending':
        query = query.filter(SecurityBriefingData.status == 'PENDING')
    elif tab == 'completed':
        query = query.filter(SecurityBriefingData.status == 'COMPLETED')
    elif tab == 'new':
        query = query.filter(SecurityBriefingData.synced_from_po.is_(True),
                             SecurityBriefingData.status == 'PENDING')
    # 'all' falls through unfiltered.

    briefings = query.order_by(SecurityBriefingData.created_at.desc()).limit(100).all()

    stats['new_from_installations'] = SecurityBriefingData.query.filter(
        SecurityBriefingData.synced_from_po.is_(True),
        SecurityBriefingData.status == 'PENDING').count()

    return render_template('security/dashboard.html',
                         stats=stats,
                         briefings=briefings,
                         tab=tab)


@security_bp.route('/briefings')
@login_required
@role_required('security', 'admin', 'executive')
def briefings():
    """List security briefings"""
    briefing_service = SecurityBriefingService()
    
    status = request.args.get('status', '')
    search = request.args.get('search', '')
    
    filters = {}
    if status:
        filters['status'] = status
    
    result = briefing_service.get_briefings(filters=filters, search=search)
    
    return render_template('security/briefings.html',
                         briefings=result['items'],
                         total=result['total'],
                         status=status,
                         search=search)


@security_bp.route('/briefing/<int:briefing_id>', methods=['GET', 'POST'])
@login_required
@role_required('security', 'admin')
def briefing_edit(briefing_id):
    """View/Edit security briefing"""
    briefing_service = SecurityBriefingService()
    briefing = briefing_service.get_by_id(briefing_id)
    
    if not briefing:
        flash('Briefing not found', 'danger')
        return redirect(url_for('security.briefings'))
    
    form = SecurityBriefingForm(obj=briefing)
    
    if form.validate_on_submit():
        data = {
            # Customer details (stored on briefing)
            'segment': form.segment.data.upper() if form.segment.data else None,
            'cnic': form.cnic.data,
            'address': form.address.data.upper() if form.address.data else None,
            'father_name': form.father_name.data.upper() if form.father_name.data else None,
            'mother_name': form.mother_name.data.upper() if form.mother_name.data else None,
            'secondary_user_name': form.secondary_user_name.data.upper() if form.secondary_user_name.data else None,
            'secondary_user_phone': form.secondary_user_phone.data,
            'emergency_user_name': form.emergency_user_name.data.upper() if form.emergency_user_name.data else None,
            'emergency_user_phone': form.emergency_user_phone.data,
            # Security credentials and checklist
            'password_1': form.password_1.data,
            'password_2': form.password_2.data,
            'fence': form.fence.data,
            'security_training_completed': form.security_training_completed.data,
            'customer_demonstration': form.customer_demonstration.data,
            'services_explained': form.services_explained.data,
            'customer_signature': form.customer_signature.data.upper() if form.customer_signature.data else None,
            'acknowledgement': form.acknowledgement.data,
            'officer_notes': form.officer_notes.data,
        }
        
        # Handle completion
        if form.status.data == 'COMPLETED' and briefing.status != 'COMPLETED':
            try:
                # Update non-completed fields first before completing
                briefing_service.update(briefing_id, **data)
                briefing_service.complete_briefing(briefing_id, current_user.name or current_user.username)
                flash('Security briefing completed!', 'success')
            except Exception as e:
                flash(str(e), 'danger')
                return render_template('security/briefing_form.html', form=form, briefing=briefing)
        else:
            data['status'] = form.status.data
            briefing_service.update(briefing_id, **data)
            flash('Security briefing updated!', 'success')
        
        return redirect(url_for('security.briefings'))
    
    return render_template('security/briefing_form.html', form=form, briefing=briefing)


# Pending Sync is gone.
#
# It existed because briefings had to be pulled across from completed POs by
# hand. Completing an installation now raises the briefing in the same step
# that sends the completion email (POService._create_security_briefing), so
# there is nothing left to sync - a screen listing "POs awaiting sync" would
# only ever be empty, or worse, look like work that still needed doing.