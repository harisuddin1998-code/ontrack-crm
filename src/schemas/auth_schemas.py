# src/schemas/auth_schemas.py
"""
Authentication Pydantic Schemas
"""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, validator


class LoginRequest(BaseModel):
    """Login request schema"""
    username: str = Field(..., min_length=3, max_length=80)
    password: str = Field(..., min_length=1)
    remember_me: bool = False


class LoginResponse(BaseModel):
    """Login response schema"""
    success: bool
    user: Optional['UserResponse'] = None
    error: Optional[str] = None


class UserResponse(BaseModel):
    """User response schema"""
    id: int
    username: str
    email: str
    name: Optional[str] = None
    role: str
    role_display: str
    is_active: bool
    last_login: Optional[datetime] = None
    permissions: Optional[list] = []
    
    class Config:
        from_attributes = True


class ChangePasswordRequest(BaseModel):
    """Change password request schema"""
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6)
    
    @validator('new_password')
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters')
        return v


class ResetPasswordRequest(BaseModel):
    """Reset password request schema"""
    email: EmailStr


class ResetPasswordConfirm(BaseModel):
    """Reset password confirm schema"""
    token: str
    new_password: str = Field(..., min_length=6)
    
    @validator('new_password')
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters')
        return v