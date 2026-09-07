# src/app.py
"""
Application Factory Pattern
Creates and configures the Flask application
"""
import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from flask import Flask, jsonify, redirect, url_for, request, render_template, flash
from werkzeug.exceptions import HTTPException

from src.config import get_config
from src.extensions import init_extensions, db, socketio, cache, limiter, metrics, login_manager
from src.models.user import User
from src.utils.logging import setup_logging
from src.scheduler import start_scheduler


from typing import Optional, Dict, Any, List

def create_app(config_name: Optional[str] = None, config_object: Optional[object] = None):
    """
    Application factory
    
    Args:
        config_name: Name of configuration to use ('development', 'testing', 'production', 'docker')
        config_object: Configuration object to use directly (overrides config_name)
    
    Returns:
        Flask application instance
    """
    
    # Create Flask app
    app = Flask(
        __name__,
        instance_path=str(Path(__file__).parent.parent / "instance"),
        instance_relative_config=True,
        template_folder="templates",
        static_folder="static"
    )
    
    # Load configuration
    if config_object:
        app.config.from_object(config_object)
    else:
        config = get_config(config_name or os.environ.get('FLASK_ENV', 'development'))
        app.config.from_object(config)
    
    # Ensure required directories exist
    _ensure_directories(app)
    
    # Setup logging
    setup_logging(app)
    
    # Initialize extensions
    init_extensions(app)
    
    # Flask-Login user loader
    @login_manager.user_loader
    def load_user(user_id):
        """Load user for Flask-Login"""
        try:
            return db.session.get(User, int(user_id))
        except (ValueError, TypeError):
            return None
    
    # Register blueprints (routes)
    _register_blueprints(app)
    
    # Register error handlers
    _register_error_handlers(app)
    
    # Register context processors
    _register_context_processors(app)

    # Accounting number formatting available to every template
    from src.utils.formatting import register_formatting_filters
    register_formatting_filters(app)

    # Static assets carry a version stamp so a changed stylesheet or logo
    # reaches users immediately. Without it the browser keeps serving the
    # cached copy against freshly-changed markup, which looks like a broken
    # layout rather than a stale file.
    _register_static_versioning(app)
    
    # Register CLI commands
    _register_commands(app)
    
    # Register before/after request hooks
    _register_request_hooks(app)
    
    # ✅ Start background scheduler (self-contained, no external services needed)
    #
    # Off is a supported way to run: exactly one process may own the schedule,
    # or the month-end management email goes out once per worker. See
    # SCHEDULER_ENABLED in src/config.py for how that is arranged.
    if app.config.get('SCHEDULER_ENABLED', True):
        start_scheduler(app)
        app.logger.info("✅ Application initialized with background scheduler")
    else:
        app.logger.info("Application initialized; background scheduler disabled "
                        "(SCHEDULER_ENABLED=false)")
    app.logger.info(f"Application created with config: {app.config.get('ENV', 'unknown')}")
    
    return app


def _ensure_directories(app):
    """Ensure all required directories exist"""
    directories = [
        app.config.get('UPLOAD_FOLDER', 'uploads'),
        app.config.get('LOG_PATH', 'logs'),
        app.instance_path,
        Path(app.instance_path) / "uploads",
        Path(app.instance_path) / "uploads" / "excel",
        Path(app.instance_path) / "uploads" / "pdf",
    ]
    
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)


# Home page for each role, checked in order so that a user holding several
# roles lands on the most privileged one. Every role in User.ROLES must have an
# entry - `_verify_role_landing_pages` fails startup if one is missing, because
# a role with no home page previously fell through into an infinite redirect
# loop between '/' and '/auth/login'.
#
# The endpoint chosen must be one the role can actually open (check the
# @role_required decorator on that view), otherwise the user lands on a
# permission error instead of a dashboard.
ROLE_LANDING_PAGES = {
    'admin':             'admin.dashboard',
    'manager':           'annual_recovery.dashboard',
    'sales':             'sales.dashboard',
    'installation':      'installation.dashboard',
    'security':          'security.dashboard',
    'payment_recovery':  'payment.dashboard',
    'recovery_officer':  'annual_recovery.dashboard',
    'redo_technician':   'redo.dashboard',
    'removal':           'removal.dashboard',
    'complaint_manager': 'complaint.dashboard',
    'inventory':         'inventory.dashboard',
    'device_recovery':   'payment.installation_recovery_dashboard',
    'suggestion_manager': 'suggestions.wallboard',
    'executive':         'admin.executive_dashboard',
}


