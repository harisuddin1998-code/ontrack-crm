# src/web/context_processors.py
"""
Template context processors
"""
from flask import current_app
from src.utils.timezone import get_current_time, format_pkt_time
from src.services.auth_service import AuthService


def get_utilities():
    """Return utility functions for templates"""
    return {
        'now': get_current_time,
        'format_pkt_time': format_pkt_time,
        'current_user': AuthService().get_user_by_id,  # Will be used with user_id
        'app_name': 'Ontrack Insight',
        'app_version': current_app.config.get('API_VERSION', '1.0.0'),
    } 
