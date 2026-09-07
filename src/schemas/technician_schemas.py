# src/schemas/technician_schemas.py
"""
Technician Pydantic Schemas
"""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class TechnicianSchema(BaseModel):
    """Technician schema"""
    id: int
    name: str
    contact: Optional[str] = None
    address: Optional[str] = None
    home_lat: Optional[str] = None
    home_lng: Optional[str] = None
    is_active: bool
    has_bike: bool
    bike_registration: Optional[str] = None
    bike_imei: Optional[str] = None
    created_at: Optional[str] = None
    
    class Config:
        from_attributes = True


class TechnicianBikeSchema(BaseModel):
    """Technician bike schema"""
    id: int
    technician_id: int
    technician_name: Optional[str] = None
    imei: str
    bike_registration: str
    bike_model: Optional[str] = None
    fuel_efficiency: float
    is_active: bool
    current_location: Optional[dict] = None
    created_at: Optional[str] = None
    
    class Config:
        from_attributes = True


class TechnicianTripSchema(BaseModel):
    """Technician trip schema"""
    id: int
    po_id: int
    po_number: Optional[str] = None
    technician_id: int
    technician_name: Optional[str] = None
    imei: Optional[str] = None
    trip_order: int
    start_lat: Optional[str] = None
    start_lng: Optional[str] = None
    start_address: Optional[str] = None
    start_time: Optional[datetime] = None
    end_lat: Optional[str] = None
    end_lng: Optional[str] = None
    end_address: Optional[str] = None
    end_time: Optional[datetime] = None
    distance_km: float
    fuel_used_liters: float
    fuel_cost: float
    petrol_rate_at_time: Optional[float] = None
    status: str
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class TechnicianTripSummary(BaseModel):
    """Technician trip summary"""
    technician_id: int
    technician_name: str
    total_trips: int
    total_distance: float
    total_fuel_liters: float
    total_fuel_cost: float
    avg_distance_per_trip: float


class FuelInvoiceSchema(BaseModel):
    """Fuel reimbursement invoice schema"""
    id: int
    invoice_number: str
    technician_id: int
    technician_name: Optional[str] = None
    start_date: datetime
    end_date: datetime
    total_distance: float
    total_fuel_liters: float
    total_amount: float
    customer_fuel_sum: float
    net_payable: float
    petrol_rate_applied: Optional[float] = None
    status: str
    paid_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True 
