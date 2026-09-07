# src/models/technician.py
"""
Technician and Bike models for field operations
"""
from typing import Dict, Any, Optional

from src.extensions import db
from src.models.base import BaseModel, StatusMixin


class Technician(BaseModel, StatusMixin):
    """Field technician model"""
    __tablename__ = 'technicians'
    
    name = db.Column(db.String(100), nullable=False, unique=True)
    contact = db.Column(db.String(50))
    address = db.Column(db.String(500))
    home_lat = db.Column(db.String(20))
    home_lng = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationships
    bike = db.relationship('TechnicianBike', backref='technician_ref', 
                          uselist=False, foreign_keys='TechnicianBike.technician_id')
    trips = db.relationship('TechnicianTrip', backref='technician_ref', lazy='dynamic')
    invoices = db.relationship('FuelReimbursementInvoice', backref='technician_ref', lazy='dynamic')
    
    def get_full_name(self) -> str:
        """Get technician's full name"""
        return self.name
    
    def has_bike(self) -> bool:
        """Check if technician has a bike assigned"""
        return self.bike is not None
    
    def get_assigned_bike(self) -> Optional['TechnicianBike']:
        """Get assigned bike"""
        return self.bike
    
    @property
    def bike_assignment(self) -> Optional['TechnicianBike']:
        """Alias for bike relationship"""
        return self.bike
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'contact': self.contact,
            'address': self.address,
            'home_lat': self.home_lat,
            'home_lng': self.home_lng,
            'is_active': self.is_active,
            'has_bike': self.has_bike(),
            'bike_registration': self.bike.bike_registration if self.bike else None,
            'bike_imei': self.bike.imei if self.bike else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
    
    def __repr__(self) -> str:
        return f"<Technician {self.name}>"


