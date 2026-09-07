# src/models/amc_invoice.py
"""
AMC Invoice ledger - a record of every Annual Recovery invoice raised.

An invoice used to be a document generated on demand and forgotten: the PDF
went out and nothing in the CRM knew it had ever existed. That made three
things impossible - reissuing an invoice under the same number, telling how
many invoices were raised in a period, and seeing the difference between what
a customer owed and what they were actually billed.

That difference is the point of this table. An officer settling a fleet often
invoices below the outstanding balance, and until now the concession vanished
the moment the PDF was downloaded. Here it is recorded as `discount_amount`
against the officer who granted it.

Every figure is stored rather than derived. An invoice is a point-in-time
document: it says what was owed and what was charged on the day it was
raised, and it must keep saying that after the underlying vehicle rows have
moved on.
"""
from datetime import datetime
from typing import Any, Dict

from src.extensions import db
from src.utils.timezone import get_current_time


class AmcInvoice(db.Model):
    """One raised AMC invoice - vehicle-wise or customer-wise."""
    __tablename__ = 'amc_invoices'

    # How the invoice was raised. Vehicle-wise bills one vehicle;
    # customer-wise bills every billable vehicle a customer owns on the
    # sheets the officer may see.
    BASIS_VEHICLE = 'VEHICLE'
    BASIS_CUSTOMER = 'CUSTOMER'

    id = db.Column(db.Integer, primary_key=True)

    # AMC_ONT_<4-char customer code>_<YYYYMMDD-HHMMSS>. Unique in the
    # database, not just by construction - two invoices raised for the same
    # customer inside the same second must not be able to share a number.
    invoice_number = db.Column(db.String(60), unique=True, nullable=False, index=True)

    basis = db.Column(db.String(10), nullable=False, default=BASIS_CUSTOMER)

    client_id = db.Column(db.Integer, db.ForeignKey('recovery_clients.id'), index=True)
    # Null on a customer-wise invoice, which covers many vehicles.
    vehicle_id = db.Column(db.Integer, db.ForeignKey('recovery_vehicles.id'), index=True)

    client_name = db.Column(db.String(200), default='')
    vehicle_count = db.Column(db.Integer, default=0, nullable=False)
    sheet_names = db.Column(db.String(300), default='')

    # What the vehicles on this invoice were worth when it was raised.
    total_charges = db.Column(db.Float, default=0.0, nullable=False)
    total_received = db.Column(db.Float, default=0.0, nullable=False)
    # Charges less receipts, floored at zero - what the customer owed.
    outstanding_amount = db.Column(db.Float, default=0.0, nullable=False)
    # What the invoice was actually raised for. Equal to outstanding unless
    # the officer overrode it.
    invoiced_amount = db.Column(db.Float, default=0.0, nullable=False)
    # outstanding_amount - invoiced_amount, floored at zero. Stored rather
    # than computed on read so the report and the dashboard agree with the
    # document that was sent, forever.
    discount_amount = db.Column(db.Float, default=0.0, nullable=False)
    # Why the officer billed under the balance. Only meaningful with a
    # discount, and required by the route when one is granted.
    discount_reason = db.Column(db.String(300), default='')

    generated_by = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    created_at = db.Column(db.DateTime, default=get_current_time, nullable=False, index=True)

    client = db.relationship('AnnualRecoveryClient', foreign_keys=[client_id])
    vehicle = db.relationship('AnnualRecoveryVehicle', foreign_keys=[vehicle_id])
    generated_by_user = db.relationship('User', foreign_keys=[generated_by])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @property
    def is_discounted(self) -> bool:
        return (self.discount_amount or 0.0) > 0

    @property
    def basis_label(self) -> str:
        return 'Vehicle-wise' if self.basis == self.BASIS_VEHICLE else 'Customer-wise'

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'invoiceNumber': self.invoice_number,
            'basis': self.basis,
            'basisLabel': self.basis_label,
            'clientId': self.client_id,
            'clientName': self.client_name or '',
            'vehicleId': self.vehicle_id,
            'vehicleCount': self.vehicle_count or 0,
            'sheetNames': self.sheet_names or '',
            'totalCharges': self.total_charges or 0.0,
            'totalReceived': self.total_received or 0.0,
            'outstandingAmount': self.outstanding_amount or 0.0,
            'invoicedAmount': self.invoiced_amount or 0.0,
            'discountAmount': self.discount_amount or 0.0,
            'discountReason': self.discount_reason or '',
            'generatedBy': (self.generated_by_user.name or self.generated_by_user.username)
                           if self.generated_by_user else None,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<AmcInvoice {self.invoice_number} {self.invoiced_amount:.2f}>"
