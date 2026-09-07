# src/models/gps.py
"""
GPS Location Models
"""
from typing import Dict, Any, Optional
from datetime import datetime

from src.extensions import db
from src.models.base import BaseModel
from src.utils.timezone import get_current_time


class CurrentLocation(BaseModel):
    """Current GPS location of devices"""
    __tablename__ = 'current_locations'
    
    device_imei = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100))  # Device name
    lat = db.Column(db.String(20))
    lng = db.Column(db.String(20))
    address = db.Column(db.String(500))
    speed = db.Column(db.String(10))
    last_updated = db.Column(db.DateTime, default=get_current_time, onupdate=get_current_time)
    
    def get_coordinates(self) -> Optional[tuple]:
        """Get coordinates as tuple (lat, lng)"""
        if self.lat and self.lng:
            try:
                return (float(self.lat), float(self.lng))
            except (ValueError, TypeError):
                return None
        return None
    
    def is_active(self, minutes: int = 30) -> bool:
        """Check if location is recent (within last X minutes)"""
        if not self.last_updated:
            return False
        now = get_current_time()
        last_updated = self.last_updated
        if last_updated.tzinfo is None and now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        elif last_updated.tzinfo is not None and now.tzinfo is None:
            last_updated = last_updated.replace(tzinfo=None)
        delta = now - last_updated
        return delta.total_seconds() / 60 < minutes
    
    def to_dict(self) -> Dict[str, Any]:
        coords = self.get_coordinates()
        return {
            'id': self.id,
            'device_imei': self.device_imei,
            'name': self.name,
            'lat': self.lat,
            'lng': self.lng,
            'latitude': coords[0] if coords else None,
            'longitude': coords[1] if coords else None,
            'address': self.address,
            'speed': self.speed,
            'is_active': self.is_active(),
            'last_updated': self.last_updated.isoformat() if self.last_updated else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
    
    def __repr__(self) -> str:
        return f"<CurrentLocation {self.device_imei} - {self.lat}, {self.lng}>"


class NonReportingVehicle(BaseModel):
    """Vehicles not reporting GPS data"""
    __tablename__ = 'non_reporting_vehicles'
    
    registration_no = db.Column(db.String(50), unique=True, nullable=False, index=True)
    customer_name = db.Column(db.String(200))
    customer_contact = db.Column(db.String(50))
    customer_phone2 = db.Column(db.String(50))
    customer_phone3 = db.Column(db.String(50))
    emergency_mobile = db.Column(db.String(50))
    emergency_name = db.Column(db.String(100))
    res_phone = db.Column(db.String(50))
    office_phone = db.Column(db.String(50))
    
    # Vehicle details
    imei_no = db.Column(db.String(50))
    sim_no = db.Column(db.String(50))
    make = db.Column(db.String(50))
    model = db.Column(db.String(50))
    city = db.Column(db.String(100))
    engine_no = db.Column(db.String(100))
    chassis_no = db.Column(db.String(100))
    vehicle_year = db.Column(db.String(4))
    vehicle_color = db.Column(db.String(20))
    device_location = db.Column(db.String(200))
    unit_location = db.Column(db.String(200))
    
    # Reporting & GS Tracker info
    dt_tracker = db.Column(db.DateTime)
    dt_server = db.Column(db.DateTime)
    lat = db.Column(db.String(20))
    lng = db.Column(db.String(20))
    speed = db.Column(db.String(20))
    last_reporting_time = db.Column(db.DateTime)
    first_detected_time = db.Column(db.DateTime, default=get_current_time)
    
    # Status
    status = db.Column(db.String(20), default='PENDING')
    priority = db.Column(db.String(10), default='NORMAL')

    # Outcome of the most recent customer contact attempt (separate from the
    # PENDING/IN_PROGRESS/COMPLETED/ESCALATED workflow status above, which
    # drives the dashboard's bucket/stat filters). One of: 'No Answer',
    # 'Technician Assigned', 'Phone Switched Off', 'Vehicle Out of City',
    # 'Client Requested Removal'.
    contact_outcome = db.Column(db.String(50))
    
    # Assignment
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'))
    assigned_at = db.Column(db.DateTime)
    scheduled_date = db.Column(db.Date)
    last_contact_date = db.Column(db.DateTime)
    next_followup_date = db.Column(db.Date)
    
    # Notes
    issue_summary = db.Column(db.Text)
    resolution_notes = db.Column(db.Text)
    technician_notes = db.Column(db.Text)
    device_imei = db.Column(db.String(50))
    device_sim = db.Column(db.String(50))
    
    # Relationships
    assigned_technician = db.relationship('User', backref='assigned_non_reporting_ref',
                                          foreign_keys=[assigned_to])
    conversations = db.relationship('NonReportingConversation', backref='vehicle_ref',
                                    lazy='dynamic')
    
    # Priority constants
    PRIORITY_LOW = 'LOW'
    PRIORITY_NORMAL = 'NORMAL'
    PRIORITY_HIGH = 'HIGH'
    PRIORITY_CRITICAL = 'CRITICAL'
    
    # Status constants
    STATUS_PENDING = 'PENDING'
    STATUS_IN_PROGRESS = 'IN_PROGRESS'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_ESCALATED = 'ESCALATED'
    
    def _clean_str(self, val: Optional[str]) -> str:
        if not val:
            return 'N/A'
        s = str(val).strip()
        if not s or s in ['.', '-', 'None', 'nan', 'null', '0', 'N/A', 'NULL']:
            return 'N/A'
        return s

    @property
    def clean_emergency_mobile(self) -> str:
        return self._clean_str(self.emergency_mobile or self.customer_contact)

    @property
    def clean_emergency_name(self) -> str:
        return self._clean_str(self.emergency_name or self.customer_name)

    @property
    def clean_res_phone(self) -> str:
        return self._clean_str(self.res_phone)

    @property
    def clean_office_phone(self) -> str:
        return self._clean_str(self.office_phone)

    @property
    def clean_customer_name(self) -> str:
        return self._clean_str(self.customer_name)

    def get_days_non_reporting(self) -> int:
        """Get number of days since last report"""
        if not self.last_reporting_time:
            return 0
        ref_time = self.last_reporting_time
        now = get_current_time()
        if ref_time.tzinfo is None and now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        elif ref_time.tzinfo is not None and now.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=None)
        delta = now - ref_time
        return max(0, delta.days)
    
    def get_latest_signal_time(self) -> Optional[datetime]:
        """Get the latest signal timestamp between dt_server, dt_tracker, and last_reporting_time"""
        times = [t for t in [self.dt_server, self.dt_tracker, self.last_reporting_time] if t is not None]
        return max(times) if times else None

    def get_hours_non_reporting(self) -> int:
        """Get number of hours since last report based on latest signal received"""
        ref_time = self.get_latest_signal_time()
        if not ref_time:
            return 48
        now = get_current_time()
        if ref_time.tzinfo is None and now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        elif ref_time.tzinfo is not None and now.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=None)
        delta = now - ref_time
        return max(0, int(delta.total_seconds() / 3600))
        
    def get_aging_bucket(self) -> str:
        """Categorize non-reporting vehicle into aging buckets based on offline hours.
        
        Buckets:
        - 24 Hours: Exactly 24 hours offline (24h)
        - 25-36 Hours: 25 to 36 hours offline
        - 37-48 Hours: 37 to 48 hours offline
        - 48+ Hours: More than 48 hours offline
        """
        hours = self.get_hours_non_reporting()
        if hours <= 24:
            return '24 Hours'
        elif hours <= 36:
            return '25-36 Hours'
        elif hours <= 48:
            return '37-48 Hours'
        else:
            return '48+ Hours'
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'registration_no': self.registration_no,
            'customer_name': self.customer_name,
            'customer_contact': self.customer_contact,
            'customer_phone2': self.customer_phone2,
            'customer_phone3': self.customer_phone3,
            'imei_no': self.imei_no,
            'sim_no': self.sim_no,
            'make': self.make,
            'model': self.model,
            'city': self.city,
            'engine_no': self.engine_no,
            'chassis_no': self.chassis_no,
            'vehicle_year': self.vehicle_year,
            'vehicle_color': self.vehicle_color,
            'device_location': self.device_location,
            'last_reporting_time': self.last_reporting_time.isoformat() if self.last_reporting_time else None,
            'first_detected_time': self.first_detected_time.isoformat() if self.first_detected_time else None,
            'days_non_reporting': self.get_days_non_reporting(),
            'hours_non_reporting': self.get_hours_non_reporting(),
            'status': self.status,
            'contact_outcome': self.contact_outcome,
            'priority': self.priority,
            'assigned_to': self.assigned_to,
            'assigned_at': self.assigned_at.isoformat() if self.assigned_at else None,
            'scheduled_date': self.scheduled_date.isoformat() if self.scheduled_date else None,
            'issue_summary': self.issue_summary,
            'resolution_notes': self.resolution_notes,
            'technician_notes': self.technician_notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
    
    def __repr__(self) -> str:
        return f"<NonReportingVehicle {self.registration_no} - {self.status}>"


