# src/models/removal.py
"""
Removal and Transfer Activity Models
"""
from typing import Dict, Any, Optional
from datetime import date

from src.extensions import db
from src.models.base import BaseModel, StatusMixin


class RemovalTransferActivity(BaseModel, StatusMixin):
    """Device transfer activity from one vehicle to another"""
    __tablename__ = 'removal_transfer_activities'
    
    # Old Vehicle
    old_registration_no = db.Column(db.String(50), nullable=False, index=True)
    old_make = db.Column(db.String(50))
    old_model = db.Column(db.String(50))
    old_year = db.Column(db.String(4))
    old_color = db.Column(db.String(20))
    old_chassis_no = db.Column(db.String(100))
    old_engine_no = db.Column(db.String(100))
    old_customer_name = db.Column(db.String(200))
    old_customer_contact = db.Column(db.String(50))
    old_imei_no = db.Column(db.String(50))
    old_sim_no = db.Column(db.String(50))
    old_device_location = db.Column(db.String(200))
    
    # New Vehicle
    new_registration_no = db.Column(db.String(50), nullable=False)
    new_make = db.Column(db.String(50))
    new_model = db.Column(db.String(50))
    new_year = db.Column(db.String(4))
    new_color = db.Column(db.String(20))
    new_chassis_no = db.Column(db.String(100))
    new_engine_no = db.Column(db.String(100))
    new_customer_name = db.Column(db.String(200))
    new_customer_contact = db.Column(db.String(50))
    
    # Transfer Details
    transfer_reason = db.Column(db.Text)
    device_transferred_date = db.Column(db.Date)
    
    # Assignment
    # Two different people, deliberately: `assigned_to` is the removal
    # officer who owns the case - a login, which is what scopes their
    # dashboard to their own work - and `technician_id` is the technician
    # from Technician Management who physically does the job. The picker
    # labelled "Technician" used to write the officer column, so the roster
    # and the record could never agree on who did the work.
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'))
    technician_id = db.Column(db.Integer, db.ForeignKey('technicians.id'))
    assigned_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    assigned_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    
    # Completion
    completion_notes = db.Column(db.Text)
    completed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    completed_at = db.Column(db.DateTime)
    
    # Relationships
    assigned_to_user = db.relationship('User', foreign_keys=[assigned_to],
                                        backref='transfer_assigned_to')
    technician = db.relationship('Technician', foreign_keys=[technician_id],
                                 backref='transfer_activities')
    assigned_by_user = db.relationship('User', foreign_keys=[assigned_by],
                                        backref='transfer_assigned_by')
    completed_by_user = db.relationship('User', foreign_keys=[completed_by],
                                         backref='transfer_completed_by')
    
    def complete(self, user_id: int, notes: Optional[str] = None) -> None:
        """Mark transfer as completed"""
        self.status = self.STATUS_COMPLETED
        self.completed_by = user_id
        self.completed_at = db.func.current_timestamp()
        if notes:
            self.completion_notes = notes
        db.session.commit()
    
    def assign(self, technician_id: int, assigned_by_id: int) -> None:
        """Assign transfer to a technician on the roster"""
        self.technician_id = technician_id
        self.assigned_by = assigned_by_id
        self.assigned_at = db.func.current_timestamp()
        self.status = self.STATUS_IN_PROGRESS
        db.session.commit()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'old_registration_no': self.old_registration_no,
            'old_make': self.old_make,
            'old_model': self.old_model,
            'old_year': self.old_year,
            'old_color': self.old_color,
            'old_chassis_no': self.old_chassis_no,
            'old_engine_no': self.old_engine_no,
            'old_customer_name': self.old_customer_name,
            'old_customer_contact': self.old_customer_contact,
            'old_imei_no': self.old_imei_no,
            'old_sim_no': self.old_sim_no,
            'old_device_location': self.old_device_location,
            'new_registration_no': self.new_registration_no,
            'new_make': self.new_make,
            'new_model': self.new_model,
            'new_year': self.new_year,
            'new_color': self.new_color,
            'new_chassis_no': self.new_chassis_no,
            'new_engine_no': self.new_engine_no,
            'new_customer_name': self.new_customer_name,
            'new_customer_contact': self.new_customer_contact,
            'transfer_reason': self.transfer_reason,
            'device_transferred_date': self.device_transferred_date.isoformat() if self.device_transferred_date else None,
            'assigned_to': self.assigned_to,
            'assigned_to_name': self.assigned_to_user.name if self.assigned_to_user else None,
            'technician_id': self.technician_id,
            'technician_name': self.technician.name if self.technician else None,
            'assigned_by': self.assigned_by,
            'assigned_by_name': self.assigned_by_user.name if self.assigned_by_user else None,
            'assigned_at': self.assigned_at.isoformat() if self.assigned_at else None,
            'status': self.status,
            'completion_notes': self.completion_notes,
            'completed_by': self.completed_by,
            'completed_by_name': self.completed_by_user.name if self.completed_by_user else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
    
    def __repr__(self) -> str:
        return f"<RemovalTransferActivity {self.id} - {self.old_registration_no} -> {self.new_registration_no}>"


