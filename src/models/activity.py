# src/models/activity.py
"""
Activity Log Models
"""
from typing import Dict, Any, Optional

from src.extensions import db
from src.models.base import BaseModel


class ActivityLog(BaseModel):
    """Activity log for user actions"""
    __tablename__ = 'activity_logs'
    
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(100))
    po_id = db.Column(db.Integer, db.ForeignKey('purchase_orders.id'))
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    
    # Relationships
    user = db.relationship('User', backref='activities', foreign_keys=[user_id])
    purchase_order = db.relationship('PurchaseOrder', backref='activities',
                                     foreign_keys=[po_id])
    
    @classmethod
    def log(cls, user_id: int, action: str, po_id: Optional[int] = None, 
            details: Optional[str] = None, ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> 'ActivityLog':
        """Create a new activity log entry"""
        log = cls(
            user_id=user_id,
            action=action,
            po_id=po_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent
        )
        db.session.add(log)
        db.session.commit()
        return log
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'user_id': self.user_id,
            'username': self.user.username if self.user else None,
            'user_name': self.user.name if self.user else None,
            'action': self.action,
            'po_id': self.po_id,
            'po_number': self.purchase_order.po_number if self.purchase_order else None,
            'details': self.details,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
    
    def __repr__(self) -> str:
        return f"<ActivityLog {self.id} - {self.action} - User {self.user_id}>" 
