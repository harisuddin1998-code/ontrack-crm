# src/services/complaint_service.py
"""
Complaint Service - Business logic for Complaint Management
"""
from typing import Optional, List, Dict, Any

from src.models.complaint import Complaint
from src.repositories.complaint_repository import ComplaintRepository
from src.services.base_service import BaseService
from src.services.notification_service import NotificationService
from src.utils.logging import get_logger

logger = get_logger(__name__)


class ComplaintService(BaseService[Complaint]):
    """Service for complaint operations"""

    def __init__(self):
        self.complaint_repo = ComplaintRepository()
        self.notification_service = NotificationService()
        super().__init__(self.complaint_repo)

    def create_complaint(self, data: Dict[str, Any], user_id: Optional[int] = None) -> Complaint:
        """Create a new complaint ticket"""
        data = data.copy()
        if 'ticket_no' not in data or not data['ticket_no']:
            data['ticket_no'] = self.complaint_repo.generate_ticket_no()

        if user_id:
            data['created_by'] = user_id

        data['status'] = data.get('status', 'OPEN')
        data['severity'] = data.get('severity', 'MEDIUM')

        complaint = self.complaint_repo.create(**data)
        logger.info(f"Complaint ticket created: {complaint.ticket_no}")

        # Raised here rather than in the route so every path that logs a
        # ticket notifies - a complaint created by an import or a future
        # API would otherwise reach nobody. Never raises: failing to
        # announce a ticket must not undo logging it.
        self.notification_service.notify_complaint_raised(complaint)
        return complaint

    def update_complaint(self, complaint_id: int, data: Dict[str, Any]) -> Optional[Complaint]:
        """Update complaint details"""
        return self.complaint_repo.update(complaint_id, **data)

    def assign_complaint(self, complaint_id: int, technician_id: int) -> Optional[Complaint]:
        """Assign a complaint to a technician from the Technician Management
        roster."""
        complaint = self.complaint_repo.get_by_id(complaint_id)
        if complaint:
            complaint.mark_in_progress(technician_id=technician_id)
            logger.info(f"Complaint {complaint.ticket_no} assigned to technician {technician_id}")
        return complaint

    def resolve_complaint(self, complaint_id: int, user_id: int, resolution_notes: str) -> Optional[Complaint]:
        """Resolve a complaint ticket and tell whoever raised it."""
        complaint = self.complaint_repo.get_by_id(complaint_id)
        if not complaint:
            return None

        # Only a real transition notifies. Saving the resolution form again
        # to correct a typo must not send the customer a second "your
        # complaint has been resolved" - the requirement is one resolution
        # notice per resolution.
        was_resolved = complaint.status == 'RESOLVED'
        complaint.mark_resolved(user_id=user_id, notes=resolution_notes)
        logger.info(f"Complaint {complaint.ticket_no} resolved by user {user_id}")

        if not was_resolved:
            self.notification_service.notify_complaint_resolved(complaint)
        return complaint

    def get_complaints(self, filters: Optional[Dict[str, Any]] = None, page: int = 1,
                       per_page: int = 20,
                       criteria: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Complaints for the board, filtered, searched and paginated.

        `filters` are the status/severity buttons; `criteria` is what was
        typed into the search fields (ticket number, registration, contact,
        date range). Both go to the same query, so a search made from a
        filtered board stays inside that filter instead of quietly widening
        back out to everything.
        """
        criteria = criteria or {}
        items, total = self.complaint_repo.search_tickets(
            ticket_no=criteria.get('ticket_no'),
            reg_no=criteria.get('reg_no'),
            contact=criteria.get('contact'),
            date_from=criteria.get('date_from'),
            date_to=criteria.get('date_to'),
            filters=filters or {},
            page=page,
            per_page=per_page,
        )
        return {'items': items, 'total': total, 'page': page, 'per_page': per_page}

    def get_dashboard_stats(self, user_id: Optional[int] = None) -> Dict[str, Any]:
        """Complaint counts - for everyone, or for one person's own tickets.

        Passing `user_id` scopes every count to the tickets that user raised,
        which is what backs their personal wallboard. Same counting code
        either way, so a user's "Resolved" and the manager's "Resolved" can
        never be computed differently.
        """
        return self.complaint_repo.get_dashboard_stats(created_by=user_id)

    def get_user_complaints(self, user_id: int) -> List[Complaint]:
        """Every complaint one user raised, newest first.

        The only way the user-facing wallboard reads complaints, so the
        "you see your own tickets and nobody else's" rule lives in one place
        rather than being re-stated at each call site.
        """
        return self.complaint_repo.get_by_creator(user_id)

    def auto_seed_sample_complaints(self) -> None:
        """Seed initial sample complaints if database table is empty"""
        if self.count() > 0:
            return

        samples = [
            {
                'ticket_no': 'CMP-2026-0001',
                'customer_name': 'Pak National Logistics',
                'customer_contact': '0300-8451122',
                'reg_no': 'LEB-2021-9981',
                'city': 'LAHORE',
                'complaint_type': 'GPS_NOT_WORKING',
                'severity': 'CRITICAL',
                'status': 'OPEN',
                'description': 'Device stopped updating position 48 hours ago near Thokar Niaz Baig.',
            },
            {
                'ticket_no': 'CMP-2026-0002',
                'customer_name': 'Atlas Honda Distribution',
                'customer_contact': '0312-9988776',
                'reg_no': 'ICT-2023-4510',
                'city': 'ISLAMABAD',
                'complaint_type': 'INCORRECT_LOCATION',
                'severity': 'HIGH',
                'status': 'IN_PROGRESS',
                'description': 'Vehicle showing location in Rawalpindi while physically parked in I-9 Islamabad.',
            },
            {
                'ticket_no': 'CMP-2026-0003',
                'customer_name': 'Habib Metro Services',
                'customer_contact': '0321-7766554',
                'reg_no': 'KHI-2022-8871',
                'city': 'KARACHI',
                'complaint_type': 'ENGINE_CUTOFF_ISSUE',
                'severity': 'MEDIUM',
                'status': 'RESOLVED',
                'description': 'Engine immobilizer relay test requested by customer after scheduled service.',
                'resolution_notes': 'Relay wiring inspected and re-calibrated. Cutoff test successful.'
            }
        ]

        for s in samples:
            self.complaint_repo.create(**s)
        logger.info("Auto-seeded sample customer complaints")
