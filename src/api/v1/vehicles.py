# src/api/v1/vehicles.py
"""
Vehicle API Endpoints
"""
from flask import request, jsonify
from flask_login import login_required

from src.api import api_v1_bp
from src.services.vehicle_service import (
    VehicleMakeService, VehicleModelService, VehicleYearService,
    VehicleColorService, DeviceTypeService, CityService
)
from src.utils.logging import get_logger

logger = get_logger(__name__)


@api_v1_bp.route('/vehicles/makes', methods=['GET'])
@login_required
def get_makes():
    """Get all vehicle makes"""
    service = VehicleMakeService()
    makes = service.get_all_makes()
    return jsonify([m.to_dict() for m in makes]), 200


@api_v1_bp.route('/vehicles/makes', methods=['POST'])
@login_required
def create_make():
    """Create a new vehicle make"""
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({'error': 'Name required'}), 400
    
    service = VehicleMakeService()
    try:
        make = service.create_make(data['name'])
        return jsonify(make.to_dict()), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@api_v1_bp.route('/vehicles/models', methods=['GET'])
@login_required
def get_models():
    """Get vehicle models"""
    make_id = request.args.get('make_id', type=int)
    
    service = VehicleModelService()
    if make_id:
        models = service.get_models_by_make(make_id)
    else:
        models = service.get_all()
    
    return jsonify([m.to_dict() for m in models]), 200


@api_v1_bp.route('/vehicles/models', methods=['POST'])
@login_required
def create_model():
    """Create a new vehicle model"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Missing request body'}), 400
    
    name = data.get('name')
    make_id = data.get('make_id')
    
    if not name or not make_id:
        return jsonify({'error': 'Name and make_id required'}), 400
    
    service = VehicleModelService()
    try:
        model = service.create_model(name, make_id)
        return jsonify(model.to_dict()), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@api_v1_bp.route('/vehicles/years', methods=['GET'])
@login_required
def get_years():
    """Get all vehicle years"""
    service = VehicleYearService()
    years = service.get_all_years()
    return jsonify([y.to_dict() for y in years]), 200


@api_v1_bp.route('/vehicles/colors', methods=['GET'])
@login_required
def get_colors():
    """Get all vehicle colors"""
    service = VehicleColorService()
    colors = service.get_all_colors()
    return jsonify([c.to_dict() for c in colors]), 200


@api_v1_bp.route('/vehicles/device-types', methods=['GET'])
@login_required
def get_device_types():
    """Get all device types"""
    service = DeviceTypeService()
    devices = service.get_all_device_types()
    return jsonify([d.to_dict() for d in devices]), 200


@api_v1_bp.route('/vehicles/cities', methods=['GET'])
@login_required
def get_cities():
    """Get all cities"""
    service = CityService()
    cities = service.get_all_cities()
    return jsonify([c.to_dict() for c in cities]), 200 
