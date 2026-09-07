# src/models/installation_recovery.py
"""
Installation Recovery - device replacement cost recovery for REDO activities
flagged with a device_change_reason (damaged, missing, or power-issue
devices). One charge per REDO device-change event, fixed at creation per a
flat fee schedule, worked by a Payment Recovery officer through the same
PENDING -> CONTACTED -> RECOVERED/LOST lifecycle already used elsewhere in
this system (e.g. Live AMC assignments) - once assigned, an officer's charge
is never reassigned or deleted, only its status/payment fields change.
"""
from typing import Any, Dict, Optional

from src.extensions import db
from src.models.base import BaseModel
from src.utils.timezone import get_current_time

# Fixed recovery fee schedule (PKR) by device_change_reason.
RECOVERY_AMOUNT_BY_REASON = {
    'Device Damage': 5000.0,
    'Device Missing': 10000.0,
    'Power Issue': 5000.0,
}

# Historical REDO rows may still carry old/retired labels - "Device Burnt"
# was renamed to "Device Damage", and "Water Damage" was retired as a
# separate reason (it billed at the same rate as Device Damage anyway) -
# both fold into the Device Damage bucket everywhere reason is read.
REASON_ALIASES = {
    'Device Burnt': 'Device Damage',
    'Water Damage': 'Device Damage',
}


def normalize_device_change_reason(reason: Optional[str]) -> Optional[str]:
    if not reason:
        return reason
    return REASON_ALIASES.get(reason, reason)


def get_recovery_amount(reason: Optional[str]) -> float:
    return RECOVERY_AMOUNT_BY_REASON.get(normalize_device_change_reason(reason) or '', 0.0)


class InstallationRecoveryCharge(BaseModel):
    __tablename__ = 'installation_recovery_charges'

    STATUS_PENDING = 'PENDING'
    STATUS_CONTACTED = 'CONTACTED'
    STATUS_RECOVERED = 'RECOVERED'
    STATUS_LOST = 'LOST'

    redo_activity_id = db.Column(db.Integer, db.ForeignKey('redo_activities.id', ondelete='CASCADE'),
                                  nullable=False, unique=True, index=True)
    reason = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Float, default=0.0, nullable=False)
    status = db.Column(db.String(20), default=STATUS_PENDING, nullable=False, index=True)

    assigned_officer_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    assigned_at = db.Column(db.DateTime)

    payment_method = db.Column(db.String(20))  # ONLINE / CASH / CHEQUE
    payment_reference = db.Column(db.String(100))
    proof_of_payment_path = db.Column(db.String(255))
    recovered_at = db.Column(db.DateTime)

    notes = db.Column(db.Text)

    redo_activity = db.relationship('RedoActivity', foreign_keys=[redo_activity_id])
    assigned_officer = db.relationship('User', foreign_keys=[assigned_officer_id])

    def get_outstanding(self) -> float:
        return self.amount if self.status not in (self.STATUS_RECOVERED, self.STATUS_LOST) else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'redo_activity_id': self.redo_activity_id,
            'registration_no': self.redo_activity.registration_no if self.redo_activity else None,
            'customer_name': self.redo_activity.customer_name if self.redo_activity else None,
            'reason': self.reason,
            'amount': self.amount,
            'status': self.status,
            'assigned_officer_id': self.assigned_officer_id,
            'assigned_officer_name': self.assigned_officer.name if self.assigned_officer else None,
            'payment_method': self.payment_method,
            'payment_reference': self.payment_reference,
            'proof_of_payment_path': self.proof_of_payment_path,
            'recovered_at': self.recovered_at.isoformat() if self.recovered_at else None,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<InstallationRecoveryCharge redo={self.redo_activity_id} {self.reason} PKR{self.amount} {self.status}>"


class InstallationRecoveryFollowup(BaseModel):
    """Call/WhatsApp follow-up log for a device recovery charge - mirrors
    NonReportingConversation's shape (src.models.gps) so the Installation
    Recovery Follow-up Report reads the same way as the REDO one."""
    __tablename__ = 'installation_recovery_followups'

    charge_id = db.Column(db.Integer, db.ForeignKey('installation_recovery_charges.id', ondelete='CASCADE'),
                           nullable=False, index=True)
    conversation_date = db.Column(db.DateTime, default=get_current_time)
    conversation_type = db.Column(db.String(20))  # PHONE_CALL / WHATSAPP
    direction = db.Column(db.String(10))  # IN / OUT
    contact_person = db.Column(db.String(100))
    contact_number = db.Column(db.String(50))
    summary = db.Column(db.Text, nullable=False)
    action_taken = db.Column(db.Text)
    follow_up_required = db.Column(db.Boolean, default=False)
    follow_up_date = db.Column(db.Date)
    recorded_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    recorded_by_name = db.Column(db.String(100))

    charge = db.relationship('InstallationRecoveryCharge', foreign_keys=[charge_id], backref='followups')
    recorded_by_user = db.relationship('User', foreign_keys=[recorded_by])

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'charge_id': self.charge_id,
            'conversation_date': self.conversation_date.isoformat() if self.conversation_date else None,
            'conversation_type': self.conversation_type,
            'direction': self.direction,
            'contact_person': self.contact_person,
            'contact_number': self.contact_number,
            'summary': self.summary,
            'action_taken': self.action_taken,
            'follow_up_required': self.follow_up_required,
            'follow_up_date': self.follow_up_date.isoformat() if self.follow_up_date else None,
            'recorded_by_name': self.recorded_by_name,
        }

    def __repr__(self) -> str:
        return f"<InstallationRecoveryFollowup charge={self.charge_id} {self.conversation_type}>"
