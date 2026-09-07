# src/web/__init__.py
"""
Web Blueprints - Register all web routes
"""
from flask import Blueprint

# Create blueprints (url_prefix is configured upon app.register_blueprint)
auth_bp = Blueprint('auth', __name__)
admin_bp = Blueprint('admin', __name__)
sales_bp = Blueprint('sales', __name__)
installation_bp = Blueprint('installation', __name__)
security_bp = Blueprint('security', __name__)
payment_bp = Blueprint('payment', __name__)
redo_bp = Blueprint('redo', __name__)
removal_bp = Blueprint('removal', __name__)
complaint_bp = Blueprint('complaint', __name__)
inventory_bp = Blueprint('inventory', __name__)
live_amc_bp = Blueprint('live_amc', __name__)
notifications_bp = Blueprint('notifications', __name__)
suggestions_bp = Blueprint('suggestions', __name__)


# Import routes (must be after blueprint creation to avoid circular imports)
from .annual_recovery import annual_recovery_bp
from . import auth, admin, sales, installation, security, payment, redo, removal, errors, context_processors, annual_recovery, complaint, inventory, live_amc, notifications, suggestions