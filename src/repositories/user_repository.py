# src/repositories/user_repository.py
"""
User Repository
"""
from typing import Optional, List, Dict, Any

from src.models.user import User
from src.repositories.base_repository import BaseRepository
from src.extensions import db


class UserRepository(BaseRepository[User]):
    """Repository for User operations"""
    
    def __init__(self):
        super().__init__(User)
    
    def get_by_username(self, username: str) -> Optional[User]:
        """Get user by username"""
        return self.get_by(username=username)
    
    def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email"""
        return self.get_by(email=email)
    
    def get_by_role(self, role: str) -> List[User]:
        """Get users by role"""
        return self.get_all(role=role)
    
    def get_active_users(self) -> List[User]:
        """Get active users"""
        return self.get_all(is_active=True)
    
    def get_inactive_users(self) -> List[User]:
        """Get inactive users"""
        return self.get_all(is_active=False)
    
    def get_sales_users(self) -> List[User]:
        """Get sales users"""
        return self.get_by_role(User.ROLE_SALES)
    
    def get_installation_users(self) -> List[User]:
        """Get installation users"""
        return self.get_by_role(User.ROLE_INSTALLATION)
    
    def get_security_users(self) -> List[User]:
        """Get security users"""
        return self.get_by_role(User.ROLE_SECURITY)
    
    def get_payment_recovery_users(self) -> List[User]:
        """Get payment recovery users"""
        return self.get_by_role(User.ROLE_PAYMENT_RECOVERY)
    
    def get_redo_technicians(self) -> List[User]:
        """Get REDO technicians"""
        return self.get_by_role(User.ROLE_REDO_TECHNICIAN)
    
    def get_removal_users(self) -> List[User]:
        """Get removal users"""
        return self.get_by_role(User.ROLE_REMOVAL)
    
    def authenticate(self, username: str, password: str) -> Optional[User]:
        """Authenticate user by username and password"""
        user = self.get_by_username(username)
        if user and user.is_active and user.check_password(password):
            return user
        return None
    
    def create_user(self, username: str, email: str, password: str,
                    role: str, name: Optional[str] = None, contact: Optional[str] = None,
                    is_active: bool = True, additional_roles: Optional[str] = None,
                    created_by_id: Optional[int] = None) -> User:
        """Create a new user with password"""
        user = User(
            username=username,
            email=email,
            role=role,
            name=name,
            contact=contact,
            is_active=is_active,
            additional_roles=additional_roles,
            created_by_id=created_by_id
        )
        user.set_password(password)
        self.session.add(user)
        self.session.commit()
        return user
    
    def update_password(self, user_id: int, new_password: str) -> Optional[User]:
        """Update user password"""
        user = self.get_by_id(user_id)
        if user:
            user.set_password(new_password)
            self.session.commit()
        return user
    
    def get_role_counts(self) -> Dict[str, int]:
        """Get count of users by role"""
        from sqlalchemy import func
        
        results = self.session.query(
            User.role,
            func.count(User.id).label('count')
        ).group_by(User.role).all()
        
        return {r[0]: r[1] for r in results}
    
    def search_users(self, search_term: str) -> List[User]:
        """Search users by username, email, or name"""
        return self.session.query(User).filter(
            db.or_(
                User.username.ilike(f'%{search_term}%'),
                User.email.ilike(f'%{search_term}%'),
                User.name.ilike(f'%{search_term}%')
            )
        ).all() 
