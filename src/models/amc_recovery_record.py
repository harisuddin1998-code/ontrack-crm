# src/models/amc_recovery_record.py
"""
AMC Recoveries - Database Method. A synced snapshot of SJ_MIS's AMCInfo
table (the authoritative AMC payment/collection ledger - real money
collected, with cheque/bank/transaction detail), denormalized with vehicle,
client, install-date and live GPS context at sync time.

This is the second of the two AMC tracking methods requested: the "Sheet
Method" (Live AMC / Annual Recovery, driven by the imported spreadsheet
data in AnnualRecoveryVehicle, with daily round-robin officer assignment)
and this "Database Method" (a read-only extraction straight from SJ_MIS's
own payment ledger, used to see/verify what has actually been recorded as
collected in the source system).

Records are financial history and must never be deleted or overwritten
into oblivion once synced - sync() upserts by serial_id (refreshing
denormalized display fields like phone numbers or GPS status, which do
legitimately change over time) but never removes a locally-synced row,
even if a later sync no longer sees that serial_id in SJ_MIS.
"""
from typing import Any, Dict, Optional

from src.extensions import db
from src.models.base import BaseModel


class AmcRecoveryRecord(BaseModel):
    __tablename__ = 'amc_recovery_records'

    serial_id = db.Column(db.Integer, unique=True, nullable=False, index=True)

    vehicle_id = db.Column(db.Integer, index=True)
    client_id = db.Column(db.Integer, index=True)

    registration_no = db.Column(db.String(50), index=True)
    imei = db.Column(db.String(50))
    vehicle_status = db.Column(db.String(50))

    client_name = db.Column(db.String(200))
    res_phone = db.Column(db.String(50))
    office_phone = db.Column(db.String(50))
    cell1 = db.Column(db.String(50))
    cell2 = db.Column(db.String(50))
    is_defaulter = db.Column(db.Boolean, default=False)
    secondary_user1 = db.Column(db.String(50))
    secondary_user2 = db.Column(db.String(50))
    secondary_user3 = db.Column(db.String(50))
    secondary_user4 = db.Column(db.String(50))

    installation_date = db.Column(db.Date)

    receivable_amount = db.Column(db.Float, default=0)
    received_amount = db.Column(db.Float, default=0)
    discount_amount = db.Column(db.Float, default=0)
    commission = db.Column(db.Float, default=0)
    paid_amount = db.Column(db.Float, default=0)

    from_year = db.Column(db.String(10))
    to_year = db.Column(db.String(10))

    payment_type = db.Column(db.String(50))
    transaction_id = db.Column(db.String(50))
    payment_date = db.Column(db.DateTime)
    cheque_number = db.Column(db.String(50))
    bank = db.Column(db.String(100))
    collection_date = db.Column(db.DateTime)
    collected_by = db.Column(db.String(100))

    last_gps_at = db.Column(db.DateTime)
    last_gps_address = db.Column(db.String(300))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)

    synced_at = db.Column(db.DateTime)

    def get_outstanding(self) -> float:
        return max(0.0, (self.receivable_amount or 0) - (self.received_amount or 0) - (self.discount_amount or 0))

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'serial_id': self.serial_id,
            'registration_no': self.registration_no,
            'client_name': self.client_name,
            'from_year': self.from_year,
            'to_year': self.to_year,
            'receivable_amount': self.receivable_amount,
            'received_amount': self.received_amount,
            'outstanding': self.get_outstanding(),
            'payment_type': self.payment_type,
            'collection_date': self.collection_date.isoformat() if self.collection_date else None,
            'synced_at': self.synced_at.isoformat() if self.synced_at else None,
        }

    def __repr__(self) -> str:
        return f"<AmcRecoveryRecord {self.registration_no} {self.from_year}-{self.to_year}>"
