# src/api/v1/reports.py
"""
Reports API Endpoints
"""
from flask import request, jsonify
from flask_login import login_required

from src.api import api_v1_bp
from src.services import POService, PaymentRecoveryService, SecurityBriefingService
from src.services.report_service import ReportService
from src.utils.logging import get_logger

logger = get_logger(__name__)


@api_v1_bp.route('/reports/po-summary', methods=['GET'])
@login_required
def get_po_summary():
    """Get PO summary report"""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    from datetime import datetime
    start = datetime.strptime(start_date, '%Y-%m-%d') if start_date else None
    end = datetime.strptime(end_date, '%Y-%m-%d') if end_date else None
    
    service = POService()
    stats = service.get_dashboard_stats()
    
    # Get POs for the period
    filters = {}
    if start:
        filters['created_at__gte'] = start
    if end:
        filters['created_at__lte'] = end
    
    result = service.get_pos(filters=filters)
    
    # Calculate totals
    total_rates = sum(po.rates or 0 for po in result['items'])
    total_amc = sum(po.amc or 0 for po in result['items'])
    total_amount = total_rates + total_amc
    
    return jsonify({
        'period': {
            'start_date': start_date,
            'end_date': end_date
        },
        'summary': stats,
        'totals': {
            'total_orders': len(result['items']),
            'total_rates': total_rates,
            'total_amc': total_amc,
            'total_amount': total_amount
        }
    }), 200


@api_v1_bp.route('/reports/payment-summary', methods=['GET'])
@login_required
def get_payment_summary():
    """Get payment summary report"""
    service = PaymentRecoveryService()
    stats = service.get_dashboard_stats()
    
    # Get recent payments
    payments = service.get_recent(50)
    
    return jsonify({
        'summary': stats,
        'recent_payments': [p.to_dict() for p in payments]
    }), 200


@api_v1_bp.route('/reports/security-summary', methods=['GET'])
@login_required
def get_security_summary():
    """Get security briefing summary"""
    service = SecurityBriefingService()
    stats = service.get_dashboard_stats()
    
    briefings = service.get_recent(50)
    
    return jsonify({
        'summary': stats,
        'recent_briefings': [b.to_dict() for b in briefings]
    }), 200


@api_v1_bp.route('/reports/technician-performance', methods=['GET'])
@login_required
def get_technician_performance():
    """Get technician performance report"""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    technician_id = request.args.get('technician_id', type=int)
    
    from datetime import datetime
    start = datetime.strptime(start_date, '%Y-%m-%d') if start_date else None
    end = datetime.strptime(end_date, '%Y-%m-%d') if end_date else None
    
    from src.services.technician_service import TechnicianService, TechnicianTripService
    tech_service = TechnicianService()
    trip_service = TechnicianTripService()
    
    if technician_id:
        technicians = [tech_service.get_technician(technician_id)]
    else:
        technicians = tech_service.get_all_technicians()
    
    performance = []
    for tech in technicians:
        if not tech:
            continue
        
        trips = trip_service.get_by_technician(tech.id, start, end)
        
        performance.append({
            'technician_id': tech.id,
            'technician_name': tech.name,
            'total_trips': len(trips),
            'total_distance': sum(t.distance_km or 0 for t in trips),
            'total_fuel_used': sum(t.fuel_used_liters or 0 for t in trips),
            'total_fuel_cost': sum(t.fuel_cost or 0 for t in trips),
            'avg_distance_per_trip': sum(t.distance_km or 0 for t in trips) / len(trips) if trips else 0
        })
    
    return jsonify({
        'period': {
            'start_date': start_date,
            'end_date': end_date
        },
        'performance': performance
    }), 200


@api_v1_bp.route('/reports/generate', methods=['POST'])
@login_required
def generate_report():
    """Generate custom report (PDF)"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Missing request body'}), 400
    
    report_type = data.get('type')
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    
    if not report_type:
        return jsonify({'error': 'Report type required'}), 400
    
    from datetime import datetime
    start = datetime.strptime(start_date, '%Y-%m-%d') if start_date else None
    end = datetime.strptime(end_date, '%Y-%m-%d') if end_date else None
    
    service = ReportService()
    
    try:
        if report_type == 'po':
            report_data = service.generate_po_report(start, end)
        elif report_type == 'payment':
            report_data = service.generate_payment_report(start, end)
        elif report_type == 'security':
            report_data = service.generate_security_report(start, end)
        elif report_type == 'technician':
            technician_id = data.get('technician_id')
            report_data = service.generate_technician_report(start, end, technician_id)
        else:
            return jsonify({'error': 'Invalid report type'}), 400
        
        return jsonify(report_data), 200
    except Exception as e:
        logger.error(f"Error generating report: {e}")
        return jsonify({'error': str(e)}), 500 
