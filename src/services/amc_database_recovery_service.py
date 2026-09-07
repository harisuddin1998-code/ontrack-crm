# src/services/amc_database_recovery_service.py
"""
AMC Recoveries - Database Method: building the daily follow-up list.

The page used to be a browse of SJ_MIS's AMCInfo ledger - every payment row
ever recorded, filtered and paged. That is a record, not a day's work: it
does not say who should call whom today, and nobody can be held to it.

This service applies the Live AMC rule to that ledger instead. AMC renews
annually on the vehicle's installation anniversary, so on any given date the
vehicles due are the ones whose install date's day and month match it, across
every install year on record. Those vehicles are clubbed by customer and the
customers are round-robined across the Recovery Officers, so each officer
gets whole customers to call rather than scattered vehicles belonging to
people their colleagues are also ringing.

The result is stored (AmcDatabaseAssignment), which is what lets a past date
be generated and read back, and what stops a day's list reshuffling under an
officer who is halfway through it.
"""
import calendar
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from src.extensions import db
from src.models.amc_database_assignment import AmcDatabaseAssignment
from src.models.amc_recovery_record import AmcRecoveryRecord
from src.models.user import User
from src.utils.logging import get_logger

logger = get_logger(__name__)

# A customer with no id of their own in SJ_MIS still has to be clubbed with
# themselves rather than spread across officers, so their name stands in.
_NO_CLIENT = 'UNIDENTIFIED CUSTOMER'


def _client_key(record: AmcRecoveryRecord) -> str:
    """What makes two ledger rows the same customer.

    The client id when SJ_MIS has one, otherwise the name - a customer with
    no id must still be one call, not one call per vehicle.
    """
    if record.client_id:
        return f'id:{record.client_id}'
    name = (record.client_name or '').strip().upper()
    return f'name:{name or _NO_CLIENT}'


