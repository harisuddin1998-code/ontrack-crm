# src/services/redo_service.py
"""
REDO Activity Service - Business logic for REDO activities
"""
from typing import Optional, List, Dict, Any
from datetime import datetime

from src.models.redo import RedoActivity
from src.models.user import User
from src.repositories.base_repository import BaseRepository
from src.services.base_service import BaseService
from src.extensions import db
from src.utils.timezone import get_current_time, get_current_date
from src.utils.logging import get_logger

logger = get_logger(__name__)

DEVICE_RECOVERY_REASONS = ('Power Issue', 'Device Damage', 'Device Missing', 'Device Burnt', 'Water Damage')


class RedoService(BaseService[RedoActivity]):
    """Service for REDO activity operations"""
    
    def __init__(self):
        super().__init__(BaseRepository(RedoActivity))
    
    def get_redo_activities(self, filters: Optional[Dict[str, Any]] = None, page: int = 1,
                            per_page: int = 20, search: Optional[str] = None) -> Dict[str, Any]:
        """Get REDO activities with filters and pagination"""
        if filters is None:
            filters = {}
        
        # Handle search
        if search:
            query = self.repository.session.query(RedoActivity).filter(
                db.or_(
                    RedoActivity.registration_no.ilike(f'%{search}%'),
                    RedoActivity.customer_name.ilike(f'%{search}%')
                )
            )
            total = query.count()
            items = query.offset((page - 1) * per_page).limit(per_page).all()
            return {'items': items, 'total': total, 'page': page, 'per_page': per_page}
        
        # Regular filtering
        items, total = self.repository.get_paginated(page, per_page, **filters)
        return {'items': items, 'total': total, 'page': page, 'per_page': per_page}
    
    def get_by_technician(self, technician_id: int, active_only: bool = True, include_recovery: bool = False) -> List[RedoActivity]:
        """Get REDO activities assigned to a technician.
        
        Args:
            technician_id: The technician user ID
            active_only: If True, exclude COMPLETED and CANCELLED activities (wallboard view)
            include_recovery: If True, include device recovery charges
        """
        query = self.repository.session.query(RedoActivity).filter(
            RedoActivity.assigned_to == technician_id
        )
        if active_only:
            query = query.filter(
                RedoActivity.status.notin_(['COMPLETED', 'CANCELLED'])
            )
        if not include_recovery:
            query = query.filter(
                db.or_(
                    RedoActivity.device_change_reason.is_(None),
                    RedoActivity.device_change_reason.notin_(DEVICE_RECOVERY_REASONS)
                )
            )
        return query.order_by(RedoActivity.created_at.desc()).all()
    
    def get_active_activities(self, include_recovery: bool = False) -> List[RedoActivity]:
        """Get all active (non-completed, non-cancelled) REDO activities for wallboard"""
        query = self.repository.session.query(RedoActivity).filter(
            RedoActivity.status.notin_(['COMPLETED', 'CANCELLED'])
        )
        if not include_recovery:
            query = query.filter(
                db.or_(
                    RedoActivity.device_change_reason.is_(None),
                    RedoActivity.device_change_reason.notin_(DEVICE_RECOVERY_REASONS)
                )
            )
        return query.order_by(RedoActivity.created_at.desc()).all()

    def get_all(self, include_recovery: bool = False, **kwargs) -> List[RedoActivity]:
        """Get all REDO activities, excluding device recovery charges by default."""
        query = self.repository.session.query(RedoActivity)
        if not include_recovery:
            query = query.filter(
                db.or_(
                    RedoActivity.device_change_reason.is_(None),
                    RedoActivity.device_change_reason.notin_(DEVICE_RECOVERY_REASONS)
                )
            )
        if kwargs:
            query = self.repository._apply_filters(query, **kwargs)
        return query.order_by(RedoActivity.created_at.desc()).all()

    
    def get_pending(self) -> List[RedoActivity]:
        """Get pending REDO activities"""
        return self.repository.get_all(status='PENDING')
    
    def get_in_progress(self) -> List[RedoActivity]:
        """Get in-progress REDO activities"""
        return self.repository.get_all(status='IN_PROGRESS')
    
    def get_completed(self) -> List[RedoActivity]:
        """Get completed REDO activities"""
        return self.repository.get_all(status='COMPLETED')
    
    def create_redo(self, data: Dict[str, Any], user_id: int) -> RedoActivity:
        """Create a new REDO activity with auto-generated REDO number"""
        data['created_by'] = user_id
        data['status'] = 'PENDING'
        data['priority'] = data.get('priority', 'NORMAL')
        if 'redo_number' not in data or not data['redo_number']:
            data['redo_number'] = RedoActivity.generate_redo_number()
        
        redo = self.repository.create(**data)
        logger.info(f"REDO activity {redo.redo_number} created for {redo.registration_no} by user {user_id}")
        return redo

    def complete_redo(self, redo_id: int, user_id: int, notes: Optional[str] = None) -> Optional[RedoActivity]:
        """Complete a REDO activity and send notification email"""
        redo = self.repository.get_by_id(redo_id)
        if not redo:
            return None
        
        redo.status = 'COMPLETED'
        redo.resolution_status = 'Completed'
        redo.completed_by = user_id
        redo.completed_at = get_current_time()
        redo.rework_completed_date = get_current_date()
        if notes:
            redo.completion_notes = notes
        
        db.session.commit()
        logger.info(f"REDO {redo.redo_number or redo_id} completed by user {user_id}")

        # Send REDO Completion Email
        try:
            from src.services.email_service import EmailService
            email_service = EmailService()
            email_service.send_redo_completion_email(redo)
            logger.info(f"REDO completion email sent for {redo.redo_number or redo_id}")
        except Exception as e:
            logger.error(f"Failed to send REDO completion email: {e}")

        return redo
    
    def update_status(self, redo_id: int, status: str) -> Optional[RedoActivity]:
        """Update REDO status"""
        valid_statuses = ['PENDING', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED']
        if status not in valid_statuses:
            raise ValueError(f"Invalid status. Must be one of: {', '.join(valid_statuses)}")
        
        redo = self.repository.update(redo_id, status=status)
        if redo:
            logger.info(f"REDO {redo_id} status updated to {status}")
        return redo
    
    def assign_technician(self, redo_id: int, technician_id: int, assigned_by_id: int) -> Optional[RedoActivity]:
        """Assign a technician to REDO activity"""
        redo = self.repository.get_by_id(redo_id)
        if not redo:
            return None
        
        if redo.status == 'COMPLETED':
            raise ValueError("Cannot assign to completed REDO")
        
        redo.assigned_to = technician_id
        redo.assigned_by = assigned_by_id
        redo.assigned_at = get_current_time()
        redo.status = 'IN_PROGRESS'
        db.session.commit()
        
        logger.info(f"REDO {redo_id} assigned to technician {technician_id}")
        return redo
    
    def get_dashboard_stats(self, include_recovery: bool = False) -> Dict[str, Any]:
        """Get dashboard statistics excluding device recovery charges by default"""
        base_query = self.repository.session.query(RedoActivity)
        if not include_recovery:
            base_query = base_query.filter(
                db.or_(
                    RedoActivity.device_change_reason.is_(None),
                    RedoActivity.device_change_reason.notin_(DEVICE_RECOVERY_REASONS)
                )
            )

        total = base_query.count()
        pending = base_query.filter(RedoActivity.status == 'PENDING').count()
        in_progress = base_query.filter(RedoActivity.status == 'IN_PROGRESS').count()
        completed = base_query.filter(RedoActivity.status == 'COMPLETED').count()
        cancelled = base_query.filter(RedoActivity.status == 'CANCELLED').count()

        # REDOs scheduled (created) within the current calendar month
        now = get_current_time()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        this_month = base_query.filter(
            RedoActivity.created_at >= month_start
        ).count()

        # Automatic backend data-quality check (replaces the old manual
        # admin-click "Verify" workflow) - how many activities currently
        # fail validation and would be excluded from an MIS export if one
        # were generated right now.
        from src.services.data_validation_service import DataValidationService
        all_activities = base_query.all()
        _valid, invalid_activities = DataValidationService().split_redo_activities(all_activities)

        return {
            'total': total,
            'this_month': this_month,
            'pending': pending,
            'in_progress': in_progress,
            'completed': completed,
            'cancelled': cancelled,
            'data_issues': len(invalid_activities),
        }
    
    def get_recent(self, limit: int = 10) -> List[RedoActivity]:
        """Get recent REDO activities"""
        return self.repository.session.query(RedoActivity).order_by(
            RedoActivity.created_at.desc()
        ).limit(limit).all()
    
    def sync_redo_from_external_db(self) -> Dict[str, int]:
        """
        Sync REDO data from external SJ_MIS database
        Returns count of new and updated records
        """
        from src.services.db_sync_service import DBSyncService
        sync_service = DBSyncService()
        
        new_count = 0
        updated_count = 0
        page = 1
        rows_per_page = 100
        
        while True:
            # Fetch data from external DB
            external_data = sync_service.fetch_redo_data_from_sj_mis(page, rows_per_page)
            
            if not external_data:
                break
            
            for data in external_data:
                # Check if REDO activity already exists by IR_ID or registration_no
                existing = self.repository.session.query(RedoActivity).filter(
                    db.or_(
                        RedoActivity.registration_no == data.get('RegNo'),
                        RedoActivity.imei_no == data.get('IMEINo')
                    )
                ).first()
                
                if existing:
                    # Update existing record
                    existing.customer_name = data.get('EmergencyName') or existing.customer_name
                    existing.customer_contact = data.get('EmergencyMobile') or existing.customer_contact
                    existing.engine_no = data.get('EngineNum') or existing.engine_no
                    existing.chassis_no = data.get('ChassisNum') or existing.chassis_no
                    existing.sim_no = data.get('SIMNo') or existing.sim_no
                    existing.imei_no = data.get('IMEINo') or existing.imei_no
                    existing.device_location = data.get('UnitLocation') or existing.device_location
                    updated_count += 1
                else:
                    # Create new REDO activity
                    redo = RedoActivity(
                        registration_no=data.get('RegNo', 'N/A'),
                        customer_name=data.get('EmergencyName', 'N/A'),
                        customer_contact=data.get('EmergencyMobile', 'N/A'),
                        engine_no=data.get('EngineNum'),
                        chassis_no=data.get('ChassisNum'),
                        sim_no=data.get('SIMNo'),
                        imei_no=data.get('IMEINo'),
                        device_location=data.get('UnitLocation'),
                        status='PENDING',
                        priority='NORMAL'
                    )
                    self.repository.session.add(redo)
                    new_count += 1
            
            self.repository.session.commit()
            
            # If we got less than rows_per_page, we've reached the end
            if len(external_data) < rows_per_page:
                break
            
            page += 1
        
        logger.info(f"REDO sync complete - New: {new_count}, Updated: {updated_count}")
        return {'new': new_count, 'updated': updated_count}
    
    def get_external_redo_data(self, page: int = 1, per_page: int = 20) -> Dict[str, Any]:
        """
        Get REDO data directly from external database (for display purposes)
        Returns formatted data with aging calculations
        """
        from src.services.db_sync_service import DBSyncService
        sync_service = DBSyncService()
        
        # Fetch data from external DB
        external_data = sync_service.fetch_redo_data_from_sj_mis(page, per_page)
        total_count = sync_service.get_total_redo_count()
        
        # Calculate aging for each record
        now = datetime.now()
        formatted_data = []
        
        for data in external_data:
            # Calculate age based on dt_tracker or dt_server
            dt_tracker = data.get('dt_tracker')
            dt_server = data.get('dt_server')
            
            age_hours = None
            sla_exceeded = False
            
            if dt_tracker:
                age_hours = (now - dt_tracker).total_seconds() / 3600.0
            elif dt_server:
                age_hours = (now - dt_server).total_seconds() / 3600.0
            
            if age_hours:
                sla_exceeded = age_hours > 24.0
            
            formatted_data.append({
                'ir_id': data.get('IR_ID'),
                'registration_no': data.get('RegNo'),
                'engine_no': data.get('EngineNum'),
                'chassis_no': data.get('ChassisNum'),
                'sim_no': data.get('SIMNo'),
                'imei_no': data.get('IMEINo'),
                'device_location': data.get('UnitLocation'),
                'customer_name': data.get('EmergencyName'),
                'customer_contact': data.get('EmergencyMobile'),
                'emergency_phone': data.get('EmergencyPhone'),
                'emergency_relation': data.get('EmergencyRelation'),
                'res_phone': data.get('ResPhone'),
                'office_phone': data.get('OfficePhone'),
                'secondary_users': [
                    data.get('SecondaryUser1'),
                    data.get('SecondaryUser2'),
                    data.get('SecondaryUser3'),
                    data.get('SecondaryUser4')
                ],
                'dt_tracker': dt_tracker,
                'dt_server': dt_server,
                'lat': data.get('lat'),
                'lng': data.get('lng'),
                'speed': data.get('speed'),
                'age_hours': round(age_hours, 1) if age_hours else None,
                'sla_exceeded': sla_exceeded,
                'source': 'external_db'
            })
        
        return {
            'items': formatted_data,
            'total': total_count,
            'page': page,
            'per_page': per_page
        }
