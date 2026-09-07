# src/utils/decorators.py
"""
Custom Decorators for the application
"""
from functools import wraps
from flask import flash, redirect, url_for, request, jsonify
from flask_login import current_user
from src.utils.logging import get_logger

logger = get_logger(__name__)


def login_required(role=None):
    """
    Decorator to require login and optionally a specific role
    
    Usage:
        @login_required
        def view(): ...
        
        @login_required('admin')
        def admin_view(): ...
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Please login to access this page', 'warning')
                return redirect(url_for('auth.login', next=request.url))
            
            if role and current_user.role != role:
                if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'error': 'Permission denied'}), 403
                flash('You do not have permission to access this page', 'danger')
                return redirect(url_for('auth.unauthorized'))
            
            return f(*args, **kwargs)
        return wrapped
    return decorator


def anonymous_required(f):
    """
    Decorator to require that user is NOT logged in
    Redirects to dashboard if already authenticated
    
    Usage:
        @anonymous_required
        def login_page(): ...
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        if current_user.is_authenticated:
            flash('You are already logged in', 'info')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return wrapped


def role_required(*roles):
    """
    Decorator to require one of multiple roles
    
    Usage:
        @role_required('admin', 'sales')
        def view(): ...
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Please login to access this page', 'warning')
                return redirect(url_for('auth.login', next=request.url))
            
            if not current_user.has_any_role(roles):
                if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'error': 'Permission denied'}), 403
                flash('You do not have permission to access this page', 'danger')
                return redirect(url_for('auth.unauthorized'))

            return f(*args, **kwargs)
        return wrapped
    return decorator


def admin_required(f):
    """
    Decorator to require admin role
    
    Usage:
        @admin_required
        def admin_view(): ...
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('auth.login', next=request.url))
        
        if not current_user.is_admin():
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Admin access required'}), 403
            flash('Admin access required', 'danger')
            return redirect(url_for('auth.unauthorized'))
        
        return f(*args, **kwargs)
    return wrapped


def sales_required(f):
    """
    Decorator to require sales role or admin
    
    Usage:
        @sales_required
        def sales_view(): ...
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('auth.login', next=request.url))
        
        if not (current_user.is_admin() or current_user.is_sales()):
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Sales access required'}), 403
            flash('Sales access required', 'danger')
            return redirect(url_for('auth.unauthorized'))
        
        return f(*args, **kwargs)
    return wrapped


def installation_required(f):
    """
    Decorator to require installation role or admin
    
    Usage:
        @installation_required
        def installation_view(): ...
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('auth.login', next=request.url))
        
        if not (current_user.is_admin() or current_user.is_installation()):
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Installation access required'}), 403
            flash('Installation access required', 'danger')
            return redirect(url_for('auth.unauthorized'))
        
        return f(*args, **kwargs)
    return wrapped


def security_required(f):
    """
    Decorator to require security role or admin
    
    Usage:
        @security_required
        def security_view(): ...
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('auth.login', next=request.url))
        
        if not (current_user.is_admin() or current_user.is_security()):
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Security access required'}), 403
            flash('Security access required', 'danger')
            return redirect(url_for('auth.unauthorized'))
        
        return f(*args, **kwargs)
    return wrapped


def payment_required(f):
    """
    Decorator to require payment recovery role or admin
    
    Usage:
        @payment_required
        def payment_view(): ...
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('auth.login', next=request.url))
        
        if not (current_user.is_admin() or current_user.is_payment_recovery()):
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Payment access required'}), 403
            flash('Payment access required', 'danger')
            return redirect(url_for('auth.unauthorized'))
        
        return f(*args, **kwargs)
    return wrapped


def redo_required(f):
    """
    Decorator to require redo technician role or admin
    
    Usage:
        @redo_required
        def redo_view(): ...
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('auth.login', next=request.url))
        
        if not (current_user.is_admin() or current_user.is_redo_technician()):
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'REDO access required'}), 403
            flash('REDO access required', 'danger')
            return redirect(url_for('auth.unauthorized'))
        
        return f(*args, **kwargs)
    return wrapped


def removal_required(f):
    """
    Decorator to require removal role or admin
    
    Usage:
        @removal_required
        def removal_view(): ...
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('auth.login', next=request.url))
        
        if not (current_user.is_admin() or current_user.is_removal()):
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Removal access required'}), 403
            flash('Removal access required', 'danger')
            return redirect(url_for('auth.unauthorized'))
        
        return f(*args, **kwargs)
    return wrapped


def api_login_required(f):
    """
    Decorator for API endpoints requiring login
    Returns JSON error instead of redirect
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return wrapped


def api_role_required(*roles):
    """
    Decorator for API endpoints requiring specific role
    Returns JSON error instead of redirect
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401
            
            if current_user.role not in roles:
                return jsonify({'error': 'Permission denied'}), 403
            
            return f(*args, **kwargs)
        return wrapped
    return decorator


def log_activity(action):
    """
    Decorator to log user activity
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            result = f(*args, **kwargs)
            
            if current_user.is_authenticated:
                from src.models.activity import ActivityLog
                logger.info(f"User {current_user.username} performed: {action}")
            
            return result
        return wrapped
    return decorator


def rate_limit(limit):
    """
    Decorator for custom rate limiting
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            # Basic rate limiting - can be extended with Redis
            # For now, just log and pass through
            logger.debug(f"Rate limit check: {limit}")
            return f(*args, **kwargs)
        return wrapped
    return decorator


def sales_only(f):
    """
    Decorator to allow only sales users or admin to access a view
    
    Usage:
        @sales_only
        def sales_dashboard(): ...
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('auth.login', next=request.url))
        
        if not (current_user.is_admin() or current_user.is_sales()):
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Sales access required'}), 403
            flash('Sales access required', 'danger')
            return redirect(url_for('auth.unauthorized'))
        
        return f(*args, **kwargs)
    return wrapped


def view_own_po_only(f):
    """
    Decorator to ensure sales users can only view their own POs
    Admin can view all POs
    
    Usage:
        @view_own_po_only
        def po_detail(po_id): ...
    """
    @wraps(f)
    def wrapped(po_id, *args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('auth.login', next=request.url))
        
        # Admin and Executive can view all POs
        if current_user.is_admin() or current_user.is_executive():
            return f(po_id, *args, **kwargs)
        
        # Sales can only view their own POs
        if current_user.is_sales():
            from src.services import POService
            po_service = POService()
            po = po_service.get_po(po_id)
            
            if not po:
                flash('PO not found', 'danger')
                return redirect(url_for('sales.dashboard'))
            
            if po.sales_person_id != current_user.id:
                flash('You do not have permission to view this PO', 'danger')
                return redirect(url_for('sales.dashboard'))
            
            return f(po_id, *args, **kwargs)
        
        flash('Access denied', 'danger')
        return redirect(url_for('auth.unauthorized'))
    return wrapped


def can_update_po(f):
    """
    Decorator to ensure only installers and admin can update POs
    
    Usage:
        @can_update_po
        def update_po(po_id): ...
    """
    @wraps(f)
    def wrapped(po_id, *args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('auth.login', next=request.url))
        
        # Admin and Installers can update POs
        if current_user.is_admin() or current_user.is_installation():
            return f(po_id, *args, **kwargs)
        
        flash('Only installers and admin can update POs', 'danger')
        return redirect(url_for('auth.unauthorized'))
    return wrapped