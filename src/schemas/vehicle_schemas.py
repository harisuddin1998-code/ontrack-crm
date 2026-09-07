# src/schemas/vehicle_schemas.py
"""
Vehicle Pydantic Schemas
"""
from typing import Optional
from pydantic import BaseModel, Field


class VehicleMakeSchema(BaseModel):
    """Vehicle make schema"""
    id: int
    name: str
    created_at: Optional[str] = None
    
    class Config:
        from_attributes = True


class VehicleModelSchema(BaseModel):
    """Vehicle model schema"""
    id: int
    name: str
    make_id: int
    make_name: Optional[str] = None
    created_at: Optional[str] = None
    
    class Config:
        from_attributes = True


class VehicleYearSchema(BaseModel):
    """Vehicle year schema"""
    id: int
    year: str
    
    class Config:
        from_attributes = True


class VehicleColorSchema(BaseModel):
    """Vehicle color schema"""
    id: int
    name: str
    code: Optional[str] = None
    
    class Config:
        from_attributes = True


class DeviceTypeSchema(BaseModel):
    """Device type schema"""
    id: int
    name: str
    created_at: Optional[str] = None
    
    class Config:
        from_attributes = True


class CitySchema(BaseModel):
    """City schema"""
    id: int
    name: str
    created_at: Optional[str] = None
    
    class Config:
        from_attributes = True


class VehicleLookupRequest(BaseModel):
    """Vehicle lookup request"""
    reg_no: str = Field(..., min_length=1, max_length=50) 
