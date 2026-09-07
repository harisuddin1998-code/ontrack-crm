# src/api/v1/payment.py
"""
Payment Recovery API Endpoints
"""
from flask import request, jsonify
from flask_login import login_required, current_user

from src.api import api_v1_bp
from src.services import PaymentRecoveryService
from src.utils.logging import get_logger

logger = get_logger(__name__)
payment_service = PaymentRecoveryService()


@api_v1_bp.route('/payments', methods=['GET'])
@login_required
def get_payments():
    """
    Get payment records
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    status = request.args.get('status', '')
    search = request.args.get('search', '')
    
    filters = {}
    if status:
        filters['payment_status'] = status
    
    result = payment_service.get_payments(
        filters=filters,
        page=page,
        per_page=per_page,
        search=search
    )
    
    return jsonify({
        'items': [p.to_dict() for p in result['items']],
        'total': result['total'],
        'page': result['page'],
        'per_page': result['per_page']
    }), 200


@api_v1_bp.route('/payments/<int:payment_id>', methods=['GET'])
@login_required
def get_payment(payment_id):
    """Get payment record by ID"""
    payment = payment_service.get_by_id(payment_id)
    if not payment:
        return jsonify({'error': 'Payment record not found'}), 404
    return jsonify(payment.to_dict()), 200


@api_v1_bp.route('/payments/<int:payment_id>/add-payment', methods=['POST'])
@login_required
def add_payment(payment_id):
    """Add payment to a recovery record"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Missing request body'}), 400
    
    amount = data.get('amount')
    notes = data.get('notes', '')
    
    if not amount or amount <= 0:
        return jsonify({'error': 'Valid amount required'}), 400
    
    try:
        payment = payment_service.add_payment(
            payment_id=payment_id,
            amount=amount,
            user_id=current_user.id,
            notes=notes
        )
        if not payment:
            return jsonify({'error': 'Payment record not found'}), 404
        return jsonify(payment.to_dict()), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@api_v1_bp.route('/payments/<int:payment_id>/status', methods=['PUT'])
@login_required
def update_payment_status(payment_id):
    """Update payment status"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Missing request body'}), 400
    
    status = data.get('status')
    if not status:
        return jsonify({'error': 'Status required'}), 400
    
    try:
        payment = payment_service.update_status(payment_id, status)
        if not payment:
            return jsonify({'error': 'Payment record not found'}), 404
        return jsonify(payment.to_dict()), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@api_v1_bp.route('/payments/<int:payment_id>/follow-up', methods=['POST'])
@login_required
def schedule_follow_up(payment_id):
    """Schedule follow-up"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Missing request body'}), 400
    
    next_follow_up = data.get('next_follow_up')
    if not next_follow_up:
        return jsonify({'error': 'next_follow_up date required'}), 400
    
    from datetime import datetime
    follow_up_date = datetime.strptime(next_follow_up, '%Y-%m-%d').date()
    
    try:
        payment = payment_service.schedule_follow_up(payment_id, follow_up_date)
        if not payment:
            return jsonify({'error': 'Payment record not found'}), 404
        return jsonify(payment.to_dict()), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@api_v1_bp.route('/payments/<int:payment_id>/history', methods=['GET'])
@login_required
def get_payment_history(payment_id):
    """Get payment history"""
    history = payment_service.get_payment_history(payment_id)
    return jsonify([h.to_dict() for h in history]), 200


@api_v1_bp.route('/payments/stats', methods=['GET'])
@login_required
def get_payment_stats():
    """Get payment statistics"""
    stats = payment_service.get_dashboard_stats()
    return jsonify(stats), 200 
