# src/repositories/technician_repository.py
"""
Technician Repository
"""
from typing import Optional, List, Dict, Any

from src.models.technician import Technician, TechnicianBike, TechnicianTrip
from src.repositories.base_repository import BaseRepository
from src.extensions import db


class TechnicianRepository(BaseRepository[Technician]):
    """Repository for Technician operations"""
    
    def __init__(self):
        super().__init__(Technician)
    
    def get_by_name(self, name: str) -> Optional[Technician]:
        """Get technician by name"""
        return self.get_by(name=name)
    
    def get_active_technicians(self) -> List[Technician]:
        """Get active technicians"""
        return self.get_all(is_active=True)
    
    def get_with_bike(self) -> List[Technician]:
        """Get technicians with bike assigned"""
        return self.session.query(Technician).join(
            TechnicianBike, TechnicianBike.technician_id == Technician.id
        ).filter(
            Technician.is_active == True,
            TechnicianBike.is_active == True
        ).all()
    
    def get_without_bike(self) -> List[Technician]:
        """Get technicians without bike assigned"""
        return self.session.query(Technician).outerjoin(
            TechnicianBike, TechnicianBike.technician_id == Technician.id
        ).filter(
            TechnicianBike.id.is_(None)
        ).all()


class TechnicianBikeRepository(BaseRepository[TechnicianBike]):
    """Repository for Technician Bike operations"""
    
    def __init__(self):
        super().__init__(TechnicianBike)
    
    def get_by_imei(self, imei: str) -> Optional[TechnicianBike]:
        """Get bike by IMEI"""
        return self.get_by(imei=imei)
    
    def get_by_registration(self, registration: str) -> Optional[TechnicianBike]:
        """Get bike by registration number"""
        return self.get_by(bike_registration=registration)
    
    def get_by_technician(self, technician_id: int) -> Optional[TechnicianBike]:
        """Get bike by technician ID"""
        return self.get_by(technician_id=technician_id)
    
    def get_active_bikes(self) -> List[TechnicianBike]:
        """Get active bikes"""
        return self.get_all(is_active=True)
    
    def get_assigned_bikes(self) -> List[TechnicianBike]:
        """Get bikes assigned to technicians"""
        return self.session.query(TechnicianBike).join(
            Technician, TechnicianBike.technician_id == Technician.id
        ).filter(
            TechnicianBike.is_active == True
        ).all()


class TechnicianTripRepository(BaseRepository[TechnicianTrip]):
    """Repository for Technician Trip operations"""
    
    def __init__(self):
        super().__init__(TechnicianTrip)
    
    def get_by_po(self, po_id: int) -> List[TechnicianTrip]:
        """Get trips by PO ID"""
        return self.get_all(po_id=po_id)
    
    def get_by_technician(self, technician_id: int) -> List[TechnicianTrip]:
        """Get trips by technician"""
        return self.get_all(technician_id=technician_id)
    
    def get_by_date_range(self, technician_id: int, start_date, end_date) -> List[TechnicianTrip]:
        """Get trips by date range for a technician"""
        return self.session.query(TechnicianTrip).filter(
            TechnicianTrip.technician_id == technician_id,
            TechnicianTrip.start_time >= start_date,
            TechnicianTrip.start_time <= end_date
        ).order_by(TechnicianTrip.start_time).all()
    
    def get_pending_trips(self) -> List[TechnicianTrip]:
        """Get pending trips"""
        return self.get_all(status='PENDING')
    
    def get_completed_trips(self) -> List[TechnicianTrip]:
        """Get completed trips"""
        return self.get_all(status='COMPLETED')
    
    def get_trip_summary(self, technician_id: int, start_date, end_date) -> Dict[str, Any]:
        """Get trip summary for a technician"""
        trips = self.get_by_date_range(technician_id, start_date, end_date)
        
        total_distance = sum(t.distance_km or 0 for t in trips)
        total_fuel = sum(t.fuel_used_liters or 0 for t in trips)
        total_cost = sum(t.fuel_cost or 0 for t in trips)
        
        return {
            'total_trips': len(trips),
            'total_distance': round(total_distance, 2),
            'total_fuel_liters': round(total_fuel, 2),
            'total_fuel_cost': round(total_cost, 2),
            'trips': trips
        }