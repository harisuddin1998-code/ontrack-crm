# src/services/payment_service.py
"""
Payment Recovery Service - Business logic for payment recovery
"""
from typing import Optional, List, Dict, Any
from datetime import date, datetime, timedelta

from src.models.payment import PaymentRecovery, PaymentHistory
from src.repositories.po_repository import POURepository
from src.repositories.base_repository import BaseRepository
from src.services.base_service import BaseService
from src.services.notification_service import NotificationService
from src.extensions import db
from src.utils.timezone import get_current_date, get_current_time
from src.utils.logging import get_logger

logger = get_logger(__name__)


class PaymentRecoveryService(BaseService[PaymentRecovery]):
    """Service for payment recovery operations"""
    
    def __init__(self):
        super().__init__(BaseRepository(PaymentRecovery))
        self.po_repo = POURepository()
        self.notification_service = NotificationService()
    
    def count(self, payment_status: Optional[str] = None) -> int:
        """Count payment recoveries with optional status filter"""
        try:
            query = PaymentRecovery.query
            if payment_status:
                query = query.filter_by(payment_status=payment_status)
            return query.count()
        except Exception as e:
            logger.error(f"Error counting payment recoveries: {e}")
            return 0
    
    def get_dashboard_stats(self) -> Dict[str, Any]:
        """Get dashboard statistics"""
        try:
            total = self.count()
            pending = self.count(payment_status='PENDING')
            partial = self.count(payment_status='PARTIAL')
            paid = self.count(payment_status='PAID')
            overdue = self.count(payment_status='OVERDUE')
            
            # Calculate total pending amount
            all_payments = self.repository.get_all()
            total_amount_pending = sum(
                p.remaining_amount for p in all_payments
                if p.payment_status in ['PENDING', 'PARTIAL', 'OVERDUE']
            )

            # Installation charges (total_rates) and AMC/monitoring charges
            # (total_amc) are billed together per-PO but are two different
            # job functions' money - kept as separate totals here rather
            # than blended into one figure, same as the list view below.
            total_installation_billed = sum(p.total_rates or 0.0 for p in all_payments)
            total_amc_billed = sum(p.total_amc or 0.0 for p in all_payments)

            return {
                'total': total,
                'pending': pending,
                'partial': partial,
                'paid': paid,
                'overdue': overdue,
                'total_amount_pending': total_amount_pending,
                'pending_count': pending,
                'total_installation_billed': total_installation_billed,
                'total_amc_billed': total_amc_billed,
            }
        except Exception as e:
            logger.error(f"Error getting payment stats: {e}")
            return {
                'total': 0,
                'pending': 0,
                'partial': 0,
                'paid': 0,
                'overdue': 0,
                'total_amount_pending': 0,
                'pending_count': 0,
                'total_installation_billed': 0,
                'total_amc_billed': 0,
            }
    
    def get_payments(self, filters: Optional[Dict[str, Any]] = None, page: int = 1,
                     per_page: int = 20, search: Optional[str] = None) -> Dict[str, Any]:
        """Get payments with filters and pagination"""
        if filters is None:
            filters = {}
        
        if search:
            query = PaymentRecovery.query.join(
                PaymentRecovery.purchase_order
            ).filter(
                db.or_(
                    PaymentRecovery.purchase_order.has(po_number=search),
                    PaymentRecovery.purchase_order.has(owner_name=search)
                )
            )
            total = query.count()
            items = query.offset((page - 1) * per_page).limit(per_page).all()
            return {'items': items, 'total': total, 'page': page, 'per_page': per_page}
        
        items, total = self.repository.get_paginated(page, per_page, **filters)
        return {'items': items, 'total': total, 'page': page, 'per_page': per_page}
    
    def get_by_po(self, po_id: int) -> Optional[PaymentRecovery]:
        """Get payment recovery by PO ID"""
        return self.repository.get_by(po_id=po_id)
    
    def add_payment(self, payment_id: int, amount: float, user_id: int,
                    notes: Optional[str] = None, payment_method: Optional[str] = None,
                    proof_of_payment_path: Optional[str] = None,
                    reference: Optional[str] = None) -> Optional[PaymentRecovery]:
        """Add a payment to a recovery record"""
        payment = self.repository.get_by_id(payment_id)
        if not payment:
            return None

        if amount <= 0:
            raise ValueError("Amount must be greater than 0")

        payment.amount_received += amount
        payment.remaining_amount = payment.total_amount - payment.amount_received
        payment.payment_received_date = get_current_date()
        payment.payment_received_by = user_id
        if payment_method:
            payment.payment_method = payment_method
        if proof_of_payment_path:
            payment.proof_of_payment_path = proof_of_payment_path
        if reference:
            if payment_method == 'CHEQUE':
                payment.cheque_number = reference
            else:
                payment.transaction_id = reference

        if payment.remaining_amount <= 0:
            payment.payment_status = 'PAID'
        else:
            payment.payment_status = 'PARTIAL'

        history = PaymentHistory(
            payment_recovery_id=payment.id,
            action='PAYMENT_RECEIVED',
            user_id=user_id,
            amount=amount,
            details=notes or f"Payment of PKR {amount:,.2f} received"
        )
        db.session.add(history)
        db.session.commit()
        
        self.notification_service.notify_payment_received(payment, amount)
        
        logger.info(f"Payment of PKR {amount:,.2f} added to payment {payment_id}")
        return payment
    
    def update_status(self, payment_id: int, status: str) -> Optional[PaymentRecovery]:
        """Update payment status"""
        valid_statuses = ['PENDING', 'PARTIAL', 'PAID', 'OVERDUE']
        if status not in valid_statuses:
            raise ValueError(f"Invalid status. Must be one of: {', '.join(valid_statuses)}")
        
        payment = self.repository.update(payment_id, payment_status=status)
        if payment:
            logger.info(f"Payment {payment_id} status updated to {status}")
        return payment
    
    def schedule_follow_up(self, payment_id: int, follow_up_date: date) -> Optional[PaymentRecovery]:
        """Schedule a follow-up"""
        payment = self.repository.update(
            payment_id,
            next_follow_up=follow_up_date,
            last_follow_up=get_current_date()
        )
        if payment:
            logger.info(f"Follow-up scheduled for payment {payment_id} on {follow_up_date}")
        return payment
    
    def get_payment_history(self, payment_id: int) -> List[PaymentHistory]:
        """Get payment history for a recovery record"""
        return PaymentHistory.query.filter_by(
            payment_recovery_id=payment_id
        ).order_by(PaymentHistory.created_at.desc()).all()
    
    def get_recent(self, limit: int = 10) -> List[PaymentRecovery]:
        """Get recent payment records"""
        return PaymentRecovery.query.order_by(
            PaymentRecovery.created_at.desc()
        ).limit(limit).all()
    
    def update_overdue_status(self) -> int:
        """Update overdue status for payments"""
        today = get_current_date()
        payments = self.repository.get_all(
            payment_status=['PENDING', 'PARTIAL']
        )
        
        updated_count = 0
        for payment in payments:
            if payment.payment_due_date and payment.payment_due_date < today:
                payment.payment_status = 'OVERDUE'
                updated_count += 1
        
        if updated_count > 0:
            db.session.commit()
            logger.info(f"Updated {updated_count} payments to OVERDUE")
        
        return updated_count
    
    def create_from_po(self, po) -> PaymentRecovery:
        """Create payment recovery from PO"""
        total_amount = po.rates or 0
        due_date = po.scheduled_date or get_current_date()
        due_date = due_date + timedelta(days=30)
        
        existing = self.get_by_po(po.id)
        if existing:
            return existing
        
        payment = PaymentRecovery(
            po_id=po.id,
            total_rates=po.rates or 0,
            total_amc=po.amc or 0,
            total_amount=total_amount,
            payment_status='PENDING',
            payment_due_date=due_date,
            amount_received=0,
            remaining_amount=total_amount
        )
        db.session.add(payment)
        db.session.commit()
        
        logger.info(f"Payment recovery created for PO {po.po_number}")
        return payment