# src/models/amc_snapshot.py
"""
AMC Snapshot Model - Immutable daily snapshots of Annual Recovery vehicle data
"""
from typing import Dict, Any

from src.extensions import db
from src.utils.timezone import get_current_time


class AmcSnapshot(db.Model):
    """Immutable daily snapshot of AMC vehicle recovery data.
    
    Once created, snapshot records cannot be modified or deleted.
    This ensures historical data integrity for auditing and reporting.
    """
    __tablename__ = 'amc_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    snapshot_date = db.Column(db.Date, nullable=False, index=True)
    
    # Vehicle identification
    vehicle_id = db.Column(db.Integer, nullable=False)
    reg_no = db.Column(db.String(100), index=True)
    
    # Installation details
    installation_date = db.Column(db.String(50), default='')
    installation_year = db.Column(db.String(10), default='')
    
    # Financial snapshot
    amc_charges = db.Column(db.Float, default=0.0)
    recovered_amount = db.Column(db.Float, default=0.0)
    outstanding = db.Column(db.Float, default=0.0)
    
    # Status at time of snapshot
    amc_status = db.Column(db.String(50), default='')
    client_name = db.Column(db.String(200), default='')
    sheet_name = db.Column(db.String(100), default='')
    
    # Immutability flag
    is_locked = db.Column(db.Boolean, default=True, nullable=False)
    
    # Metadata
    created_at = db.Column(db.DateTime, default=get_current_time)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'snapshot_date': self.snapshot_date.isoformat() if self.snapshot_date else '',
            'vehicle_id': self.vehicle_id,
            'reg_no': self.reg_no or '',
            'installation_date': self.installation_date or '',
            'installation_year': self.installation_year or '',
            'amc_charges': self.amc_charges or 0.0,
            'recovered_amount': self.recovered_amount or 0.0,
            'outstanding': self.outstanding or 0.0,
            'amc_status': self.amc_status or '',
            'client_name': self.client_name or '',
            'sheet_name': self.sheet_name or '',
            'is_locked': self.is_locked,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else ''
        }


# Prevent updates to locked snapshots
@db.event.listens_for(AmcSnapshot, 'before_update')
def prevent_locked_snapshot_update(mapper, connection, target):
    """Raise error if attempting to modify a locked snapshot record"""
    if target.is_locked:
        raise ValueError(f"AMC Snapshot #{target.id} is locked and cannot be modified")


# Prevent deletion of locked snapshots
@db.event.listens_for(AmcSnapshot, 'before_delete')
def prevent_locked_snapshot_delete(mapper, connection, target):
    """Raise error if attempting to delete a locked snapshot record"""
    if target.is_locked:
        raise ValueError(f"AMC Snapshot #{target.id} is locked and cannot be deleted")