class NonReportingConversation(BaseModel):
    """Conversation history for non-reporting vehicles"""
    __tablename__ = 'non_reporting_conversations'
    
    vehicle_id = db.Column(db.Integer, db.ForeignKey('non_reporting_vehicles.id'))
    conversation_date = db.Column(db.DateTime, default=get_current_time)
    conversation_type = db.Column(db.String(20))  # CALL, EMAIL, SMS, VISIT
    direction = db.Column(db.String(10))  # IN, OUT
    contact_person = db.Column(db.String(100))
    contact_number = db.Column(db.String(50))
    summary = db.Column(db.Text)
    action_taken = db.Column(db.Text)
    follow_up_required = db.Column(db.Boolean, default=False)
    follow_up_date = db.Column(db.Date)
    recorded_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    recorded_by_name = db.Column(db.String(100))
    
    # Relationships
    vehicle = db.relationship('NonReportingVehicle', backref='conversations_ref',
                              foreign_keys=[vehicle_id])
    recorded_by_user = db.relationship('User', backref='non_reporting_conversations',
                                       foreign_keys=[recorded_by])
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'conversation_date': self.conversation_date.isoformat() if self.conversation_date else None,
            'conversation_type': self.conversation_type,
            'direction': self.direction,
            'contact_person': self.contact_person,
            'contact_number': self.contact_number,
            'summary': self.summary,
            'action_taken': self.action_taken,
            'follow_up_required': self.follow_up_required,
            'follow_up_date': self.follow_up_date.isoformat() if self.follow_up_date else None,
            'recorded_by': self.recorded_by,
            'recorded_by_name': self.recorded_by_name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
    
    def __repr__(self) -> str:
        return f"<NonReportingConversation {self.id} - {self.vehicle_id}>" 