class TechnicianBike(BaseModel):
    """Bike assigned to technician"""
    __tablename__ = 'technician_bikes'
    
    technician_id = db.Column(db.Integer, db.ForeignKey('technicians.id'), 
                             unique=True, nullable=False)
    imei = db.Column(db.String(50), unique=True, nullable=False)
    bike_registration = db.Column(db.String(50), nullable=False)
    bike_model = db.Column(db.String(100))
    fuel_efficiency = db.Column(db.Float, default=35.0)  # km per liter
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationships
    # No backref here - Technician.bike_assignment is already defined as an
    # explicit @property below (SQLAlchemy warns that an auto-generated
    # backref of the same name silently overwrites it, undefined behavior
    # that becomes a hard error in a future release).
    technician = db.relationship('Technician', foreign_keys=[technician_id])
    
    def get_current_location(self) -> Optional[Dict[str, Any]]:
        """Get current GPS location of bike"""
        from src.models.gps import CurrentLocation
        location = CurrentLocation.query.filter_by(device_imei=self.imei).first()
        if location:
            return location.to_dict()
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        location = self.get_current_location()
        return {
            'id': self.id,
            'technician_id': self.technician_id,
            'technician_name': self.technician.name if self.technician else None,
            'imei': self.imei,
            'bike_registration': self.bike_registration,
            'bike_model': self.bike_model,
            'fuel_efficiency': self.fuel_efficiency,
            'is_active': self.is_active,
            'current_location': location,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
    
    def __repr__(self) -> str:
        return f"<TechnicianBike {self.bike_registration} - {self.technician.name if self.technician else 'Unassigned'}>"


class TechnicianTrip(BaseModel):
    """Trip record for technician"""
    __tablename__ = 'technician_trips'
    
    po_id = db.Column(db.Integer, db.ForeignKey('purchase_orders.id'), nullable=False)
    technician_id = db.Column(db.Integer, db.ForeignKey('technicians.id'), nullable=False)
    imei = db.Column(db.String(50))
    trip_order = db.Column(db.Integer, default=1)
    
    # Trip details
    start_lat = db.Column(db.String(20))
    start_lng = db.Column(db.String(20))
    start_address = db.Column(db.String(500))
    start_time = db.Column(db.DateTime)
    
    end_lat = db.Column(db.String(20))
    end_lng = db.Column(db.String(20))
    end_address = db.Column(db.String(500))
    end_time = db.Column(db.DateTime)
    
    # Calculated fields
    distance_km = db.Column(db.Float, default=0.0)
    fuel_used_liters = db.Column(db.Float, default=0.0)
    fuel_cost = db.Column(db.Float, default=0.0)
    petrol_rate_at_time = db.Column(db.Float)
    
    # Metadata
    previous_trip_id = db.Column(db.Integer)
    status = db.Column(db.String(20), default='PENDING')
    
    # Relationships
    purchase_order = db.relationship('PurchaseOrder', backref='trips_ref', 
                                     foreign_keys=[po_id])
    technician = db.relationship('Technician', backref='trips_ref', 
                                 foreign_keys=[technician_id])
    
    def calculate_fuel_usage(self) -> float:
        """Calculate fuel used based on distance and efficiency"""
        if self.distance_km and self.technician and self.technician.bike:
            efficiency = self.technician.bike.fuel_efficiency or 35.0
            return round(self.distance_km / efficiency, 2)
        return 0.0
    
    def calculate_fuel_cost(self, petrol_rate: Optional[float] = None) -> float:
        """Calculate fuel cost"""
        from src.services.petrol_service import PetrolService
        
        if petrol_rate is None:
            petrol_rate = PetrolService.get_current_rate()
        
        fuel_used = self.calculate_fuel_usage()
        return round(fuel_used * petrol_rate, 2)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'po_id': self.po_id,
            'po_number': self.purchase_order.po_number if self.purchase_order else None,
            'technician_id': self.technician_id,
            'technician_name': self.technician.name if self.technician else None,
            'imei': self.imei,
            'trip_order': self.trip_order,
            'start_lat': self.start_lat,
            'start_lng': self.start_lng,
            'start_address': self.start_address,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_lat': self.end_lat,
            'end_lng': self.end_lng,
            'end_address': self.end_address,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'distance_km': self.distance_km,
            'fuel_used_liters': self.fuel_used_liters,
            'fuel_cost': self.fuel_cost,
            'petrol_rate_at_time': self.petrol_rate_at_time,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
    
    def __repr__(self) -> str:
        return f"<TechnicianTrip {self.id} - PO {self.po_id}>"


class PetrolRate(BaseModel):
    """Petrol rate per liter"""
    __tablename__ = 'petrol_rates'
    
    rate_per_liter = db.Column(db.Float, nullable=False)
    effective_date = db.Column(db.Date, nullable=False, default=db.func.current_date())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'rate_per_liter': self.rate_per_liter,
            'effective_date': self.effective_date.isoformat() if self.effective_date else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
    
    def __repr__(self) -> str:
        return f"<PetrolRate {self.rate_per_liter} - {self.effective_date}>"


class FuelReimbursementInvoice(BaseModel):
    """Fuel reimbursement invoice for technician"""
    __tablename__ = 'fuel_reimbursement_invoices'
    
    invoice_number = db.Column(db.String(50), unique=True, nullable=False)
    technician_id = db.Column(db.Integer, db.ForeignKey('technicians.id'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    
    # Calculated fields
    total_distance = db.Column(db.Float, default=0.0)
    total_fuel_liters = db.Column(db.Float, default=0.0)
    total_amount = db.Column(db.Float, default=0.0)
    petrol_rate_applied = db.Column(db.Float)
    
    # Status
    status = db.Column(db.String(20), default='PENDING')
    paid_at = db.Column(db.DateTime)
    
    # Relationships
    technician = db.relationship('Technician', backref='invoices_ref',
                                 foreign_keys=[technician_id])
    expenses = db.relationship('FuelInvoiceExpense', backref='invoice',
                               cascade='all, delete-orphan', lazy='select')

    def additional_expenses_total(self) -> float:
        """Everything claimed on this invoice besides fuel.

        Mobile top-offs, relays and sundries are reimbursed alongside fuel
        but are not derived from distance, so they are added to the payable
        rather than folded into the fuel maths.
        """
        return round(sum(e.amount or 0.0 for e in self.expenses), 2)

    def calculate_customer_fuel_sum(self) -> float:
        """Calculate total customer-provided fuel for this period"""
        from src.models.purchase_order import PurchaseOrder
        from datetime import timedelta
        
        trips = TechnicianTrip.query.filter(
            TechnicianTrip.technician_id == self.technician_id,
            TechnicianTrip.start_time >= self.start_date,
            TechnicianTrip.start_time <= self.end_date + timedelta(days=1),
            TechnicianTrip.status == 'COMPLETED'
        ).all()
        
        customer_sum = 0.0
        for trip in trips:
            po = trip.purchase_order
            if po and po.fuel and po.fuel != 'Not provided':
                try:
                    # Parse numeric value from fuel string
                    import re
                    cleaned = re.sub(r'[^\d.]', '', str(po.fuel))
                    if cleaned:
                        customer_sum += float(cleaned)
                except (ValueError, TypeError):
                    pass
        return round(customer_sum, 2)
    
    @property
    def net_payable(self) -> float:
        """Fuel owed after customer-provided fuel, plus additional expenses.

        The fuel side is floored at zero - a customer who provided more fuel
        than the trip consumed does not create a debt - but that floor must
        not swallow separately-claimed expenses, so they are added after it.
        """
        customer_fuel = self.calculate_customer_fuel_sum()
        fuel_payable = max(0.0, (self.total_amount or 0.0) - customer_fuel)
        return round(fuel_payable + self.additional_expenses_total(), 2)


    def calculate_net_payable(self) -> float:
        """Calculate net payable after customer fuel"""
        return self.net_payable
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'invoice_number': self.invoice_number,
            'technician_id': self.technician_id,
            'technician_name': self.technician.name if self.technician else None,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'total_distance': self.total_distance,
            'total_fuel_liters': self.total_fuel_liters,
            'total_amount': self.total_amount,
            'customer_fuel_sum': self.calculate_customer_fuel_sum(),
            'additional_expenses': self.additional_expenses_total(),
            'net_payable': self.calculate_net_payable(),
            'petrol_rate_applied': self.petrol_rate_applied,
            'status': self.status,
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
    
    def __repr__(self) -> str:
        return f"<FuelReimbursementInvoice {self.invoice_number}>"


class FuelInvoiceExpense(BaseModel):
    """A non-fuel item claimed on a fuel reimbursement invoice.

    Field work incurs costs that distance cannot predict - a mobile top-off
    to reach a customer, a relay bought on site. They belong on the same
    invoice as the fuel, but they are recorded as their own lines so the
    fuel figures stay derived purely from routing and stay auditable.
    """
    __tablename__ = 'fuel_invoice_expenses'

    CATEGORY_MOBILE_TOP_OFF = 'MOBILE_TOP_OFF'
    CATEGORY_RELAYS = 'RELAYS'
    CATEGORY_OTHER = 'OTHER'

    CATEGORIES = [
        (CATEGORY_MOBILE_TOP_OFF, 'Mobile Top Off'),
        (CATEGORY_RELAYS, 'Relays'),
        (CATEGORY_OTHER, 'Other Items'),
    ]

    invoice_id = db.Column(db.Integer, db.ForeignKey('fuel_reimbursement_invoices.id'),
                           nullable=False, index=True)
    category = db.Column(db.String(30), default=CATEGORY_OTHER, nullable=False)
    description = db.Column(db.String(255))
    amount = db.Column(db.Float, default=0.0, nullable=False)
    added_by_name = db.Column(db.String(100))

    @classmethod
    def category_label(cls, value: str) -> str:
        return dict(cls.CATEGORIES).get(value, value or 'Other Items')

    @property
    def label(self) -> str:
        return self.category_label(self.category)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'invoice_id': self.invoice_id,
            'category': self.category,
            'category_label': self.label,
            'description': self.description,
            'amount': self.amount,
            'added_by_name': self.added_by_name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<FuelInvoiceExpense {self.category} {self.amount}>"
