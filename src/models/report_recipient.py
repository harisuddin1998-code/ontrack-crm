# src/models/report_recipient.py
"""
Who receives the month-end management reports.

This list used to be a constant in the code, which meant changing it was a
deployment. It lives here so an administrator can manage it from Settings,
with the original constant kept as the seed and as the fallback if this
table is ever unavailable - a reports run must never quietly go to nobody.
"""
from typing import Any, Dict, List

from src.extensions import db
from src.models.base import BaseModel


class ReportRecipient(BaseModel):
    """One address on the restricted management distribution."""
    __tablename__ = 'report_recipients'

    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    name = db.Column(db.String(120))
    # Deactivating rather than deleting keeps the record of who used to be on
    # the list - useful when someone asks why a report stopped arriving.
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    @staticmethod
    def normalize(email: str) -> str:
        return (email or '').strip().lower()

    @classmethod
    def active_emails(cls) -> List[str]:
        rows = cls.query.filter_by(is_active=True).order_by(cls.email).all()
        return [row.email for row in rows]

    @classmethod
    def ensure_seeded(cls, defaults: List[str]) -> int:
        """Put the built-in list into the table the first time it is looked at.

        Only when the table is completely empty: once an administrator has
        edited the list, re-adding the defaults would undo their removals
        every time the page loaded.
        """
        if cls.query.first() is not None:
            return 0

        for address in defaults:
            db.session.add(cls(email=cls.normalize(address), is_active=True))
        db.session.commit()
        return len(defaults)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'is_active': self.is_active,
            'added': self.created_at.strftime('%d %b %Y') if self.created_at else '',
        }

    def __repr__(self) -> str:
        return f'<ReportRecipient {self.email}>'
