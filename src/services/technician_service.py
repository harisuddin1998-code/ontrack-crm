# src/services/technician_service.py
"""
Technician Service - Technician and bike management
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from math import radians, sin, cos, sqrt, asin

from src.models.technician import Technician, TechnicianBike, TechnicianTrip, PetrolRate, FuelReimbursementInvoice
from src.repositories.technician_repository import (
    TechnicianRepository, TechnicianBikeRepository, TechnicianTripRepository
)
from src.repositories.base_repository import BaseRepository  # ✅ ADD THIS
from src.services.base_service import BaseService
from src.services.gps_service import GPSService
from src.extensions import db
from src.utils.timezone import get_current_time, get_current_date
from src.utils.logging import get_logger

logger = get_logger(__name__)


class TechnicianService(BaseService[Technician]):
    """Service for technician operations"""
    
    def __init__(self):
        super().__init__(TechnicianRepository())
        self.tech_repo = TechnicianRepository()
        self.gps_service = GPSService()
    
    def get_all_technicians(self, active_only: bool = True) -> List[Technician]:
        """Get all technicians"""
        if active_only:
            return self.tech_repo.get_active_technicians()
        return self.tech_repo.get_all()

    @staticmethod
    def get_roster() -> List[Technician]:
        """The technician roster, as maintained in Technician Management.

        Every technician picker in the CRM reads this one list, so a person
        offered as a technician anywhere is a technician who exists here and
        is still active. Ordered by name because that is how a dropdown is
        read; a roster ordered by insertion id makes people hunt.
        """
        return Technician.query.filter_by(is_active=True).order_by(Technician.name).all()
    
    def get_technician(self, technician_id: int) -> Optional[Technician]:
        """Get technician by ID"""
        return self.tech_repo.get_by_id(technician_id)
    
    def get_technician_by_name(self, name: str) -> Optional[Technician]:
        """Get technician by name"""
        return self.tech_repo.get_by_name(name)
    
    def create_technician(self, data: Dict[str, Any]) -> Technician:
        """Create a new technician"""
        data = self.sanitize_data(data)

        name = data.get('name')
        if not name:
            raise ValueError("Technician name is required")
        if self.get_technician_by_name(name):
            raise ValueError(f"Technician '{name}' already exists")

        return self.tech_repo.create(**data)
    
    def update_technician(self, technician_id: int, data: Dict[str, Any]) -> Optional[Technician]:
        """Update a technician"""
        data = self.sanitize_data(data)
        
        name = data.get('name')
        if name:
            existing = self.get_technician_by_name(name)
            if existing and existing.id != technician_id:
                raise ValueError(f"Technician '{name}' already exists")
        
        return self.tech_repo.update(technician_id, **data)
    
    def get_technician_with_bike(self, technician_id: int) -> Optional[Technician]:
        """Get technician with bike details"""
        return self.get_technician(technician_id)
    
    def get_technicians_with_bikes(self) -> List[Technician]:
        """Get all technicians with their bikes"""
        return self.tech_repo.get_with_bike()
    
    def get_available_technicians(self) -> List[Technician]:
        """Get technicians available for assignment (with bike, active)"""
        return self.tech_repo.get_with_bike()
    
    def get_technician_trips(self, technician_id: int, start_date: Optional[date] = None, 
                             end_date: Optional[date] = None) -> List[TechnicianTrip]:
        """Get trips for a technician"""
        trip_service = TechnicianTripService()
        return trip_service.get_by_technician(technician_id, start_date, end_date)


class TechnicianBikeService(BaseService[TechnicianBike]):
    """Service for technician bike operations"""
    
    def __init__(self):
        super().__init__(TechnicianBikeRepository())
        self.bike_repo = TechnicianBikeRepository()
    
    def get_by_imei(self, imei: str) -> Optional[TechnicianBike]:
        """Get bike by IMEI number"""
        return self.bike_repo.get_by_imei(imei)
    
    def assign_bike(self, technician_id: int, imei: str, registration: str, 
                    model: Optional[str] = None, fuel_efficiency: float = 35.0) -> TechnicianBike:
        """Assign a bike to a technician"""
        existing = self.bike_repo.get_by_technician(technician_id)
        if existing:
            raise ValueError(f"Technician ID {technician_id} already has a bike assigned")
        
        imei_exists = self.get_by_imei(imei)
        if imei_exists:
            raise ValueError(f"IMEI '{imei}' is already assigned to another bike")
        
        return self.bike_repo.create(
            technician_id=technician_id,
            imei=imei,
            bike_registration=registration.upper(),
            bike_model=model.upper() if model else None,
            fuel_efficiency=fuel_efficiency,
            is_active=True
        )
    
    def update_bike(self, bike_id: int, data: Dict[str, Any]) -> Optional[TechnicianBike]:
        """Update bike details"""
        data = self.sanitize_data(data)
        
        imei = data.get('imei')
        if imei:
            existing = self.get_by_imei(imei)
            if existing and existing.id != bike_id:
                raise ValueError(f"IMEI '{imei}' is already assigned to another bike")
        
        return self.bike_repo.update(bike_id, **data)
    
    def get_bike_by_technician(self, technician_id: int) -> Optional[TechnicianBike]:
        """Get bike by technician ID"""
        return self.bike_repo.get_by_technician(technician_id)
    
    def get_bike_by_imei(self, imei: str) -> Optional[TechnicianBike]:
        """Get bike by IMEI"""
        return self.bike_repo.get_by_imei(imei)
    
    def get_bike_location(self, bike_id: int) -> Optional[Dict[str, Any]]:
        """Get current location of a bike"""
        bike = self.bike_repo.get_by_id(bike_id)
        if not bike:
            return None
        
        from src.services.gps_service import GPSService
        gps_service = GPSService()
        return gps_service.get_location_by_imei(bike.imei)
    
    def deactivate_bike(self, bike_id: int) -> Optional[TechnicianBike]:
        """Deactivate a bike"""
        return self.bike_repo.update(bike_id, is_active=False)
    
    def activate_bike(self, bike_id: int) -> Optional[TechnicianBike]:
        """Activate a bike"""
        return self.bike_repo.update(bike_id, is_active=True)


class TechnicianTripService(BaseService[TechnicianTrip]):
    """Service for technician trip operations"""
    
    def __init__(self):
        super().__init__(TechnicianTripRepository())
        self.trip_repo = TechnicianTripRepository()
    
    def create_trip(self, po_id: int, technician_id: int, imei: str, 
                    start_lat: float, start_lng: float, start_address: Optional[str] = None) -> TechnicianTrip:
        """Create a new trip"""
        existing_trips = self.trip_repo.get_by_po(po_id)
        trip_order = len(existing_trips) + 1
        
        previous_trip = self.trip_repo.get_latest(po_id=po_id, status='PENDING') if existing_trips else None
        
        trip = self.trip_repo.create(
            po_id=po_id,
            technician_id=technician_id,
            imei=imei,
            trip_order=trip_order,
            start_lat=str(start_lat),
            start_lng=str(start_lng),
            start_address=start_address,
            start_time=get_current_time(),
            previous_trip_id=previous_trip.id if previous_trip else None,
            status='PENDING'
        )
        
        if previous_trip:
            self._update_trip_end(previous_trip.id, start_lat, start_lng, start_address)
        
        return trip
    
    def complete_trip(self, trip_id: int, end_lat: float, end_lng: float, 
                      end_address: Optional[str] = None) -> Optional[TechnicianTrip]:
        """Complete a trip with end location"""
        trip = self.trip_repo.get_by_id(trip_id)
        if not trip:
            return None
        
        self._update_trip_end(trip_id, end_lat, end_lng, end_address)
        
        if trip.start_lat and trip.end_lat:
            # Both ends are real GPS fixes here - the technician's phone
            # reported them - so the only correction needed is road versus
            # straight line.
            distance = road_distance_km(
                (float(trip.start_lat), float(trip.start_lng), PRECISION_GPS),
                (float(trip.end_lat), float(trip.end_lng), PRECISION_GPS),
            ) or 0.0
            trip.distance_km = distance
            
            if trip.technician and trip.technician.bike:
                efficiency = trip.technician.bike.fuel_efficiency or 35.0
                trip.fuel_used_liters = round(distance / efficiency, 2)
                
                from src.services.technician_service import PetrolRateService
                petrol_rate = PetrolRateService.get_current_rate()
                trip.petrol_rate_at_time = petrol_rate
                trip.fuel_cost = round(trip.fuel_used_liters * petrol_rate, 2)
        
        trip.status = 'COMPLETED'
        trip.end_time = get_current_time()
        db.session.commit()
        
        logger.info(f"Trip {trip_id} completed with distance {trip.distance_km}km")
        return trip
    
    def _update_trip_end(self, trip_id: int, lat: float, lng: float, address: Optional[str] = None) -> None:
        """Update trip end location"""
        self.trip_repo.update(trip_id, 
            end_lat=str(lat),
            end_lng=str(lng),
            end_address=address,
            end_time=get_current_time()
        )
    
    def _calculate_distance(self, lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Calculate distance in kilometers between two points"""
        if None in (lat1, lng1, lat2, lng2):
            return 0.0
        
        R = 6371
        dlat = radians(lat2 - lat1)
        dlng = radians(lng2 - lng1)
        a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng/2)**2
        c = 2 * asin(min(1.0, sqrt(a)))
        return round(R * c, 2)
    
    def get_by_po(self, po_id: int) -> List[TechnicianTrip]:
        """Get trips by PO ID"""
        return self.trip_repo.get_by_po(po_id)
    
    def get_by_technician(self, technician_id: int, start_date: Optional[date] = None, 
                          end_date: Optional[date] = None) -> List[TechnicianTrip]:
        """Get trips by technician"""
        if start_date and end_date:
            return self.trip_repo.get_by_date_range(technician_id, start_date, end_date)
        return self.trip_repo.get_by_technician(technician_id)
    
    def get_trip_summary(self, technician_id: int, start_date: date, 
                         end_date: date) -> Dict[str, Any]:
        """Get trip summary for a technician"""
        return self.trip_repo.get_trip_summary(technician_id, start_date, end_date)


