# src/schemas/po_schemas.py
"""
Purchase Order Pydantic Schemas
"""
from typing import Optional
from datetime import date, datetime
from pydantic import BaseModel, Field, validator


class POCreateRequest(BaseModel):
    """PO creation request schema"""
    owner_name: str = Field(..., min_length=1, max_length=200)
    owner_contact: str = Field(..., min_length=1, max_length=50)
    contact_person_driver: Optional[str] = Field(None, max_length=200)
    
    reg_no: str = Field(..., min_length=1, max_length=50)
    vehicle_make: str = Field(..., min_length=1, max_length=50)
    vehicle_model: str = Field(..., min_length=1, max_length=50)
    vehicle_year: str = Field(..., min_length=4, max_length=4)
    vehicle_color: str = Field(..., min_length=1, max_length=20)
    engine_number: str = Field(..., min_length=1, max_length=100)
    chassis_number: str = Field(..., min_length=1, max_length=100)
    
    city: Optional[str] = Field(None, max_length=100)
    vehicle_availability_location: str = Field(..., max_length=200)
    existing_customer_name: Optional[str] = Field(None, max_length=200)
    existing_vehicle_number: Optional[str] = Field(None, max_length=100)
    
    scheduled_date: Optional[date] = None
    sales_person_id: int
    
    rates: float = Field(0.0, ge=0)
    amc: float = Field(0.0, ge=0)
    
    @validator('reg_no')
    def validate_reg_no(cls, v):
        return v.upper().strip()
    
    @validator('owner_name', 'vehicle_make', 'vehicle_model', 'vehicle_color', 
               'engine_number', 'chassis_number')
    def validate_upper(cls, v):
        return v.upper().strip() if v else v


class POUpdateRequest(BaseModel):
    """PO update request schema"""
    owner_name: Optional[str] = Field(None, max_length=200)
    owner_contact: Optional[str] = Field(None, max_length=50)
    contact_person_driver: Optional[str] = Field(None, max_length=200)
    reg_no: Optional[str] = Field(None, max_length=50)
    vehicle_make: Optional[str] = Field(None, max_length=50)
    vehicle_model: Optional[str] = Field(None, max_length=50)
    vehicle_year: Optional[str] = Field(None, min_length=4, max_length=4)
    vehicle_color: Optional[str] = Field(None, max_length=20)
    engine_number: Optional[str] = Field(None, max_length=100)
    chassis_number: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    vehicle_availability_location: Optional[str] = Field(None, max_length=200)
    scheduled_date: Optional[date] = None
    technician_assigned: Optional[str] = Field(None, max_length=100)
    imei_no: Optional[str] = Field(None, max_length=50)
    sim_no: Optional[str] = Field(None, max_length=50)
    device_type: Optional[str] = Field(None, max_length=50)
    device_location: Optional[str] = Field(None, max_length=200)
    fuel: Optional[str] = Field(None, max_length=50)
    tested_by: Optional[str] = Field(None, max_length=100)
    arranged_by_sales_person: Optional[str] = Field(None, max_length=100)
    remarks: Optional[str] = None
    status: Optional[str] = None
    rates: Optional[float] = Field(None, ge=0)
    amc: Optional[float] = Field(None, ge=0)


class POResponse(BaseModel):
    """PO response schema"""
    id: int
    po_number: str
    activity_type: str
    owner_name: str
    owner_contact: str
    contact_person_driver: Optional[str]
    reg_no: str
    vehicle_make: str
    vehicle_model: str
    vehicle_year: str
    vehicle_color: str
    engine_number: str
    chassis_number: str
    sales_person_id: int
    city: Optional[str]
    vehicle_availability_location: str
    existing_customer_name: Optional[str]
    existing_vehicle_number: Optional[str]
    scheduled_date: Optional[date]
    technician_assigned: Optional[str]
    imei_no: Optional[str]
    sim_no: Optional[str]
    device_type: Optional[str]
    device_location: Optional[str]
    fuel: Optional[str]
    tested_by: Optional[str]
    arranged_by_sales_person: Optional[str]
    remarks: Optional[str]
    status: str
    rates: float
    amc: float
    total_amount: float
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class POListResponse(BaseModel):
    """PO list response schema"""
    items: list[POResponse]
    total: int
    page: int
    per_page: int
    pages: int