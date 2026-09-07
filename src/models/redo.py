# src/models/redo.py
"""
REDO Activity Models - Full Specification
"""
from typing import Dict, Any, Optional
from datetime import datetime

from src.extensions import db
from src.models.base import BaseModel, StatusMixin


class RedoActivity(BaseModel, StatusMixin):
    __tablename__ = 'redo_activities'

    # Auto-generated Activity Number: REDO-YYYYMMDD-NNNN
    redo_number = db.Column(db.String(30), unique=True, index=True)

    # Status and Dynamic Attributes
    status = db.Column(db.String(20), default='PENDING', nullable=False)
    
    @property
    def age_hours(self) -> Optional[float]:
        return getattr(self, '_age_hours', None)

    @age_hours.setter
    def age_hours(self, value: Optional[float]) -> None:
        self._age_hours = value

    @property
    def sla_exceeded(self) -> Optional[bool]:
        return getattr(self, '_sla_exceeded', None)

    @sla_exceeded.setter
    def sla_exceeded(self, value: Optional[bool]) -> None:
        self._sla_exceeded = value

    @property
    def aging_display(self) -> Optional[str]:
        return getattr(self, '_aging_display', None)

    @aging_display.setter
    def aging_display(self, value: Optional[str]) -> None:
        self._aging_display = value

    # Activity Details
    activity_type = db.Column(db.String(50), default='REDO')  # REDO, Removal Transfer, Rework, etc.
    scheduled_date = db.Column(db.Date)
    rates = db.Column(db.String(50))

    # Customer Information
    customer_name = db.Column(db.String(200))
    customer_contact = db.Column(db.String(50))
    sale_person = db.Column(db.String(100))
    arranged_by = db.Column(db.String(100))
    previous_customer = db.Column(db.String(200))

    # Vehicle Information
    registration_no = db.Column(db.String(50), nullable=False, index=True)
    make = db.Column(db.String(50))
    model = db.Column(db.String(50))
    year = db.Column(db.String(4))
    color = db.Column(db.String(20))
    chassis_no = db.Column(db.String(100))
    engine_no = db.Column(db.String(100))
    old_vehicle = db.Column(db.String(100))

    # Device Information
    imei_no = db.Column(db.String(50))
    sim_no = db.Column(db.String(50))
    device_type = db.Column(db.String(50))
    device_location = db.Column(db.String(200))
    old_imei_no = db.Column(db.String(50))
    old_sim_no = db.Column(db.String(50))
    new_device = db.Column(db.String(50))
    new_sim = db.Column(db.String(50))
    # Why the device was swapped - one of: Power Issue, Device Damage, Water
    # Damage, Device Missing. Only meaningful alongside new_device/new_sim.
    # Historical rows may still hold the old label "Device Burnt" - normalize
    # via src.models.installation_recovery.normalize_device_change_reason.
    device_change_reason = db.Column(db.String(50))

    # Technical Details
    technician = db.Column(db.String(100))
    tested_by = db.Column(db.String(100))
    city = db.Column(db.String(100))
    vehicle_location = db.Column(db.String(200))
    transfer_installation = db.Column(db.String(10), default='No')  # Yes/No
    transfer_charges = db.Column(db.String(50))
    fuel = db.Column(db.String(50))

    # Resolution & Remarks
    resolution_status = db.Column(db.String(30), default='Pending')  # Pending, Completed, Cancelled
    remarks = db.Column(db.Text)
    rework_reason = db.Column(db.Text)
    issue_description = db.Column(db.Text)
    previous_installation_notes = db.Column(db.Text)

    # Assignment & System Meta
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'))
    assigned_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    assigned_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    priority = db.Column(db.String(10), default='NORMAL')

    # Completion
    completion_notes = db.Column(db.Text)
    completed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    completed_at = db.Column(db.DateTime)
    rework_completed_date = db.Column(db.Date)

    # QA Verification - set by an admin/supervisor once the activity's
    # details have been reviewed. Only verified activities are counted in
    # MIS exports/reports; unverified ones stay visible on the wallboard but
    # flagged as pending review.
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    verified_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    verified_at = db.Column(db.DateTime)

    # Relationships
    assigned_to_user = db.relationship('User', foreign_keys=[assigned_to], backref='redo_assigned_to')
    assigned_by_user = db.relationship('User', foreign_keys=[assigned_by], backref='redo_assigned_by')
    completed_by_user = db.relationship('User', foreign_keys=[completed_by], backref='redo_completed_by')
    verified_by_user = db.relationship('User', foreign_keys=[verified_by], backref='redo_verified_by')

    # Priority constants
    PRIORITY_LOW = 'LOW'
    PRIORITY_NORMAL = 'NORMAL'
    PRIORITY_HIGH = 'HIGH'
    PRIORITY_URGENT = 'URGENT'

    @staticmethod
    def generate_redo_number() -> str:
        """Generate auto REDO Activity number in format REDO-YYYYMMDD-NNNN"""
        today_str = datetime.now().strftime('%Y%m%d')
        prefix = f"REDO-{today_str}-"
        last = RedoActivity.query.filter(RedoActivity.redo_number.like(f"{prefix}%")).order_by(RedoActivity.id.desc()).first()
        if last and last.redo_number:
            try:
                seq = int(last.redo_number.split('-')[-1]) + 1
            except ValueError:
                seq = 1
        else:
            seq = 1
        return f"{prefix}{seq:04d}"

    def complete(self, user_id: int, notes: Optional[str] = None) -> None:
        """Mark REDO as completed"""
        self.status = self.STATUS_COMPLETED
        self.resolution_status = 'Completed'
        self.completed_by = user_id
        self.completed_at = db.func.current_timestamp()
        self.rework_completed_date = db.func.current_date()
        if notes:
            self.completion_notes = notes
        db.session.commit()

    def assign(self, technician_id: int, assigned_by_id: int) -> None:
        """Assign REDO to technician"""
        self.assigned_to = technician_id
        self.assigned_by = assigned_by_id
        self.assigned_at = db.func.current_timestamp()
        self.status = self.STATUS_IN_PROGRESS
        db.session.commit()

    def verify(self, user_id: int) -> None:
        """Mark this REDO activity as verified so it counts toward MIS
        totals and reports."""
        self.is_verified = True
        self.verified_by = user_id
        self.verified_at = db.func.current_timestamp()
        db.session.commit()

    def unverify(self) -> None:
        """Revoke verification, e.g. if details need to be corrected."""
        self.is_verified = False
        self.verified_by = None
        self.verified_at = None
        db.session.commit()

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'redo_number': self.redo_number,
            'activity_type': self.activity_type,
            'scheduled_date': self.scheduled_date.isoformat() if self.scheduled_date else None,
            'rates': self.rates,
            'registration_no': self.registration_no,
            'make': self.make,
            'model': self.model,
            'year': self.year,
            'color': self.color,
            'chassis_no': self.chassis_no,
            'engine_no': self.engine_no,
            'old_vehicle': self.old_vehicle,
            'customer_name': self.customer_name,
            'customer_contact': self.customer_contact,
            'sale_person': self.sale_person,
            'arranged_by': self.arranged_by,
            'previous_customer': self.previous_customer,
            'imei_no': self.imei_no,
            'sim_no': self.sim_no,
            'device_type': self.device_type,
            'device_location': self.device_location,
            'old_imei_no': self.old_imei_no,
            'old_sim_no': self.old_sim_no,
            'new_device': self.new_device,
            'new_sim': self.new_sim,
            'device_change_reason': self.device_change_reason,
            'technician': self.technician,
            'tested_by': self.tested_by,
            'city': self.city,
            'vehicle_location': self.vehicle_location,
            'transfer_installation': self.transfer_installation,
            'transfer_charges': self.transfer_charges,
            'fuel': self.fuel,
            'resolution_status': self.resolution_status,
            'remarks': self.remarks,
            'rework_reason': self.rework_reason,
            'status': self.status,
            'priority': self.priority,
            'assigned_to': self.assigned_to,
            'assigned_to_name': self.assigned_to_user.name if self.assigned_to_user else self.technician,
            'completed_by': self.completed_by,
            'completed_by_name': self.completed_by_user.name if self.completed_by_user else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'is_verified': self.is_verified,
            'verified_by_name': self.verified_by_user.name if self.verified_by_user else None,
            'verified_at': self.verified_at.isoformat() if self.verified_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<RedoActivity {self.redo_number or self.id} - {self.registration_no} - {self.status}>"
