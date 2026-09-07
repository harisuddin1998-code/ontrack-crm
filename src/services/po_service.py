# src/services/po_service.py
"""
Purchase Order Service - Business logic for POs
"""
from typing import Optional, Dict, Any
from datetime import datetime, date, timedelta
from flask import current_app

from src.models.purchase_order import PurchaseOrder
from src.models.payment import PaymentRecovery
from src.models.security import SecurityBriefingData
from src.repositories.po_repository import POURepository
from src.services.base_service import BaseService
from src.services.notification_service import NotificationService
from src.services.email_service import EmailService
from src.extensions import db
from src.utils.helpers import generate_po_number
from src.utils.timezone import get_current_time, get_current_date
from src.utils.logging import get_logger

logger = get_logger(__name__)


class POService(BaseService[PurchaseOrder]):
    """Purchase Order Service"""
    
    def __init__(self):
        super().__init__(POURepository())
        self.po_repo = POURepository()
        self.notification_service = NotificationService()
        self.email_service = EmailService()
    
    def create_po(self, data: Dict[str, Any], user_id: int) -> PurchaseOrder:
        """
        Create a new purchase order - Sales creates PO, NO EMAIL SENT HERE
        """
        # Sanitize data
        data = self.sanitize_data(data)
        
        # Generate PO number
        data['po_number'] = generate_po_number()
        data['activity_type'] = 'INSTALLATION'
        data['status'] = 'PENDING'
        data['created_by'] = user_id
        
        # Validate required fields - vehicle_year/color, engine/chassis
        # numbers aren't collected at creation time; the installer fills
        # them in later when updating the PO.
        required = ['owner_name', 'owner_contact', 'reg_no', 'vehicle_make',
                   'vehicle_model', 'sales_person_id']
        
        missing = self.validate_data(data, required)
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")
        
        # Create PO
        po = self.po_repo.create(**data)
        
        # Create payment recovery
        self._create_payment_recovery(po)
        
        # Send SocketIO notification to installers (popup only, no email)
        try:
            self.notification_service.notify_installers_new_po(po)
            logger.info(f"🔔 Popup notification sent to installers for PO {po.po_number}")
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
        
        # Log activity
        self._log_activity(user_id, 'created_po', po.id, f"Created PO {po.po_number}")
        
        logger.info(f"📋 PO {po.po_number} created by user {user_id} - NO EMAIL SENT")
        return po
    
    def get_po(self, po_id: int) -> Optional[PurchaseOrder]:
        """Get PO by ID"""
        return self.po_repo.get_by_id(po_id)
    
    def get_po_by_number(self, po_number: str) -> Optional[PurchaseOrder]:
        """Get PO by PO number"""
        return self.po_repo.get_by_po_number(po_number)
    
    def get_pos(self, filters: Optional[Dict[str, Any]] = None, page: int = 1,
                per_page: int = 20, search: Optional[str] = None,
                order_by: Optional[str] = None, desc: bool = False) -> Dict[str, Any]:
        """Get POs with filters and pagination"""
        if filters is None:
            filters = {}

        # Handle search
        if search:
            results = self.po_repo.search(search)
            total = len(results)
            # Manual pagination for search results
            start = (page - 1) * per_page
            end = start + per_page
            items = results[start:end]
            return {'items': items, 'total': total, 'page': page, 'per_page': per_page}

        # Regular filtering
        items, total = self.po_repo.get_paginated(page, per_page, order_by=order_by, desc=desc, **filters)
        return {'items': items, 'total': total, 'page': page, 'per_page': per_page}
    
    def update_po(self, po_id: int, data: Dict[str, Any], user_id: int) -> Optional[PurchaseOrder]:
        """
        Update a purchase order - ONLY HERE DOES EMAIL GET SENT WHEN COMPLETED
        """
        po = self.po_repo.get_by_id(po_id)
        if not po:
            return None
        
        # Sanitize data
        data = self.sanitize_data(data)
        
        # Get old status
        old_status = po.status
        new_status = data.get('status', old_status)
        
        # Update PO
        data['updated_by'] = user_id
        updated_po = self.po_repo.update(po_id, **data)
        
        # ✅ ONLY WHEN INSTALLER MARKS AS COMPLETED - SEND EMAIL
        if old_status != 'COMPLETED' and new_status == 'COMPLETED':
            logger.info(f"📧 PO {po.po_number} marked as COMPLETED - SENDING EMAIL...")
            self._handle_completion(updated_po, user_id)
        
        # Handle cancellation
        if old_status != 'CANCELLED' and new_status == 'CANCELLED':
            self._handle_cancellation(updated_po, user_id)
        
        # Log activity
        self._log_activity(user_id, 'updated_po', po.id, f"Updated PO {po.po_number}")
        
        logger.info(f"📋 PO {po.po_number} updated by user {user_id}")
        return updated_po
    
    def complete_po(self, po_id: int, user_id: int) -> Optional[PurchaseOrder]:
        """Mark PO as completed - triggers email"""
        return self.update_po(po_id, {'status': 'COMPLETED'}, user_id)
    
    def cancel_po(self, po_id: int, user_id: int, reason: Optional[str] = None) -> Optional[PurchaseOrder]:
        """Cancel PO"""
        data = {'status': 'CANCELLED'}
        if reason:
            data['remarks'] = f"Cancelled: {reason}"
        return self.update_po(po_id, data, user_id)
    
    # What the installation team may write from the installation update
    # screen: what was fitted, by whom, where, and how far along it is.
    INSTALLATION_FIELDS = [
        'vehicle_make', 'vehicle_model', 'vehicle_year', 'vehicle_color',
        'transmission', 'power_cc',
        'engine_number', 'chassis_number', 'city',
        'scheduled_date', 'technician_assigned', 'imei_no', 'sim_no',
        'device_type', 'device_location', 'fuel', 'tested_by',
        'arranged_by_sales_person', 'vehicle_availability_location', 'remarks', 'status'
    ]

    # The order's own particulars - who it is for, which vehicle, what it is
    # worth. Writable from the same screen by the Administrator only: these
    # describe the order Sales raised, not the work the installer did.
    ORDER_FIELDS = [
        'owner_name', 'owner_contact', 'contact_person_driver', 'reg_no',
        'sales_person_id', 'existing_customer_name', 'existing_vehicle_number',
        'rates', 'amc'
    ]

    def update_installation_details(self, po_id: int, data: Dict[str, Any], user_id: int,
                                    include_order_fields: bool = False) -> Optional[PurchaseOrder]:
        """Update installation details.

        The whitelist is the point of this method: it is what stops the
        installation screen writing a field it was never meant to reach.
        `include_order_fields` widens it to the whole order and is passed
        only for an Administrator - the caller checks the role, this decides
        what that role may write.
        """
        allowed_fields = self.INSTALLATION_FIELDS + (
            self.ORDER_FIELDS if include_order_fields else [])

        filtered_data = {k: v for k, v in data.items() if k in allowed_fields}
        return self.update_po(po_id, filtered_data, user_id)
    
    def _handle_completion(self, po: PurchaseOrder, user_id: int) -> None:
        """Handle PO completion - ✅ SEND EMAIL HERE"""
        try:
            # 1. ✅ SEND COMPLETION EMAIL - ONLY HERE!
            self.email_service.send_completion_email(po)
            logger.info(f"✅ COMPLETION EMAIL SENT for PO {po.po_number}")

            # Record the exact moment the email went out - this is the
            # authoritative "installation date" used on documents like the
            # Tracker Certificate, immune to later unrelated edits to the PO.
            po.completion_email_sent_at = get_current_time()
            db.session.commit()

            # 2. Send SocketIO notification
            self.notification_service.notify_completion(po)
            
            # 3. Create security briefing
            self._create_security_briefing(po)
            
            # 4. Update payment recovery
            self._update_payment_recovery(po)

            # 5. AMC/monitoring charges don't stay a one-time line item here -
            # transfer them into Annual Recovery, which already re-matches
            # every vehicle against its installation-date anniversary every
            # year (Live AMC), so the AMC obligation loops annually instead
            # of being billed once and forgotten.
            self._transfer_amc_to_annual_recovery(po)

            logger.info(f"✅ PO {po.po_number} completion handled successfully")

        except Exception as e:
            logger.error(f"❌ Error handling PO completion {po.po_number}: {e}")
    
    def _handle_cancellation(self, po: PurchaseOrder, user_id: int) -> None:
        """Handle PO cancellation"""
        # Update payment recovery status
        payment = PaymentRecovery.query.filter_by(po_id=po.id).first()
        if payment:
            payment.payment_status = 'CANCELLED'
            db.session.commit()
        
        logger.info(f"PO {po.po_number} cancelled by user {user_id}")
    
    def _create_payment_recovery(self, po: PurchaseOrder) -> None:
        """Create payment recovery record"""
        total_amount = po.rates or 0
        due_date = po.scheduled_date or get_current_date()
        
        payment = PaymentRecovery(
            po_id=po.id,
            total_rates=po.rates or 0,
            total_amc=po.amc or 0,
            total_amount=total_amount,
            payment_status='PENDING',
            payment_due_date=due_date + timedelta(days=30),
            amount_received=0,
            remaining_amount=total_amount
        )
        db.session.add(payment)
        db.session.commit()
    
    def _create_security_briefing(self, po: PurchaseOrder) -> None:
        """Raise the security briefing for a completed installation.

        Only real columns are set. Registration, make/model, customer, the
        technician and so on are not stored on the briefing at all - they are
        read straight off the linked PO through SecurityBriefingData's
        BRIEFING_MAPPING, so there is one copy of each fact.

        This previously passed those mapped names as constructor arguments,
        which SQLAlchemy rejects outright. The TypeError was caught by
        _handle_completion's error handler, so every installation logged an
        error and silently created no briefing - the Security wallboard never
        populated itself.
        """
        # Check if briefing already exists
        if SecurityBriefingData.query.filter_by(po_id=po.id).first():
            return

        briefing = SecurityBriefingData(
            po_id=po.id,
            synced_from_po=True,
            status='PENDING'
        )
        db.session.add(briefing)
        db.session.commit()

        # The briefing is now on the Security wallboard. Tell the officer by
        # name, so the work and the notice about it arrive together instead
        # of the row sitting there unnoticed.
        try:
            self.notification_service.notify_security_briefing_created(briefing)
        except Exception as e:
            logger.error(f"Failed to notify security of new briefing: {e}")

        logger.info(f"Security briefing created for PO {po.po_number}")
    
    def _update_payment_recovery(self, po: PurchaseOrder) -> None:
        """Update payment recovery when PO is completed"""
        payment = PaymentRecovery.query.filter_by(po_id=po.id).first()
        if payment:
            # Update total amounts in case they changed
            payment.total_rates = po.rates or 0
            payment.total_amc = po.amc or 0
            payment.total_amount = (po.rates or 0) + (po.amc or 0)
            payment.remaining_amount = payment.total_amount - payment.amount_received
            
            # Update status if fully paid
            if payment.remaining_amount <= 0:
                payment.payment_status = 'PAID'
            
            db.session.commit()

    def _transfer_amc_to_annual_recovery(self, po: PurchaseOrder) -> None:
        """Hand the PO's AMC/monitoring charge off to Annual Recovery as a
        recurring obligation, rather than leaving it a one-time figure on
        the Installation Payment Recovery dashboard. Annual Recovery's Live
        AMC module re-matches every AnnualRecoveryVehicle against its
        installation-date day+month every year regardless of which year
        it's currently on, so creating this one record here is enough to
        put the vehicle into that annual loop for good. Idempotent - a
        vehicle already on record for this reg_no is never duplicated or
        overwritten (its own recovery history since transfer takes
        priority over the PO's original figure)."""
        if not po.amc or po.amc <= 0:
            return

        reg_no = (po.reg_no or '').strip().upper()
        if not reg_no:
            return

        from src.models.annual_recovery import AnnualRecoveryClient, AnnualRecoveryVehicle

        if AnnualRecoveryVehicle.query.filter_by(reg_no=reg_no).first():
            return

        install_dt = po.completion_email_sent_at or get_current_time()
        install_date = install_dt.date() if hasattr(install_dt, 'date') else install_dt

        client_name = (po.owner_name or '').strip().upper()
        client_cell = (po.owner_contact or '').strip()
        client = AnnualRecoveryClient.query.filter_by(name=client_name, cell1=client_cell).first()
        if not client:
            client = AnnualRecoveryClient(name=client_name, cell1=client_cell, employee_name='')
            db.session.add(client)
            db.session.flush()

        vehicle = AnnualRecoveryVehicle(
            client_id=client.id,
            reg_no=reg_no,
            installation_date=install_date.strftime('%Y-%m-%d'),
            installation_year=str(install_date.year),
            amc_charges=po.amc,
            recovered_amount=0.0,
            status='PENDING',
            remarks=f'Transferred from PO {po.po_number} on completion',
            sheet_name='Installation Transfer',
        )
        db.session.add(vehicle)
        client.total_amc_charges = (client.total_amc_charges or 0.0) + po.amc
        db.session.commit()

        logger.info(f"AMC/monitoring charge PKR {po.amc} for PO {po.po_number} transferred to "
                    f"Annual Recovery as vehicle {reg_no} (client #{client.id})")

    def _log_activity(self, user_id: int, action: str, po_id: int, details: str) -> None:
        """Log activity"""
        from src.models.activity import ActivityLog
        log = ActivityLog(
            user_id=user_id,
            action=action,
            po_id=po_id,
            details=details
        )
        db.session.add(log)
        db.session.commit()
    
    def get_dashboard_stats(self, user_id: Optional[int] = None) -> Dict[str, Any]:
        """Get dashboard statistics"""
        filters = {}
        if user_id:
            # Check if user is sales
            from src.models.user import User
            user = User.query.get(user_id)
            if user and user.is_sales():
                filters['sales_person_id'] = user_id
        
        stats = self.po_repo.get_dashboard_stats()
        stats['recent'] = self.po_repo.get_recent(10)
        
        if not user_id or (user_id and User.query.get(user_id).is_admin()):
            stats['by_sales_person'] = self.po_repo.count_by_sales_person()
            stats['by_city'] = self.po_repo.count_by_city()
        
        return stats

    def assign_technician(self, po_id: int, technician_name: str, user_id: int) -> Optional[PurchaseOrder]:
        """Assign technician to PO"""
        return self.update_po(po_id, {
            'technician_assigned': technician_name,
            'status': 'IN_PROGRESS'
        }, user_id)