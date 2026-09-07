# src/web/errors.py
"""
Custom error handlers for the application
"""
from flask import render_template, jsonify, request, flash, redirect
from werkzeug.exceptions import HTTPException

from src.web import auth_bp
from src.utils.logging import get_logger

logger = get_logger(__name__)


def handle_404(e):
    """Handle 404 Not Found errors"""
    if request.accept_mimetypes.best == 'application/json':
        return jsonify({'error': 'Not Found', 'message': 'The requested resource was not found'}), 404
    return render_template('errors/404.html'), 404


def handle_403(e):
    """Handle 403 Forbidden errors"""
    if request.accept_mimetypes.best == 'application/json':
        return jsonify({'error': 'Forbidden', 'message': 'You do not have permission to access this resource'}), 403
    return render_template('errors/403.html'), 403


def handle_500(e):
    """Handle 500 Internal Server Error"""
    logger.error(f"500 Error: {e}")
    if request.accept_mimetypes.best == 'application/json':
        return jsonify({'error': 'Internal Server Error', 'message': 'An unexpected error occurred'}), 500
    return render_template('errors/500.html'), 500


def handle_validation_error(e):
    """Handle validation errors"""
    if request.accept_mimetypes.best == 'application/json':
        return jsonify({'error': 'Validation Error', 'message': str(e)}), 400
    flash(str(e), 'danger')
    return redirect(request.referrer or '/')


def handle_db_error(e):
    """Handle database errors"""
    logger.error(f"Database Error: {e}")
    if request.accept_mimetypes.best == 'application/json':
        return jsonify({'error': 'Database Error', 'message': 'A database error occurred'}), 500
    flash('A database error occurred. Please try again.', 'danger')
    return redirect(request.referrer or '/') 
