# src/models/payment.py
"""
Payment Recovery Models
"""
from typing import Dict, Any, Optional
from datetime import date

from src.extensions import db
from src.models.base import BaseModel


class PaymentRecovery(BaseModel):
    """Payment recovery tracking for POs"""
    __tablename__ = 'payment_recovery'
    
    po_id = db.Column(db.Integer, db.ForeignKey('purchase_orders.id'), 
                     unique=True, nullable=False)
    
    # Financials
    total_rates = db.Column(db.Float, default=0.0)
    total_amc = db.Column(db.Float, default=0.0)
    total_amount = db.Column(db.Float, default=0.0)
    amount_received = db.Column(db.Float, default=0.0)
    remaining_amount = db.Column(db.Float, default=0.0)
    
    # Payment Status
    payment_status = db.Column(db.String(20), default='PENDING')
    payment_due_date = db.Column(db.Date)
    payment_received_date = db.Column(db.Date)
    payment_received_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    # Payment Details
    payment_method = db.Column(db.String(20))  # ONLINE / CASH / CHEQUE
    proof_of_payment_path = db.Column(db.String(255))
    cheque_number = db.Column(db.String(50))
    bank_name = db.Column(db.String(100))
    transaction_id = db.Column(db.String(100))
    recovery_notes = db.Column(db.Text)
    
    # Follow-up
    last_follow_up = db.Column(db.Date)
    next_follow_up = db.Column(db.Date)
    
    # Relationships
    purchase_order = db.relationship('PurchaseOrder', backref='payment_recovery_ref', 
                                     foreign_keys=[po_id])
    payment_received_by_user = db.relationship('User', backref='payment_recoveries_ref',
                                               foreign_keys=[payment_received_by])
    payment_history = db.relationship('PaymentHistory', backref='payment_recovery_ref',
                                      lazy='dynamic')
    
    # Status constants
    STATUS_PENDING = 'PENDING'
    STATUS_PARTIAL = 'PARTIAL'
    STATUS_PAID = 'PAID'
    STATUS_OVERDUE = 'OVERDUE'
    
    def is_paid(self) -> bool:
        """Check if payment is fully paid"""
        return self.payment_status == self.STATUS_PAID
    
    def is_overdue(self) -> bool:
        """Check if payment is overdue"""
        if self.payment_status in [self.STATUS_PAID, self.STATUS_OVERDUE]:
            return self.payment_status == self.STATUS_OVERDUE
        
        if self.payment_due_date and self.payment_due_date < date.today():
            return True
        return False
    
    def is_pending(self) -> bool:
        """Check if payment is pending"""
        return self.payment_status == self.STATUS_PENDING
    
    def get_payment_percentage(self) -> float:
        """Get percentage of amount received"""
        if self.total_amount == 0:
            return 0.0
        return round((self.amount_received / self.total_amount) * 100, 2)
    
    def update_status(self) -> None:
        """Update payment status based on amounts"""
        if self.remaining_amount <= 0:
            self.payment_status = self.STATUS_PAID
        elif self.amount_received > 0:
            self.payment_status = self.STATUS_PARTIAL
        elif self.is_overdue():
            self.payment_status = self.STATUS_OVERDUE
        else:
            self.payment_status = self.STATUS_PENDING
    
    def add_payment(self, amount: float, user_id: int, notes: Optional[str] = None,
                    payment_method: Optional[str] = None, proof_of_payment_path: Optional[str] = None,
                    reference: Optional[str] = None) -> None:
        """Add a payment and update status. payment_method/proof_of_payment_path
        were previously collected on the form but never reached this method -
        they're persisted here now so the recorded method isn't silently lost."""
        self.amount_received += amount
        self.remaining_amount = self.total_amount - self.amount_received
        self.payment_received_date = date.today()
        self.payment_received_by = user_id
        if payment_method:
            self.payment_method = payment_method
        if proof_of_payment_path:
            self.proof_of_payment_path = proof_of_payment_path
        if reference:
            if payment_method == 'CHEQUE':
                self.cheque_number = reference
            else:
                self.transaction_id = reference

        # Update status
        if self.remaining_amount <= 0:
            self.payment_status = self.STATUS_PAID
        else:
            self.payment_status = self.STATUS_PARTIAL

        # Add history
        history = PaymentHistory(
            payment_recovery_id=self.id,
            action='PAYMENT_RECEIVED',
            user_id=user_id,
            amount=amount,
            details=notes
        )
        db.session.add(history)
        db.session.commit()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'po_id': self.po_id,
            'po_number': self.purchase_order.po_number if self.purchase_order else None,
            'total_rates': self.total_rates,
            'total_amc': self.total_amc,
            'total_amount': self.total_amount,
            'amount_received': self.amount_received,
            'remaining_amount': self.remaining_amount,
            'payment_percentage': self.get_payment_percentage(),
            'payment_status': self.payment_status,
            'payment_due_date': self.payment_due_date.isoformat() if self.payment_due_date else None,
            'payment_received_date': self.payment_received_date.isoformat() if self.payment_received_date else None,
            'payment_received_by': self.payment_received_by,
            'payment_method': self.payment_method,
            'proof_of_payment_path': self.proof_of_payment_path,
            'cheque_number': self.cheque_number,
            'bank_name': self.bank_name,
            'transaction_id': self.transaction_id,
            'recovery_notes': self.recovery_notes,
            'last_follow_up': self.last_follow_up.isoformat() if self.last_follow_up else None,
            'next_follow_up': self.next_follow_up.isoformat() if self.next_follow_up else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
    
    def __repr__(self) -> str:
        return f"<PaymentRecovery {self.id} - PO {self.po_id} - {self.payment_status}>"


class PaymentHistory(BaseModel):
    """Payment history tracking"""
    __tablename__ = 'payment_history'
    
    payment_recovery_id = db.Column(db.Integer, db.ForeignKey('payment_recovery.id'))
    action = db.Column(db.String(50))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    user_name = db.Column(db.String(100))
    details = db.Column(db.Text)
    amount = db.Column(db.Float, default=0.0)
    
    # Relationships
    payment_recovery = db.relationship('PaymentRecovery', backref='payment_history_ref',
                                        foreign_keys=[payment_recovery_id])
    user = db.relationship('User', backref='payment_history_ref',
                          foreign_keys=[user_id])
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'payment_recovery_id': self.payment_recovery_id,
            'action': self.action,
            'user_id': self.user_id,
            'user_name': self.user_name,
            'details': self.details,
            'amount': self.amount,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
    
    def __repr__(self) -> str:
        return f"<PaymentHistory {self.id} - {self.action}>"