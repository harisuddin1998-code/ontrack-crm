# src/web/auth.py
"""
Authentication Routes - Login, Logout, Password Reset
"""
from flask import render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import login_user, logout_user, login_required, current_user

from src.web import auth_bp
from src.services.auth_service import ACTION_LOGOUT, AuthService
from src.forms.auth_forms import LoginForm, PasswordChangeForm, PasswordResetForm, PasswordResetRequestForm
from src.utils.decorators import anonymous_required
from src.utils.logging import get_logger

logger = get_logger(__name__)
auth_service = AuthService()


@auth_bp.route('/login', methods=['GET', 'POST'])
@anonymous_required
def login():
    """User login"""
    form = LoginForm()
    
    if form.validate_on_submit():
        username = form.username.data or ''
        password = form.password.data or ''

        logger.info(f"Login attempt for user: {username}")

        user = auth_service.authenticate(
            username=username,
            password=password,
            ip_address=request.remote_addr
        )
        
        if user:
            logger.info(f"User {username} authenticated successfully")
            login_user(user, remember=form.remember_me.data)
            session['user_id'] = user.id
            session['role'] = user.role

            # Greet them by name on the page they land on. A late arrival is
            # told so, and somebody late several days running is told that
            # instead - see AuthService.record_attendance, which has already
            # noted today's arrival by this point.
            greeting = auth_service.greeting(user)
            flash(greeting, 'warning' if 'late' in greeting or 'habitual' in greeting else 'info')

            # Redirect based on role
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            
            # Redirect to index which handles role-based redirect
            return redirect(url_for('index'))
        else:
            logger.warning(f"Failed login for user: {username}")
            flash('Invalid username or password', 'danger')
    
    return render_template('auth/login.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout():
    """User logout"""
    # Recorded before the session is torn down - afterwards `current_user` is
    # anonymous and there is nobody left to record it against.
    auth_service.record_session_event(current_user, ACTION_LOGOUT)

    logout_user()
    session.clear()
    flash('You have been logged out successfully', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Change user password"""
    form = PasswordChangeForm()
    
    if form.validate_on_submit():
        success, message = auth_service.change_password(
            user_id=current_user.id,
            old_password=form.current_password.data or '',
            new_password=form.new_password.data or ''
        )
        
        if success:
            flash(message, 'success')
            return redirect(url_for('auth.logout'))
        else:
            flash(message, 'danger')
    
    return render_template('auth/change_password.html', form=form)


@auth_bp.route('/reset-password-request', methods=['GET', 'POST'])
@anonymous_required
def reset_password_request():
    """Request password reset"""
    form = PasswordResetRequestForm()
    
    if form.validate_on_submit():
        success, message = auth_service.reset_password(form.email.data or '')
        flash(message, 'success' if success else 'danger')
        if success:
            return redirect(url_for('auth.login'))
    
    return render_template('auth/reset_password_request.html', form=form)


@auth_bp.route('/reset-password', methods=['GET', 'POST'])
@anonymous_required
def reset_password():
    """Reset password with token"""
    token = request.args.get('token')
    if not token:
        flash('Invalid or missing reset token', 'danger')
        return redirect(url_for('auth.login'))
    
    # Verify token
    user_id = auth_service.verify_reset_token(token)
    if not user_id:
        flash('Invalid or expired reset token', 'danger')
        return redirect(url_for('auth.login'))
    
    form = PasswordResetForm()
    
    if form.validate_on_submit():
        from src.models.user import User
        from src.extensions import db
        
        user = User.query.get(user_id)
        if user:
            user.set_password(form.new_password.data)
            db.session.commit()
            flash('Password reset successfully! Please login.', 'success')
            return redirect(url_for('auth.login'))
        else:
            flash('User not found', 'danger')
    
    return render_template('auth/reset_password.html', form=form, token=token)


@auth_bp.route('/unauthorized')
def unauthorized():
    """Unauthorized access page"""
    return render_template('auth/unauthorized.html'), 403


@auth_bp.route('/dashboard-redirect')
def dashboard_redirect():
    """Redirect to appropriate dashboard based on role.

    Delegates to ROLE_LANDING_PAGES rather than keeping its own role list. This
    used to be a second, shorter if/elif chain that fell through to the login
    page for any role it did not name - and sending an authenticated user to
    the login page is what produced the infinite redirect loop. It was already
    missing four roles when this was written.
    """
    from src.app import ROLE_LANDING_PAGES

    if not current_user.is_authenticated:
        return redirect(url_for('auth.login'))

    for role, endpoint in ROLE_LANDING_PAGES.items():
        if current_user.has_role(role):
            return redirect(url_for(endpoint))

    return redirect(url_for('auth.unauthorized'))