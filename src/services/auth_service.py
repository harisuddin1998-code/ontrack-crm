# src/services/auth_service.py
"""
Authentication Service - User authentication and session management
"""
from typing import Optional, Dict, Any, List
from datetime import datetime, time, timedelta
try:
    import jwt
except ImportError:
    jwt = None
from flask import current_app

from src.models.user import User
from src.repositories.user_repository import UserRepository
from src.services.base_service import BaseService
from src.extensions import db
from src.utils.logging import get_logger
from src.utils.timezone import get_current_time

logger = get_logger(__name__)

# Arriving after this is late. One definition, because the figure the
# greeting quotes and the figure the streak counts have to be the same one.
LATE_AFTER = time(10, 30)

# Late this many days running stops being a bad morning and starts being a
# habit, and the greeting says so.
HABITUAL_AFTER_DAYS = 3

# How a sign-in and a sign-out are named in the activity log. Constants
# because the two places that write them and the report that reads them back
# have to agree exactly - a renamed string would empty the report silently.
ACTION_LOGIN = 'login'
ACTION_LOGOUT = 'logout'


class AuthService(BaseService[User]):
    """Authentication service"""
    
    def __init__(self):
        super().__init__(UserRepository())
        self.user_repo = UserRepository()
    
    def authenticate(self, username: str, password: str, 
                     ip_address: Optional[str] = None) -> Optional[User]:
        """
        Authenticate a user
        
        Args:
            username: Username
            password: Password
            ip_address: Client IP address (for logging)
            
        Returns:
            User if authenticated, None otherwise
        """
        user = self.user_repo.authenticate(username, password)

        if user:
            # Timekeeping first: it reads the day of the previous sign-in,
            # which the line below is about to overwrite.
            self.record_attendance(user)

            # Update last login
            user.last_login = datetime.now()
            user.last_login_ip = ip_address
            db.session.commit()

            # Recorded here rather than in the login routes so the web form
            # and the API both land in the report - one of them being missed
            # would make the report quietly incomplete rather than wrong,
            # which is worse.
            self.record_session_event(user, ACTION_LOGIN, ip_address)

            logger.info(f"User {user.username} logged in from {ip_address}")
        else:
            logger.warning(f"Failed login attempt for {username} from {ip_address}")

        return user

    @staticmethod
    def record_session_event(user, action: str,
                             ip_address: Optional[str] = None) -> None:
        """Log a sign-in or sign-out against the user it belongs to.

        Written to ActivityLog rather than to a table of its own: it already
        records who did what, from which address, on which browser and when,
        which is the whole of a session event. The login/logout report reads
        these two actions back out of it.

        Never raises. Failing to write the log must not stop somebody signing
        in - still less stop them signing out.
        """
        from flask import has_request_context, request
        from src.models.activity import ActivityLog

        if user is None or getattr(user, 'id', None) is None:
            return

        try:
            user_agent = None
            if has_request_context():
                ip_address = ip_address or request.remote_addr
                # The column holds 255; a long browser string is trimmed here
                # rather than rejected by the database on write.
                user_agent = (request.headers.get('User-Agent') or '')[:255] or None

            ActivityLog.log(user_id=user.id, action=action,
                            ip_address=ip_address, user_agent=user_agent)
        except Exception as e:
            db.session.rollback()
            logger.error(f"Could not record {action} for user "
                         f"{getattr(user, 'username', '?')}: {e}")

    def record_attendance(self, user: User, now: Optional[datetime] = None) -> None:
        """Note whether this user arrived on time today.

        Judged on the *first* sign-in of the day only. Somebody who starts at
        09:00 and signs in again after lunch has not arrived twice, and
        counting the second one would make almost everybody late.

        The streak counts consecutive late days and any on-time day clears
        it, so it measures a habit rather than a running total of every late
        morning a person has ever had.
        """
        now = now or get_current_time()
        today = now.date()

        if user.last_login_day == today:
            return

        user.last_login_day = today
        if now.time() > LATE_AFTER:
            user.late_login_streak = (user.late_login_streak or 0) + 1
            user.last_late_login = today
        else:
            user.late_login_streak = 0

    @staticmethod
    def greeting(user: User, now: Optional[datetime] = None) -> str:
        """How to greet this user as they land.

        Derived from what `record_attendance` stored rather than recomputed,
        so the greeting and the streak behind it can never tell two different
        stories about the same morning.
        """
        now = now or get_current_time()
        name = user.name or user.username

        hour = now.hour
        part = 'morning' if hour < 12 else ('afternoon' if hour < 17 else 'evening')
        opening = f'Good {part}, {name}'

        if user.last_late_login != now.date():
            return f'{opening} — hope you are doing well.'

        if (user.late_login_streak or 0) >= HABITUAL_AFTER_DAYS:
            return (f'{opening} — you have become habitual. '
                    'Please improve your timings.')

        return f'{opening} — you are late today.'

    def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Get user by ID"""
        return self.user_repo.get_by_id(user_id)
    
    def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username"""
        return self.user_repo.get_by_username(username)
    
    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email"""
        return self.user_repo.get_by_email(email)
    
    def change_password(self, user_id: int, old_password: str, 
                         new_password: str) -> tuple:
        """
        Change user password
        
        Returns:
            (success, message)
        """
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return False, "User not found"
        
        if not user.check_password(old_password):
            return False, "Current password is incorrect"
        
        if len(new_password) < 6:
            return False, "New password must be at least 6 characters"
        
        user.set_password(new_password)
        db.session.commit()
        
        logger.info(f"Password changed for user {user.username}")
        return True, "Password changed successfully"
    
    def reset_password(self, email: str) -> tuple:
        """
        Reset password (send reset link)
        
        Returns:
            (success, message)
        """
        user = self.user_repo.get_by_email(email)
        if not user:
            return False, "No user found with this email"
        
        # Generate reset token
        token = self._generate_reset_token(user.id)
        
        # Send reset email (implement in email service)
        from src.services.email_service import EmailService
        email_service = EmailService()
        email_service.send_password_reset_email(user, token)
        
        logger.info(f"Password reset requested for {user.email}")
        return True, "Password reset link sent to your email"
    
    def _generate_reset_token(self, user_id: int) -> str:
        """Generate password reset token"""
        if jwt is None:
            return str(user_id)
        secret = current_app.config.get('SECRET_KEY')
        from datetime import timezone
        payload = {
            'user_id': user_id,
            'exp': datetime.now(timezone.utc) + timedelta(hours=24)
        }
        res = jwt.encode(payload, secret, algorithm='HS256')
        return res.decode('utf-8') if isinstance(res, bytes) else res
    
    def verify_reset_token(self, token: str) -> Optional[int]:
        """
        Verify reset token and return user ID
        
        Returns:
            User ID if valid, None otherwise
        """
        if jwt is None:
            try:
                return int(token)
            except ValueError:
                return None
        try:
            secret = current_app.config.get('SECRET_KEY')
            payload = jwt.decode(token, secret, algorithms=['HS256'])
            return payload.get('user_id')
        except Exception:
            return None
    
    def get_user_permissions(self, user: User) -> List[str]:
        """
        Get permissions for a user based on role
        
        Returns:
            List of permission strings
        """
        permissions = []
        
        if user.is_admin():
            permissions.extend([
                'view_all', 'create_all', 'edit_all', 'delete_all',
                'manage_users', 'manage_settings'
            ])
        
        if user.is_sales():
            permissions.extend([
                'view_pos', 'create_pos', 'edit_own_pos',
                'view_customers', 'create_customers'
            ])
        
        if user.is_installation():
            permissions.extend([
                'view_pos', 'update_installation_status',
                'view_technicians', 'view_trips'
            ])
        
        if user.is_security():
            permissions.extend([
                'view_security_briefings', 'create_security_briefings',
                'complete_security_briefings'
            ])
        
        if user.is_payment_recovery():
            permissions.extend([
                'view_payments', 'process_payments',
                'view_payment_history'
            ])
        
        if user.is_redo_technician():
            permissions.extend([
                'view_redo', 'update_redo',
                'view_non_reporting', 'update_non_reporting'
            ])
        
        if user.is_removal():
            permissions.extend([
                'view_removal', 'update_removal',
                'view_transfers', 'update_transfers'
            ])
        
        return permissions
    
    def has_permission(self, user: User, permission: str) -> bool:
        """Check if user has a specific permission"""
        return permission in self.get_user_permissions(user)
    
    def get_dashboard_stats(self) -> Dict[str, Any]:
        """Get dashboard statistics"""
        return {
            'total_users': self.user_repo.count(),
            'active_users': self.user_repo.count(is_active=True),
            'inactive_users': self.user_repo.count(is_active=False),
            'role_counts': self.user_repo.get_role_counts(),
        } 