class AmcDatabaseRecoveryService:
    """The daily anniversary worklist built from SJ_MIS's AMC ledger."""

    # ------------------------------------------------------------------
    # Who the work goes to
    # ------------------------------------------------------------------

    def get_recovery_officers(self) -> List[User]:
        """Active Recovery Officers, in a stable order.

        Ordered by id so the round robin is deterministic: the same day
        generated twice hands the same customers to the same people.
        """
        officers = User.query.filter_by(is_active=True).order_by(User.id).all()
        return [u for u in officers if u.is_recovery_officer()]

    # ------------------------------------------------------------------
    # What is due
    # ------------------------------------------------------------------

    def get_due_records(self, day: int, month: int) -> List[AmcRecoveryRecord]:
        """One ledger row per vehicle whose AMC anniversary is this day.

        The ledger holds a row per AMC period, so a vehicle installed in 2019
        and billed every year since is in it several times over with the same
        install date. Only the latest period is kept here - that is the one
        whose money is still open - so an officer is handed each vehicle once.
        """
        due = (AmcRecoveryRecord.query
               .filter(AmcRecoveryRecord.installation_date.isnot(None))
               .filter(db.extract('day', AmcRecoveryRecord.installation_date) == day)
               .filter(db.extract('month', AmcRecoveryRecord.installation_date) == month)
               .all())

        latest: Dict[str, AmcRecoveryRecord] = {}
        for record in due:
            key = (record.registration_no or '').strip().upper()
            if not key:
                continue
            held = latest.get(key)
            if held is None or self._period_sort_key(record) > self._period_sort_key(held):
                latest[key] = record
        return [latest[key] for key in sorted(latest)]

    @staticmethod
    def _period_sort_key(record: AmcRecoveryRecord) -> Tuple[int, int]:
        """Which of a vehicle's ledger rows is the current one.

        The AMC period it covers first (a 2026-2027 row is more current than
        a 2022-2023 one), then the serial id to break ties on rows that
        cover the same period.
        """
        try:
            to_year = int(str(record.to_year or '').strip()[:4])
        except (TypeError, ValueError):
            to_year = 0
        return (to_year, record.serial_id or 0)

    def count_due(self, day: int, month: int) -> int:
        """How many vehicles fall due on a given day/month."""
        return len(self.get_due_records(day, month))

    def get_month_matrix(self, year: int, month: int) -> List[Dict[str, Any]]:
        """Day-by-day counts for a whole month, for the calendar strip.

        The counts come from one pass over the month's ledger rows rather
        than a query per day - a month of 31 separate scans over the whole
        ledger is the kind of thing that makes a page feel broken.
        """
        today = date.today()
        days_in_month = calendar.monthrange(year, month)[1]

        month_records = (AmcRecoveryRecord.query
                         .filter(AmcRecoveryRecord.installation_date.isnot(None))
                         .filter(db.extract('month', AmcRecoveryRecord.installation_date) == month)
                         .all())

        per_day: Dict[int, set] = {}
        for record in month_records:
            reg = (record.registration_no or '').strip().upper()
            if not reg:
                continue
            per_day.setdefault(record.installation_date.day, set()).add(reg)

        matrix = []
        for day in range(1, days_in_month + 1):
            this_date = date(year, month, day)
            matrix.append({
                'day': day,
                'date': this_date,
                'count': len(per_day.get(day, ())),
                'is_today': this_date == today,
                'is_past': this_date < today,
                'is_future': this_date > today,
            })
        return matrix

    # ------------------------------------------------------------------
    # Generating a day
    # ------------------------------------------------------------------

    def get_or_create_assignments(self, target_date: date,
                                  actor_user_id: Optional[int] = None,
                                  regenerate: bool = False) -> List[AmcDatabaseAssignment]:
        """The day's list, generating it the first time it is asked for.

        Idempotent: once a day has been generated, later calls return what
        was generated rather than reshuffling it. Past dates generate on
        demand exactly like today does - the anniversary rule does not depend
        on when the question is asked, so a day that went by unworked can
        still be reconstructed and followed up.

        `regenerate` clears the day first. It is the deliberate "this was
        distributed before the officer list was right" action, and it throws
        away the work statuses recorded against that day, so it is kept
        behind an explicit request rather than happening on its own.
        """
        existing = (AmcDatabaseAssignment.query
                    .filter_by(due_date=target_date)
                    .order_by(AmcDatabaseAssignment.id).all())
        if existing and not regenerate:
            return existing

        if existing and regenerate:
            for row in existing:
                db.session.delete(row)
            db.session.flush()

        records = self.get_due_records(target_date.day, target_date.month)
        if not records:
            db.session.commit()
            return []

        officers = self.get_recovery_officers()
        if not officers:
            logger.warning("AMC Database Method: no active recovery_officer users - "
                           "the day's vehicles are left unassigned")

        # Club the vehicles customer-wise, then round-robin the customers.
        # Distributing vehicles instead would split one customer's six cars
        # across four officers, and that customer would take four calls.
        groups: Dict[str, List[AmcRecoveryRecord]] = {}
        for record in records:
            groups.setdefault(_client_key(record), []).append(record)

        ordered_keys = sorted(
            groups,
            key=lambda k: ((groups[k][0].client_name or '').strip().upper(), k))

        now = datetime.utcnow()
        assignments: List[AmcDatabaseAssignment] = []
        for index, key in enumerate(ordered_keys):
            officer = officers[index % len(officers)] if officers else None
            for record in groups[key]:
                assignment = AmcDatabaseAssignment(
                    record_id=record.id,
                    due_date=target_date,
                    match_day=target_date.day,
                    match_month=target_date.month,
                    client_id=record.client_id,
                    client_name=(record.client_name or '').strip() or _NO_CLIENT,
                    registration_no=(record.registration_no or '').strip().upper(),
                    installation_date=record.installation_date,
                    outstanding_amount=record.get_outstanding(),
                    assigned_officer_id=officer.id if officer else None,
                    assigned_at=now,
                    work_status=AmcDatabaseAssignment.STATUS_PENDING,
                    created_by=actor_user_id,
                )
                db.session.add(assignment)
                assignments.append(assignment)

        db.session.commit()
        logger.info(f"AMC Database Method: generated {len(assignments)} follow-up(s) for "
                    f"{target_date} across {len(ordered_keys)} customer(s) and "
                    f"{len(officers)} officer(s)")
        return assignments

    # ------------------------------------------------------------------
    # Reading a day back
    # ------------------------------------------------------------------

    def get_assignments_for_view(self, target_date: date, current_user: Any) -> List[AmcDatabaseAssignment]:
        """A day's follow-ups, scoped to whoever is looking.

        A Recovery Officer sees the customers that were given to them and
        nobody else's; administrators and managers see the whole day. The
        scoping is the query, so there is no combination of parameters that
        widens it.
        """
        query = AmcDatabaseAssignment.query.filter_by(due_date=target_date)
        if current_user.is_recovery_officer() and not (current_user.is_admin() or current_user.is_manager() or current_user.is_executive()):
            query = query.filter_by(assigned_officer_id=current_user.id)
        return query.order_by(AmcDatabaseAssignment.client_name,
                              AmcDatabaseAssignment.registration_no).all()

    def group_by_customer(self, assignments: List[AmcDatabaseAssignment]) -> List[Dict[str, Any]]:
        """The day's follow-ups as customers, each carrying their vehicles.

        This is the shape the work is actually done in: one customer, one
        call, however many vehicles came due. The contact numbers come off
        the ledger row, deduplicated, because a customer's numbers are the
        customer's - repeating them under every vehicle just makes the
        officer's screen longer.
        """
        groups: Dict[str, Dict[str, Any]] = {}
        for assignment in assignments:
            record = assignment.record
            key = (f'id:{assignment.client_id}' if assignment.client_id
                   else f'name:{(assignment.client_name or _NO_CLIENT).upper()}')
            group = groups.get(key)
            if group is None:
                group = {
                    'key': key,
                    'client_id': assignment.client_id,
                    'client_name': assignment.client_name or _NO_CLIENT,
                    'officer': assignment.assigned_officer,
                    'officer_name': assignment.officer_name(),
                    'is_defaulter': bool(record.is_defaulter) if record else False,
                    'contacts': [],
                    'vehicles': [],
                    'outstanding': 0.0,
                    'pending': 0,
                }
                groups[key] = group

            if record:
                for number in (record.cell1, record.cell2, record.res_phone,
                               record.office_phone):
                    value = (number or '').strip()
                    if value and value not in group['contacts']:
                        group['contacts'].append(value)
                if record.is_defaulter:
                    group['is_defaulter'] = True

            group['vehicles'].append(assignment)
            group['outstanding'] += assignment.outstanding_amount or 0.0
            if assignment.work_status == AmcDatabaseAssignment.STATUS_PENDING:
                group['pending'] += 1

        return sorted(groups.values(), key=lambda g: g['client_name'].upper())

    @staticmethod
    def day_summary(assignments: List[AmcDatabaseAssignment]) -> Dict[str, Any]:
        """The four figures the top of the page shows."""
        return {
            'vehicles': len(assignments),
            'customers': len({(a.client_id or a.client_name) for a in assignments}),
            'outstanding': sum(a.outstanding_amount or 0.0 for a in assignments),
            'pending': sum(1 for a in assignments
                           if a.work_status == AmcDatabaseAssignment.STATUS_PENDING),
        }

    # ------------------------------------------------------------------
    # Recording what happened
    # ------------------------------------------------------------------

    def update_assignment(self, assignment_id: int, work_status: Optional[str] = None,
                          remarks: Optional[str] = None) -> Optional[AmcDatabaseAssignment]:
        """Record the outcome of a follow-up.

        Only the follow-up's own fields. The money stays in SJ_MIS's ledger,
        which this module reads and never writes - a recovery recorded here
        that SJ_MIS did not know about would put the two out of step, and the
        ledger is the one that gets audited.
        """
        assignment = AmcDatabaseAssignment.query.get(assignment_id)
        if not assignment:
            return None

        if work_status and work_status in AmcDatabaseAssignment.WORK_STATUSES:
            assignment.work_status = work_status
            if work_status != AmcDatabaseAssignment.STATUS_PENDING:
                assignment.last_contacted_at = datetime.utcnow()
        if remarks is not None:
            assignment.remarks = remarks.strip() or None

        db.session.commit()
        return assignment

    def update_customer(self, due_date: date, client_key: str, work_status: Optional[str],
                        remarks: Optional[str], current_user: Any) -> int:
        """Record one outcome against every vehicle a customer had due.

        The call was made once, so the officer should not have to type the
        same result six times. Scoped through the same rule as the view: an
        officer can only close out their own customers.
        """
        query = AmcDatabaseAssignment.query.filter_by(due_date=due_date)
        if current_user.is_recovery_officer() and not (current_user.is_admin() or current_user.is_manager()):
            query = query.filter_by(assigned_officer_id=current_user.id)

        if client_key.startswith('id:'):
            try:
                query = query.filter_by(client_id=int(client_key[3:]))
            except ValueError:
                return 0
        else:
            query = query.filter(
                db.func.upper(AmcDatabaseAssignment.client_name) == client_key[5:])

        rows = query.all()
        now = datetime.utcnow()
        for row in rows:
            if work_status and work_status in AmcDatabaseAssignment.WORK_STATUSES:
                row.work_status = work_status
                if work_status != AmcDatabaseAssignment.STATUS_PENDING:
                    row.last_contacted_at = now
            if remarks is not None:
                row.remarks = remarks.strip() or None
        db.session.commit()
        return len(rows)

    # ------------------------------------------------------------------
    # The daily job
    # ------------------------------------------------------------------

    def run_daily(self, target_date: Optional[date] = None,
                  sync_first: bool = True) -> Dict[str, Any]:
        """Refresh the ledger from SJ_MIS, then generate the day's list.

        Both halves in one place because they are one operation: a list
        generated from a stale ledger would miss a vehicle installed last
        week, and a ledger refreshed with nobody looking at it changes
        nothing on its own.

        A failed sync does not stop the generation - yesterday's ledger still
        knows which vehicles have an anniversary today, and an officer with a
        slightly stale list is better served than one with no list.
        """
        target_date = target_date or date.today()
        synced = None

        if sync_first:
            from src.services.db_sync_service import DBSyncService
            result = DBSyncService().sync_amc_recoveries()
            synced = result.get('records', 0)
            if result.get('error'):
                logger.warning("AMC Database Method: ledger sync failed - generating "
                               "the day's list from the ledger already on file")
                synced = None

        assignments = self.get_or_create_assignments(target_date)
        return {
            'date': target_date,
            'synced_records': synced,
            'assignments': len(assignments),
        }
