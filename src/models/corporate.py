# src/models/corporate.py
"""
Corporate Fleet Roster - which vehicles belong to a "corporate" client (5+
vehicle fleet), synced from SJ_MIS's Vehicles+Clients tables. Used to scope
the Corporate Non-Reporting dashboard to fleet customers only.
"""
from typing import Dict, Any

from src.extensions import db
from src.models.base import BaseModel


class CorporateVehicle(BaseModel):
    """A single vehicle belonging to a client with 5+ vehicles in SJ_MIS.
    This is a derived roster/cache, fully replaced on each sync - not
    user-edited data."""
    __tablename__ = 'corporate_vehicles'

    registration_no = db.Column(db.String(50), unique=True, nullable=False, index=True)
    client_id = db.Column(db.String(50), index=True)
    client_name = db.Column(db.String(200))
    fleet_size = db.Column(db.Integer)
    synced_at = db.Column(db.DateTime)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'registration_no': self.registration_no,
            'client_id': self.client_id,
            'client_name': self.client_name,
            'fleet_size': self.fleet_size,
            'synced_at': self.synced_at.isoformat() if self.synced_at else None,
        }

    def __repr__(self) -> str:
        return f"<CorporateVehicle {self.registration_no} - {self.client_name}>"
