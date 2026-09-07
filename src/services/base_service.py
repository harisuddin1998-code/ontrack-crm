# src/services/base_service.py
"""
Base Service - Common business logic utilities
"""
from typing import Optional, List, Dict, Any, TypeVar, Generic
from src.repositories.base_repository import BaseRepository
from src.extensions import db

T = TypeVar('T')


class BaseService(Generic[T]):
    """
    Base service with common business logic
    
    All services should inherit from this class.
    """
    
    def __init__(self, repository: BaseRepository[T]):
        self.repository = repository
    
    def get_by_id(self, id: int) -> Optional[T]:
        """Get record by ID"""
        return self.repository.get_by_id(id)
    
    def get_all(self, order_by: Optional[str] = None, desc: bool = False, **filters) -> List[T]:
        """Get all records matching filters with optional ordering"""
        return self.repository.get_all(order_by=order_by, desc=desc, **filters)
    
    def get_paginated(self, page: int = 1, per_page: int = 20, 
                      order_by: Optional[str] = None, desc: bool = False, **filters):
        """Get paginated results with optional ordering"""
        return self.repository.get_paginated(page, per_page, order_by, desc, **filters)
    
    def create(self, **kwargs) -> T:
        """Create a new record"""
        return self.repository.create(**kwargs)
    
    def update(self, id: int, **kwargs) -> Optional[T]:
        """Update a record"""
        return self.repository.update(id, **kwargs)
    
    def delete(self, id: int) -> bool:
        """Delete a record"""
        return self.repository.delete(id)
    
    def count(self, **filters) -> int:
        """Count records"""
        return self.repository.count(**filters)
    
    def exists(self, **filters) -> bool:
        """Check if record exists"""
        return self.repository.exists(**filters)
    
    def validate_data(self, data: Dict[str, Any], required_fields: List[str]) -> List[str]:
        """
        Validate required fields in data
        
        Returns:
            List of missing field names
        """
        missing = []
        for field in required_fields:
            if field not in data or data[field] is None or data[field] == '':
                missing.append(field)
        return missing
    
    def sanitize_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize input data by stripping whitespace and handling None values
        
        Args:
            data: Input dictionary
            
        Returns:
            Sanitized dictionary
        """
        sanitized = {}
        excluded_keys = [
            'email', 'password', 'password_hash', 'url', 'api_key', 
            'gps_api_key', 'gps_api_url', 'username', 'token'
        ]
        for key, value in data.items():
            if isinstance(value, str):
                val = value.strip()
                if val:
                    # Convert to uppercase unless excluded
                    if key.lower() not in excluded_keys:
                        val = val.upper()
                    sanitized[key] = val
                else:
                    sanitized[key] = None
            elif value == '':
                sanitized[key] = None
            else:
                sanitized[key] = value
        return sanitized