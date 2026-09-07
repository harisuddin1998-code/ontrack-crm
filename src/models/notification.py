# src/models/notification.py
"""
Per-user notification.

The CRM already emitted socket.io events, but nothing in the browser ever
subscribed to them, so those notifications went nowhere. A notification is
stored per user instead: it survives a page reload, a logout, and a browser
that was closed when the event happened, and it is what the desktop
notification in base.html is raised from.

Addressed to one user, not to a role, because the messages are personal
("You have a new PO, Ayesha") and because two installers must not both be
told the same job is theirs.
"""
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import BaseModel


class UserNotification(BaseModel):
    """A single notification addressed to a single user."""
    __tablename__ = 'user_notifications'

    # Categories - used for the icon and for filtering, keep in step with the
    # senders in NotificationService.
    CATEGORY_PO = 'PO'
    CATEGORY_SECURITY_BRIEFING = 'SECURITY_BRIEFING'
    CATEGORY_ASSIGNMENT = 'ASSIGNMENT'
    CATEGORY_PAYMENT = 'PAYMENT'
    CATEGORY_COMPLAINT = 'COMPLAINT'
    CATEGORY_SUGGESTION = 'SUGGESTION'
    CATEGORY_SYSTEM = 'SYSTEM'

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Where clicking the notification takes the user. Stored as a path so it
    # survives a change of host.
    url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    category: Mapped[str] = mapped_column(String(40), default=CATEGORY_SYSTEM, nullable=False)

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Set once the browser has actually raised the desktop notification, so a
    # reload doesn't pop the same toast again.
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'title': self.title,
            'body': self.body,
            'url': self.url,
            'category': self.category,
            'is_read': self.is_read,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<UserNotification {self.id} user={self.user_id} {self.category}>"
