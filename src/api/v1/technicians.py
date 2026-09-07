# src/api/v1/technicians.py
"""
Technician API Endpoints
"""
from flask import request, jsonify
from flask_login import login_required

from src.api import api_v1_bp
from src.services.technician_service import (
    TechnicianService, TechnicianBikeService, TechnicianTripService,
    FuelReimbursementInvoiceService
)
from src.utils.logging import get_logger

logger = get_logger(__name__)


@api_v1_bp.route('/technicians', methods=['GET'])
@login_required
def get_technicians():
    """Get all technicians"""
    active_only = request.args.get('active_only', 'true').lower() == 'true'
    service = TechnicianService()
    technicians = service.get_all_technicians(active_only)
    return jsonify([t.to_dict() for t in technicians]), 200


@api_v1_bp.route('/technicians/<int:tech_id>', methods=['GET'])
@login_required
def get_technician(tech_id):
    """Get technician by ID"""
    service = TechnicianService()
    tech = service.get_technician(tech_id)
    if not tech:
        return jsonify({'error': 'Technician not found'}), 404
    return jsonify(tech.to_dict()), 200


@api_v1_bp.route('/technicians', methods=['POST'])
@login_required
def create_technician():
    """Create a new technician"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Missing request body'}), 400
    
    service = TechnicianService()
    try:
        tech = service.create_technician(data)
        return jsonify(tech.to_dict()), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@api_v1_bp.route('/technicians/<int:tech_id>', methods=['PUT'])
@login_required
def update_technician(tech_id):
    """Update technician"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Missing request body'}), 400
    
    service = TechnicianService()
    try:
        tech = service.update_technician(tech_id, data)
        if not tech:
            return jsonify({'error': 'Technician not found'}), 404
        return jsonify(tech.to_dict()), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@api_v1_bp.route('/technicians/<int:tech_id>/bike', methods=['GET'])
@login_required
def get_technician_bike(tech_id):
    """Get technician's bike"""
    service = TechnicianBikeService()
    bike = service.get_bike_by_technician(tech_id)
    if not bike:
        return jsonify({'error': 'No bike assigned to this technician'}), 404
    return jsonify(bike.to_dict()), 200


@api_v1_bp.route('/technicians/<int:tech_id>/bike', methods=['POST'])
@login_required
def assign_bike(tech_id):
    """Assign bike to technician"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Missing request body'}), 400
    
    imei = data.get('imei')
    registration = data.get('registration')
    
    if not imei or not registration:
        return jsonify({'error': 'IMEI and registration required'}), 400
    
    service = TechnicianBikeService()
    try:
        bike = service.assign_bike(
            technician_id=tech_id,
            imei=imei,
            registration=registration,
            model=data.get('model'),
            fuel_efficiency=data.get('fuel_efficiency', 35.0)
        )
        return jsonify(bike.to_dict()), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@api_v1_bp.route('/technicians/<int:tech_id>/trips', methods=['GET'])
@login_required
def get_technician_trips(tech_id):
    """Get technician trips"""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    from datetime import datetime
    start = datetime.strptime(start_date, '%Y-%m-%d') if start_date else None
    end = datetime.strptime(end_date, '%Y-%m-%d') if end_date else None
    
    service = TechnicianTripService()
    trips = service.get_by_technician(tech_id, start, end)
    
    return jsonify([t.to_dict() for t in trips]), 200


@api_v1_bp.route('/technicians/<int:tech_id>/trips/summary', methods=['GET'])
@login_required
def get_trip_summary(tech_id):
    """Get trip summary for a technician"""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    from datetime import datetime
    start = datetime.strptime(start_date, '%Y-%m-%d') if start_date else None
    end = datetime.strptime(end_date, '%Y-%m-%d') if end_date else None
    
    if not start or not end:
        return jsonify({'error': 'start_date and end_date required'}), 400
    
    service = TechnicianTripService()
    summary = service.get_trip_summary(tech_id, start, end)
    
    return jsonify(summary), 200


@api_v1_bp.route('/technicians/bikes', methods=['GET'])
@login_required
def get_bikes():
    """Get all technician bikes"""
    service = TechnicianBikeService()
    bikes = service.get_all()
    return jsonify([b.to_dict() for b in bikes]), 200


@api_v1_bp.route('/technicians/bikes/<int:bike_id>/location', methods=['GET'])
@login_required
def get_bike_location(bike_id):
    """Get bike current location"""
    service = TechnicianBikeService()
    location = service.get_bike_location(bike_id)
    if not location:
        return jsonify({'error': 'Location not found'}), 404
    return jsonify(location), 200


@api_v1_bp.route('/technicians/invoices', methods=['GET'])
@login_required
def get_invoices():
    """Get fuel invoices"""
    technician_id = request.args.get('technician_id', type=int)
    status = request.args.get('status', '')
    
    service = FuelReimbursementInvoiceService()
    
    filters = {}
    if technician_id:
        filters['technician_id'] = technician_id
    if status:
        filters['status'] = status
    
    invoices = service.get_all(**filters)
    return jsonify([i.to_dict() for i in invoices]), 200


@api_v1_bp.route('/technicians/invoices', methods=['POST'])
@login_required
def create_invoice():
    """Create fuel reimbursement invoice"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Missing request body'}), 400
    
    technician_id = data.get('technician_id')
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    
    if not all([technician_id, start_date, end_date]):
        return jsonify({'error': 'technician_id, start_date, and end_date required'}), 400
    
    from datetime import datetime
    start = datetime.strptime(start_date, '%Y-%m-%d').date()
    end = datetime.strptime(end_date, '%Y-%m-%d').date()
    
    service = FuelReimbursementInvoiceService()
    try:
        invoice = service.create_invoice(technician_id, start, end, current_user.id)
        return jsonify(invoice.to_dict()), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@api_v1_bp.route('/technicians/invoices/<int:invoice_id>/pay', methods=['POST'])
@login_required
def pay_invoice(invoice_id):
    """Mark invoice as paid"""
    service = FuelReimbursementInvoiceService()
    invoice = service.mark_paid(invoice_id)
    if not invoice:
        return jsonify({'error': 'Invoice not found'}), 404
    return jsonify(invoice.to_dict()), 200 
