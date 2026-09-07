# src/services/removal_service.py
"""
Removal Service - Business logic for removal and transfer activities
"""
from typing import Optional, List, Dict, Any
from datetime import datetime

from src.models.removal import RemovalTransferActivity, RemovalRetainedActivity, VehicleFlag
from src.repositories.base_repository import BaseRepository
from src.services.base_service import BaseService
from src.extensions import db
from src.utils.timezone import get_current_time
from src.utils.logging import get_logger

logger = get_logger(__name__)

# How a removal raised by AMC recovery starts its remarks. Matched on to keep
# `flag_amc_lost_vehicle` idempotent, so it is a constant rather than a phrase
# written out twice - a reworded copy would silently start duplicating flags.
AMC_LOST_REASON_PREFIX = 'AMC recovery marked this vehicle LOST'


def _amc_lost_reason(vehicle: Any, client: Any) -> str:
    """The remarks a removal raised from AMC recovery carries.

    Everything the technician and the removal desk need without opening the
    recovery module: who the vehicle belongs to, which sheet wrote it off,
    how much was given up on, and whatever the recovery officer had already
    noted against it.
    """
    parts = [f'{AMC_LOST_REASON_PREFIX} - device to be recovered.']

    client_name = (getattr(client, 'name', '') or '').strip()
    if client_name:
        parts.append(f'Client: {client_name}.')

    sheet = (getattr(vehicle, 'sheet_name', '') or '').strip()
    if sheet:
        parts.append(f'Sheet: {sheet}.')

    charges = getattr(vehicle, 'amc_charges', 0) or 0
    recovered = getattr(vehicle, 'recovered_amount', 0) or 0
    if charges:
        parts.append(f'AMC billed PKR {charges:,.2f}, recovered PKR {recovered:,.2f}, '
                     f'written off PKR {charges - recovered:,.2f}.')

    notes = (getattr(vehicle, 'remarks', '') or '').strip()
    if notes:
        parts.append(f'Recovery remarks: {notes}')

    return ' '.join(parts)


