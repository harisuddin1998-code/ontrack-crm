# src/models/base.py
"""
Base Model with common fields and utilities
"""
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, Integer, String, inspect
from sqlalchemy.orm import Mapped, mapped_column

from src.extensions import db
from src.utils.timezone import get_current_time


class BaseModel(db.Model):
    """
    Abstract base model with common fields and methods

    All models should inherit from this class.
    """
    __abstract__ = True

    # Common fields
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_current_time)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=get_current_time, onupdate=get_current_time)
    created_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    def __init__(self, **kwargs):
        """Initialize model with validation"""
        super().__init__(**kwargs)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert model to dictionary
        Override in child classes for custom fields
        """
        result = {}
        state = inspect(self)
        assert state is not None
        for column in state.mapper.columns:
            value = getattr(self, column.name)
            if isinstance(value, datetime):
                value = value.isoformat() if value else None
            result[column.name] = value
        return result
    
    def to_json(self) -> Dict[str, Any]:
        """Alias for to_dict"""
        return self.to_dict()
    
    def update(self, **kwargs) -> 'BaseModel':
        """
        Update model with validation
        
        Args:
            **kwargs: Fields to update
            
        Returns:
            self (chainable)
        """
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        return self
    
    def save(self) -> 'BaseModel':
        """
        Save model to database
        
        Returns:
            self (chainable)
        """
        db.session.add(self)
        db.session.commit()
        return self
    
    def delete(self) -> None:
        """Delete model from database"""
        db.session.delete(self)
        db.session.commit()
    
    @classmethod
    def get_by_id(cls, id: int) -> Optional['BaseModel']:
        """Get record by ID"""
        return db.session.get(cls, id)
    
    @classmethod
    def get_all(cls, **filters) -> list:
        """Get all records matching filters"""
        query = cls.query
        for key, value in filters.items():
            if value is not None:
                query = query.filter(getattr(cls, key) == value)
        return query.all()
    
    @classmethod
    def count(cls, **filters) -> int:
        """Count records matching filters"""
        query = cls.query
        for key, value in filters.items():
            if value is not None:
                query = query.filter(getattr(cls, key) == value)
        return query.count()
    
    @classmethod
    def exists(cls, **filters) -> bool:
        """Check if any record exists matching filters"""
        return cls.count(**filters) > 0
    
    @classmethod
    def paginate(cls, page: int = 1, per_page: int = 20, **filters):
        """Get paginated results"""
        query = cls.query
        for key, value in filters.items():
            if value is not None:
                query = query.filter(getattr(cls, key) == value)
        return query.paginate(page=page, per_page=per_page, error_out=False)
    
    def __repr__(self) -> str:
        """String representation"""
        return f"<{self.__class__.__name__} {self.id}>"


class TimestampMixin:
    """Mixin for timestamp fields"""
    created_at: Mapped[datetime] = mapped_column(DateTime, default=get_current_time)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=get_current_time, onupdate=get_current_time)


class SoftDeleteMixin:
    """Mixin for soft delete functionality"""
    is_deleted: Mapped[bool] = mapped_column(db.Boolean, default=False, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    deleted_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    def soft_delete(self, user_id: Optional[int] = None) -> None:
        """Soft delete the record"""
        self.is_deleted = True
        self.deleted_at = get_current_time()
        self.deleted_by = user_id
        db.session.commit()

    def restore(self) -> None:
        """Restore a soft-deleted record"""
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        db.session.commit()

    @classmethod
    def query_active(cls):
        """Query only non-deleted records"""
        return cls.query.filter(cls.is_deleted == False)  # type: ignore[attr-defined]


class AuditMixin:
    """Mixin for audit fields"""
    created_by_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    updated_by_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_by_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    def set_creator(self, user) -> None:
        """Set creator information"""
        if user:
            self.created_by_id = user.id if hasattr(user, 'id') else None
            self.created_by_name = user.name or user.username if hasattr(user, 'name') else None
    
    def set_updater(self, user) -> None:
        """Set updater information"""
        if user:
            self.updated_by_id = user.id if hasattr(user, 'id') else None
            self.updated_by_name = user.name or user.username if hasattr(user, 'name') else None


class StatusMixin:
    """Mixin for status fields"""
    STATUS_PENDING = 'PENDING'
    STATUS_IN_PROGRESS = 'IN_PROGRESS'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_CANCELLED = 'CANCELLED'
    STATUS_ACTIVE = 'ACTIVE'
    STATUS_INACTIVE = 'INACTIVE'
    STATUS_OVERDUE = 'OVERDUE'
    STATUS_PAID = 'PAID'
    STATUS_PARTIAL = 'PARTIAL'
    
    status: Mapped[str] = mapped_column(String(20), default='PENDING', nullable=False)
    
    @classmethod
    def get_status_choices(cls) -> list:
        """Get list of status choices"""
        return [
            ('PENDING', 'Pending'),
            ('IN_PROGRESS', 'In Progress'),
            ('COMPLETED', 'Completed'),
            ('CANCELLED', 'Cancelled'),
            ('ACTIVE', 'Active'),
            ('INACTIVE', 'Inactive'),
            ('OVERDUE', 'Overdue'),
            ('PAID', 'Paid'),
            ('PARTIAL', 'Partial'),
        ] 
