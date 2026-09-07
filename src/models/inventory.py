# src/models/inventory.py
"""
Inventory Module - GPS device stock synced from SJ_MIS's gs_objects table,
extended locally with which technician currently holds a device and whether
it has since been installed on a vehicle via the Installation or REDO module.
"""
from typing import Dict, Any, Optional
from datetime import timedelta

from src.extensions import db
from src.models.base import BaseModel
from src.utils.timezone import get_current_time


class InventoryDevice(BaseModel):
    """A single GPS tracker unit (by IMEI), mirrored from SJ_MIS gs_objects
    and extended with local stock/assignment tracking."""
    __tablename__ = 'inventory_devices'

    STATUS_IN_STOCK = 'IN_STOCK'
    STATUS_ASSIGNED = 'ASSIGNED'
    STATUS_INSTALLED = 'INSTALLED'
    STATUS_RETURNED = 'RETURNED'

    # Mirrored from SJ_MIS gs_objects (source of truth is SJ_MIS; re-synced
    # periodically, not user-editable here)
    gs_object_id = db.Column(db.String(50), index=True)
    imei = db.Column(db.String(50), unique=True, nullable=False, index=True)
    sim_number = db.Column(db.String(50))
    device_name = db.Column(db.String(200))
    plate_number = db.Column(db.String(50))
    dt_server = db.Column(db.DateTime)
    dt_tracker = db.Column(db.DateTime)
    gs_last_update = db.Column(db.DateTime)
    last_synced_at = db.Column(db.DateTime)

    # Local stock/assignment tracking
    status = db.Column(db.String(20), default=STATUS_IN_STOCK, nullable=False, index=True)
    assigned_technician_id = db.Column(db.Integer, db.ForeignKey('technicians.id'))
    assigned_at = db.Column(db.DateTime)
    assigned_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    installed_registration_no = db.Column(db.String(50))
    installed_at = db.Column(db.DateTime)
    notes = db.Column(db.Text)

    assigned_technician = db.relationship('Technician', foreign_keys=[assigned_technician_id])
    assigned_by_user = db.relationship('User', foreign_keys=[assigned_by])

    def is_reporting(self, hours: int = 24) -> bool:
        """Whether this device has pinged SJ_MIS within the last N hours,
        based on the most recent of dt_server/dt_tracker from the sync."""
        ref = self.dt_server or self.dt_tracker
        if not ref:
            return False
        now = get_current_time()
        if ref.tzinfo is None and now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        elif ref.tzinfo is not None and now.tzinfo is None:
            ref = ref.replace(tzinfo=None)
        return (now - ref) < timedelta(hours=hours)

    def assign_to(self, technician_id: int, user_id: int) -> None:
        """Issue this device to a technician's field stock."""
        self.status = self.STATUS_ASSIGNED
        self.assigned_technician_id = technician_id
        self.assigned_at = get_current_time()
        self.assigned_by = user_id
        db.session.commit()

    def unassign(self) -> None:
        """Return this device to general stock."""
        self.status = self.STATUS_IN_STOCK
        self.assigned_technician_id = None
        self.assigned_at = None
        self.assigned_by = None
        db.session.commit()

    def mark_installed(self, registration_no: str) -> None:
        """Record that this device has actually been installed on a
        vehicle, as reported by the Installation or REDO module."""
        self.status = self.STATUS_INSTALLED
        self.installed_registration_no = registration_no
        self.installed_at = get_current_time()
        db.session.commit()

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'imei': self.imei,
            'sim_number': self.sim_number,
            'device_name': self.device_name,
            'plate_number': self.plate_number,
            'dt_server': self.dt_server.isoformat() if self.dt_server else None,
            'dt_tracker': self.dt_tracker.isoformat() if self.dt_tracker else None,
            'is_reporting': self.is_reporting(),
            'status': self.status,
            'assigned_technician_id': self.assigned_technician_id,
            'assigned_technician_name': self.assigned_technician.name if self.assigned_technician else None,
            'assigned_at': self.assigned_at.isoformat() if self.assigned_at else None,
            'installed_registration_no': self.installed_registration_no,
            'installed_at': self.installed_at.isoformat() if self.installed_at else None,
            'notes': self.notes,
            'last_synced_at': self.last_synced_at.isoformat() if self.last_synced_at else None,
        }

    def __repr__(self) -> str:
        return f"<InventoryDevice {self.imei} - {self.status}>"


class InventoryStockItem(BaseModel):
    """Monthly stock ledger for non-GPS-device inventory: accessories
    (tape, relays, sensors, converters, etc.) and old/legacy stock issue.
    Separate from InventoryDevice, which tracks individual GPS trackers by
    IMEI - these are consumable/bulk items counted by quantity, entered
    manually each month by whoever manages physical stock (mirrors the
    "SUMMARY FOR THE MONTH" report shared by the Inventory Manager)."""
    __tablename__ = 'inventory_stock_items'

    CATEGORY_ACCESSORY = 'ACCESSORY'
    CATEGORY_OLD_STOCK = 'OLD_STOCK'

    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(20), nullable=False, default=CATEGORY_ACCESSORY)
    period = db.Column(db.String(7), nullable=False, index=True)  # 'YYYY-MM'
    total_received = db.Column(db.Float, default=0)
    total_issued = db.Column(db.Float, default=0)
    notes = db.Column(db.Text)

    __table_args__ = (
        db.UniqueConstraint('name', 'category', 'period', name='uq_stock_item_name_category_period'),
    )

    def get_remaining(self) -> float:
        return (self.total_received or 0) - (self.total_issued or 0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'category': self.category,
            'period': self.period,
            'total_received': self.total_received,
            'total_issued': self.total_issued,
            'remaining': self.get_remaining(),
            'notes': self.notes,
        }

    def __repr__(self) -> str:
        return f"<InventoryStockItem {self.name} ({self.category}) {self.period}>"


class TechnicianStockIssuance(BaseModel):
    """How many accessory units were issued to a technician on a given
    day. The technician list this is entered against is always read live
    from the Technician table, so it stays current as technicians are
    added or removed - nothing here is a hardcoded roster."""
    __tablename__ = 'technician_stock_issuances'

    technician_id = db.Column(db.Integer, db.ForeignKey('technicians.id'), nullable=False, index=True)
    issue_date = db.Column(db.Date, nullable=False, index=True)
    quantity = db.Column(db.Float, default=0)
    notes = db.Column(db.Text)

    technician = db.relationship('Technician', foreign_keys=[technician_id])

    __table_args__ = (
        db.UniqueConstraint('technician_id', 'issue_date', name='uq_tech_issuance_technician_date'),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'technician_id': self.technician_id,
            'technician_name': self.technician.name if self.technician else None,
            'issue_date': self.issue_date.isoformat() if self.issue_date else None,
            'quantity': self.quantity,
            'notes': self.notes,
        }

    def __repr__(self) -> str:
        return f"<TechnicianStockIssuance tech={self.technician_id} {self.issue_date} qty={self.quantity}>"
