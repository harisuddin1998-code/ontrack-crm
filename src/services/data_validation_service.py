# src/services/data_validation_service.py
"""
Automatic data-quality gate for MIS/report generation. Replaces the old
manual admin-click "Verify" workflow on REDO activities: instead of a
human having to sign off on every record before it counts toward MIS
totals, this runs a fixed set of completeness checks automatically
whenever a report is generated. Records that pass go into the official
numbers; records that fail are excluded and listed with their specific
reason, so nothing incomplete silently becomes an official figure - but
nothing waits on a human clicking a button either.
"""
from typing import Any, List, Tuple


class DataValidationService:
    """Validates activity records before they're allowed into MIS exports."""

    def validate_redo_activity(self, activity: Any) -> List[str]:
        """Return a list of validation problems for a REDO activity. An
        empty list means the record is clean enough to count officially."""
        errors: List[str] = []

        if not (activity.registration_no or '').strip():
            errors.append('Missing registration number')
        if not (activity.customer_name or '').strip():
            errors.append('Missing customer name')

        if activity.status == 'COMPLETED':
            if not activity.completed_at:
                errors.append('Marked COMPLETED but has no completion date')
            if not (activity.technician or activity.assigned_to):
                errors.append('Marked COMPLETED but no technician assigned')

        return errors

    def split_redo_activities(self, activities: List[Any]) -> Tuple[List[Any], List[Tuple[Any, List[str]]]]:
        """Split a list of REDO activities into (valid, invalid) - invalid
        entries paired with their specific validation errors."""
        valid: List[Any] = []
        invalid: List[Tuple[Any, List[str]]] = []
        for activity in activities:
            errors = self.validate_redo_activity(activity)
            if errors:
                invalid.append((activity, errors))
            else:
                valid.append(activity)
        return valid, invalid