class PetrolRateService(BaseService[PetrolRate]):
    """Service for petrol rate operations"""
    
    def __init__(self):
        super().__init__(BaseRepository(PetrolRate))  # ✅ Now BaseRepository is imported
    
    @classmethod
    def get_current_rate(cls) -> float:
        """Get the current petrol rate"""
        from src.models.technician import PetrolRate
        rate = PetrolRate.query.order_by(PetrolRate.effective_date.desc()).first()
        return rate.rate_per_liter if rate else 280.0
    
    def set_rate(self, rate: float, effective_date: Optional[date] = None) -> PetrolRate:
        """Set a new petrol rate"""
        if effective_date is None:
            effective_date = get_current_date()
        
        return self.repository.create(
            rate_per_liter=rate,
            effective_date=effective_date
        )
    
    def get_rate_on_date(self, target_date: date) -> float:
        """Get petrol rate on a specific date"""
        rate = PetrolRate.query.filter(
            PetrolRate.effective_date <= target_date
        ).order_by(PetrolRate.effective_date.desc()).first()
        return rate.rate_per_liter if rate else 280.0


class FuelReimbursementInvoiceService(BaseService[FuelReimbursementInvoice]):
    """Service for fuel reimbursement invoices"""
    
    def __init__(self):
        super().__init__(BaseRepository(FuelReimbursementInvoice))
        self.trip_service = TechnicianTripService()
    
    def generate_trips_for_period(self, technician_id: int, start_date: date, end_date: date) -> None:
        """Dynamically generate and save trips for a technician for a period if not already done"""
        from datetime import timedelta
        
        tech = TechnicianService().get_by_id(technician_id)
        if not tech:
            return
            
        current_date = start_date
        while current_date <= end_date:
            self.generate_trips_for_day(tech, current_date)
            current_date += timedelta(days=1)

    def generate_trips_for_day(self, tech, target_date: date) -> List[TechnicianTrip]:
        """Generate and save trips for a technician on a specific day"""
        import re
        from datetime import datetime, timedelta
        
        # Check if completed trips already exist for this technician on this date
        # If so, do not regenerate (this locks the trips and the rate applied on that day)
        existing = TechnicianTrip.query.filter(
            TechnicianTrip.technician_id == tech.id,
            db.func.date(TechnicianTrip.end_time) == target_date
        ).all()
        if existing:
            return existing
            
        activities = []
        
        # 1. Fetch completed Installation POs
        from src.models.purchase_order import PurchaseOrder
        pos = PurchaseOrder.query.filter(
            PurchaseOrder.technician_assigned == tech.name,
            PurchaseOrder.status == 'COMPLETED',
            db.func.date(PurchaseOrder.scheduled_date) == target_date
        ).all()
        for po in pos:
            # Parse compensated fuel amount
            fuel_comp = 0.0
            if po.fuel:
                try:
                    cleaned_fuel = re.sub(r'[^\d.]', '', str(po.fuel))
                    fuel_comp = float(cleaned_fuel) if cleaned_fuel else 0.0
                except (ValueError, TypeError):
                    pass
            activities.append({
                'po_id': po.id,
                'imei': po.imei_no,
                'address': po.vehicle_availability_location or 'Installation Site',
                'time': po.updated_at or datetime.combine(target_date, datetime.min.time()),
                'fuel_compensated': fuel_comp
            })
            
        # 2. Fetch completed REDO Activities
        from src.models.redo import RedoActivity
        redos = RedoActivity.query.filter(
            RedoActivity.assigned_to == tech.id,
            RedoActivity.status == 'COMPLETED',
            db.func.date(RedoActivity.completed_at) == target_date
        ).all()
        for redo in redos:
            linked_po = PurchaseOrder.query.filter_by(reg_no=redo.registration_no).first()
            activities.append({
                'po_id': linked_po.id if linked_po else None,
                'imei': redo.imei_no,
                'address': redo.device_location or 'REDO Site',
                'time': redo.completed_at or datetime.combine(target_date, datetime.min.time()),
                'fuel_compensated': 0.0
            })
            
        # 3. Fetch completed Removals/Vehicle Flags
        from src.models.removal import VehicleFlag
        flags = VehicleFlag.query.filter(
            VehicleFlag.assigned_to == tech.id,
            VehicleFlag.status == 'COMPLETED',
            db.func.date(VehicleFlag.completed_at) == target_date
        ).all()
        for flag in flags:
            linked_po = PurchaseOrder.query.filter_by(reg_no=flag.registration_no).first()
            activities.append({
                'po_id': linked_po.id if linked_po else None,
                'imei': flag.imei_no,
                'address': flag.device_location or 'Removal Site',
                'time': flag.completed_at or datetime.combine(target_date, datetime.min.time()),
                'fuel_compensated': 0.0
            })
            
        # 4. Fetch completed Transfers
        from src.models.removal import RemovalTransferActivity
        transfers = RemovalTransferActivity.query.filter(
            RemovalTransferActivity.assigned_to == tech.id,
            RemovalTransferActivity.status == 'COMPLETED',
            db.func.date(RemovalTransferActivity.completed_at) == target_date
        ).all()
        for trans in transfers:
            linked_po = PurchaseOrder.query.filter_by(reg_no=trans.old_registration_no).first()
            activities.append({
                'po_id': linked_po.id if linked_po else None,
                'imei': trans.old_imei_no,
                'address': trans.old_device_location or 'Transfer Site',
                'time': trans.completed_at or datetime.combine(target_date, datetime.min.time()),
                'fuel_compensated': 0.0
            })
            
        if not activities:
            return []
            
        # Sort activities by completed time
        activities.sort(key=lambda x: x['time'])
        
        # Get starting location (Home)
        home_lat = tech.home_lat
        home_lng = tech.home_lng
        home_address = tech.address or "Technician Home"
        
        if home_lat and home_lng:
            # The technician's recorded home coordinates are an exact fix.
            current_point = (float(home_lat), float(home_lng), PRECISION_GPS)
        else:
            current_point = resolve_coordinates(home_address)

        current_address = home_address

        # Get petrol rate for target day
        from src.services.fuel_rate_service import FuelRateService
        petrol_rate = FuelRateService.get_rate_on_date(target_date)

        # The bike's own recorded efficiency, not a constant. The invoice
        # header states this figure, so computing against a different one made
        # the document disagree with itself.
        efficiency = (tech.bike.fuel_efficiency
                      if tech.bike and tech.bike.fuel_efficiency else 35.0)

        generated_trips = []
        unmeasurable = 0
        for idx, act in enumerate(activities, 1):
            addr_val = str(act['address']) if act.get('address') is not None else None
            imei_val = str(act['imei']) if act.get('imei') is not None else None
            dest_point = resolve_coordinates(addr_val, imei_val)
            dest_address = act['address']

            # None means the distance is unknown, which is recorded as zero
            # and counted below - never filled in with a plausible number.
            # An invented kilometre here is money paid out on a guess.
            measured = road_distance_km(current_point, dest_point)
            if measured is None:
                unmeasurable += 1
                logger.warning(
                    f"Trip {idx} for technician {tech.id} on {target_date}: no "
                    f"measurable distance from {current_address!r} to "
                    f"{dest_address!r} - recorded as 0 km for manual review")
            distance = measured or 0.0

            fuel_used = round(distance / efficiency, 2)

            # Fuel cost = fuel_used * rate
            raw_cost = round(fuel_used * petrol_rate, 2)

            # Carry the resolved point forward only if it is one; an
            # unresolved destination must not become the next leg's origin.
            dest_lat = dest_point[0] if dest_point[0] is not None else current_point[0]
            dest_lng = dest_point[1] if dest_point[1] is not None else current_point[1]

            # Resolve PO id
            po_id = act['po_id']
            if not po_id:
                # Use a default PO if none linked
                first_po = PurchaseOrder.query.filter_by(status='COMPLETED').first()
                po_id = first_po.id if first_po else 1
                
            # Ensure act['time'] is a datetime object for correct type arithmetic
            act_time = act['time']
            if not isinstance(act_time, datetime):
                act_time = datetime.combine(target_date, datetime.min.time())
                
            trip = TechnicianTrip(
                po_id=po_id,
                technician_id=tech.id,
                imei=act['imei'] or (tech.bike.imei if tech.bike else None),
                trip_order=idx,
                start_lat=current_point[0],
                start_lng=current_point[1],
                start_address=current_address,
                start_time=act_time - timedelta(hours=1),
                end_lat=dest_lat,
                end_lng=dest_lng,
                end_address=dest_address,
                end_time=act_time,
                distance_km=distance,
                fuel_used_liters=fuel_used,
                fuel_cost=raw_cost,
                petrol_rate_at_time=petrol_rate,
                status='COMPLETED'
            )
            db.session.add(trip)
            generated_trips.append(trip)
            
            # Update starting point for next leg. An unresolved destination
            # leaves the origin where it was rather than moving it to nowhere.
            if dest_point[0] is not None:
                current_point = dest_point
            current_address = dest_address

        db.session.commit()
        if unmeasurable:
            logger.warning(
                f"{unmeasurable} of {len(activities)} trips for technician "
                f"{tech.id} on {target_date} had no measurable distance and "
                f"were recorded as 0 km")
        return generated_trips

    @staticmethod
    def generate_invoice_number(technician_id: int, now=None) -> str:
        """FUEL_ONT_<TECH>_<YYYYMMDD-HHMMSS>, unique in the table.

        The number used to be `ONT-{count + 1:06d}`, derived from how many
        invoice rows existed. Deleting any invoice - which the Fuel Invoices
        page offers - dropped the count, so the next invoice generated
        reclaimed a number already in use and hit the unique constraint on
        `invoice_number`. Two invoices generated at once collided the same
        way.

        Now it carries the date and time it was raised and the technician it
        belongs to, in the same shape as the AMC invoice number, and the
        result is confirmed free before it is used.
        """
        from src.models.technician import Technician
        from src.services.pdf_service import PDFService

        technician = Technician.query.get(technician_id)
        code = PDFService.customer_code(technician.name if technician else '')
        stamp = (now or get_current_time()).strftime('%Y%m%d-%H%M%S')
        base = f"FUEL_ONT_{code}_{stamp}"

        candidate = base
        suffix = 1
        while FuelReimbursementInvoice.query.filter_by(
                invoice_number=candidate).first() is not None:
            suffix += 1
            candidate = f"{base}-{suffix}"
        return candidate

    def create_invoice(self, technician_id: int, start_date: date, 
                       end_date: date, user_id: int) -> FuelReimbursementInvoice:
        """Create a fuel reimbursement invoice"""
        # Dynamic trip generation for period
        self.generate_trips_for_period(technician_id, start_date, end_date)
        
        trips = self.trip_service.get_by_technician(technician_id, start_date, end_date)
        
        if not trips:
            raise ValueError(f"No trips found for technician {technician_id} in the given period")
        
        total_distance = sum(t.distance_km or 0 for t in trips)
        total_fuel = sum(t.fuel_used_liters or 0 for t in trips)
        total_cost = sum(t.fuel_cost or 0 for t in trips)
        
        petrol_rate = PetrolRateService.get_current_rate()
        
        invoice_number = self.generate_invoice_number(technician_id)
        
        invoice = self.repository.create(
            invoice_number=invoice_number,
            technician_id=technician_id,
            start_date=start_date,
            end_date=end_date,
            total_distance=total_distance,
            total_fuel_liters=total_fuel,
            total_amount=total_cost,
            petrol_rate_applied=petrol_rate,
            status='PENDING',
            created_by=user_id
        )
        
        logger.info(f"Fuel invoice {invoice_number} created for technician {technician_id}")
        return invoice
    
    def mark_paid(self, invoice_id: int) -> Optional[FuelReimbursementInvoice]:
        """Mark invoice as paid"""
        invoice = self.repository.get_by_id(invoice_id)
        if invoice:
            invoice.status = 'PAID'
            invoice.paid_at = get_current_time()
            db.session.commit()
            logger.info(f"Invoice {invoice.invoice_number} marked as paid")
        return invoice
    
    def get_by_technician(self, technician_id: int) -> List[FuelReimbursementInvoice]:
        """Get invoices by technician"""
        return self.repository.get_all(technician_id=technician_id)
    
    def get_pending_invoices(self) -> List[FuelReimbursementInvoice]:
        """Get pending invoices"""
        return self.repository.get_all(status='PENDING')
    
    def get_invoice_summary(self, technician_id: Optional[int] = None) -> Dict[str, Any]:
        """Get invoice summary"""
        filters: Dict[str, Any] = {}
        if technician_id:
            filters['technician_id'] = technician_id
        
        total = self.repository.count(**filters)
        pending = self.repository.count(**filters, status='PENDING')
        paid = self.repository.count(**filters, status='PAID')
        
        return {
            'total': total,
            'pending': pending,
            'paid': paid,
            'total_amount': sum(i.total_amount for i in self.repository.get_all(**filters)),
        }


