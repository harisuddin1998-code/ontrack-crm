# src/api/__init__.py
"""
API Blueprints - REST API endpoints
"""
from flask import Blueprint

# Create API blueprint
api_v1_bp = Blueprint('api_v1', __name__, url_prefix='/api/v1')

# Import routes (must be after blueprint creation)
from src.api.v1 import auth, pos, vehicles, technicians, gps, security, payment, reports 