def _verify_role_landing_pages(app):
    """Fail fast if any role has no home page, or names one that doesn't exist.

    This turns "a whole role silently cannot log in" into an error at startup,
    which is how the '/' redirect loop went unnoticed until users hit it.
    """
    from src.models.user import User

    missing = [role for role in User.ROLES if role not in ROLE_LANDING_PAGES]
    unknown = [role for role in ROLE_LANDING_PAGES if role not in User.ROLES]
    bad_endpoints = [
        f'{role} -> {endpoint}'
        for role, endpoint in ROLE_LANDING_PAGES.items()
        if endpoint not in app.view_functions
    ]

    problems = []
    if missing:
        problems.append(
            f"roles with no landing page (users with these roles cannot sign in): {missing}"
        )
    if bad_endpoints:
        problems.append(f"landing pages pointing at endpoints that do not exist: {bad_endpoints}")
    if problems:
        raise RuntimeError(
            'ROLE_LANDING_PAGES is incomplete - ' + '; '.join(problems)
            + '. Add the role to ROLE_LANDING_PAGES in src/app.py.'
        )

    if unknown:
        # Not fatal: a stale entry is harmless, but it signals drift.
        app.logger.warning(f"ROLE_LANDING_PAGES lists roles not in User.ROLES: {unknown}")


def _register_blueprints(app):
    """Register all blueprints"""
    from src.web import auth_bp, admin_bp, sales_bp, installation_bp
    from src.web import security_bp, payment_bp, redo_bp, removal_bp, annual_recovery_bp, complaint_bp, inventory_bp, live_amc_bp
    from src.web import notifications_bp, suggestions_bp
    from src.api.v1 import api_v1_bp
    
    # Web blueprints
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(sales_bp, url_prefix='/sales')
    app.register_blueprint(installation_bp, url_prefix='/installation')
    app.register_blueprint(security_bp, url_prefix='/security')
    app.register_blueprint(payment_bp, url_prefix='/payment')
    app.register_blueprint(redo_bp, url_prefix='/redo')
    app.register_blueprint(removal_bp, url_prefix='/removal')
    app.register_blueprint(annual_recovery_bp, url_prefix='/annual-recovery')
    app.register_blueprint(complaint_bp, url_prefix='/complaints')
    app.register_blueprint(inventory_bp, url_prefix='/inventory')
    app.register_blueprint(live_amc_bp, url_prefix='/live-amc')
    app.register_blueprint(notifications_bp, url_prefix='/notifications')
    app.register_blueprint(suggestions_bp, url_prefix='/suggestions')

    # API blueprint
    app.register_blueprint(api_v1_bp, url_prefix='/api/v1')
    
    # Root route - send each signed-in user to their role's home page.
    #
    # This route caused an infinite redirect loop once: a role with no entry
    # here fell through to /auth/login, which bounces an already-authenticated
    # user straight back to '/' (see @anonymous_required). Two rules keep that
    # from returning, and `_verify_role_landing_pages` below enforces the first
    # at startup:
    #   1. Every role in User.ROLES must appear in ROLE_LANDING_PAGES.
    #   2. An authenticated user is NEVER redirected to the login route.
    @app.route('/')
    def index():
        from flask_login import current_user

        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))

        for role, endpoint in ROLE_LANDING_PAGES.items():
            if current_user.has_role(role):
                return redirect(url_for(endpoint))

        # Rule 2: unreachable while rule 1 holds, but must never bounce back to
        # the login route - that is precisely what created the loop before.
        app.logger.error(
            f"No landing page mapped for role '{current_user.role}' "
            f"(user '{current_user.username}'). Add it to ROLE_LANDING_PAGES."
        )
        flash('No dashboard is assigned to your role. Please contact an administrator.', 'warning')
        return redirect(url_for('auth.unauthorized'))

    @app.route('/login')
    def login_redirect():
        return redirect(url_for('auth.login'))

    @app.route('/logout')
    def logout_redirect():
        return redirect(url_for('auth.logout'))

    @app.route('/dashboard')
    def dashboard_redirect():
        return redirect(url_for('index'))

    @app.route('/redo')
    def redo_redirect():
        return redirect(url_for('redo.dashboard'))

    @app.route('/followups')
    def followups_redirect():
        return redirect(url_for('redo.followups'))

    @app.route('/non-reporting')
    def non_reporting_redirect():
        return redirect(url_for('redo.non_reporting_dashboard'))

    _verify_role_landing_pages(app)

    app.logger.info("Blueprints registered")