# Major-city centres, used only when an address names one of them.
CITY_CENTRES = {
    'KARACHI': (24.8607, 67.0011),
    'LAHORE': (31.5204, 74.3587),
    'ISLAMABAD': (33.6844, 73.0479),
    'RAWALPINDI': (33.5984, 73.0441),
    'FAISALABAD': (31.4504, 73.1350),
    'MULTAN': (30.1575, 71.5249),
    'PESHAWAR': (34.0151, 71.5249),
    'QUETTA': (30.1798, 66.9750),
    'SIALKOT': (32.4945, 74.5229),
    'GUJRANWALA': (32.1877, 74.1945),
}

# Roads are not straight lines. Haversine gives the great-circle distance, and
# a rider on a road covers meaningfully more than that - roughly a third more
# over a mixed urban/intercity route. Reimbursing the straight line
# systematically underpays every genuine claim.
ROAD_DISTANCE_FACTOR = 1.3

# How coordinates were arrived at. A distance is only as good as the worse of
# its two endpoints, and an invoice should not treat a guess like a fix.
PRECISION_GPS = 'gps'      # the device's own reported position
PRECISION_CITY = 'city'    # the centre of a city named in the address
PRECISION_NONE = None      # not resolvable


def resolve_coordinates(address_string: Optional[str], imei: Optional[str] = None) -> tuple:
    """(lat, lng, precision) for an address or device IMEI.

    Returns (None, None, None) when the location cannot be established.
    It used to return Lahore's city centre in that case, which turned every
    unrecognised address into a ~1,000km leg on a Karachi technician's
    invoice - the single largest source of wrong money on these claims.
    """
    # 1. The device's own GPS position - the only exact answer available.
    if imei:
        from src.models.gps import CurrentLocation
        loc = CurrentLocation.query.filter_by(device_imei=imei).first()
        if loc and loc.lat and loc.lng:
            try:
                lat = float(loc.lat)
                lng = float(loc.lng)
                if lat != 0.0 and lng != 0.0:
                    return lat, lng, PRECISION_GPS
            except (ValueError, TypeError):
                pass

    # 2. A city named in the address. Coarse but honest: good enough to
    #    measure a Karachi-to-Lahore leg, useless within one city - which is
    #    what `precision` is for. No positional jitter is added: the old code
    #    offset the centre by the address's *character count*, so two sites
    #    with equal-length addresses sat on top of each other and unequal
    #    ones were pushed apart by an amount unrelated to geography.
    if address_string:
        addr_upper = address_string.upper()
        for city, coords in CITY_CENTRES.items():
            if city in addr_upper:
                return coords[0], coords[1], PRECISION_CITY

    # 3. Unknown. Say so rather than inventing somewhere.
    return None, None, PRECISION_NONE


