# src/repositories/complaint_repository.py
"""
Complaint Repository - Database operations for Complaints
"""
from datetime import date, datetime, time
from typing import Optional, List, Dict, Any, Tuple

from sqlalchemy import func

from src.models.complaint import Complaint
from src.repositories.base_repository import BaseRepository
from src.extensions import db

# Characters people put in a phone number that carry no meaning. A ticket
# saved as "0300-1234567" has to be findable by typing "03001234567", and
# vice versa, so both sides of the comparison are stripped of these.
_PHONE_NOISE = (' ', '-', '+', '(', ')')


def _stripped(column):
    """SQL expression for a phone column with its separators removed."""
    expr = column
    for ch in _PHONE_NOISE:
        expr = func.replace(expr, ch, '')
    return expr


class ComplaintRepository(BaseRepository[Complaint]):
    """Repository for Complaint operations"""

    def __init__(self):
        super().__init__(Complaint)

    def get_by_ticket_no(self, ticket_no: str) -> Optional[Complaint]:
        """Get complaint by ticket number"""
        return self.get_by(ticket_no=ticket_no)

    def get_by_status(self, status: str) -> List[Complaint]:
        """Get complaints by status"""
        return self.get_all(status=status)

    def get_by_technician(self, technician_id: int) -> List[Complaint]:
        """Every complaint assigned to one technician."""
        return self.get_all(technician_id=technician_id)

    def get_by_creator(self, user_id: int) -> List[Complaint]:
        """Complaints raised by one user, newest first.

        Ordered here rather than by the caller: this backs a wallboard where
        the ticket someone just logged has to be the one at the top.
        """
        return self.session.query(Complaint).filter(
            Complaint.created_by == user_id
        ).order_by(Complaint.created_at.desc()).all()

    def search_tickets(self, *, ticket_no: Optional[str] = None,
                       reg_no: Optional[str] = None,
                       contact: Optional[str] = None,
                       date_from: Optional[date] = None,
                       date_to: Optional[date] = None,
                       filters: Optional[Dict[str, Any]] = None,
                       page: int = 1, per_page: int = 20) -> Tuple[List[Complaint], int]:
        """Find tickets by date, ticket number, registration or contact.

        Every field given narrows the result - they are AND-ed, not OR-ed, so
        a date range plus a registration number means "that vehicle, in that
        window" rather than "either of those". A field left blank is not a
        filter at all, which is what makes the search box usable one field at
        a time.

        Counting and paging happen in the database rather than over a list
        pulled into Python, so a board with years of tickets on it pages at
        the same speed as one with a dozen.
        """
        query = self.session.query(Complaint)

        for field, value in (filters or {}).items():
            query = query.filter(getattr(Complaint, field) == value)

        if ticket_no:
            query = query.filter(Complaint.ticket_no.ilike(f'%{ticket_no.strip()}%'))

        if reg_no:
            query = query.filter(Complaint.reg_no.ilike(f'%{reg_no.strip()}%'))

        if contact:
            raw = contact.strip()
            digits = raw
            for ch in _PHONE_NOISE:
                digits = digits.replace(ch, '')
            conditions = [Complaint.customer_contact.ilike(f'%{raw}%')]
            if digits:
                conditions.append(_stripped(Complaint.customer_contact).ilike(f'%{digits}%'))
            query = query.filter(db.or_(*conditions))

        # created_at is a timestamp; a date filter has to cover the whole of
        # the day the user picked, not the midnight instant that starts it.
        if date_from:
            query = query.filter(Complaint.created_at >= datetime.combine(date_from, time.min))
        if date_to:
            query = query.filter(Complaint.created_at <= datetime.combine(date_to, time.max))

        total = query.count()
        items = (query.order_by(Complaint.created_at.desc())
                 .offset((page - 1) * per_page).limit(per_page).all())
        return items, total

    def generate_ticket_no(self) -> str:
        """Generate unique ticket number (e.g. CMP-2026-0001)"""
        from datetime import datetime
        year = datetime.now().year
        prefix = f"CMP-{year}-"
        
        latest = self.session.query(Complaint).filter(
            Complaint.ticket_no.like(f"{prefix}%")
        ).order_by(Complaint.id.desc()).first()

        if latest and latest.ticket_no:
            try:
                seq_num = int(latest.ticket_no.split('-')[-1]) + 1
            except ValueError:
                seq_num = 1
        else:
            seq_num = 1

        return f"{prefix}{seq_num:04d}"

    def get_dashboard_stats(self, created_by: Optional[int] = None) -> Dict[str, Any]:
        """Complaint statistics, optionally narrowed to one person's tickets.

        `created_by=None` means every complaint - that is what the
        Administrator and the Complaint Manager see. Passing a user id
        returns the same five figures counted over only that user's own
        tickets, which is what their personal wallboard shows. One method
        rather than two, so the two views cannot drift apart.
        """
        scope = {'created_by': created_by} if created_by is not None else {}
        return {
            'total': self.count(**scope),
            'open': self.count(status='OPEN', **scope),
            'in_progress': self.count(status='IN_PROGRESS', **scope),
            'resolved': self.count(status='RESOLVED', **scope),
            'critical': self.count(severity='CRITICAL', **scope),
        }
