# src/services/live_amc_service.py
"""
Live AMC Service - anniversary-based daily AMC recovery assignment.

Every vehicle in the Annual Recovery module has an installation date. AMC
renews annually, so a vehicle's follow-up "comes due" every year on the
calendar day+month of its original install - regardless of which year it
was installed in. This service finds, for any given day, every active
(non-recovered, non-lost) vehicle whose install-date anniversary falls on
that day, and round-robins that day's list across the pool of Recovery
Officer users, once, stably (re-visiting the page never reshuffles it).
"""
import calendar
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from src.extensions import db
from src.models.annual_recovery import AnnualRecoveryVehicle
from src.models.live_amc import LiveAmcAssignment
from src.models.user import User
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Statuses that no longer need daily AMC follow-up.
_CLOSED_STATUSES = ('RECOVERED', 'LOST')


def parse_install_date(raw: Optional[str]) -> Optional[date]:
    """Parse AnnualRecoveryVehicle.installation_date (a free-text legacy
    field) into a real date. The migrated dataset is consistently ISO
    (YYYY-MM-DD), so that's tried first; a couple of common fallback
    formats are tried after in case future manual/Excel entry drifts.
    Returns None (never raises) for anything unparseable, since a small
    fraction of bad legacy data shouldn't crash the whole day's matching."""
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y'):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


class LiveAmcService:
    """Service for Live AMC daily anniversary matching and assignment."""

    def get_recovery_officers(self) -> List[User]:
        """Active users holding the recovery_officer role, in a stable
        order so round-robin distribution is deterministic."""
        officers = User.query.filter_by(is_active=True).order_by(User.id).all()
        return [u for u in officers if u.is_recovery_officer()]

    def get_matching_vehicles(self, day: int, month: int) -> List[AnnualRecoveryVehicle]:
        """Every active (not yet RECOVERED/LOST) vehicle whose installation
        date's day+month anniversary matches the given day/month, across
        every year on record."""
        vehicles = AnnualRecoveryVehicle.query.filter(
            AnnualRecoveryVehicle.status.notin_(_CLOSED_STATUSES)
        ).all()
        matches = []
        for v in vehicles:
            parsed = parse_install_date(v.installation_date)
            if parsed and parsed.day == day and parsed.month == month:
                matches.append(v)
        return matches

    def get_month_matrix(self, year: int, month: int) -> List[Dict[str, Any]]:
        """Day-by-day breakdown for a whole month: for each calendar day,
        how many active vehicles have their AMC anniversary that day, and
        whether that day is today/past/future - powers the calendar view
        the year/month dropdowns feed into."""
        today = date.today()
        days_in_month = calendar.monthrange(year, month)[1]
        matrix = []
        for day in range(1, days_in_month + 1):
            this_date = date(year, month, day)
            count = len(self.get_matching_vehicles(day, month))
            matrix.append({
                'day': day,
                'date': this_date,
                'count': count,
                'is_today': this_date == today,
                'is_past': this_date < today,
                'is_future': this_date > today,
            })
        return matrix

    def get_or_create_assignments(self, target_date: date, actor_user_id: Optional[int] = None) -> List[LiveAmcAssignment]:
        """Idempotently return target_date's assignments - generating them
        via round robin on first call for that date, and simply returning
        the already-made assignments on every later call, so a day's work
        list never reshuffles once officers have started on it. Only ever
        called for target_date <= today (see route layer) - the round
        robin for a day should reflect real staffing at the time that day
        actually happens, not be fabricated after the fact for past days
        or pre-committed for future ones."""
        existing = LiveAmcAssignment.query.filter_by(due_date=target_date).all()
        if existing:
            return existing

        vehicles = self.get_matching_vehicles(target_date.day, target_date.month)
        if not vehicles:
            return []

        officers = self.get_recovery_officers()
        if not officers:
            logger.warning("Live AMC: no active recovery_officer users to assign - vehicles left unassigned")

        assignments = []
        for i, vehicle in enumerate(vehicles):
            officer = officers[i % len(officers)] if officers else None
            assignment = LiveAmcAssignment(
                vehicle_id=vehicle.id,
                due_date=target_date,
                match_day=target_date.day,
                match_month=target_date.month,
                assigned_officer_id=officer.id if officer else None,
                assigned_at=datetime.utcnow(),
                work_status=LiveAmcAssignment.STATUS_PENDING,
                created_by=actor_user_id,
            )
            db.session.add(assignment)
            assignments.append(assignment)
        db.session.commit()

        logger.info(f"Live AMC: generated {len(assignments)} assignments for {target_date} across {len(officers)} officer(s)")
        return assignments

    def get_assignments_for_view(self, target_date: date, current_user: Any) -> List[LiveAmcAssignment]:
        """Assignments for a due date, scoped to the viewer: recovery
        officers only ever see their own slice, everyone else (admin/
        manager) sees the full day."""
        query = LiveAmcAssignment.query.filter_by(due_date=target_date)
        if current_user.is_recovery_officer() and not (current_user.is_admin() or current_user.is_executive()):
            query = query.filter_by(assigned_officer_id=current_user.id)
        return query.all()

    def update_assignment(self, assignment_id: int, work_status: Optional[str] = None,
                          remarks: Optional[str] = None) -> Optional[LiveAmcAssignment]:
        """Update an assignment's daily work-tracking fields (not the
        underlying AMC financials - those go through the shared Annual
        Recovery recover-payment endpoint so there's one source of truth
        for money recovered)."""
        assignment = LiveAmcAssignment.query.get(assignment_id)
        if not assignment:
            return None
        if work_status:
            assignment.work_status = work_status
        if remarks is not None:
            assignment.remarks = remarks
        db.session.commit()
        return assignment