def calculate_distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometres (Haversine).

    Straight-line: see `road_distance_km` for what a rider actually covers.
    """
    from math import radians, sin, cos, sqrt, asin
    if None in (lat1, lng1, lat2, lng2):
        return 0.0
    R = 6371
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng/2)**2
    c = 2 * asin(min(1.0, sqrt(a)))
    return round(R * c, 2)


def road_distance_km(start: tuple, end: tuple) -> Optional[float]:
    """Road distance between two resolved points, or None if unmeasurable.

    Each point is (lat, lng, precision) from `resolve_coordinates`.

    None means "we do not know", and that is different from zero. A trip
    whose endpoints cannot be placed - or two coarse points that both land on
    the same city centre, which says only that the job was somewhere in that
    city - has no distance this code can honestly state, and the previous
    behaviour of substituting `8.5 + trip_number * 1.5` put invented
    kilometres onto a reimbursement claim.
    """
    start_lat, start_lng, start_precision = start
    end_lat, end_lng, end_precision = end

    if start_precision is PRECISION_NONE or end_precision is PRECISION_NONE:
        return None

    straight = calculate_distance_km(float(start_lat), float(start_lng),
                                     float(end_lat), float(end_lng))

    # Both ends only known to city level, and it is the same city: the
    # separation between them is exactly the detail this data does not have.
    if (start_precision == PRECISION_CITY and end_precision == PRECISION_CITY
            and straight < 1.0):
        return None

    return round(straight * ROAD_DISTANCE_FACTOR, 2)