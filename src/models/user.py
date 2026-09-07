# src/models/user.py
"""
User Model - Authentication and Authorization
"""
from datetime import datetime
from typing import Optional, Dict, Any
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from src.extensions import db
from src.models.base import BaseModel, AuditMixin, StatusMixin


class UserCodeSequence(db.Model):
    """Single-row persistent counter backing User.user_code. Kept separate
    from `users` so a deleted user's code number is never reissued -
    MAX(user_code) would go backwards after a delete; this doesn't."""
    __tablename__ = 'user_code_sequence'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    next_value = db.Column(db.Integer, nullable=False, default=1)


class User(BaseModel, UserMixin, AuditMixin, StatusMixin):
    """User model for authentication and authorization"""
    __tablename__ = 'users'
    __table_args__ = {'extend_existing': True}
    
    # User fields
    # Stable, human-readable, never-reused identifier (USR-0001, USR-0002, ...)
    # - independent of the raw `id` primary key, which SQLite can silently
    # reuse once a row is deleted. Assigned automatically on creation (see
    # the before_insert listener below) for every user, present and future.
    user_code = db.Column(db.String(20), unique=True, index=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False, index=True)
    name = db.Column(db.String(100))
    contact = db.Column(db.String(50))
    # Comma-separated extra roles on top of the primary `role` - lets a
    # manager (or anyone) be granted additional department views without
    # changing their primary role or duplicating accounts.
    additional_roles = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    last_login = db.Column(db.DateTime)
    last_login_ip = db.Column(db.String(45))  # IPv6 compatible

    # Sign-in timekeeping, behind the greeting on the landing page.
    #
    # `last_login_day` is the Pakistan-time date of the user's most recent
    # *first* sign-in of a day. Kept separately from `last_login`, which is
    # overwritten on every sign-in and stamped in server time: whether
    # somebody was late is a question about the first time they arrived that
    # day, so it needs a value the second sign-in does not overwrite, on the
    # clock the office actually runs on.
    last_login_day = db.Column(db.Date)
    last_late_login = db.Column(db.Date)
    # Consecutive days arrived late, reset by any on-time day.
    late_login_streak = db.Column(db.Integer, default=0, nullable=False)
    
    # Relationships - FIXED: Changed backref names to avoid conflicts
    # Sales person relationship
    purchase_orders = db.relationship('PurchaseOrder', backref='sales_person', 
                                       foreign_keys='PurchaseOrder.sales_person_id')
    
    # Payment recovery relationship - FIXED: Changed backref name
    payment_recoveries = db.relationship('PaymentRecovery', backref='received_by_user',
                                          foreign_keys='PaymentRecovery.payment_received_by')
    
    # Non-reporting vehicle assignment
    assigned_non_reporting = db.relationship('NonReportingVehicle', backref='assigned_user',
                                             foreign_keys='NonReportingVehicle.assigned_to')
    
    # Removed the problematic created_pos relationship since it causes conflicts
    
    # Role constants
    ROLE_ADMIN = 'admin'
    ROLE_MANAGER = 'manager'
    ROLE_SALES = 'sales'
    ROLE_INSTALLATION = 'installation'
    ROLE_SECURITY = 'security'
    ROLE_PAYMENT_RECOVERY = 'payment_recovery'
    ROLE_REDO_TECHNICIAN = 'redo_technician'
    ROLE_NR_TEAM = 'redo_technician'  # NR Team (Not Reporting & REDO operations)
    ROLE_REMOVAL = 'removal'
    ROLE_COMPLAINT_MANAGER = 'complaint_manager'
    ROLE_RECOVERY_OFFICER = 'recovery_officer'
    ROLE_INVENTORY = 'inventory'
    # Device Recovery (Power Issue / Device Damage / Device Missing) is its own
    # job function. It used to be reachable only by holding payment_recovery,
    # which also grants the Installation Payment Recovery ledger - so it could
    # not be handed to someone as a standalone view.
    ROLE_DEVICE_RECOVERY = 'device_recovery'
    # Works the Suggestions wallboard alongside the Administrator: triaging
    # what users report about the CRM itself and answering them. Raising a
    # suggestion needs no role at all - every user can do that - so this
    # grants only the triage side.
    ROLE_SUGGESTION_MANAGER = 'suggestion_manager'
    ROLE_EXECUTIVE = 'executive'

    ROLES = [
        ROLE_ADMIN,
        ROLE_MANAGER,
        ROLE_SALES,
        ROLE_INSTALLATION,
        ROLE_SECURITY,
        ROLE_PAYMENT_RECOVERY,
        ROLE_REDO_TECHNICIAN,
        ROLE_REMOVAL,
        ROLE_COMPLAINT_MANAGER,
        ROLE_RECOVERY_OFFICER,
        ROLE_INVENTORY,
        ROLE_DEVICE_RECOVERY,
        ROLE_SUGGESTION_MANAGER,
        ROLE_EXECUTIVE,
    ]
    
    def __init__(self, **kwargs):
        """Initialize user with password handling"""
        password = kwargs.pop('password', None)
        super().__init__(**kwargs)
        if password:
            self.set_password(password)
    
    def set_password(self, password: str) -> None:
        """Set password hash"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password: str) -> bool:
        """Check password against hash"""
        return check_password_hash(self.password_hash, password)
    
    def get_additional_roles(self) -> list:
        """Extra roles granted on top of the primary role, as a clean list"""
        if not self.additional_roles:
            return []
        return [r.strip() for r in self.additional_roles.split(',') if r.strip()]

    def get_all_roles(self) -> list:
        """Primary role plus any additional roles, deduplicated, primary first"""
        roles = [self.role] + self.get_additional_roles()
        seen: list = []
        for r in roles:
            if r and r not in seen:
                seen.append(r)
        return seen

    def set_additional_roles(self, roles: list) -> None:
        """Replace the additional-roles list (primary role is excluded automatically)"""
        clean = [r.strip() for r in roles if r and r.strip() and r.strip() != self.role]
        self.additional_roles = ','.join(clean) if clean else None

    def has_role(self, role: str) -> bool:
        """Check if user holds a role, whether primary or additional"""
        return role in self.get_all_roles()

    def has_any_role(self, roles: list) -> bool:
        """Check if user holds any of the given roles, primary or additional"""
        return bool(set(self.get_all_roles()) & set(roles))

    def is_admin(self) -> bool:
        """Check if user is admin"""
        return self.has_role(self.ROLE_ADMIN)

    def is_manager(self) -> bool:
        """Check if user is a manager"""
        return self.has_role(self.ROLE_MANAGER)

    def is_sales(self) -> bool:
        """Check if user is sales"""
        return self.has_role(self.ROLE_SALES)

    def is_installation(self) -> bool:
        """Check if user is installation"""
        return self.has_role(self.ROLE_INSTALLATION)

    def is_security(self) -> bool:
        """Check if user is security officer"""
        return self.has_role(self.ROLE_SECURITY)

    def is_payment_recovery(self) -> bool:
        """Check if user is payment recovery officer"""
        return self.has_role(self.ROLE_PAYMENT_RECOVERY)

    def is_redo_technician(self) -> bool:
        """Check if user is redo technician / NR team member"""
        return self.has_role(self.ROLE_REDO_TECHNICIAN)

    def is_nr_team(self) -> bool:
        """Alias: Check if user is NR team member"""
        return self.is_redo_technician()

    def is_removal(self) -> bool:
        """Check if user is removal technician"""
        return self.has_role(self.ROLE_REMOVAL)

    def is_complaint_manager(self) -> bool:
        """Check if user manages the Complaints & Tickets module"""
        return self.has_role(self.ROLE_COMPLAINT_MANAGER)

    def is_recovery_officer(self) -> bool:
        """Check if user is a Live AMC recovery officer"""
        return self.has_role(self.ROLE_RECOVERY_OFFICER)

    def is_inventory(self) -> bool:
        """Check if user has Inventory module access"""
        return self.has_role(self.ROLE_INVENTORY)

    def is_device_recovery(self) -> bool:
        """Check if user works Device Recovery (Power/Damage/Missing)"""
        return self.has_role(self.ROLE_DEVICE_RECOVERY)

    def is_suggestion_manager(self) -> bool:
        """Check if user triages the Suggestions wallboard"""
        return self.has_role(self.ROLE_SUGGESTION_MANAGER)

    def is_executive(self) -> bool:
        """Check if user has executive role"""
        return self.has_role(self.ROLE_EXECUTIVE)

    def can_manage_suggestions(self) -> bool:
        """Whether this user answers suggestions rather than only raising them.

        The Administrator is the one who can actually change the software, so
        they always can; the role exists so the triage work can be shared
        without handing over an admin account.
        """
        return self.is_admin() or self.is_suggestion_manager() or self.is_executive()

    def get_role_display(self, role: Optional[str] = None) -> str:
        """Get display name for a role (defaults to this user's primary role)"""
        role_map = {
            self.ROLE_ADMIN: 'Admin',
            self.ROLE_MANAGER: 'Manager',
            self.ROLE_SALES: 'Sales',
            self.ROLE_INSTALLATION: 'Installation',
            self.ROLE_SECURITY: 'Security',
            self.ROLE_PAYMENT_RECOVERY: 'Inst. Recovery',
            self.ROLE_REDO_TECHNICIAN: 'NR Team',
            self.ROLE_REMOVAL: 'Removal',
            self.ROLE_COMPLAINT_MANAGER: 'Complaints',
            self.ROLE_RECOVERY_OFFICER: 'AMC Recovery',
            self.ROLE_INVENTORY: 'Inventory',
            self.ROLE_DEVICE_RECOVERY: 'Device Recovery',
            self.ROLE_SUGGESTION_MANAGER: 'Suggestions',
            self.ROLE_EXECUTIVE: 'Executive',
        }
        target = role if role is not None else self.role
        return role_map.get(target, target.title())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert user to dictionary"""
        return {
            'id': self.id,
            'user_code': self.user_code,
            'username': self.username,
            'email': self.email,
            'name': self.name,
            'contact': self.contact,
            'role': self.role,
            'role_display': self.get_role_display(),
            'additional_roles': self.get_additional_roles(),
            'additional_roles_display': [self.get_role_display(r) for r in self.get_additional_roles()],
            'is_active': self.is_active,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
    
    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role})>"


@db.event.listens_for(User, 'before_insert')
def _assign_user_code(mapper, connection, target: User) -> None:
    """Auto-assign the next USR-#### code on creation, for every user
    going forward regardless of which code path creates them.

    Uses a persistent counter (user_code_sequence table) rather than
    MAX(existing user_code) - deleting the highest-numbered user would
    otherwise let a later user get re-issued the same code, defeating the
    whole point of a stable, never-reused identifier.
    """
    if target.user_code:
        return
    row = connection.execute(db.text("SELECT next_value FROM user_code_sequence WHERE id = 1")).fetchone()
    if row is None:
        seeded = connection.execute(
            db.text("SELECT MAX(CAST(SUBSTR(user_code, 5) AS INTEGER)) FROM users WHERE user_code LIKE 'USR-%'")
        ).scalar() or 0
        next_num = seeded + 1
        connection.execute(
            db.text("INSERT INTO user_code_sequence (id, next_value) VALUES (1, :v)"), {'v': next_num + 1}
        )
    else:
        next_num = row[0]
        connection.execute(
            db.text("UPDATE user_code_sequence SET next_value = :v WHERE id = 1"), {'v': next_num + 1}
        )
    target.user_code = f"USR-{next_num:04d}"