class RemovalRetainedActivity(BaseModel, StatusMixin):
    """Device removal and retention activity"""
    __tablename__ = 'removal_retained_activities'
    
    # Vehicle Information
    registration_no = db.Column(db.String(50), nullable=False, index=True)
    make = db.Column(db.String(50))
    model = db.Column(db.String(50))
    year = db.Column(db.String(4))
    color = db.Column(db.String(20))
    chassis_no = db.Column(db.String(100))
    engine_no = db.Column(db.String(100))
    customer_name = db.Column(db.String(200))
    customer_contact = db.Column(db.String(50))
    imei_no = db.Column(db.String(50))
    sim_no = db.Column(db.String(50))
    device_location = db.Column(db.String(200))
    
    # Removal Details
    removal_reason = db.Column(db.Text)
    removal_date = db.Column(db.Date)
    removal_type = db.Column(db.String(50), default='RETAINED')  # RETAINED, TRANSFERRED, DISPOSED
    
    # Device Return
    device_returned = db.Column(db.Boolean, default=False)
    return_date = db.Column(db.Date)
    device_condition = db.Column(db.String(100))
    
    # Retention
    retained_by = db.Column(db.String(100))
    storage_location = db.Column(db.String(200))
    
    # Assignment
    # Two different people, deliberately: `assigned_to` is the removal
    # officer who owns the case - a login, which is what scopes their
    # dashboard to their own work - and `technician_id` is the technician
    # from Technician Management who physically does the job. The picker
    # labelled "Technician" used to write the officer column, so the roster
    # and the record could never agree on who did the work.
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'))
    technician_id = db.Column(db.Integer, db.ForeignKey('technicians.id'))
    assigned_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    assigned_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    
    # Completion
    completion_notes = db.Column(db.Text)
    completed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    completed_at = db.Column(db.DateTime)
    
    # Relationships
    assigned_to_user = db.relationship('User', foreign_keys=[assigned_to],
                                        backref='retained_assigned_to')
    technician = db.relationship('Technician', foreign_keys=[technician_id],
                                 backref='retained_activities')
    assigned_by_user = db.relationship('User', foreign_keys=[assigned_by],
                                        backref='retained_assigned_by')
    completed_by_user = db.relationship('User', foreign_keys=[completed_by],
                                         backref='retained_completed_by')
    
    def complete(self, user_id: int, notes: Optional[str] = None) -> None:
        """Mark removal as completed"""
        self.status = self.STATUS_COMPLETED
        self.completed_by = user_id
        self.completed_at = db.func.current_timestamp()
        if notes:
            self.completion_notes = notes
        db.session.commit()
    
    def assign(self, technician_id: int, assigned_by_id: int) -> None:
        """Assign removal to a technician on the roster"""
        self.technician_id = technician_id
        self.assigned_by = assigned_by_id
        self.assigned_at = db.func.current_timestamp()
        self.status = self.STATUS_IN_PROGRESS
        db.session.commit()
    
    def mark_returned(self, return_date: date, condition: str) -> None:
        """Mark device as returned"""
        self.device_returned = True
        self.return_date = return_date
        self.device_condition = condition
        db.session.commit()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'registration_no': self.registration_no,
            'make': self.make,
            'model': self.model,
            'year': self.year,
            'color': self.color,
            'chassis_no': self.chassis_no,
            'engine_no': self.engine_no,
            'customer_name': self.customer_name,
            'customer_contact': self.customer_contact,
            'imei_no': self.imei_no,
            'sim_no': self.sim_no,
            'device_location': self.device_location,
            'removal_reason': self.removal_reason,
            'removal_date': self.removal_date.isoformat() if self.removal_date else None,
            'removal_type': self.removal_type,
            'device_returned': self.device_returned,
            'return_date': self.return_date.isoformat() if self.return_date else None,
            'device_condition': self.device_condition,
            'retained_by': self.retained_by,
            'storage_location': self.storage_location,
            'assigned_to': self.assigned_to,
            'assigned_to_name': self.assigned_to_user.name if self.assigned_to_user else None,
            'technician_id': self.technician_id,
            'technician_name': self.technician.name if self.technician else None,
            'assigned_by': self.assigned_by,
            'assigned_by_name': self.assigned_by_user.name if self.assigned_by_user else None,
            'assigned_at': self.assigned_at.isoformat() if self.assigned_at else None,
            'status': self.status,
            'completion_notes': self.completion_notes,
            'completed_by': self.completed_by,
            'completed_by_name': self.completed_by_user.name if self.completed_by_user else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
    
    def __repr__(self) -> str:
        return f"<RemovalRetainedActivity {self.id} - {self.registration_no} - {self.status}>"


