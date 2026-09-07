# src/schemas/gps_schemas.py
"""
GPS Pydantic Schemas
"""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class GPSLocationSchema(BaseModel):
    """GPS location schema"""
    id: int
    device_imei: str
    name: Optional[str] = None
    lat: Optional[str] = None
    lng: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None
    speed: Optional[str] = None
    is_active: bool
    last_updated: Optional[datetime] = None
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class NonReportingVehicleSchema(BaseModel):
    """Non-reporting vehicle schema"""
    id: int
    registration_no: str
    customer_name: Optional[str] = None
    customer_contact: Optional[str] = None
    imei_no: Optional[str] = None
    sim_no: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    city: Optional[str] = None
    last_reporting_time: Optional[datetime] = None
    first_detected_time: Optional[datetime] = None
    days_non_reporting: int
    hours_non_reporting: int
    status: str
    priority: str
    assigned_to: Optional[int] = None
    issue_summary: Optional[str] = None
    resolution_notes: Optional[str] = None
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class GPSDiagnoseResponse(BaseModel):
    """GPS diagnose response"""
    hostname: str
    status: str
    dns: Optional[dict] = None
    port: Optional[dict] = None
    api: Optional[dict] = None
    error: Optional[str] = None 
