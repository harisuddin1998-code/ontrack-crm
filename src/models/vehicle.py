# src/models/vehicle.py
"""
Vehicle related models: Make, Model, Year, Color, Device Type
"""
from typing import Dict, Any

from src.extensions import db
from src.models.base import BaseModel


class VehicleMake(BaseModel):
    """Vehicle make/model brand"""
    __tablename__ = 'vehicle_makes'
    
    name = db.Column(db.String(100), unique=True, nullable=False)
    
    # Relationships
    models = db.relationship('VehicleModel', backref='make', lazy='dynamic')
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
    
    def __repr__(self) -> str:
        return f"<VehicleMake {self.name}>"


class VehicleModel(BaseModel):
    """Vehicle model"""
    __tablename__ = 'vehicle_models'
    
    name = db.Column(db.String(100), nullable=False)
    make_id = db.Column(db.Integer, db.ForeignKey('vehicle_makes.id'), nullable=False)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'make_id': self.make_id,
            'make_name': self.make.name if self.make else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
    
    def __repr__(self) -> str:
        return f"<VehicleModel {self.name} ({self.make.name if self.make else 'No Make'})>"


class VehicleYear(BaseModel):
    """Vehicle year"""
    __tablename__ = 'vehicle_years'
    
    year = db.Column(db.String(4), unique=True, nullable=False)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'year': self.year,
        }
    
    def __repr__(self) -> str:
        return f"<VehicleYear {self.year}>"


class VehicleColor(BaseModel):
    """Vehicle color"""
    __tablename__ = 'vehicle_colors'
    
    name = db.Column(db.String(50), unique=True, nullable=False)
    code = db.Column(db.String(20))  # Hex color code
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'code': self.code,
        }
    
    def __repr__(self) -> str:
        return f"<VehicleColor {self.name}>"


class DeviceType(BaseModel):
    """Device type (GPS Tracker, Fuel Sensor, etc.)"""
    __tablename__ = 'device_types'
    
    name = db.Column(db.String(100), unique=True, nullable=False)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
    
    def __repr__(self) -> str:
        return f"<DeviceType {self.name}>"


class City(BaseModel):
    """City model"""
    __tablename__ = 'cities'
    
    name = db.Column(db.String(100), unique=True, nullable=False)
    
    # FIXED: Removed the problematic relationship since PurchaseOrder.city is not a ForeignKey
    # The relationship will be handled through the city column in PurchaseOrder
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
    
    def __repr__(self) -> str:
        return f"<City {self.name}>"