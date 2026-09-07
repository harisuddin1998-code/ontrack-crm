# src/models/complaint.py
"""
Complaint Model - Customer complaint and ticket tracking
"""
from datetime import datetime
from typing import Dict, Any, Optional

from src.extensions import db
from src.models.base import BaseModel, StatusMixin, AuditMixin


class Complaint(BaseModel, StatusMixin, AuditMixin):
    """Customer Complaint model"""
    __tablename__ = 'complaints'

    # Complaint Identification
    ticket_no = db.Column(db.String(30), unique=True, nullable=False, index=True)
    
    # Customer Details
    customer_name = db.Column(db.String(200), nullable=False)
    customer_contact = db.Column(db.String(50), nullable=False)
    reg_no = db.Column(db.String(50), index=True)
    city = db.Column(db.String(100))
    vehicle_location = db.Column(db.String(200))  # Physical device location in vehicle (e.g., CENTER DASHBOARD, STEERING BOX)
    
    # Complaint Particulars
    complaint_type = db.Column(db.String(50), default='GPS_NOT_WORKING', nullable=False)
    severity = db.Column(db.String(20), default='MEDIUM', nullable=False)
    status = db.Column(db.String(20), default='OPEN', nullable=False)
    description = db.Column(db.Text, nullable=False)
    resolution_notes = db.Column(db.Text)
    
    # Assignments & Timestamps
    # The technician a ticket goes to is a technician from Technician
    # Management, not an arbitrary login. This used to point at users.id
    # while the dropdown listed technicians, so the id saved belonged to one
    # table and was read back out of another - the assigned name shown was
    # whoever happened to hold that id in `users`.
    technician_id = db.Column(db.Integer, db.ForeignKey('technicians.id'), nullable=True)
    assigned_at = db.Column(db.DateTime, nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    po_id = db.Column(db.Integer, db.ForeignKey('purchase_orders.id'), nullable=True)

    # Relationships
    technician = db.relationship('Technician', foreign_keys=[technician_id], backref='complaints')
    resolver_user = db.relationship('User', foreign_keys=[resolved_by], backref='resolved_complaints')
    purchase_order = db.relationship('PurchaseOrder', foreign_keys=[po_id], backref='complaints')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def mark_resolved(self, user_id: int, notes: str) -> None:
        """Mark complaint as resolved"""
        self.status = 'RESOLVED'
        self.resolution_notes = notes
        self.resolved_by = user_id
        self.resolved_at = datetime.now()
        db.session.commit()

    def mark_in_progress(self, technician_id: Optional[int] = None) -> None:
        """Mark complaint in progress, optionally against a technician."""
        self.status = 'IN_PROGRESS'
        if technician_id:
            self.technician_id = technician_id
            self.assigned_at = datetime.now()
        db.session.commit()

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'ticket_no': self.ticket_no,
            'customer_name': self.customer_name,
            'customer_contact': self.customer_contact,
            'reg_no': self.reg_no or '',
            'city': self.city or '',
            'vehicle_location': self.vehicle_location or '',
            'complaint_type': self.complaint_type,
            'severity': self.severity,
            'status': self.status,
            'description': self.description,
            'resolution_notes': self.resolution_notes or '',
            'technician_id': self.technician_id,
            'technician_name': self.technician.name if self.technician else None,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else '',
            'resolved_at': self.resolved_at.strftime('%Y-%m-%d %H:%M:%S') if self.resolved_at else '',
        }
