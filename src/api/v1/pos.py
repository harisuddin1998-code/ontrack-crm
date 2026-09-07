# src/api/v1/pos.py
"""
Purchase Order API Endpoints
"""
from flask import request, jsonify
from flask_login import login_required, current_user

from src.api import api_v1_bp
from src.services import POService
from src.schemas.po_schemas import (
    POCreateRequest, POUpdateRequest, POResponse, POListResponse
)
from src.utils.decorators import role_required
from src.utils.logging import get_logger

logger = get_logger(__name__)
po_service = POService()


@api_v1_bp.route('/pos', methods=['GET'])
@login_required
def get_pos():
    """
    Get list of purchase orders
    ---
    tags:
      - Purchase Orders
    parameters:
      - name: page
        in: query
        type: integer
        description: Page number
        default: 1
      - name: per_page
        in: query
        type: integer
        description: Items per page
        default: 20
      - name: status
        in: query
        type: string
        description: Filter by status
        enum: [PENDING, IN_PROGRESS, COMPLETED, CANCELLED]
      - name: search
        in: query
        type: string
        description: Search by PO number, customer name, or registration
    responses:
      200:
        description: List of POs
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    status = request.args.get('status', '')
    search = request.args.get('search', '')
    
    filters = {}
    if status:
        filters['status'] = status
    
    # Sales users can only see their own POs
    if current_user.is_sales():
        filters['sales_person_id'] = current_user.id
    
    result = po_service.get_pos(filters=filters, page=page, per_page=per_page, search=search)
    
    return jsonify({
        'items': [po.to_dict() for po in result['items']],
        'total': result['total'],
        'page': result['page'],
        'per_page': result['per_page'],
        'pages': (result['total'] + result['per_page'] - 1) // result['per_page']
    }), 200


@api_v1_bp.route('/pos', methods=['POST'])
@login_required
@role_required('sales', 'admin')
def create_po():
    """
    Create a new purchase order
    """
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'Missing request body'}), 400
    
    # Validate required fields
    required_fields = ['owner_name', 'owner_contact', 'reg_no', 'vehicle_make', 
                       'vehicle_model', 'vehicle_year', 'vehicle_color', 
                       'engine_number', 'chassis_number']
    
    missing = [f for f in required_fields if not data.get(f)]
    if missing:
        return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400
    
    # Determine sales person
    if current_user.is_sales():
        data['sales_person_id'] = current_user.id
    
    try:
        po = po_service.create_po(data, current_user.id)
        return jsonify(po.to_dict()), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error creating PO: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@api_v1_bp.route('/pos/<int:po_id>', methods=['GET'])
@login_required
def get_po(po_id):
    """
    Get purchase order by ID
    """
    po = po_service.get_po(po_id)
    
    if not po:
        return jsonify({'error': 'PO not found'}), 404
    
    # Check permission
    if current_user.is_sales() and po.sales_person_id != current_user.id:
        return jsonify({'error': 'You do not have permission to view this PO'}), 403
    
    return jsonify(po.to_dict()), 200


@api_v1_bp.route('/pos/<int:po_id>', methods=['PUT'])
@login_required
@role_required('admin')
def update_po(po_id):
    """
    Update purchase order
    """
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'Missing request body'}), 400
    
    try:
        po = po_service.update_po(po_id, data, current_user.id)
        if not po:
            return jsonify({'error': 'PO not found'}), 404
        return jsonify(po.to_dict()), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error updating PO: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@api_v1_bp.route('/pos/<int:po_id>', methods=['DELETE'])
@login_required
@role_required('admin')
def delete_po(po_id):
    """
    Delete purchase order
    """
    try:
        success = po_service.delete(po_id)
        if not success:
            return jsonify({'error': 'PO not found'}), 404
        return jsonify({'success': True}), 200
    except Exception as e:
        logger.error(f"Error deleting PO: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@api_v1_bp.route('/pos/<int:po_id>/complete', methods=['POST'])
@login_required
@role_required('installation', 'admin')
def complete_po(po_id):
    """
    Mark PO as completed
    """
    try:
        po = po_service.complete_po(po_id, current_user.id)
        if not po:
            return jsonify({'error': 'PO not found'}), 404
        return jsonify({'success': True, 'po': po.to_dict()}), 200
    except Exception as e:
        logger.error(f"Error completing PO: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@api_v1_bp.route('/pos/<int:po_id>/cancel', methods=['POST'])
@login_required
@role_required('admin')
def cancel_po(po_id):
    """
    Cancel PO
    """
    data = request.get_json() or {}
    reason = data.get('reason')
    
    try:
        po = po_service.cancel_po(po_id, current_user.id, reason)
        if not po:
            return jsonify({'error': 'PO not found'}), 404
        return jsonify({'success': True, 'po': po.to_dict()}), 200
    except Exception as e:
        logger.error(f"Error cancelling PO: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@api_v1_bp.route('/pos/stats', methods=['GET'])
@login_required
def get_po_stats():
    """
    Get PO statistics
    """
    user_id = current_user.id if current_user.is_sales() else None
    stats = po_service.get_dashboard_stats(user_id)
    return jsonify(stats), 200 
