# src/services/suggestion_service.py
"""
Suggestions - raising them, answering them, and keeping both sides informed.

Every rule about who may see or say what lives here rather than in the
routes, so the wallboard, a user's own dashboard and the detail page cannot
end up disagreeing about it. The routes decide *which* view to render; this
decides what is in it.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.extensions import db
from src.models.notification import UserNotification
from src.models.suggestion import Suggestion, SuggestionMessage
from src.services.notification_service import NotificationService
from src.utils.logging import get_logger

logger = get_logger(__name__)


class SuggestionService:
    """Business logic for the Suggestions module."""

    def __init__(self):
        self.notification_service = NotificationService()

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def generate_reference(self) -> str:
        """Next SUG-YYYY-#### reference.

        Numbered per year, from the most recent one issued rather than from a
        row count - a count would collide with an existing reference as soon
        as the numbering restarts in January.
        """
        prefix = f'SUG-{datetime.now().year}-'
        latest = (Suggestion.query
                  .filter(Suggestion.reference.like(f'{prefix}%'))
                  .order_by(Suggestion.id.desc())
                  .first())

        seq = 1
        if latest and latest.reference:
            try:
                seq = int(latest.reference.split('-')[-1]) + 1
            except ValueError:
                seq = 1
        return f'{prefix}{seq:04d}'

    def get(self, suggestion_id: int) -> Optional[Suggestion]:
        return Suggestion.query.get(suggestion_id)

    def for_user(self, user_id: int, status: str = '') -> List[Suggestion]:
        """One person's own suggestions, newest first.

        The scoping is the query, not something the template applies, so
        there is no arrangement of parameters that widens it.
        """
        query = Suggestion.query.filter(Suggestion.raised_by == user_id)
        if status:
            query = query.filter(Suggestion.status == status)
        return query.order_by(Suggestion.created_at.desc()).all()

    def wallboard(self, status: str = '', area: str = '',
                  search: str = '') -> List[Suggestion]:
        """Every suggestion, for whoever triages them.

        Ordered oldest-first within the open ones so the longest-waiting
        suggestion is at the top - a wallboard sorted newest-first buries
        exactly the item that most needs attention.
        """
        query = Suggestion.query
        if status:
            query = query.filter(Suggestion.status == status)
        if area:
            query = query.filter(Suggestion.area == area)
        if search:
            term = f'%{search.strip()}%'
            query = query.filter(db.or_(Suggestion.reference.ilike(term),
                                        Suggestion.title.ilike(term),
                                        Suggestion.description.ilike(term)))

        suggestions = query.all()
        suggestions.sort(key=lambda s: (s.is_closed(), s.created_at or datetime.min))
        return suggestions

    def stats(self, user_id: Optional[int] = None) -> Dict[str, int]:
        """Counts per status, for the cards above either board.

        Passing `user_id` counts one person's own suggestions, so their
        dashboard's cards describe their list rather than everybody's.
        """
        query = Suggestion.query
        if user_id is not None:
            query = query.filter(Suggestion.raised_by == user_id)
        suggestions = query.all()

        return {
            'total': len(suggestions),
            'new': sum(1 for s in suggestions if s.status == Suggestion.STATUS_NEW),
            'in_progress': sum(1 for s in suggestions if s.status == Suggestion.STATUS_IN_PROGRESS),
            'completed': sum(1 for s in suggestions if s.status == Suggestion.STATUS_COMPLETED),
            'rejected': sum(1 for s in suggestions if s.status == Suggestion.STATUS_REJECTED),
        }

    @staticmethod
    def can_view(suggestion: Suggestion, user) -> bool:
        """Whether this user may open this suggestion.

        Whoever raised it, and whoever answers them. Nobody else - a
        suggestion often describes what somebody found confusing, and that is
        theirs to share, not the whole company's to browse.
        """
        return suggestion.raised_by == user.id or user.can_manage_suggestions()

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def create(self, user, title: str, area: str, description: str) -> Suggestion:
        """Raise a suggestion and tell the people who answer them."""
        suggestion = Suggestion(
            reference=self.generate_reference(),
            raised_by=user.id,
            title=title.strip(),
            area=area if area in Suggestion.AREAS else 'Something else',
            description=description.strip(),
            status=Suggestion.STATUS_NEW,
            created_by=user.id,
        )
        db.session.add(suggestion)
        db.session.commit()

        logger.info(f"Suggestion {suggestion.reference} raised by {user.username}")
        self._notify_managers(suggestion)
        return suggestion

    def add_message(self, suggestion: Suggestion, user, body: str,
                    from_admin: bool, status_change: Optional[str] = None
                    ) -> Optional[SuggestionMessage]:
        """Add one reply to the thread, and tell the other side.

        `from_admin` is passed by the caller rather than read off the user's
        role here, because the caller already knows which side of the
        conversation it is rendering - and a manager who raised their own
        suggestion is a user on it, not staff.
        """
        body = (body or '').strip()
        if not body:
            return None

        message = SuggestionMessage(
            suggestion_id=suggestion.id,
            author_id=user.id,
            body=body,
            from_admin=from_admin,
            status_change=status_change,
            created_by=user.id,
        )
        db.session.add(message)
        db.session.commit()

        if from_admin:
            self._notify_raiser(suggestion, body)
        else:
            self._notify_managers(suggestion, reply=True)
        return message

    def set_status(self, suggestion: Suggestion, user, status: str,
                   remarks: str = '') -> Suggestion:
        """Move a suggestion, recording who moved it and why.

        The change is written into the thread as a message, so the person who
        raised it reads what happened in the same place they read everything
        else about it, in order. A status that has not actually changed is
        still allowed to carry remarks - that is just a reply.
        """
        if status not in Suggestion.STATUSES:
            raise ValueError(f'{status} is not a suggestion status')

        changed = suggestion.status != status
        suggestion.status = status
        suggestion.handled_by = user.id
        suggestion.closed_at = (datetime.now()
                                if status in Suggestion.CLOSED_STATUSES else None)
        db.session.commit()

        note = remarks.strip() or (
            f'Marked {Suggestion.STATUS_LABELS[status]}.' if changed else '')
        if note:
            self.add_message(suggestion, user, note, from_admin=True,
                             status_change=status if changed else None)
        elif changed:
            # Nothing was typed and nothing was generated - still tell the
            # raiser, since the state of their suggestion has moved.
            self._notify_raiser(suggestion, f'Now {suggestion.status_label()}.')

        logger.info(f"Suggestion {suggestion.reference} set to {status} by {user.username}")
        return suggestion

    # ------------------------------------------------------------------
    # Telling people
    # ------------------------------------------------------------------

    @staticmethod
    def _managers() -> List[Any]:
        """Active users who answer suggestions."""
        from src.models.user import User
        return [u for u in User.query.filter_by(is_active=True).all()
                if u.can_manage_suggestions()]

    def _notify_managers(self, suggestion: Suggestion, reply: bool = False) -> None:
        """Tell the people who triage suggestions that one needs them.

        Never raises: a notification failing must not undo the suggestion it
        is about.
        """
        try:
            from flask import url_for
            try:
                target = url_for('suggestions.detail', suggestion_id=suggestion.id)
            except Exception:
                target = f'/suggestions/{suggestion.id}'

            what = 'replied to a suggestion' if reply else 'sent a suggestion'
            self.notification_service.notify_users(
                self._managers(),
                title_for=lambda u: f'{suggestion.raiser_name()} {what}',
                body_for=lambda u: f'{suggestion.reference} - {suggestion.title}',
                url=target,
                category=UserNotification.CATEGORY_SUGGESTION)
        except Exception as e:
            logger.error(f"Failed to notify managers of {suggestion.reference}: {e}")

    def _notify_raiser(self, suggestion: Suggestion, body: str) -> None:
        """Tell whoever raised a suggestion that it has moved."""
        try:
            from flask import url_for
            try:
                target = url_for('suggestions.detail', suggestion_id=suggestion.id)
            except Exception:
                target = f'/suggestions/{suggestion.id}'

            self.notification_service.notify_user(
                suggestion.raiser,
                title=f'Your suggestion is {suggestion.status_label()}',
                body=f'{suggestion.reference} - {body[:140]}',
                url=target,
                category=UserNotification.CATEGORY_SUGGESTION)
        except Exception as e:
            logger.error(f"Failed to notify the raiser of {suggestion.reference}: {e}")