class RemovalService:
    """Service for removal and transfer operations"""
    
    def __init__(self):
        self.transfer_repo = BaseRepository(RemovalTransferActivity)
        self.retained_repo = BaseRepository(RemovalRetainedActivity)
        self.flag_repo = BaseRepository(VehicleFlag)
    
    # ---------- Flag Operations ----------
    
    def flag_vehicle(self, data: Dict[str, Any], user_id: int) -> VehicleFlag:
        """Flag a vehicle for removal/retention/transfer"""
        data['flagged_by'] = user_id
        data['status'] = 'PENDING'
        data['flagged_at'] = get_current_time()
        
        # Check if vehicle already flagged
        existing = self.flag_repo.get_by(registration_no=data['registration_no'], status='PENDING')
        if existing:
            raise ValueError(f"Vehicle {data['registration_no']} is already flagged for removal")
        
        flag = self.flag_repo.create(**data)
        logger.info(f"Vehicle {flag.registration_no} flagged for {flag.flag_type} by user {user_id}")
        return flag

    def flag_amc_lost_vehicle(self, vehicle: Any,
                              user_id: Optional[int] = None) -> Optional[VehicleFlag]:
        """Put a vehicle AMC recovery has written off onto the Removal board.

        Marking a vehicle LOST in AMC recovery is a decision to stop chasing
        the money, and the next thing that has to happen is that the device
        comes back. Until now the two were unconnected: the vehicle went
        quiet in one module and nobody in Removal was told, so the hardware
        stayed in a vehicle nobody was billing for.

        The flag carries why it was raised - the client, the sheet, the money
        written off and whatever the recovery officer had noted - because a
        removal job with no explanation is one the technician has to go and
        ask about.

        Idempotent: a vehicle already carrying an AMC-lost flag is left
        alone, whatever state that flag is in. Re-raising it would put a job
        back on the board that somebody has already been out and done.
        """
        registration = (getattr(vehicle, 'reg_no', '') or '').strip().upper()
        if not registration:
            logger.warning(f"AMC vehicle #{getattr(vehicle, 'id', '?')} has no registration - "
                           "cannot raise a removal flag for it")
            return None

        existing = VehicleFlag.query.filter(
            VehicleFlag.registration_no == registration,
            VehicleFlag.flag_reason.like(f'{AMC_LOST_REASON_PREFIX}%')).first()
        if existing:
            return None

        client = getattr(vehicle, 'client', None)

        return self.flag_vehicle({
            'registration_no': registration,
            'customer_name': (getattr(client, 'name', '') or '').strip().upper() or None,
            'customer_contact': (getattr(client, 'cell1', '') or '').strip() or None,
            'flag_type': 'REMOVAL',
            'priority': 'HIGH',
            'flag_reason': _amc_lost_reason(vehicle, client),
        }, user_id)

    def get_flagged_vehicles(self, filters: Optional[Dict[str, Any]] = None, page: int = 1,
                             per_page: int = 20, search: Optional[str] = None) -> Dict[str, Any]:
        """Get flagged vehicles with filters and pagination"""
        if filters is None:
            filters = {}
        
        # Build the base query
        query = self.flag_repo.session.query(VehicleFlag)
        
        # Handle search
        if search:
            query = query.filter(
                db.or_(
                    VehicleFlag.registration_no.ilike(f'%{search}%'),
                    VehicleFlag.customer_name.ilike(f'%{search}%')
                )
            )
        
        # Handle status filter - support both single status and list of statuses
        if 'status' in filters:
            status_value = filters['status']
            if isinstance(status_value, list):
                # If it's a list, use IN clause
                query = query.filter(VehicleFlag.status.in_(status_value))
            else:
                # If it's a single value, use equals
                query = query.filter(VehicleFlag.status == status_value)
            # Remove status from filters so it doesn't get processed again
            filters.pop('status', None)
        
        # Handle flag_type filter
        if 'flag_type' in filters:
            query = query.filter(VehicleFlag.flag_type == filters['flag_type'])
            filters.pop('flag_type', None)
        
        # Handle any other filters
        for key, value in filters.items():
            if value is not None and key not in ['status', 'flag_type']:
                query = query.filter(getattr(VehicleFlag, key) == value)
        
        # Order by priority (descending - URGENT first)
        query = query.order_by(
            db.case(
                (VehicleFlag.priority == 'URGENT', 1),
                (VehicleFlag.priority == 'HIGH', 2),
                (VehicleFlag.priority == 'NORMAL', 3),
                (VehicleFlag.priority == 'LOW', 4),
                else_=5
            ).asc()
        )
        
        # Get total count before pagination
        total = query.count()
        
        # Apply pagination
        items = query.offset((page - 1) * per_page).limit(per_page).all()
        
        return {'items': items, 'total': total, 'page': page, 'per_page': per_page}
    
    def get_flag(self, flag_id: int) -> Optional[VehicleFlag]:
        """Get flag by ID"""
        return self.flag_repo.get_by_id(flag_id)
    
    def update_flag_status(self, flag_id: int, status: str) -> Optional[VehicleFlag]:
        """Update flag status"""
        return self.flag_repo.update(flag_id, status=status)
    
    def assign_flag(self, flag_id: int, technician_id: int) -> Optional[VehicleFlag]:
        """Put a flagged vehicle on a technician from Technician Management."""
        flag = self.flag_repo.get_by_id(flag_id)
        if not flag:
            return None
        
        flag.technician_id = technician_id
        flag.assigned_at = get_current_time()
        flag.status = 'IN_PROGRESS'
        db.session.commit()
        
        logger.info(f"Flag {flag_id} assigned to technician {technician_id}")
        return flag
    
    def complete_flag(self, flag_id: int, user_id: int, notes: Optional[str] = None) -> Optional[VehicleFlag]:
        """Complete a flagged vehicle"""
        flag = self.flag_repo.get_by_id(flag_id)
        if not flag:
            return None
        
        flag.status = 'COMPLETED'
        flag.completed_at = get_current_time()
        if notes:
            flag.completion_notes = notes
        db.session.commit()
        
        logger.info(f"Flag {flag_id} completed by user {user_id}")
        return flag
    
    def get_flagged_dashboard_stats(self) -> Dict[str, Any]:
        """Get flagged vehicles statistics"""
        total = self.flag_repo.count()
        pending = self.flag_repo.count(status='PENDING')
        in_progress = self.flag_repo.count(status='IN_PROGRESS')
        completed = self.flag_repo.count(status='COMPLETED')
        
        return {
            'total': total,
            'pending': pending,
            'in_progress': in_progress,
            'completed': completed,
        }
    
    # ---------- Transfer Activities ----------
    
    def get_transfers(self, filters: Optional[Dict[str, Any]] = None, page: int = 1,
                      per_page: int = 20, search: Optional[str] = None) -> Dict[str, Any]:
        """Get transfer activities with filters and pagination"""
        if filters is None:
            filters = {}
        
        if search:
            query = self.transfer_repo.session.query(RemovalTransferActivity).filter(
                db.or_(
                    RemovalTransferActivity.old_registration_no.ilike(f'%{search}%'),
                    RemovalTransferActivity.new_registration_no.ilike(f'%{search}%'),
                    RemovalTransferActivity.old_customer_name.ilike(f'%{search}%')
                )
            )
            total = query.count()
            items = query.offset((page - 1) * per_page).limit(per_page).all()
            return {'items': items, 'total': total, 'page': page, 'per_page': per_page}
        
        items, total = self.transfer_repo.get_paginated(page, per_page, **filters)
        return {'items': items, 'total': total, 'page': page, 'per_page': per_page}
    
    def get_transfer(self, transfer_id: int) -> Optional[RemovalTransferActivity]:
        """Get transfer by ID"""
        return self.transfer_repo.get_by_id(transfer_id)
    
    def create_transfer(self, data: Dict[str, Any], user_id: int) -> RemovalTransferActivity:
        """Create a new transfer activity"""
        data['status'] = 'PENDING'
        data['assigned_by'] = user_id
        transfer = self.transfer_repo.create(**data)
        logger.info(f"Transfer created from {transfer.old_registration_no} to {transfer.new_registration_no}")
        return transfer
    
    def assign_transfer(self, transfer_id: int, technician_id: int, assigned_by_id: int) -> Optional[RemovalTransferActivity]:
        """Assign a technician to transfer"""
        transfer = self.transfer_repo.get_by_id(transfer_id)
        if not transfer:
            return None
        
        transfer.technician_id = technician_id
        transfer.assigned_by = assigned_by_id
        transfer.assigned_at = get_current_time()
        transfer.status = 'IN_PROGRESS'
        db.session.commit()
        
        logger.info(f"Transfer {transfer_id} assigned to technician {technician_id}")
        return transfer
    
    def update_transfer_status(self, transfer_id: int, status: str) -> Optional[RemovalTransferActivity]:
        """Update transfer status"""
        return self.transfer_repo.update(transfer_id, status=status)
    
    def complete_transfer(self, transfer_id: int, user_id: int, notes: Optional[str] = None) -> Optional[RemovalTransferActivity]:
        """Complete a transfer"""
        transfer = self.transfer_repo.get_by_id(transfer_id)
        if not transfer:
            return None
        
        transfer.status = 'COMPLETED'
        transfer.completed_by = user_id
        transfer.completed_at = get_current_time()
        if notes:
            transfer.completion_notes = notes
        db.session.commit()
        
        logger.info(f"Transfer {transfer_id} completed")
        return transfer
    
    # ---------- Retained Activities ----------
    
    def get_retained(self, filters: Optional[Dict[str, Any]] = None, page: int = 1,
                     per_page: int = 20, search: Optional[str] = None) -> Dict[str, Any]:
        """Get retained activities with filters and pagination"""
        if filters is None:
            filters = {}
        
        if search:
            query = self.retained_repo.session.query(RemovalRetainedActivity).filter(
                db.or_(
                    RemovalRetainedActivity.registration_no.ilike(f'%{search}%'),
                    RemovalRetainedActivity.customer_name.ilike(f'%{search}%')
                )
            )
            total = query.count()
            items = query.offset((page - 1) * per_page).limit(per_page).all()
            return {'items': items, 'total': total, 'page': page, 'per_page': per_page}
        
        items, total = self.retained_repo.get_paginated(page, per_page, **filters)
        return {'items': items, 'total': total, 'page': page, 'per_page': per_page}
    
    def get_retained_by_id(self, retained_id: int) -> Optional[RemovalRetainedActivity]:
        """Get retained by ID"""
        return self.retained_repo.get_by_id(retained_id)
    
    def create_retained(self, data: Dict[str, Any], user_id: int) -> RemovalRetainedActivity:
        """Create a new retained activity"""
        data['status'] = 'PENDING'
        data['assigned_by'] = user_id
        data['removal_type'] = data.get('removal_type', 'RETAINED')
        retained = self.retained_repo.create(**data)
        logger.info(f"Retained activity created for {retained.registration_no}")
        return retained
    
    def assign_retained(self, retained_id: int, technician_id: int, assigned_by_id: int) -> Optional[RemovalRetainedActivity]:
        """Assign a technician to retained activity"""
        retained = self.retained_repo.get_by_id(retained_id)
        if not retained:
            return None
        
        retained.technician_id = technician_id
        retained.assigned_by = assigned_by_id
        retained.assigned_at = get_current_time()
        retained.status = 'IN_PROGRESS'
        db.session.commit()
        
        logger.info(f"Retained {retained_id} assigned to technician {technician_id}")
        return retained
    
    def update_retained_status(self, retained_id: int, status: str) -> Optional[RemovalRetainedActivity]:
        """Update retained status"""
        return self.retained_repo.update(retained_id, status=status)
    
    def complete_retained(self, retained_id: int, user_id: int, notes: Optional[str] = None) -> Optional[RemovalRetainedActivity]:
        """Complete a retained activity"""
        retained = self.retained_repo.get_by_id(retained_id)
        if not retained:
            return None
        
        retained.status = 'COMPLETED'
        retained.completed_by = user_id
        retained.completed_at = get_current_time()
        if notes:
            retained.completion_notes = notes
        db.session.commit()
        
        logger.info(f"Retained {retained_id} completed")
        return retained
    
    def get_dashboard_stats(self) -> Dict[str, Any]:
        """Get dashboard statistics"""
        # Transfer stats
        transfer_total = self.transfer_repo.count()
        transfer_pending = self.transfer_repo.count(status='PENDING')
        transfer_in_progress = self.transfer_repo.count(status='IN_PROGRESS')
        transfer_completed = self.transfer_repo.count(status='COMPLETED')
        
        # Retained stats
        retained_total = self.retained_repo.count()
        retained_pending = self.retained_repo.count(status='PENDING')
        retained_in_progress = self.retained_repo.count(status='IN_PROGRESS')
        retained_completed = self.retained_repo.count(status='COMPLETED')
        
        # Flag stats
        flag_stats = self.get_flagged_dashboard_stats()
        
        return {
            'transfer': {
                'total': transfer_total,
                'pending': transfer_pending,
                'in_progress': transfer_in_progress,
                'completed': transfer_completed,
            },
            'retained': {
                'total': retained_total,
                'pending': retained_pending,
                'in_progress': retained_in_progress,
                'completed': retained_completed,
            },
            'flags': flag_stats
        }
    
    def get_returned_count(self) -> int:
        """Get count of returned devices"""
        return self.retained_repo.count(device_returned=True)