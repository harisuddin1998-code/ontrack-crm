# src/models/purchase_order.py
"""
Purchase Order Model - Core entity for vehicle installations
"""
from datetime import date, datetime
from typing import Optional, Dict, Any

from src.extensions import db
from src.models.base import BaseModel, StatusMixin, AuditMixin


class PurchaseOrder(BaseModel, StatusMixin, AuditMixin):
    """Purchase Order for vehicle tracking installation"""
    __tablename__ = 'purchase_orders'
    
    # PO Information
    po_number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    status = db.Column(db.String(20), default='PENDING', nullable=False)
    activity_type = db.Column(db.String(50), default='INSTALLATION')
    
    # Customer Information
    owner_name = db.Column(db.String(200), nullable=False)
    owner_contact = db.Column(db.String(50), nullable=False)
    contact_person_driver = db.Column(db.String(200))
    
    # Vehicle Information
    reg_no = db.Column(db.String(50), nullable=False, index=True)
    vehicle_make = db.Column(db.String(50), nullable=False)
    vehicle_model = db.Column(db.String(50), nullable=False)
    vehicle_year = db.Column(db.String(4), nullable=False)
    vehicle_color = db.Column(db.String(20), nullable=False)
    engine_number = db.Column(db.String(100), nullable=False)
    chassis_number = db.Column(db.String(100), nullable=False)
    # SJ_MIS has columns for these but barely fills them - a fifth of the
    # fleet has a usable transmission and three percent a capacity - so the
    # order is where they get recorded properly for vehicles we handle.
    transmission = db.Column(db.String(20))
    power_cc = db.Column(db.String(20))
    
    # Sales & Location
    # Nullable so an admin can delete a sales user's account without being
    # blocked by their historical POs - SQLAlchemy nulls this out on delete
    # (no explicit cascade set), which a NOT NULL constraint used to reject
    # outright, crashing the whole delete.
    sales_person_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    city = db.Column(db.String(100))
    vehicle_availability_location = db.Column(db.String(200), nullable=False)
    
    # Existing Customer (if transfer)
    existing_customer_name = db.Column(db.String(200))
    existing_vehicle_number = db.Column(db.String(100))
    
    # Installation Details
    scheduled_date = db.Column(db.Date)
    technician_assigned = db.Column(db.String(100))
    imei_no = db.Column(db.String(50))
    sim_no = db.Column(db.String(50))
    device_type = db.Column(db.String(50))
    device_location = db.Column(db.String(200))
    fuel = db.Column(db.String(50))  # Fuel cost provided by customer
    tested_by = db.Column(db.String(100))
    arranged_by_sales_person = db.Column(db.String(100))
    remarks = db.Column(db.Text)

    # Exact moment the installation-completion email went out - this is the
    # authoritative "installation date" for documents like the Tracker
    # Certificate, independent of later, unrelated edits to the PO record.
    completion_email_sent_at = db.Column(db.DateTime)
    
    # Financial
    rates = db.Column(db.Float, default=0.0)
    amc = db.Column(db.Float, default=0.0)
    
    # Foreign Keys for relationships
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    # Relationships - FIXED: Changed backref names to avoid conflicts
    trips = db.relationship('TechnicianTrip', backref='po_trip', lazy='dynamic')
    security_briefing = db.relationship('SecurityBriefingData', backref='po_briefing', 
                                        uselist=False, foreign_keys='SecurityBriefingData.po_id')
    payment_recovery = db.relationship('PaymentRecovery', backref='po_payment',
                                       uselist=False, foreign_keys='PaymentRecovery.po_id')
    
    # Status constants (additional to base)
    STATUS_PENDING = 'PENDING'
    STATUS_IN_PROGRESS = 'IN_PROGRESS'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_CANCELLED = 'CANCELLED'
    
    def get_total_amount(self) -> float:
        """Get total amount (rates + AMC)"""
        return (self.rates or 0) + (self.amc or 0)
    
    def is_completed(self) -> bool:
        """Check if PO is completed"""
        return self.status == self.STATUS_COMPLETED
    
    def is_pending(self) -> bool:
        """Check if PO is pending"""
        return self.status == self.STATUS_PENDING
    
    def is_cancelled(self) -> bool:
        """Check if PO is cancelled"""
        return self.status == self.STATUS_CANCELLED
    
    def complete(self, user_id: Optional[int] = None) -> None:
        """Mark PO as completed"""
        self.status = self.STATUS_COMPLETED
        if user_id:
            self.updated_by = user_id
        db.session.commit()
    
    def cancel(self, user_id: Optional[int] = None) -> None:
        """Cancel PO"""
        self.status = self.STATUS_CANCELLED
        if user_id:
            self.updated_by = user_id
        db.session.commit()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert PO to dictionary"""
        return {
            'id': self.id,
            'po_number': self.po_number,
            'activity_type': self.activity_type,
            'owner_name': self.owner_name,
            'owner_contact': self.owner_contact,
            'contact_person_driver': self.contact_person_driver,
            'reg_no': self.reg_no,
            'vehicle_make': self.vehicle_make,
            'vehicle_model': self.vehicle_model,
            'vehicle_year': self.vehicle_year,
            'vehicle_color': self.vehicle_color,
            'engine_number': self.engine_number,
            'chassis_number': self.chassis_number,
            'sales_person_id': self.sales_person_id,
            'city': self.city,
            'vehicle_availability_location': self.vehicle_availability_location,
            'existing_customer_name': self.existing_customer_name,
            'existing_vehicle_number': self.existing_vehicle_number,
            'scheduled_date': self.scheduled_date.isoformat() if self.scheduled_date else None,
            'technician_assigned': self.technician_assigned,
            'imei_no': self.imei_no,
            'sim_no': self.sim_no,
            'device_type': self.device_type,
            'device_location': self.device_location,
            'fuel': self.fuel,
            'tested_by': self.tested_by,
            'arranged_by_sales_person': self.arranged_by_sales_person,
            'remarks': self.remarks,
            'status': self.status,
            'rates': self.rates,
            'amc': self.amc,
            'total_amount': self.get_total_amount(),
            'created_by': self.created_by,
            'updated_by': self.updated_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
    
    def __repr__(self) -> str:
        return f"<PurchaseOrder {self.po_number} - {self.owner_name}>"