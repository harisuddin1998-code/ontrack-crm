# src/models/annual_recovery.py
"""
Annual Recovery Models for Vehicle Device Monitoring & Recovery
"""
from datetime import datetime
from typing import Dict, Any
from sqlalchemy import Index

from src.extensions import db
from src.utils.timezone import get_current_time


class AnnualRecoveryClient(db.Model):
    """Client model for Annual Monitoring Recovery"""
    __tablename__ = 'recovery_clients'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    cell1 = db.Column(db.String(50), default='')
    employee_name = db.Column(db.String(200), default='')
    total_amc_charges = db.Column(db.Float, default=0.0)
    total_recovered = db.Column(db.Float, default=0.0)
    total_lost = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    vehicles = db.relationship('AnnualRecoveryVehicle', backref='client', lazy=True, cascade='all, delete-orphan')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def get_outstanding(self) -> float:
        total_amc = self.total_amc_charges if self.total_amc_charges else 0.0
        total_rec = self.total_recovered if self.total_recovered else 0.0
        total_lost_amt = self.total_lost if self.total_lost else 0.0
        return total_amc - total_rec - total_lost_amt

    def to_dict(self, vehicles=None) -> Dict[str, Any]:
        """Describe this client over a given set of its vehicles.

        `vehicles` is the set the caller is actually showing - one sheet, or
        the sheets a recovery officer is assigned. The totals are summed from
        that same set, so the figures printed above a list of vehicles are
        always the total of the vehicles in that list.

        This used to return the stored client-level columns regardless, which
        sum every vehicle the client owns on every sheet. The rows were scoped
        and the header was not, so an officer assigned one sheet read a total
        that included money from sheets they cannot open, and a supervisor
        filtering to a single sheet got a header that ignored the filter.

        Omitting the argument describes the client's whole book, which is what
        the stored columns mean and what an unfiltered supervisor view wants.
        """
        scoped = self.vehicles if vehicles is None else list(vehicles)

        total_amc = sum(v.amc_charges or 0.0 for v in scoped)
        total_recovered = sum(v.recovered_amount or 0.0 for v in scoped)
        # Lost is derived from vehicle status rather than the stored column,
        # matching how the dashboard's own stat cards count it - otherwise the
        # card at the top of the page and the card in the list disagree.
        total_lost = sum(v.amc_charges or 0.0 for v in scoped if v.status == 'LOST')

        return {
            'id': self.id,
            'name': self.name.upper() if self.name else '',
            'cell1': self.cell1.upper() if self.cell1 else '',
            'employeeName': self.employee_name.upper() if self.employee_name else '',
            'totalAmcCharges': total_amc,
            'totalRecovered': total_recovered,
            'totalLost': total_lost,
            'outstanding': total_amc - total_recovered - total_lost,
            'vehicles': [v.to_dict() for v in scoped]
        }


class AnnualRecoveryVehicle(db.Model):
    """Vehicle model for Annual Monitoring Recovery"""
    __tablename__ = 'recovery_vehicles'

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('recovery_clients.id', ondelete='CASCADE'))
    reg_no = db.Column(db.String(100), index=True)
    installation_date = db.Column(db.String(50), default='')
    installation_year = db.Column(db.String(10), default='')
    amc_charges = db.Column(db.Float, default=0.0)
    recovered_amount = db.Column(db.Float, default=0.0)
    remarks = db.Column(db.Text, default='')
    status = db.Column(db.String(50), default='PENDING')
    sheet_name = db.Column(db.String(100), default='')
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    assigned_user = db.relationship('User', foreign_keys=[assigned_to])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def get_outstanding(self) -> float:
        return (self.amc_charges or 0.0) - (self.recovered_amount or 0.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'regNo': self.reg_no.upper() if self.reg_no else '',
            'installationDate': self.installation_date or '',
            'installationYear': self.installation_year or '',
            'amcCharges': self.amc_charges or 0.0,
            'recoveredAmount': self.recovered_amount or 0.0,
            'outstanding': self.get_outstanding(),
            'remarks': self.remarks.upper() if self.remarks else '',
            'status': self.status.upper() if self.status else '',
            'sheetName': self.sheet_name or '',
            'assignedTo': self.assigned_to,
            'assignedToName': self.assigned_user.username if self.assigned_user else None
        }


