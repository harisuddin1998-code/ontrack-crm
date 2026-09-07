# src/services/security_service.py
"""
Security Briefing Service - Business logic for security briefings
"""
from typing import Optional, List, Dict, Any
from datetime import datetime

from src.models.security import SecurityBriefingData
from src.models.purchase_order import PurchaseOrder
from src.repositories.base_repository import BaseRepository
from src.services.base_service import BaseService
from src.services.notification_service import NotificationService
from src.services.email_service import EmailService
from src.extensions import db
from src.utils.timezone import get_current_time, get_current_date
from src.utils.logging import get_logger

logger = get_logger(__name__)


class SecurityBriefingService(BaseService[SecurityBriefingData]):
    """Service for security briefing operations"""
    
    def __init__(self):
        super().__init__(BaseRepository(SecurityBriefingData))
        self.notification_service = NotificationService()
        self.email_service = EmailService()
    
    def count(self, status: Optional[str] = None) -> int:
        """Count security briefings with optional status filter"""
        try:
            query = SecurityBriefingData.query
            if status:
                query = query.filter_by(status=status)
            return query.count()
        except Exception as e:
            logger.error(f"Error counting security briefings: {e}")
            return 0
    
    def get_dashboard_stats(self) -> Dict[str, Any]:
        """Get dashboard statistics"""
        try:
            total = self.count()
            pending = self.count(status='PENDING')
            completed = self.count(status='COMPLETED')
            
            return {
                'total': total,
                'pending': pending,
                'completed': completed,
            }
        except Exception as e:
            logger.error(f"Error getting security stats: {e}")
            return {'total': 0, 'pending': 0, 'completed': 0}
    
    def get_briefings(self, filters: Optional[Dict[str, Any]] = None, page: int = 1,
                      per_page: int = 20, search: Optional[str] = None) -> Dict[str, Any]:
        """Get briefings with filters and pagination"""
        if filters is None:
            filters = {}
        
        if search:
            query = SecurityBriefingData.query.join(
                PurchaseOrder, SecurityBriefingData.po_id == PurchaseOrder.id
            ).filter(
                db.or_(
                    PurchaseOrder.owner_name.ilike(f'%{search}%'),
                    PurchaseOrder.reg_no.ilike(f'%{search}%')
                )
            )
            total = query.count()
            items = query.offset((page - 1) * per_page).limit(per_page).all()
            return {'items': items, 'total': total, 'page': page, 'per_page': per_page}
        
        items, total = self.repository.get_paginated(page, per_page, **filters)
        return {'items': items, 'total': total, 'page': page, 'per_page': per_page}
    
    def get_by_po(self, po_id: int) -> Optional[SecurityBriefingData]:
        """Get briefing by PO ID"""
        return self.repository.get_by(po_id=po_id)
    
    def get_pending_briefings(self) -> List[SecurityBriefingData]:
        """Get pending briefings"""
        return self.repository.get_all(status='PENDING')
    
    def get_completed_briefings(self) -> List[SecurityBriefingData]:
        """Get completed briefings"""
        return self.repository.get_all(status='COMPLETED')
    
    def create_from_po(self, po_id: int) -> SecurityBriefingData:
        """Create security briefing from a PO"""
        existing = self.get_by_po(po_id)
        if existing:
            raise ValueError(f"Briefing already exists for PO {po_id}")
        
        from src.services.po_service import POService
        po_service = POService()
        po = po_service.get_po(po_id)
        
        if not po:
            raise ValueError(f"PO {po_id} not found")
        
        briefing = SecurityBriefingData(
            po_id=po.id,
            status='PENDING'
        )
        
        db.session.add(briefing)
        db.session.commit()
        
        logger.info(f"Security briefing created for PO {po.po_number}")
        return briefing
    
    def complete_briefing(self, briefing_id: int, officer_name: str) -> Optional[SecurityBriefingData]:
        """Complete a security briefing"""
        briefing = self.repository.get_by_id(briefing_id)
        if not briefing:
            return None
        
        if briefing.status == 'COMPLETED':
            raise ValueError("Briefing already completed")
        
        briefing.status = 'COMPLETED'
        briefing.briefed_by = officer_name
        briefing.completed_at = get_current_time()
        db.session.commit()
        
        try:
            self.email_service.send_security_completion_email(briefing)
        except Exception as e:
            logger.error(f"Failed to send security completion email: {e}")
        
        self.notification_service.notify_security_briefing(briefing)
        
        logger.info(f"Security briefing {briefing_id} completed by {officer_name}")
        return briefing
    
    def get_pos_pending_briefing(self) -> List[PurchaseOrder]:
        """Completed POs with no security briefing.

        The Pending Sync screen this backed is gone - briefings are now
        raised automatically when an installation is completed. Kept for the
        API and as a backfill/reconciliation check for installations
        completed before that was true.
        """
        from src.services.po_service import POService
        po_service = POService()
        completed_pos = po_service.get_pos(filters={'status': 'COMPLETED'})
        briefed_po_ids = [b.po_id for b in self.repository.get_all()]
        pending_pos = [po for po in completed_pos['items'] if po.id not in briefed_po_ids]
        return pending_pos
    
    def get_recent(self, limit: int = 10) -> List[SecurityBriefingData]:
        """Get recent briefings"""
        return SecurityBriefingData.query.order_by(
            SecurityBriefingData.created_at.desc()
        ).limit(limit).all()
    
    def update_briefing(self, briefing_id: int, data: Dict[str, Any]) -> Optional[SecurityBriefingData]:
        """Update briefing details"""
        briefing = self.repository.get_by_id(briefing_id)
        if not briefing:
            return None
        
        if briefing.status == 'COMPLETED':
            raise ValueError("Cannot update a completed briefing")
        
        updatable_fields = [
            'segment', 'cnic', 'father_name', 'mother_name', 'address',
            'secondary_user_name', 'secondary_user_phone',
            'emergency_user_name', 'emergency_user_phone',
            'device_serial_no', 'sim_network', 'accessories_installed',
            'password_1', 'password_2', 'fence', 'services',
            'security_training_completed', 'customer_demonstration',
            'services_explained', 'customer_signature', 'acknowledgement',
            'officer_notes', 'status'
        ]
        
        for field in updatable_fields:
            if field in data:
                setattr(briefing, field, data[field])
        
        db.session.commit()
        logger.info(f"Security briefing {briefing_id} updated")
        return briefing