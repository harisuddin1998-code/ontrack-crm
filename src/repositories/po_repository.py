# src/repositories/po_repository.py
"""
Purchase Order Repository
"""
from typing import Optional, List, Dict, Any
from datetime import date, datetime

from src.models.purchase_order import PurchaseOrder
from src.repositories.base_repository import BaseRepository
from src.extensions import db


class POURepository(BaseRepository[PurchaseOrder]):
    """Repository for Purchase Order operations"""
    
    def __init__(self):
        super().__init__(PurchaseOrder)
    
    def get_by_po_number(self, po_number: str) -> Optional[PurchaseOrder]:
        """Get PO by PO number"""
        return self.get_by(po_number=po_number)
    
    def get_by_reg_no(self, reg_no: str) -> List[PurchaseOrder]:
        """Get POs by registration number"""
        return self.get_all(reg_no=reg_no)
    
    def get_by_sales_person(self, sales_person_id: int) -> List[PurchaseOrder]:
        """Get POs by sales person"""
        return self.get_all(sales_person_id=sales_person_id)
    
    def get_by_status(self, status: str) -> List[PurchaseOrder]:
        """Get POs by status"""
        return self.get_all(status=status)
    
    def get_pending(self) -> List[PurchaseOrder]:
        """Get pending POs"""
        return self.get_all(status='PENDING')
    
    def get_in_progress(self) -> List[PurchaseOrder]:
        """Get in-progress POs"""
        return self.get_all(status='IN_PROGRESS')
    
    def get_completed(self) -> List[PurchaseOrder]:
        """Get completed POs"""
        return self.get_all(status='COMPLETED')
    
    def get_cancelled(self) -> List[PurchaseOrder]:
        """Get cancelled POs"""
        return self.get_all(status='CANCELLED')
    
    def get_by_date_range(self, field: str = 'created_at', start_date: Optional[date] = None, end_date: Optional[date] = None, **filters) -> List[PurchaseOrder]:
        """Get POs by date range"""
        return super().get_by_date_range(field, start_date, end_date, **filters)
    
    def get_by_scheduled_date(self, scheduled_date: date) -> List[PurchaseOrder]:
        """Get POs by scheduled date"""
        return self.get_all(scheduled_date=scheduled_date)
    
    def get_by_city(self, city: str) -> List[PurchaseOrder]:
        """Get POs by city"""
        return self.get_all(city=city)
    
    def search(self, search_term: str) -> List[PurchaseOrder]:
        """Search POs by PO number, owner name, or registration"""
        return self.session.query(PurchaseOrder).filter(
            db.or_(
                PurchaseOrder.po_number.ilike(f'%{search_term}%'),
                PurchaseOrder.owner_name.ilike(f'%{search_term}%'),
                PurchaseOrder.reg_no.ilike(f'%{search_term}%')
            )
        ).all()
    
    @staticmethod
    def today_bounds():
        """The half-open range covering today in Pakistan: [midnight, midnight).

        Defined once, here, because the dashboard's "today" counts and the
        list those cards link to both have to mean the same day - and because
        the obvious way to write this is wrong. Rows are stamped by
        `get_current_time()` in PKT, but SQLite's `current_date` is UTC, so
        comparing one against the other reported the previous day between
        midnight and 05:00 PKT every night: the cards read zero while orders
        had in fact been raised.

        A range on the bare column also lets the index be used, where
        `date(created_at) = ...` forced a scan.
        """
        from src.utils.timezone import get_current_time
        from datetime import timedelta
        start = get_current_time().replace(hour=0, minute=0, second=0, microsecond=0)
        # Naive, to compare against the naive datetimes stored in the column.
        start = start.replace(tzinfo=None)
        return start, start + timedelta(days=1)

    def get_dashboard_stats(self) -> Dict[str, Any]:
        """Get dashboard statistics"""
        start, end = self.today_bounds()
        today_total = self.session.query(PurchaseOrder).filter(
            PurchaseOrder.created_at >= start, PurchaseOrder.created_at < end
        ).count()
        # Completion is dated by when the work finished, not when the order
        # came in - hence updated_at for this one alone.
        today_completed = self.session.query(PurchaseOrder).filter(
            PurchaseOrder.status == 'COMPLETED',
            PurchaseOrder.updated_at >= start, PurchaseOrder.updated_at < end
        ).count()
        today_pending = self.session.query(PurchaseOrder).filter(
            PurchaseOrder.status == 'PENDING',
            PurchaseOrder.created_at >= start, PurchaseOrder.created_at < end
        ).count()

        return {
            'total': self.count(),
            'pending': self.count(status='PENDING'),
            'in_progress': self.count(status='IN_PROGRESS'),
            'completed': self.count(status='COMPLETED'),
            'cancelled': self.count(status='CANCELLED'),
            'today_total': today_total,
            'today_completed': today_completed,
            'today_pending': today_pending,
        }
    
    def get_recent(self, limit: int = 10) -> List[PurchaseOrder]:
        """Get recent POs"""
        return self.session.query(PurchaseOrder).order_by(
            PurchaseOrder.created_at.desc()
        ).limit(limit).all()
    
    def get_by_technician(self, technician_name: str) -> List[PurchaseOrder]:
        """Get POs assigned to technician"""
        return self.get_all(technician_assigned=technician_name)
    
    def get_pending_security_briefing(self) -> List[PurchaseOrder]:
        """Get completed POs without security briefing"""
        from src.models.security import SecurityBriefingData
        
        completed_pos = self.get_completed()
        briefed_po_ids = [b.po_id for b in SecurityBriefingData.query.all()]
        
        return [po for po in completed_pos if po.id not in briefed_po_ids]
    
    def count_by_sales_person(self) -> Dict[int, int]:
        """Count POs by sales person"""
        from sqlalchemy import func
        
        results = self.session.query(
            PurchaseOrder.sales_person_id,
            func.count(PurchaseOrder.id).label('count')
        ).group_by(PurchaseOrder.sales_person_id).all()
        
        return {r[0]: r[1] for r in results}
    
    def count_by_city(self) -> Dict[str, int]:
        """Count POs by city"""
        from sqlalchemy import func
        
        results = self.session.query(
            PurchaseOrder.city,
            func.count(PurchaseOrder.id).label('count')
        ).filter(PurchaseOrder.city.isnot(None)).group_by(
            PurchaseOrder.city
        ).all()
        
        return {r[0]: r[1] for r in results}
    
    def update_status(self, po_id: int, status: str) -> Optional[PurchaseOrder]:
        """Update PO status"""
        return self.update(po_id, status=status)
    
    def mark_completed(self, po_id: int) -> Optional[PurchaseOrder]:
        """Mark PO as completed"""
        return self.update(po_id, status='COMPLETED')
    
    def mark_cancelled(self, po_id: int) -> Optional[PurchaseOrder]:
        """Mark PO as cancelled"""
        return self.update(po_id, status='CANCELLED') 