Index('idx_rec_vehicles_reg_no', AnnualRecoveryVehicle.reg_no)
Index('idx_rec_vehicles_status', AnnualRecoveryVehicle.status)


class AnnualRecoveryFollowup(db.Model):
    """Follow-up records for Annual Monitoring Recovery"""
    __tablename__ = 'recovery_followups'

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('recovery_clients.id', ondelete='CASCADE'))
    vehicle_id = db.Column(db.Integer, db.ForeignKey('recovery_vehicles.id', ondelete='CASCADE'))
    note = db.Column(db.Text, nullable=False)
    next_date = db.Column(db.String(50), default='')
    created_by = db.Column(db.String(100), default='System')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'note': self.note,
            'nextDate': self.next_date or '',
            'createdBy': self.created_by,
            'date': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else ''
        }


class AnnualRecoveryHistory(db.Model):
    """Payment history records for Annual Monitoring Recovery"""
    __tablename__ = 'recovery_history_records'

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('recovery_clients.id', ondelete='CASCADE'))
    vehicle_id = db.Column(db.Integer, db.ForeignKey('recovery_vehicles.id', ondelete='CASCADE'))
    amount = db.Column(db.Float, default=0.0)
    payment_date = db.Column(db.String(50), default='')
    reference_no = db.Column(db.String(100), default='')
    payment_method = db.Column(db.String(50), default='Cash')
    cheque_status = db.Column(db.String(50), default='')
    proof_of_payment_path = db.Column(db.String(255))
    notes = db.Column(db.Text, default='')
    is_locked = db.Column(db.Boolean, default=False, nullable=False)
    # When the payment was recorded, in Pakistan time. This was `utcnow`,
    # which put every recovery on the history five hours earlier than it
    # happened - a payment taken at 09:00 read as 04:00, and one taken after
    # 19:00 read as the previous day. It is also the column the dashboard's
    # "AMC income received today" counts against, so the same five hours were
    # falling out of that figure each evening. Rows written before this
    # change still hold UTC and read five hours early.
    created_at = db.Column(db.DateTime, default=get_current_time)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'amount': self.amount or 0.0,
            'paymentDate': self.payment_date or '',
            'referenceNo': self.reference_no or '',
            'paymentMethod': self.payment_method or 'Cash',
            'chequeStatus': self.cheque_status or '',
            'proofOfPaymentPath': self.proof_of_payment_path or '',
            'notes': self.notes or '',
            'isLocked': self.is_locked,
            # Date *and* time - a recovery ledger has to say when, not just
            # which day, since several payments can land against one vehicle.
            'date': self.created_at.strftime('%d %b %Y, %H:%M') if self.created_at else ''
        }


# Prevent updates to locked recovery history records
@db.event.listens_for(AnnualRecoveryHistory, 'before_update')
def prevent_locked_history_update(mapper, connection, target):
    """Raise error if attempting to modify a locked payment recovery record"""
    if target.is_locked:
        raise ValueError(f"Recovery history record #{target.id} is locked and cannot be modified")


# Prevent deletion of locked recovery history records
@db.event.listens_for(AnnualRecoveryHistory, 'before_delete')
def prevent_locked_history_delete(mapper, connection, target):
    """Raise error if attempting to delete a locked payment recovery record"""
    if target.is_locked:
        raise ValueError(f"Recovery history record #{target.id} is locked and cannot be deleted")


class AnnualRecoveryAuditLog(db.Model):
    """Audit logs for Annual Monitoring Recovery module actions"""
    __tablename__ = 'recovery_audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    user = db.Column(db.String(100), default='System')
    action = db.Column(db.String(200), nullable=False)
    details = db.Column(db.Text, default='')
    ip_address = db.Column(db.String(50), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'user': self.user,
            'action': self.action,
            'details': self.details,
            'ip_address': self.ip_address,
            'date': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else ''
        }