class VehicleFlag(BaseModel):
    """Vehicle flagging for removal/retention"""
    __tablename__ = 'vehicle_flags'
    
    registration_no = db.Column(db.String(50), nullable=False, index=True)
    make = db.Column(db.String(50))
    model = db.Column(db.String(50))
    year = db.Column(db.String(4))
    color = db.Column(db.String(20))
    chassis_no = db.Column(db.String(100))
    engine_no = db.Column(db.String(100))
    customer_name = db.Column(db.String(200))
    customer_contact = db.Column(db.String(50))
    imei_no = db.Column(db.String(50))
    sim_no = db.Column(db.String(50))
    device_location = db.Column(db.String(200))
    
    # Flag Details
    flag_reason = db.Column(db.Text, nullable=False)
    flag_type = db.Column(db.String(50), nullable=False)  # REMOVAL, RETENTION, TRANSFER
    flagged_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    flagged_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    
    # Status
    status = db.Column(db.String(20), default='PENDING')  # PENDING, IN_PROGRESS, COMPLETED, CANCELLED
    priority = db.Column(db.String(10), default='NORMAL')  # LOW, NORMAL, HIGH, URGENT
    
    # Assignment
    # Two different people, deliberately: `assigned_to` is the removal
    # officer who owns the case - a login, which is what scopes their
    # dashboard to their own work - and `technician_id` is the technician
    # from Technician Management who physically does the job. The picker
    # labelled "Technician" used to write the officer column, so the roster
    # and the record could never agree on who did the work.
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'))
    technician_id = db.Column(db.Integer, db.ForeignKey('technicians.id'))
    assigned_at = db.Column(db.DateTime)
    
    # Completion
    completed_at = db.Column(db.DateTime)
    completion_notes = db.Column(db.Text)
    
    # Relationships
    flagged_by_user = db.relationship('User', foreign_keys=[flagged_by],
                                       backref='flagged_vehicles')
    assigned_to_user = db.relationship('User', foreign_keys=[assigned_to],
                                        backref='assigned_flags')
    technician = db.relationship('Technician', foreign_keys=[technician_id],
                                 backref='vehicle_flags')
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'registration_no': self.registration_no,
            'make': self.make,
            'model': self.model,
            'year': self.year,
            'color': self.color,
            'chassis_no': self.chassis_no,
            'engine_no': self.engine_no,
            'customer_name': self.customer_name,
            'customer_contact': self.customer_contact,
            'imei_no': self.imei_no,
            'sim_no': self.sim_no,
            'device_location': self.device_location,
            'flag_reason': self.flag_reason,
            'flag_type': self.flag_type,
            'flagged_by': self.flagged_by,
            'flagged_by_name': self.flagged_by_user.name if self.flagged_by_user else None,
            'flagged_at': self.flagged_at.isoformat() if self.flagged_at else None,
            'status': self.status,
            'priority': self.priority,
            'assigned_to': self.assigned_to,
            'assigned_to_name': self.assigned_to_user.name if self.assigned_to_user else None,
            'technician_id': self.technician_id,
            'technician_name': self.technician.name if self.technician else None,
            'assigned_at': self.assigned_at.isoformat() if self.assigned_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'completion_notes': self.completion_notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
    
    def __repr__(self) -> str:
        return f"<VehicleFlag {self.id} - {self.registration_no} - {self.flag_type}>"