def _register_error_handlers(app):
    """Register error handlers"""
    
    def is_api_request():
        return (
            request.path.startswith('/api/') or 
            request.path.startswith('/admin/api/') or
            request.is_json or 
            request.headers.get('Accept') == 'application/json'
        )
    
    from flask_wtf.csrf import CSRFError

    @app.errorhandler(CSRFError)
    def csrf_error(e):
        """A stale or missing CSRF token, in plain language.

        Registered ahead of the 400 handler because "The CSRF token has
        expired" is a message about the security library, not about anything
        the person did - it tells them neither what went wrong nor what to
        do next.
        """
        app.logger.warning(f'CSRF rejection on {request.path}: {e.description}')
        if is_api_request():
            return jsonify({
                'error': 'CSRF',
                'message': 'Your session expired. Reload the page and try again.'
            }), 400
        flash('This page had been open too long and your session moved on, '
              'so the change was not saved. Please try again.', 'warning')
        return redirect(request.referrer or url_for('admin.dashboard'))

    @app.errorhandler(400)
    def bad_request(e):
        if is_api_request():
            return jsonify({
                'error': 'Bad Request',
                'message': str(e) if app.debug else 'Invalid request'
            }), 400
        flash(f'⚠️ Bad Request: {getattr(e, "description", str(e))}', 'danger')
        return redirect(request.referrer or url_for('admin.dashboard'))
    
    @app.errorhandler(401)
    def unauthorized(e):
        if is_api_request():
            return jsonify({
                'error': 'Unauthorized',
                'message': 'Authentication required'
            }), 401
        flash('Please log in to access this page.', 'warning')
        return redirect(url_for('auth.login'))
    
    @app.errorhandler(403)
    def forbidden(e):
        if is_api_request():
            return jsonify({
                'error': 'Forbidden',
                'message': 'You do not have permission to access this resource'
            }), 403
        flash('You do not have permission to access this page.', 'danger')
        return redirect(request.referrer or url_for('admin.dashboard'))
    
    @app.errorhandler(404)
    def not_found(e):
        if is_api_request():
            return jsonify({
                'error': 'Not Found',
                'message': 'The requested resource was not found'
            }), 404
        return render_template('errors/404.html'), 404
    
    @app.errorhandler(405)
    def method_not_allowed(e):
        if is_api_request():
            return jsonify({
                'error': 'Method Not Allowed',
                'message': 'The method is not allowed for this endpoint'
            }), 405
        flash('Method not allowed.', 'danger')
        return redirect(request.referrer or url_for('admin.dashboard'))
    
    @app.errorhandler(429)
    def too_many_requests(e):
        if is_api_request():
            return jsonify({
                'error': 'Too Many Requests',
                'message': 'Rate limit exceeded. Please try again later.'
            }), 429
        flash('Rate limit exceeded. Please wait a moment.', 'warning')
        return redirect(request.referrer or url_for('admin.dashboard'))
    
    @app.errorhandler(500)
    def internal_server_error(e):
        app.logger.error(f"500 Error: {e}")
        if is_api_request():
            return jsonify({
                'error': 'Internal Server Error',
                'message': 'An unexpected error occurred'
            }), 500
        return render_template('errors/500.html'), 500
    
    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        return jsonify({
            'error': e.name,
            'message': e.description
        }), e.code
    
    @app.errorhandler(Exception)
    def handle_exception(e):
        app.logger.error(f"Unhandled exception: {e}", exc_info=True)
        return jsonify({
            'error': 'Internal Server Error',
            'message': 'An unexpected error occurred'
        }), 500


def _register_static_versioning(app):
    """Stamp `url_for('static', ...)` URLs with the file's modification time.

    Browsers cache CSS and images hard, keyed on the URL. Without a stamp, a
    stylesheet change reaches the user only after a manual hard refresh -
    until then they get new markup styled by an old stylesheet, which looks
    like a broken layout rather than a stale file.

    Falls back to an unstamped URL when the file cannot be found, so a
    missing asset never takes a page down.
    """
    import os

    @app.url_defaults
    def add_static_version(endpoint, values):
        if endpoint != 'static' or 'filename' not in values:
            return
        static_folder = app.static_folder
        if not static_folder:
            return
        path = os.path.join(static_folder, values['filename'])
        try:
            values['v'] = int(os.stat(path).st_mtime)
        except OSError:
            pass


def _register_context_processors(app):
    """Register template context processors"""
    
    @app.context_processor
    def utility_processor():
        """Add utility functions to all templates"""
        from flask_login import current_user
        from datetime import datetime
        return {
            'current_user': current_user,
            'now': datetime.now,
            'format_pkt_time': lambda dt: dt.strftime('%d/%m/%Y %H:%M:%S') if dt else '-',
            'get_year_choices': lambda: [(str(y), str(y)) for y in range(1900, datetime.now().year + 2)][::-1]
        }


def _register_commands(app):
    """Register CLI commands"""
    
    @app.cli.command('init-db')
    def init_db_command():
        """Initialize the database"""
        from src.scripts.init_db import init_database
        init_database()
        print("Database initialized successfully!")
    
    @app.cli.command('seed-db')
    def seed_db_command():
        """Seed the database with initial data"""
        from src.scripts.seed_data import seed_database
        seed_database()
        print("Database seeded successfully!")
    
    @app.cli.command('create-admin')
    def create_admin_command():
        """Create admin user"""
        from src.scripts.create_admin import create_admin
        create_admin()
    
    @app.cli.command('backup-db')
    def backup_db_command():
        """Backup the database"""
        from src.scripts.backup_db import backup_database
        backup_database()
        print("Database backup completed!")


def _register_request_hooks(app):
    """Register before/after request hooks"""
    
    @app.before_request
    def before_request():
        """Run before each request"""
        # Log request for debugging
        if app.debug:
            app.logger.debug(f"Request: {request.method} {request.path}")
    
    @app.after_request
    def after_request(response):
        """Run after each request"""
        # Add security headers
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        
        if app.config.get('ENV') == 'production':
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        
        return response


# Import request for before_request
from flask import request