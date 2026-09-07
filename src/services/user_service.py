# src/services/user_service.py
"""
User Service - User management operations
"""
from typing import Optional, List

from src.models.user import User
from src.repositories.user_repository import UserRepository
from src.services.base_service import BaseService
from src.utils.logging import get_logger

logger = get_logger(__name__)


class UserService(BaseService[User]):
    """Service for user operations"""
    
    def __init__(self):
        super().__init__(UserRepository())
        self.user_repo = UserRepository()
    
    def get_sales_users(self) -> List[User]:
        """Get all sales users"""
        return self.user_repo.get_sales_users()
    
    def get_installation_users(self) -> List[User]:
        """Get all installation users"""
        return self.user_repo.get_installation_users()
    
    def get_security_users(self) -> List[User]:
        """Get all security users"""
        return self.user_repo.get_security_users()
    
    def get_payment_recovery_users(self) -> List[User]:
        """Get all payment recovery users"""
        return self.user_repo.get_payment_recovery_users()
    
    def get_redo_technicians(self) -> List[User]:
        """Get all REDO technicians"""
        return self.user_repo.get_redo_technicians()
    
    def get_removal_users(self) -> List[User]:
        """Get all removal users"""
        return self.user_repo.get_removal_users()
    
    def get_by_username(self, username: str) -> Optional[User]:
        """Get user by username"""
        return self.user_repo.get_by_username(username)
    
    def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email"""
        return self.user_repo.get_by_email(email)
    
    def create_user(self, **kwargs) -> User:
        """Create a new user with password"""
        password = kwargs.pop('password', None)
        if not password:
            raise ValueError("Password is required when creating a user")
        username = kwargs.get('username')
        email = kwargs.get('email')
        role = kwargs.get('role')
        if not username or not email or not role:
            raise ValueError("username, email, and role are required when creating a user")
        return self.user_repo.create_user(
            username=username,
            email=email,
            password=password,
            role=role,
            name=kwargs.get('name'),
            contact=kwargs.get('contact'),
            is_active=kwargs.get('is_active', True),
            additional_roles=kwargs.get('additional_roles'),
            created_by_id=kwargs.get('created_by_id')
        )
    
    def update(self, id: int, **kwargs) -> Optional[User]:
        """Update a user, including password hashing if password provided"""
        password = kwargs.pop('password', None)
        user = super().update(id, **kwargs)
        if user and password and str(password).strip():
            self.user_repo.update_password(id, str(password).strip())
        return user
    
    def release_assigned_work(self, user_id: int) -> dict:
        """Return every piece of work assigned to a user back to the pool.

        Deleting a user used to leave these columns pointing at an id that no
        longer existed. That work then became invisible to every officer - the
        per-officer filter (`assigned_to == me`) matches nobody - while still
        counting for admin/manager, so nothing looked wrong from the top. 356
        Device Recovery charges sat unseen this way.

        Unassigning is deliberate rather than reassigning to someone else: the
        work resurfaces as explicitly unassigned, where a supervisor can hand it
        on, instead of silently landing on a person who was never told.
        """
        from src.extensions import db
        from src.models.annual_recovery import AnnualRecoveryVehicle
        from src.models.gps import NonReportingVehicle
        from src.models.installation_recovery import InstallationRecoveryCharge
        from src.models.live_amc import LiveAmcAssignment

        assignments = (
            (InstallationRecoveryCharge, 'assigned_officer_id'),
            (AnnualRecoveryVehicle, 'assigned_to'),
            (LiveAmcAssignment, 'assigned_officer_id'),
            (NonReportingVehicle, 'assigned_to'),
        )

        released = {}
        for model, column in assignments:
            rows = model.query.filter(getattr(model, column) == user_id).all()
            for row in rows:
                setattr(row, column, None)
            if rows:
                released[model.__tablename__] = len(rows)
        if released:
            db.session.commit()
        return released

    def delete(self, id: int) -> bool:
        """Delete a user, first releasing any work assigned to them.

        Overridden rather than handled in the route so every path that deletes
        a user goes through the handover - see release_assigned_work.
        """
        released = self.release_assigned_work(id)
        if released:
            logger.warning(
                f"User {id} deleted - released assigned work back to the pool: {released}")
        return super().delete(id)

    def get_dashboard_stats(self) -> dict:
        """Get user statistics"""
        return {
            'total': self.count(),
            'active': self.count(is_active=True),
            'inactive': self.count(is_active=False),
            'role_counts': self.user_repo.get_role_counts(),
        }