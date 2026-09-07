# src/models/suggestion.py
"""
Suggestions - the two-way channel between the people using the CRM and the
Administrator who can change it.

Every user can raise one: a fault they have hit, a field that is missing, a
screen that gets in their way. The Administrator works through them on a
wallboard - who sent it, from where, and when - and moves each one through
IN_PROGRESS to COMPLETED or REJECTED. The person who raised it sees that
happen on their own dashboard.

The conversation is a thread of messages rather than a pair of "remarks"
columns, because it is a conversation: the Administrator asks which screen,
the user answers, and both replies have to survive. A single overwritable
notes field loses whichever half was written second.
"""
from datetime import datetime
from typing import Any, Dict, Optional

from src.extensions import db
from src.models.base import BaseModel


class Suggestion(BaseModel):
    """One suggestion raised by one user."""
    __tablename__ = 'suggestions'

    # Lifecycle. NEW is where every suggestion starts - it has been sent and
    # nobody has looked at it yet, which is different from being worked on.
    STATUS_NEW = 'NEW'
    STATUS_IN_PROGRESS = 'IN_PROGRESS'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_REJECTED = 'REJECTED'

    STATUSES = (STATUS_NEW, STATUS_IN_PROGRESS, STATUS_COMPLETED, STATUS_REJECTED)

    # Statuses that mean the Administrator has finished with it, either way.
    CLOSED_STATUSES = (STATUS_COMPLETED, STATUS_REJECTED)

    STATUS_LABELS = {
        STATUS_NEW: 'New',
        STATUS_IN_PROGRESS: 'In Progress',
        STATUS_COMPLETED: 'Completed',
        STATUS_REJECTED: 'Suggestion Rejected',
    }

    # Where in the CRM the suggestion is about. Free-form would make the
    # wallboard unsortable, which is the one thing it is for.
    AREAS = (
        'Dashboards', 'Purchase Orders', 'Sales', 'Installation', 'Security',
        'REDO', 'Removal', 'Recovery & AMC', 'Payments & Invoices',
        'Inventory', 'Complaints', 'Reports & MIS', 'Notifications',
        'Something else',
    )

    reference = db.Column(db.String(30), unique=True, nullable=False, index=True)

    # Who raised it. Not nullable: an anonymous suggestion cannot be replied
    # to, and the reply is half the point of the module.
    raised_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    title = db.Column(db.String(200), nullable=False)
    area = db.Column(db.String(50), nullable=False, default='Something else')
    description = db.Column(db.Text, nullable=False)

    status = db.Column(db.String(20), nullable=False, default=STATUS_NEW, index=True)

    # Who last moved it and when it was closed out.
    handled_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)

    raiser = db.relationship('User', foreign_keys=[raised_by], backref='suggestions_raised')
    handler = db.relationship('User', foreign_keys=[handled_by], backref='suggestions_handled')

    messages = db.relationship('SuggestionMessage', backref='suggestion',
                               cascade='all, delete-orphan',
                               order_by='SuggestionMessage.created_at',
                               lazy='select')

    def status_label(self) -> str:
        return self.STATUS_LABELS.get(self.status, self.status)

    def is_closed(self) -> bool:
        return self.status in self.CLOSED_STATUSES

    def raiser_name(self) -> str:
        """Who sent it, as the wallboard should print it."""
        if not self.raiser:
            return 'Unknown'
        return self.raiser.name or self.raiser.username

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'reference': self.reference,
            'title': self.title,
            'area': self.area,
            'description': self.description,
            'status': self.status,
            'status_label': self.status_label(),
            'raised_by': self.raised_by,
            'raiser_name': self.raiser_name(),
            'raiser_role': self.raiser.get_role_display() if self.raiser else '',
            'handled_by': self.handled_by,
            'handler_name': (self.handler.name or self.handler.username) if self.handler else '',
            'message_count': len(self.messages),
            # Date *and* time: the wallboard is asked how long something has
            # been waiting, which a bare date cannot answer.
            'created_at': self.created_at.strftime('%d %b %Y, %H:%M') if self.created_at else '',
            'closed_at': self.closed_at.strftime('%d %b %Y, %H:%M') if self.closed_at else '',
        }

    def __repr__(self) -> str:
        return f"<Suggestion {self.reference} {self.status}>"


class SuggestionMessage(BaseModel):
    """One message in a suggestion's thread, from either side."""
    __tablename__ = 'suggestion_messages'

    suggestion_id = db.Column(db.Integer, db.ForeignKey('suggestions.id', ondelete='CASCADE'),
                              nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    body = db.Column(db.Text, nullable=False)

    # Whether this message came from the Administrator's side. Stored rather
    # than derived from the author's role, so a reply written by an admin
    # still reads as an admin reply after that person's role changes.
    from_admin = db.Column(db.Boolean, nullable=False, default=False)

    # Set when a status change generated the message, so the thread reads as
    # a history rather than needing a separate audit list beside it.
    status_change = db.Column(db.String(20), nullable=True)

    author = db.relationship('User', foreign_keys=[author_id])

    def author_name(self) -> str:
        if not self.author:
            return 'System'
        return self.author.name or self.author.username

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'body': self.body,
            'from_admin': self.from_admin,
            'status_change': self.status_change,
            'author_name': self.author_name(),
            'created_at': self.created_at.strftime('%d %b %Y, %H:%M') if self.created_at else '',
        }

    def __repr__(self) -> str:
        return f"<SuggestionMessage {self.id} suggestion={self.suggestion_id}>"
