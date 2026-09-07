# src/models/vehicle_registry.py
"""
Vehicle Registry - the local dump of SJ_MIS's master vehicle roster.

Every vehicle SJ_MIS knows about, cached here so the CRM can find any of
them without depending on SJ_MIS being reachable at the moment somebody
types into a search box.

Why a dump rather than a live query: the other local tables each hold a
*slice* of the fleet and only ever grow by side effect - NonReportingVehicle
holds vehicles that have gone quiet, PurchaseOrder holds vehicles we
installed through this system, RedoActivity holds vehicles that have been
serviced since. A vehicle whose device has worked perfectly since an
installation that predates this CRM appears in none of them, so the only way
to find it was a live SJ_MIS query - which is bounded to a few seconds and
returns nothing at all when the link is down. This table closes that gap.

Rows are refreshed in place by registration number and are never deleted:
a complaint or a service record can still refer to a vehicle SJ_MIS has
since retired from its own roster, and that history has to stay findable.
"""
from datetime import datetime
from typing import Any, Dict

from src.extensions import db
from src.models.base import BaseModel


class VehicleRegistryEntry(BaseModel):
    """One vehicle on the SJ_MIS master roster, as of the last sync."""
    __tablename__ = 'vehicle_registry'

    # SJ_MIS's own vehicle id. Kept so a row can be traced back to its
    # source, and so a re-registered vehicle can be recognised as the same
    # physical vehicle even after its plate changes.
    sj_vehicle_id = db.Column(db.Integer, unique=True, index=True)
    client_id = db.Column(db.Integer, index=True)

    registration_no = db.Column(db.String(50), nullable=False, index=True)
    imei_no = db.Column(db.String(50), index=True)
    sim_no = db.Column(db.String(50), index=True)
    engine_no = db.Column(db.String(50))
    chassis_no = db.Column(db.String(50))
    unit_location = db.Column(db.String(200))
    vehicle_status = db.Column(db.String(50))

    # The vehicle's specification, named the way SJ_MIS names it - which is
    # also the way the business says it. `Manufacturer` is the marque
    # (Toyota), `Brand` the particular vehicle (Corolla), and `ModelYear` the
    # year, which is what "model" means in conversation here.
    #
    # Transmission and power are on the source table but thinly filled -
    # roughly a fifth of vehicles carry a usable transmission and three
    # percent a capacity - so both are cleaned on the way in and simply
    # absent where nothing real was recorded. A Purchase Order can record
    # them properly for vehicles this CRM handles.
    manufacturer = db.Column(db.String(50), index=True)
    brand = db.Column(db.String(50))
    model_year = db.Column(db.String(10))
    color = db.Column(db.String(30))
    transmission = db.Column(db.String(20))
    power_cc = db.Column(db.String(20))

    customer_name = db.Column(db.String(200))
    emergency_mobile = db.Column(db.String(50))
    cell1 = db.Column(db.String(50))
    cell2 = db.Column(db.String(50))
    res_phone = db.Column(db.String(50))
    office_phone = db.Column(db.String(50))
    secondary_users = db.Column(db.String(300))

    # When the device last spoke to the server, as of the sync. Enough to
    # say whether the vehicle was reporting; the live position still comes
    # from CurrentLocation.
    last_signal_at = db.Column(db.DateTime)

    synced_at = db.Column(db.DateTime, default=datetime.utcnow)

    def contact_numbers(self) -> list:
        """Every number on file for this customer, best first, no blanks and
        no repeats."""
        ordered = [self.emergency_mobile, self.cell1, self.cell2,
                   self.res_phone, self.office_phone]
        seen = []
        for number in ordered:
            value = (number or '').strip()
            if value and value not in seen:
                seen.append(value)
        return seen

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'sj_vehicle_id': self.sj_vehicle_id,
            'registration_no': self.registration_no,
            'imei_no': self.imei_no,
            'sim_no': self.sim_no,
            'engine_no': self.engine_no,
            'chassis_no': self.chassis_no,
            'unit_location': self.unit_location,
            'vehicle_status': self.vehicle_status,
            'manufacturer': self.manufacturer,
            'brand': self.brand,
            'model_year': self.model_year,
            'color': self.color,
            'transmission': self.transmission,
            'power_cc': self.power_cc,
            'customer_name': self.customer_name,
            'contact_numbers': self.contact_numbers(),
            'last_signal_at': self.last_signal_at.isoformat() if self.last_signal_at else None,
            'synced_at': self.synced_at.isoformat() if self.synced_at else None,
        }

    def __repr__(self) -> str:
        return f"<VehicleRegistryEntry {self.registration_no}>"
