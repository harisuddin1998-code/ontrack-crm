# src/api/v1/security.py
"""
Security Briefing API Endpoints
"""
from flask import request, jsonify
from flask_login import login_required, current_user

from src.api import api_v1_bp
from src.services import SecurityBriefingService
from src.utils.logging import get_logger

logger = get_logger(__name__)
security_service = SecurityBriefingService()


@api_v1_bp.route('/security/briefings', methods=['GET'])
@login_required
def get_briefings():
    """
    Get security briefings
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    status = request.args.get('status', '')
    search = request.args.get('search', '')
    
    filters = {}
    if status:
        filters['status'] = status
    
    result = security_service.get_briefings(
        filters=filters,
        page=page,
        per_page=per_page,
        search=search
    )
    
    return jsonify({
        'items': [b.to_dict() for b in result['items']],
        'total': result['total'],
        'page': result['page'],
        'per_page': result['per_page']
    }), 200


@api_v1_bp.route('/security/briefings/<int:briefing_id>', methods=['GET'])
@login_required
def get_briefing(briefing_id):
    """Get security briefing by ID"""
    briefing = security_service.get_by_id(briefing_id)
    if not briefing:
        return jsonify({'error': 'Briefing not found'}), 404
    return jsonify(briefing.to_dict()), 200


@api_v1_bp.route('/security/briefings', methods=['POST'])
@login_required
def create_briefing():
    """Create security briefing from PO"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Missing request body'}), 400
    
    po_id = data.get('po_id')
    if not po_id:
        return jsonify({'error': 'po_id required'}), 400
    
    try:
        briefing = security_service.create_from_po(po_id)
        return jsonify(briefing.to_dict()), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error creating briefing: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@api_v1_bp.route('/security/briefings/<int:briefing_id>', methods=['PUT'])
@login_required
def update_briefing(briefing_id):
    """Update security briefing"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Missing request body'}), 400
    
    try:
        briefing = security_service.update(briefing_id, **data)
        if not briefing:
            return jsonify({'error': 'Briefing not found'}), 404
        return jsonify(briefing.to_dict()), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@api_v1_bp.route('/security/briefings/<int:briefing_id>/complete', methods=['POST'])
@login_required
def complete_briefing(briefing_id):
    """Complete security briefing"""
    try:
        briefing = security_service.complete_briefing(
            briefing_id,
            current_user.name or current_user.username
        )
        if not briefing:
            return jsonify({'error': 'Briefing not found'}), 404
        return jsonify(briefing.to_dict()), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@api_v1_bp.route('/security/pending-sync', methods=['GET'])
@login_required
def get_pending_sync():
    """Get POs pending security briefing"""
    pending_pos = security_service.get_pos_pending_briefing()
    return jsonify([po.to_dict() for po in pending_pos]), 200


@api_v1_bp.route('/security/stats', methods=['GET'])
@login_required
def get_security_stats():
    """Get security briefing statistics"""
    stats = security_service.get_dashboard_stats()
    return jsonify(stats), 200 
