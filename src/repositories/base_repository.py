# src/repositories/base_repository.py - Complete Fixed File

"""
Base Repository Pattern - Data Access Layer
Provides generic CRUD operations for all models
"""
from typing import TypeVar, Generic, Type, Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Query

from src.extensions import db
from src.models.base import BaseModel
from src.utils.logging import get_logger

logger = get_logger(__name__)

T = TypeVar('T', bound=BaseModel)


class BaseRepository(Generic[T]):
    """
    Base repository with common database operations
    
    Usage:
        class UserRepository(BaseRepository[User]):
            def __init__(self):
                super().__init__(User)
    """
    
    def __init__(self, model_class: Type[T]):
        """
        Initialize repository with model class
        
        Args:
            model_class: SQLAlchemy model class
        """
        self.model_class = model_class
        self.session = db.session
    
    def get_by_id(self, id: int) -> Optional[T]:
        """Get record by primary key ID"""
        return self.session.get(self.model_class, id)
    
    def get_by(self, **filters) -> Optional[T]:
        """Get first record matching filters"""
        query = self.session.query(self.model_class)
        for key, value in filters.items():
            if value is not None:
                query = query.filter(getattr(self.model_class, key) == value)
        return query.first()
    
    def get_all(self, order_by: Optional[str] = None, desc: bool = False, **filters) -> List[T]:
        """
        Get all records matching filters with optional ordering
        
        Args:
            order_by: Column name to order by (without minus sign)
            desc: If True, order descending
            filters: Key-value pairs to filter by
        """
        query = self._apply_filters(self.session.query(self.model_class), **filters)
        
        # Handle order_by - remove any minus sign if present
        if order_by:
            # Remove leading minus sign if present (e.g., "-created_at" -> "created_at")
            clean_order_by = order_by.lstrip('-')
            try:
                column = getattr(self.model_class, clean_order_by)
                # If the original had a minus sign, use desc=True
                if order_by.startswith('-'):
                    query = query.order_by(column.desc())
                elif desc:
                    query = query.order_by(column.desc())
                else:
                    query = query.order_by(column.asc())
            except AttributeError as e:
                logger.warning(f"Order by column '{clean_order_by}' not found: {e}")
        
        return query.all()
    
    def get_paginated(self, page: int = 1, per_page: int = 20, 
                      order_by: Optional[str] = None, desc: bool = False,
                      **filters) -> Tuple[List[T], int]:
        """
        Get paginated results with optional ordering
        
        Returns:
            Tuple of (items, total_count)
        """
        query = self._apply_filters(self.session.query(self.model_class), **filters)
        
        # Handle order_by - remove any minus sign if present
        if order_by:
            clean_order_by = order_by.lstrip('-')
            try:
                column = getattr(self.model_class, clean_order_by)
                if order_by.startswith('-'):
                    query = query.order_by(column.desc())
                elif desc:
                    query = query.order_by(column.desc())
                else:
                    query = query.order_by(column.asc())
            except AttributeError as e:
                logger.warning(f"Order by column '{clean_order_by}' not found: {e}")
        
        # Flask-SQLAlchemy binds its own Query subclass (with .paginate()) as the
        # session's query_class, so this works at runtime even though the plain
        # SQLAlchemy Query type above doesn't declare the method.
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)  # type: ignore[attr-defined]
        return pagination.items, pagination.total
    
    def get_by_ids(self, ids: List[int]) -> List[T]:
        """Get multiple records by IDs"""
        return self.session.query(self.model_class).filter(
            self.model_class.id.in_(ids)
        ).all()
    
    def create(self, **kwargs) -> T:
        """Create a new record"""
        instance = self.model_class(**kwargs)
        self.session.add(instance)
        self.session.commit()
        return instance
    
    def create_bulk(self, items: List[Dict[str, Any]]) -> List[T]:
        """Create multiple records"""
        instances = []
        for item in items:
            instance = self.model_class(**item)
            self.session.add(instance)
            instances.append(instance)
        self.session.commit()
        return instances
    
    def update(self, id: int, **kwargs) -> Optional[T]:
        """Update a record by ID"""
        instance = self.get_by_id(id)
        if instance:
            for key, value in kwargs.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            self.session.commit()
        return instance
    
    def update_bulk(self, ids: List[int], **kwargs: Any) -> int:
        """Update multiple records"""
        count = self.session.query(self.model_class).filter(
            self.model_class.id.in_(ids)
        ).update(dict(kwargs))  # type: ignore[arg-type]
        self.session.commit()
        return count
    
    def delete(self, id: int) -> bool:
        """Delete a record by ID"""
        instance = self.get_by_id(id)
        if instance:
            self.session.delete(instance)
            self.session.commit()
            return True
        return False
    
    def delete_bulk(self, ids: List[int]) -> int:
        """Delete multiple records by IDs"""
        count = self.session.query(self.model_class).filter(
            self.model_class.id.in_(ids)
        ).delete(synchronize_session=False)
        self.session.commit()
        return count
    
    def count(self, **filters) -> int:
        """Count records matching filters"""
        query = self._apply_filters(self.session.query(self.model_class), **filters)
        return query.count()
    
    def exists(self, **filters) -> bool:
        """Check if any record exists matching filters"""
        return self.count(**filters) > 0
    
    def first_or_create(self, defaults: Optional[Dict[str, Any]] = None, **filters) -> Tuple[T, bool]:
        """
        Get first record matching filters, or create if not exists
        
        Returns:
            Tuple of (instance, created)
        """
        instance = self.get_by(**filters)
        if instance:
            return instance, False
        
        if defaults:
            filters.update(defaults)
        
        instance = self.create(**filters)
        return instance, True
    
    def update_or_create(self, defaults: Optional[Dict[str, Any]] = None, 
                         **filters) -> Tuple[T, bool]:
        """
        Update existing record or create new one
        
        Returns:
            Tuple of (instance, created)
        """
        instance = self.get_by(**filters)
        if instance:
            if defaults:
                for key, value in defaults.items():
                    if hasattr(instance, key):
                        setattr(instance, key, value)
                self.session.commit()
            return instance, False
        
        if defaults:
            filters.update(defaults)
        
        instance = self.create(**filters)
        return instance, True
    
    def _apply_filters(self, query: Query, **filters) -> Query:
        """Apply filters to query"""
        for key, value in filters.items():
            if value is not None:
                # Skip special keys that start with underscore
                if key.startswith('_'):
                    continue
                # Handle relationship filters
                if '__' in key:
                    parts = key.split('__')
                    if len(parts) == 2:
                        attr = getattr(self.model_class, parts[0])
                        query = query.filter(attr.has(**{parts[1]: value}))
                else:
                    query = query.filter(getattr(self.model_class, key) == value)
        return query
    
    def get_latest(self, **filters) -> Optional[T]:
        """Get latest record (by created_at)"""
        query = self._apply_filters(self.session.query(self.model_class), **filters)
        return query.order_by(self.model_class.created_at.desc()).first()
    
    def get_oldest(self, **filters) -> Optional[T]:
        """Get oldest record (by created_at)"""
        query = self._apply_filters(self.session.query(self.model_class), **filters)
        return query.order_by(self.model_class.created_at.asc()).first()
    
    def get_by_date_range(self, field: str, start_date, end_date, **filters) -> List[T]:
        """Get records within date range"""
        query = self._apply_filters(self.session.query(self.model_class), **filters)
        query = query.filter(
            getattr(self.model_class, field) >= start_date,
            getattr(self.model_class, field) <= end_date
        )
        return query.all()