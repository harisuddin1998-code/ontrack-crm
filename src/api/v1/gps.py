# src/api/v1/gps.py
"""
GPS API Endpoints
"""
from flask import request, jsonify
from flask_login import login_required

from src.api import api_v1_bp
from src.services import GPSService
from src.utils.logging import get_logger

logger = get_logger(__name__)
gps_service = GPSService()


@api_v1_bp.route('/gps/locations', methods=['GET'])
@login_required
def get_locations():
    """
    Get all GPS locations
    ---
    tags:
      - GPS
    responses:
      200:
        description: List of GPS locations
    """
    # Get from local database
    locations = gps_service.get_all()
    
    # Or fetch fresh from API
    fresh = request.args.get('fresh', 'false').lower() == 'true'
    if fresh:
        data = gps_service.fetch_all_locations()
        return jsonify(data), 200
    
    return jsonify([loc.to_dict() for loc in locations]), 200


@api_v1_bp.route('/gps/locations/sync', methods=['POST'])
@login_required
def sync_locations():
    """
    Sync GPS locations from external API
    """
    try:
        count = gps_service.sync_locations()
        return jsonify({
            'success': True,
            'message': f'Synced {count} locations',
            'count': count
        }), 200
    except Exception as e:
        logger.error(f"GPS sync error: {e}")
        return jsonify({'error': str(e)}), 500


@api_v1_bp.route('/gps/locations/<string:imei>', methods=['GET'])
@login_required
def get_location_by_imei(imei):
    """
    Get GPS location by IMEI
    """
    location = gps_service.get_location_by_imei(imei)
    if not location:
        return jsonify({'error': 'Location not found'}), 404
    return jsonify(location), 200


@api_v1_bp.route('/gps/vehicles/<string:reg_no>', methods=['GET'])
@login_required
def get_vehicle_location(reg_no):
    """
    Get GPS location by vehicle registration
    """
    location = gps_service.get_vehicle_location(reg_no)
    if not location:
        return jsonify({'error': 'Vehicle location not found'}), 404
    return jsonify(location), 200


@api_v1_bp.route('/gps/active', methods=['GET'])
@login_required
def get_active_vehicles():
    """
    Get vehicles with recent GPS updates
    """
    minutes = request.args.get('minutes', 30, type=int)
    vehicles = gps_service.get_active_vehicles(minutes)
    return jsonify([v.to_dict() for v in vehicles]), 200


@api_v1_bp.route('/gps/non-reporting', methods=['GET'])
@login_required
def get_non_reporting():
    """
    Get non-reporting vehicles
    """
    vehicles = gps_service.get_non_reporting_vehicles()
    return jsonify(vehicles), 200


@api_v1_bp.route('/gps/diagnose', methods=['GET'])
@login_required
def diagnose_gps():
    """
    Diagnose GPS API connectivity
    """
    results = gps_service.diagnose_api()
    return jsonify(results), 200 
