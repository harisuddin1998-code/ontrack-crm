# src/models/amc_database_assignment.py
"""
AMC Recoveries - Database Method: the daily follow-up list.

Same rule as the Sheet Method: AMC renews annually on the vehicle's
installation anniversary, so every day the vehicles whose install date's day
and month match that date - across every install year on record - become due.
The difference is the source. The Sheet Method reads the imported
spreadsheet (AnnualRecoveryVehicle); this reads SJ_MIS's own payment ledger
(AmcRecoveryRecord), which is where the real money is recorded.

Two things make this list workable rather than just correct:

  * It is stored. The day's list is generated once and kept, so it cannot
    reshuffle under an officer who is halfway through it, and so a past day
    can be looked at afterwards and show what was actually worked.
  * It is clubbed by customer. A customer with six vehicles due is six rows
    here, but all six carry the same officer, because it is one phone call.
    The round robin therefore distributes customers, not vehicles.
"""
from datetime import datetime
from typing import Any, Dict

from src.extensions import db
from src.models.base import BaseModel


class AmcDatabaseAssignment(BaseModel):
    """One vehicle's AMC follow-up, for one due date, from the ledger."""
    __tablename__ = 'amc_database_assignments'

    STATUS_PENDING = 'PENDING'
    STATUS_CONTACTED = 'CONTACTED'
    STATUS_RECOVERED = 'RECOVERED'
    STATUS_ESCALATED = 'ESCALATED'
    STATUS_SKIPPED = 'SKIPPED'

    WORK_STATUSES = (STATUS_PENDING, STATUS_CONTACTED, STATUS_RECOVERED,
                     STATUS_ESCALATED, STATUS_SKIPPED)

    # The ledger row this came from - the most recent AMC period on record
    # for the vehicle. Kept as a plain id rather than a relationship with a
    # cascade: the ledger is financial history and is never deleted, and a
    # follow-up must not be able to reach back and change it.
    record_id = db.Column(db.Integer, db.ForeignKey('amc_recovery_records.id'),
                          nullable=False, index=True)

    due_date = db.Column(db.Date, nullable=False, index=True)
    match_day = db.Column(db.Integer, nullable=False)
    match_month = db.Column(db.Integer, nullable=False)

    # Denormalised so the day's list can be grouped, sorted and read without
    # touching the ledger, and so it still reads correctly if the customer is
    # later renamed in SJ_MIS - this is what was true on the day.
    client_id = db.Column(db.Integer, index=True)
    client_name = db.Column(db.String(200))
    registration_no = db.Column(db.String(50), index=True)
    installation_date = db.Column(db.Date)
    outstanding_amount = db.Column(db.Float, default=0.0)

    assigned_officer_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)

    work_status = db.Column(db.String(20), default=STATUS_PENDING, nullable=False)
    remarks = db.Column(db.Text)
    last_contacted_at = db.Column(db.DateTime)

    record = db.relationship('AmcRecoveryRecord', foreign_keys=[record_id])
    assigned_officer = db.relationship('User', foreign_keys=[assigned_officer_id])

    __table_args__ = (
        # One vehicle appears once on a day's list. The ledger holds a row
        # per AMC period, so the same vehicle is in it several times over;
        # without this the officer would be handed the same call repeatedly.
        db.UniqueConstraint('registration_no', 'due_date',
                            name='uq_amc_db_assignment_vehicle_due_date'),
    )

    def officer_name(self) -> str:
        officer = self.assigned_officer
        if not officer:
            return 'Unassigned'
        return officer.name or officer.username

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'record_id': self.record_id,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'client_id': self.client_id,
            'client_name': self.client_name,
            'registration_no': self.registration_no,
            'installation_date': self.installation_date.isoformat() if self.installation_date else None,
            'outstanding_amount': self.outstanding_amount or 0.0,
            'assigned_officer_id': self.assigned_officer_id,
            'assigned_officer_name': self.officer_name(),
            'work_status': self.work_status,
            'remarks': self.remarks,
            'last_contacted_at': self.last_contacted_at.isoformat() if self.last_contacted_at else None,
        }

    def __repr__(self) -> str:
        return (f"<AmcDatabaseAssignment {self.registration_no} "
                f"due={self.due_date} officer={self.assigned_officer_id}>")
