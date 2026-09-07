# src/models/security.py
"""
Security Briefing Models
"""
from typing import Dict, Any, Optional
from datetime import datetime

from src.extensions import db
from src.models.base import BaseModel, StatusMixin
from src.utils.timezone import get_current_time

# Configuration mapping linking briefing field names to PO properties (read-only lookups)
BRIEFING_MAPPING = {
    'registration_no': 'purchase_order.reg_no',
    'engine_no': 'purchase_order.engine_number',
    'chassis_no': 'purchase_order.chassis_number',
    'make': 'purchase_order.vehicle_make',
    'model': 'purchase_order.vehicle_model',
    'year': 'purchase_order.vehicle_year',
    'color': 'purchase_order.vehicle_color',
    'customer_name': 'purchase_order.owner_name',
    'phone': 'purchase_order.owner_contact',
    'installation_date': 'purchase_order.scheduled_date',
    'technician_name': 'purchase_order.technician_assigned',
    'device_location': 'purchase_order.device_location',
    'sales_person_name': 'sales_person_name_fallback',
    'imei_no': 'purchase_order.imei_no',
    'sim_no': 'purchase_order.sim_no',
    'remarks': 'purchase_order.remarks',
}


class SecurityBriefingData(BaseModel, StatusMixin):
    """Security briefing data for vehicle installations"""
    __tablename__ = 'security_briefing_data'
    
    po_id = db.Column(db.Integer, db.ForeignKey('purchase_orders.id'), 
                     unique=True, nullable=False)
    
    # Customer Details (collected during security briefing)
    segment = db.Column(db.String(50))
    cnic = db.Column(db.String(20))
    address = db.Column(db.String(500))
    father_name = db.Column(db.String(200))
    mother_name = db.Column(db.String(200))
    secondary_user_name = db.Column(db.String(200))
    secondary_user_phone = db.Column(db.String(50))
    emergency_user_name = db.Column(db.String(200))
    emergency_user_phone = db.Column(db.String(50))
    
    # Installation Details (saved by installer update form)
    device_serial_no = db.Column(db.String(100))
    sim_network = db.Column(db.String(100))
    accessories_installed = db.Column(db.String(500))
    
    # Credentials and Configuration (Security specific)
    password_1 = db.Column(db.String(100))
    password_2 = db.Column(db.String(100))
    fence = db.Column(db.String(500))
    
    # Security Checklist fields
    security_training_completed = db.Column(db.Boolean, default=False)
    customer_demonstration = db.Column(db.Boolean, default=False)
    services_explained = db.Column(db.Boolean, default=False)
    customer_signature = db.Column(db.Text)
    acknowledgement = db.Column(db.Boolean, default=False)
    
    # Briefing Metadata
    briefed_by = db.Column(db.String(100))
    briefed_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    officer_notes = db.Column(db.Text)

    # True when the briefing was raised automatically by an installation
    # being completed (the completion email going out), rather than created
    # by hand. Drives the "New from Installations" tab on the wallboard -
    # the officer's inbox of work that just arrived.
    synced_from_po = db.Column(db.Boolean, default=False, nullable=False)
    
    # Relationships
    purchase_order = db.relationship('PurchaseOrder', backref='security_briefing_data_ref', 
                                     foreign_keys=[po_id])
    
    def is_completed(self) -> bool:
        """Check if briefing is completed"""
        return self.status == self.STATUS_COMPLETED
    
    def complete(self, officer_name: str) -> None:
        """Mark briefing as completed"""
        self.status = self.STATUS_COMPLETED
        self.briefed_by = officer_name
        self.completed_at = db.func.current_timestamp()
        db.session.commit()

    def __getattr__(self, name: str) -> Any:
        # Avoid infinite recursion during sqlalchemy setup or when attributes start with underscore
        if name.startswith('_'):
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
            
        if name in BRIEFING_MAPPING:
            path = BRIEFING_MAPPING[name]
            
            # Special case for fallback sales person name resolver
            if path == 'sales_person_name_fallback':
                if self.purchase_order and self.purchase_order.sales_person_id:
                    from src.models.user import User
                    user = User.query.get(self.purchase_order.sales_person_id)
                    return user.name or user.username if user else 'N/A'
                return 'N/A'
            
            # Traverse attribute path
            parts = path.split('.')
            obj = self
            for part in parts:
                if obj is None:
                    break
                obj = getattr(obj, part, None)
            return obj
            
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'po_id': self.po_id,
            'po_number': self.purchase_order.po_number if self.purchase_order else None,
            
            # Dynamically loaded fields (from PO via __getattr__)
            'registration_no': self.registration_no,
            'engine_no': self.engine_no,
            'chassis_no': self.chassis_no,
            'make': self.make,
            'model': self.model,
            'year': self.year,
            'color': self.color,
            'customer_name': self.customer_name,
            'phone': self.phone,
            'installation_date': self.installation_date.isoformat() if self.installation_date else None,
            'technician_name': self.technician_name,
            'device_location': self.device_location,
            'sales_person_name': self.sales_person_name,
            'imei_no': self.imei_no,
            'sim_no': self.sim_no,
            'remarks': self.remarks,
            
            # Briefing-owned fields (stored as columns)
            'segment': self.segment,
            'cnic': self.cnic,
            'address': self.address,
            'father_name': self.father_name,
            'mother_name': self.mother_name,
            'secondary_user_name': self.secondary_user_name,
            'secondary_user_phone': self.secondary_user_phone,
            'emergency_user_name': self.emergency_user_name,
            'emergency_user_phone': self.emergency_user_phone,
            'device_serial_no': self.device_serial_no,
            'sim_network': self.sim_network,
            'accessories_installed': self.accessories_installed,
            
            # Security briefing specific fields
            'password_1': self.password_1,
            'password_2': self.password_2,
            'fence': self.fence,
            'security_training_completed': self.security_training_completed,
            'customer_demonstration': self.customer_demonstration,
            'services_explained': self.services_explained,
            'customer_signature': self.customer_signature,
            'acknowledgement': self.acknowledgement,
            'status': self.status,
            'briefed_by': self.briefed_by,
            'briefed_at': self.briefed_at.isoformat() if self.briefed_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'officer_notes': self.officer_notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
    
    def __repr__(self) -> str:
        return f"<SecurityBriefingData {self.id} - PO {self.po_id}>"
