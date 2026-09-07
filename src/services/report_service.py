# src/services/report_service.py
"""
Report Service - Generate reports and summaries
"""
from typing import Dict, Any, Optional, List
from datetime import datetime, date

from src.services.po_service import POService
from src.services.payment_service import PaymentRecoveryService
from src.services.security_service import SecurityBriefingService
from src.services.technician_service import TechnicianService, TechnicianTripService
from src.utils.timezone import get_current_date
from src.utils.logging import get_logger

logger = get_logger(__name__)


class ReportService:
    """Service for generating reports"""
    
    def __init__(self):
        self.po_service = POService()
        self.payment_service = PaymentRecoveryService()
        self.security_service = SecurityBriefingService()
        self.technician_service = TechnicianService()
        self.trip_service = TechnicianTripService()
    
    def generate_po_report(self, start_date: Optional[date] = None, 
                           end_date: Optional[date] = None) -> Dict[str, Any]:
        """Generate PO report for date range"""
        filters = {}
        if start_date:
            filters['created_at__gte'] = start_date
        if end_date:
            filters['created_at__lte'] = end_date
        
        result = self.po_service.get_pos(filters=filters)
        pos = result['items']
        
        # Calculate totals
        total_rates = sum(po.rates or 0 for po in pos)
        total_amc = sum(po.amc or 0 for po in pos)
        total_amount = total_rates + total_amc
        
        # Status breakdown
        status_breakdown = {}
        for po in pos:
            status_breakdown[po.status] = status_breakdown.get(po.status, 0) + 1
        
        return {
            'period': {
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None,
                'generated_at': get_current_date().isoformat()
            },
            'summary': {
                'total_orders': len(pos),
                'total_rates': total_rates,
                'total_amc': total_amc,
                'total_amount': total_amount,
                'status_breakdown': status_breakdown
            },
            'orders': [po.to_dict() for po in pos[:50]]  # Limit to 50 for report
        }
    
    def generate_payment_report(self, start_date: Optional[date] = None,
                                end_date: Optional[date] = None) -> Dict[str, Any]:
        """Generate payment report for date range"""
        filters = {}
        if start_date:
            filters['created_at__gte'] = start_date
        if end_date:
            filters['created_at__lte'] = end_date
        
        result = self.payment_service.get_payments(filters=filters)
        payments = result['items']
        
        # Calculate totals
        total_received = sum(p.amount_received or 0 for p in payments)
        total_remaining = sum(p.remaining_amount or 0 for p in payments)
        total_amount = total_received + total_remaining
        
        # Status breakdown
        status_breakdown = {}
        for p in payments:
            status_breakdown[p.payment_status] = status_breakdown.get(p.payment_status, 0) + 1
        
        return {
            'period': {
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None,
                'generated_at': get_current_date().isoformat()
            },
            'summary': {
                'total_payments': len(payments),
                'total_received': total_received,
                'total_remaining': total_remaining,
                'total_amount': total_amount,
                'status_breakdown': status_breakdown
            },
            'payments': [p.to_dict() for p in payments[:50]]
        }
    
    def generate_security_report(self, start_date: Optional[date] = None,
                                 end_date: Optional[date] = None) -> Dict[str, Any]:
        """Generate security briefing report"""
        filters = {}
        if start_date:
            filters['created_at__gte'] = start_date
        if end_date:
            filters['created_at__lte'] = end_date
        
        result = self.security_service.get_briefings(filters=filters)
        briefings = result['items']
        
        # Status breakdown
        status_breakdown = {}
        for b in briefings:
            status_breakdown[b.status] = status_breakdown.get(b.status, 0) + 1
        
        return {
            'period': {
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None,
                'generated_at': get_current_date().isoformat()
            },
            'summary': {
                'total_briefings': len(briefings),
                'status_breakdown': status_breakdown
            },
            'briefings': [b.to_dict() for b in briefings[:50]]
        }
    
    def generate_technician_report(self, start_date: Optional[date] = None,
                                   end_date: Optional[date] = None,
                                   technician_id: Optional[int] = None) -> Dict[str, Any]:
        """Generate technician performance report"""
        if technician_id:
            technicians = [self.technician_service.get_technician(technician_id)]
        else:
            technicians = self.technician_service.get_all_technicians()
        
        performance = []
        for tech in technicians:
            if not tech:
                continue
            
            trips = self.trip_service.get_by_technician(tech.id, start_date, end_date)
            
            total_distance = sum(t.distance_km or 0 for t in trips)
            total_fuel = sum(t.fuel_used_liters or 0 for t in trips)
            total_cost = sum(t.fuel_cost or 0 for t in trips)
            
            performance.append({
                'technician_id': tech.id,
                'technician_name': tech.name,
                'total_trips': len(trips),
                'total_distance': round(total_distance, 2),
                'total_fuel_liters': round(total_fuel, 2),
                'total_fuel_cost': round(total_cost, 2),
                'avg_distance_per_trip': round(total_distance / len(trips), 2) if trips else 0
            })
        
        return {
            'period': {
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None,
                'generated_at': get_current_date().isoformat()
            },
            'performance': performance
        } 
