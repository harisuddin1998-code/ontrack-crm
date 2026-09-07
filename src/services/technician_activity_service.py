# src/services/technician_activity_service.py
"""
Technician activity across every kind of job, in every status.

Installations, REDOs, Removals and Removal Transfers each live in their own
table and each records its technician differently - a PO holds a name, a REDO
holds both a name and a user id, a removal holds a roster technician id. This
service is the one place that reconciles them, so the wallboard, the MIS page
and the monthly management email all report the same numbers for the same
person.

Everything is keyed on the technician's name, upper-cased and stripped, since
that is the only identifier the four tables have in common.
"""
from typing import Any, Dict, List, Optional

from src.utils.logging import get_logger

logger = get_logger(__name__)

# The statuses reported for every activity type. Anything a table stores that
# is not one of these is still counted in `total_assigned` and shown under
# `other`, so a row's parts always add up to its total.
STATUSES = ('COMPLETED', 'PENDING', 'IN_PROGRESS', 'CANCELLED')

# The four job types a technician can be assigned.
ACTIVITY_TYPES = ('installations', 'redos', 'removals', 'transfers')

UNASSIGNED_LABEL = 'Unassigned / Other'


def _key(name: Optional[str]) -> str:
    return (name or '').strip().upper()


def _blank_counts() -> Dict[str, int]:
    counts = {status: 0 for status in STATUSES}
    counts['OTHER'] = 0
    counts['TOTAL'] = 0
    return counts


def _tally(counts: Dict[str, int], status: Optional[str]) -> None:
    normalized = (status or '').strip().upper()
    if normalized in counts and normalized != 'TOTAL':
        counts[normalized] += 1
    else:
        counts['OTHER'] += 1
    counts['TOTAL'] += 1


class TechnicianActivityService:
    """Per-technician job counts across all activity types and statuses."""

    def wallboard_rows(self, date_range: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """One row per technician, flattened for a table or a spreadsheet.

        Rows carry a count for every activity-type/status pair plus the
        totals, so a caller can show as much or as little as it has room for
        without recomputing anything.
        """
        from src.models.purchase_order import PurchaseOrder
        from src.models.redo import RedoActivity
        from src.models.removal import RemovalRetainedActivity, RemovalTransferActivity
        from src.models.technician import Technician
        from src.utils.date_ranges import apply_range

        date_range = date_range or {}

        def scoped(model):
            return apply_range(model.query, model.created_at, date_range).all()

        buckets: Dict[str, Dict[str, Any]] = {}

        def bucket(name: Optional[str]) -> Dict[str, Any]:
            key = _key(name) or _key(UNASSIGNED_LABEL)
            if key not in buckets:
                buckets[key] = {
                    'name': (name or '').strip() or UNASSIGNED_LABEL,
                    'counts': {activity: _blank_counts() for activity in ACTIVITY_TYPES},
                }
            return buckets[key]

        # Seed the roster so an active technician with nothing this period
        # still appears, at zero - an absent row reads as "no data", a zero
        # row reads as "no work", and those are different facts.
        for tech in Technician.query.filter_by(is_active=True).order_by(Technician.name).all():
            bucket(tech.name)

        for po in scoped(PurchaseOrder):
            _tally(bucket(po.technician_assigned)['counts']['installations'], po.status)

        for redo in scoped(RedoActivity):
            name = redo.technician
            if not name and redo.assigned_to_user:
                name = redo.assigned_to_user.name or redo.assigned_to_user.username
            _tally(bucket(name)['counts']['redos'], redo.status)

        # Removals and transfers name their technician off the same roster
        # every other activity type does. They used to name the removal
        # officer who owned the case instead, which put a login into a report
        # about technicians and split one technician's work across two rows
        # whenever the officer changed.
        for removal in scoped(RemovalRetainedActivity):
            _tally(bucket(removal.technician.name if removal.technician else None)['counts']['removals'],
                   removal.status)

        for transfer in scoped(RemovalTransferActivity):
            _tally(bucket(transfer.technician.name if transfer.technician else None)['counts']['transfers'],
                   transfer.status)

        rows = [self._flatten(entry) for entry in buckets.values()]

        # Technicians with nothing at all in the period stay in the list;
        # the catch-all row only appears when it actually holds something.
        rows = [r for r in rows
                if r['total_assigned'] or r['technician'] != UNASSIGNED_LABEL]
        rows.sort(key=lambda r: (-r['total_assigned'], r['technician']))
        return rows

    @staticmethod
    def _flatten(entry: Dict[str, Any]) -> Dict[str, Any]:
        counts = entry['counts']
        row: Dict[str, Any] = {'technician': entry['name']}

        for activity in ACTIVITY_TYPES:
            for status in STATUSES:
                row[f'{activity}_{status.lower()}'] = counts[activity][status]
            row[f'{activity}_total'] = counts[activity]['TOTAL']

        for status in STATUSES:
            row[status.lower()] = sum(counts[a][status] for a in ACTIVITY_TYPES)
        row['other'] = sum(counts[a]['OTHER'] for a in ACTIVITY_TYPES)
        row['total_assigned'] = sum(counts[a]['TOTAL'] for a in ACTIVITY_TYPES)
        row['completion_rate'] = (
            round(row['completed'] / row['total_assigned'] * 100, 1)
            if row['total_assigned'] else 0.0
        )
        return row

    def totals(self, rows: List[Dict[str, Any]]) -> Dict[str, int]:
        """Column totals for the wallboard's summary cards."""
        keys = ['total_assigned', 'other'] + [s.lower() for s in STATUSES] \
            + [f'{a}_total' for a in ACTIVITY_TYPES]
        return {key: sum(row.get(key, 0) for row in rows) for key in keys}
