# src/models/live_amc.py
"""
Live AMC Module - daily anniversary-based AMC recovery assignment.

Every day, vehicles whose installation date's day+month matches "today"
(across every install year on record) become due for AMC follow-up. This
model records the round-robin assignment of that day's due vehicles to
recovery officers, kept stable once made so a day's work list never
reshuffles mid-day and each officer only ever works their own slice.
"""
from datetime import datetime
from typing import Any, Dict

from src.extensions import db
from src.models.base import BaseModel


class LiveAmcAssignment(BaseModel):
    """One vehicle's AMC follow-up assignment for one due date."""
    __tablename__ = 'live_amc_assignments'

    STATUS_PENDING = 'PENDING'
    STATUS_CONTACTED = 'CONTACTED'
    STATUS_RECOVERED = 'RECOVERED'
    STATUS_ESCALATED = 'ESCALATED'
    STATUS_SKIPPED = 'SKIPPED'

    vehicle_id = db.Column(db.Integer, db.ForeignKey('recovery_vehicles.id', ondelete='CASCADE'), nullable=False, index=True)
    due_date = db.Column(db.Date, nullable=False, index=True)
    match_day = db.Column(db.Integer, nullable=False)
    match_month = db.Column(db.Integer, nullable=False)
    assigned_officer_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)
    work_status = db.Column(db.String(20), default=STATUS_PENDING, nullable=False)
    remarks = db.Column(db.Text)

    vehicle = db.relationship('AnnualRecoveryVehicle', foreign_keys=[vehicle_id])
    assigned_officer = db.relationship('User', foreign_keys=[assigned_officer_id])

    __table_args__ = (
        db.UniqueConstraint('vehicle_id', 'due_date', name='uq_live_amc_vehicle_due_date'),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'assigned_officer_id': self.assigned_officer_id,
            'assigned_officer_name': self.assigned_officer.name or self.assigned_officer.username if self.assigned_officer else 'Unassigned',
            'work_status': self.work_status,
            'remarks': self.remarks,
        }

    def __repr__(self) -> str:
        return f"<LiveAmcAssignment vehicle={self.vehicle_id} due={self.due_date} officer={self.assigned_officer_id}>"
