# src/services/non_reporting_service.py
"""
Non-Reporting Vehicle Service - Business logic for non-reporting vehicles
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, date  # ← Added 'date' here

from src.models.gps import NonReportingVehicle, NonReportingConversation
from src.repositories.base_repository import BaseRepository
from src.services.base_service import BaseService
from src.extensions import db
from src.utils.timezone import get_current_time, get_current_date
from src.utils.logging import get_logger

logger = get_logger(__name__)


class NonReportingService(BaseService[NonReportingVehicle]):
    """Service for non-reporting vehicle operations"""
    
    def __init__(self):
        super().__init__(BaseRepository(NonReportingVehicle))
        self.conversation_repo = BaseRepository(NonReportingConversation)
    
    def _confirmed_query(self, filters: Optional[Dict[str, Any]] = None, search: Optional[str] = None):
        """Build the shared filtered query for confirmed non-reporting
        vehicles (dt_tracker 24h+ stale), applying optional status filters
        and search - used both for paginated listing and for full-set
        operations like aging-bucket filtering that must see every matching
        row, not just one page of it."""
        if filters is None:
            filters = {}

        from datetime import timedelta
        cutoff_24h = get_current_time() - timedelta(hours=24)

        query = self.repository.session.query(NonReportingVehicle).filter(
            db.or_(NonReportingVehicle.dt_tracker.isnot(None), NonReportingVehicle.dt_server.isnot(None), NonReportingVehicle.last_reporting_time.isnot(None)),
            db.or_(NonReportingVehicle.dt_tracker.is_(None), NonReportingVehicle.dt_tracker < cutoff_24h),
            db.or_(NonReportingVehicle.dt_server.is_(None), NonReportingVehicle.dt_server < cutoff_24h),
            db.or_(NonReportingVehicle.last_reporting_time.is_(None), NonReportingVehicle.last_reporting_time < cutoff_24h),
            NonReportingVehicle.imei_no.isnot(None),
            NonReportingVehicle.imei_no != '',
            ~NonReportingVehicle.imei_no.ilike('%removed%')
        )

        for key, val in filters.items():
            if hasattr(NonReportingVehicle, key) and val:
                query = query.filter(getattr(NonReportingVehicle, key) == val)

        if search:
            query = query.filter(
                db.or_(
                    NonReportingVehicle.registration_no.ilike(f'%{search}%'),
                    NonReportingVehicle.customer_name.ilike(f'%{search}%'),
                    NonReportingVehicle.imei_no.ilike(f'%{search}%')
                )
            )

        return query

    def get_vehicles(self, filters: Optional[Dict[str, Any]] = None, page: int = 1,
                     per_page: int = 20, search: Optional[str] = None) -> Dict[str, Any]:
        """Get confirmed non-reporting vehicles (dt_tracker 24h+ stale).

        Only includes vehicles where:
        - dt_tracker IS NOT NULL (confirmed tracker signal exists)
        - dt_tracker is older than 24 hours (confirmed non-reporting)
        - IMEI is not 'Removed' or empty
        """
        # Auto-sync baseline data if database is empty
        if self.repository.count() == 0:
            try:
                self.sync_non_reporting_vehicles()
            except Exception as e:
                logger.warning(f"Auto-sync non-reporting failed: {e}")

        query = self._confirmed_query(filters, search)

        total = query.count()
        # Sort DESC so most-recently-offline (actionable) vehicles appear first
        items = query.order_by(NonReportingVehicle.dt_tracker.desc()).offset((page - 1) * per_page).limit(per_page).all()

        return {'items': items, 'total': total, 'page': page, 'per_page': per_page}

    def get_all_confirmed(self, filters: Optional[Dict[str, Any]] = None,
                          search: Optional[str] = None) -> List[NonReportingVehicle]:
        """Get every confirmed non-reporting vehicle matching the given
        filters/search, unpaginated. Aging-bucket filtering (24h / 25-36h /
        37-48h / 48+h) has to run against the full matching set - buckets
        aren't evenly distributed across pages, so filtering an
        already-paginated page can miss entire buckets."""
        return self._confirmed_query(filters, search).order_by(NonReportingVehicle.dt_tracker.desc()).all()

    
    def get_by_registration(self, registration_no: str) -> Optional[NonReportingVehicle]:
        """Get vehicle by registration number"""
        return self.repository.get_by(registration_no=registration_no)
    
    def get_pending(self) -> List[NonReportingVehicle]:
        """Get pending vehicles"""
        return self.repository.get_all(status='PENDING')
    
    def get_in_progress(self) -> List[NonReportingVehicle]:
        """Get in-progress vehicles"""
        return self.repository.get_all(status='IN_PROGRESS')
    
    def get_completed(self) -> List[NonReportingVehicle]:
        """Get completed vehicles"""
        return self.repository.get_all(status='COMPLETED')
    
    def create_vehicle(self, data: Dict[str, Any]) -> NonReportingVehicle:
        """Create a new non-reporting vehicle record"""
        data['status'] = 'PENDING'
        data['priority'] = data.get('priority', 'NORMAL')
        vehicle = self.repository.create(**data)
        logger.info(f"Non-reporting vehicle created: {vehicle.registration_no}")
        return vehicle
    
    def update_vehicle(self, vehicle_id: int, data: Dict[str, Any]) -> Optional[NonReportingVehicle]:
        """Update vehicle record"""
        return self.repository.update(vehicle_id, **data)
    
    def assign_technician(self, vehicle_id: int, technician_id: int) -> Optional[NonReportingVehicle]:
        """Assign technician to vehicle"""
        vehicle = self.repository.get_by_id(vehicle_id)
        if not vehicle:
            return None
        
        vehicle.assigned_to = technician_id
        vehicle.assigned_at = get_current_time()
        vehicle.status = 'IN_PROGRESS'
        db.session.commit()
        
        logger.info(f"Vehicle {vehicle.registration_no} assigned to technician {technician_id}")
        return vehicle
    
    def add_conversation(self, vehicle_id: int, conversation_type: str, direction: str,
                         contact_person: str, contact_number: str, summary: str,
                         action_taken: Optional[str] = None, follow_up_required: bool = False,
                         follow_up_date: Optional[date] = None, user_id: Optional[int] = None) -> NonReportingConversation:
        """Add a conversation record for a vehicle"""
        conversation = NonReportingConversation(
            vehicle_id=vehicle_id,
            conversation_type=conversation_type,
            direction=direction,
            contact_person=contact_person,
            contact_number=contact_number,
            summary=summary,
            action_taken=action_taken,
            follow_up_required=follow_up_required,
            follow_up_date=follow_up_date,
            recorded_by=user_id,
            conversation_date=get_current_time()
        )
        
        db.session.add(conversation)
        db.session.commit()
        
        logger.info(f"Conversation added for vehicle {vehicle_id}")
        return conversation
    
    def get_conversations(self, vehicle_id: int) -> List[NonReportingConversation]:
        """Get all conversations for a vehicle"""
        return self.conversation_repo.get_all(vehicle_id=vehicle_id)
    
    def get_dashboard_stats(self) -> Dict[str, Any]:
        """Get dashboard statistics for confirmed non-reporting vehicles (24h+ offline only)"""
        from datetime import timedelta
        cutoff_24h = get_current_time() - timedelta(hours=24)
        
        # Base query: only confirmed 24h+ non-reporting with valid IMEI
        base_q = NonReportingVehicle.query.filter(
            NonReportingVehicle.dt_tracker.isnot(None),
            NonReportingVehicle.dt_tracker < cutoff_24h,
            NonReportingVehicle.imei_no.isnot(None),
            NonReportingVehicle.imei_no != '',
            ~NonReportingVehicle.imei_no.ilike('%removed%')
        )
        
        total = base_q.count()
        pending = base_q.filter(NonReportingVehicle.status == 'PENDING').count()
        in_progress = base_q.filter(NonReportingVehicle.status == 'IN_PROGRESS').count()
        completed = base_q.filter(NonReportingVehicle.status == 'COMPLETED').count()
        escalated = base_q.filter(NonReportingVehicle.status == 'ESCALATED').count()
        
        return {
            'total': total,
            'pending': pending,
            'in_progress': in_progress,
            'completed': completed,
            'escalated': escalated,
        }
    
    def sync_non_reporting_vehicles(self) -> Dict[str, int]:
        """Sync non-reporting vehicles from external source"""
        from src.services.db_sync_service import DBSyncService
        sync_service = DBSyncService()
        return sync_service.sync_non_reporting_vehicles()