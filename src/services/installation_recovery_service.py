# src/services/installation_recovery_service.py
"""
Installation Recovery Service - auto-creates a device replacement recovery
charge whenever a REDO activity is saved with a triggering device_change_reason,
round-robins it across active Payment Recovery officers, and manages the
PENDING -> CONTACTED -> RECOVERED/LOST lifecycle.
"""
from datetime import datetime
from typing import Any, List, Optional

from src.extensions import db
from src.models.installation_recovery import (
    InstallationRecoveryCharge,
    InstallationRecoveryFollowup,
    get_recovery_amount,
    normalize_device_change_reason,
)
from src.models.user import User
from src.utils.logging import get_logger

logger = get_logger(__name__)

TRIGGERING_REASONS = ('Power Issue', 'Device Damage', 'Device Missing')


class InstallationRecoveryService:

    @staticmethod
    def is_supervisor(current_user: Any) -> bool:
        """Admin, manager, and executive see every officer's charges; an officer sees only
        their own."""
        return current_user.is_admin() or current_user.is_manager() or current_user.is_executive()

    @staticmethod
    def works_device_recovery(current_user: Any) -> bool:
        """Holds a role that is assigned Device Recovery charges.

        device_recovery is included deliberately: without it, a user granted
        only that role matches no scoping branch below and would see every
        officer's charges instead of their own.
        """
        return current_user.is_payment_recovery() or current_user.is_device_recovery()

    def get_officers(self) -> List[User]:
        """Active users who work Device Recovery charges, in a stable order so
        round-robin assignment is deterministic. Includes the standalone
        device_recovery role, so granting it also puts the user in the
        assignment rotation rather than leaving them with an empty screen."""
        officers = User.query.filter_by(is_active=True).order_by(User.id).all()
        return [u for u in officers if self.works_device_recovery(u)]

    def create_charge_if_applicable(self, redo_activity: Any, actor_user_id: Optional[int] = None) -> Optional[InstallationRecoveryCharge]:
        """Called right after a REDO activity is saved. Creates exactly one
        InstallationRecoveryCharge if device_change_reason is one of the
        four triggering reasons - idempotent (the unique constraint on
        redo_activity_id means a second call for the same activity is a
        no-op), and never fires for reasons outside the trigger set."""
        reason = normalize_device_change_reason(redo_activity.device_change_reason)
        if reason not in TRIGGERING_REASONS:
            return None

        existing = InstallationRecoveryCharge.query.filter_by(redo_activity_id=redo_activity.id).first()
        if existing:
            return existing

        officers = self.get_officers()
        officer = None
        if officers:
            idx = InstallationRecoveryCharge.query.count() % len(officers)
            officer = officers[idx]
        else:
            logger.warning("Installation Recovery: no active payment_recovery officers to assign - charge left unassigned")

        charge = InstallationRecoveryCharge(
            redo_activity_id=redo_activity.id,
            reason=reason,
            amount=get_recovery_amount(reason),
            status=InstallationRecoveryCharge.STATUS_PENDING,
            assigned_officer_id=officer.id if officer else None,
            assigned_at=datetime.utcnow() if officer else None,
            created_by=actor_user_id,
        )
        db.session.add(charge)
        db.session.commit()
        logger.info(f"Installation Recovery: charge #{charge.id} created for REDO {redo_activity.id} "
                    f"({reason}, PKR {charge.amount}) assigned to {officer.name if officer else 'nobody'}")
        return charge

    def reassign_charge(self, charge_id: int, officer_id: Optional[int],
                        actor: Any = None) -> Optional[InstallationRecoveryCharge]:
        """Move a charge to a different Device Recovery officer.

        Round-robin only ever hands a charge to whoever was on the roster the
        moment it was created, so an officer added later starts with nothing
        and no way to be given any of the standing backlog. This is that way.

        `officer_id` of None unassigns. A target who does not work Device
        Recovery, or is not active, is refused rather than quietly ignored -
        assigning to them would hide the charge from every officer at once,
        since each officer's list is filtered to their own id.
        """
        charge = InstallationRecoveryCharge.query.get(charge_id)
        if not charge:
            return None

        officer = None
        if officer_id is not None:
            officer = User.query.get(officer_id)
            if not officer or not officer.is_active or not self.works_device_recovery(officer):
                logger.warning(f"Device Recovery: refused to assign charge #{charge_id} "
                               f"to user {officer_id} - not an active Device Recovery officer")
                return None

        previous = charge.assigned_officer.name if charge.assigned_officer else 'nobody'
        charge.assigned_officer_id = officer.id if officer else None
        charge.assigned_at = datetime.utcnow() if officer else None
        db.session.commit()
        logger.info(f"Device Recovery: charge #{charge.id} moved from {previous} to "
                    f"{officer.name if officer else 'nobody'}"
                    f"{f' by {actor.username}' if actor is not None else ''}")
        return charge

    def get_charges_for_view(self, current_user: Any, status: Optional[str] = None,
                              reason: Optional[str] = None) -> List[InstallationRecoveryCharge]:
        """Charges scoped to the viewer: officers only see their own;
        admin/manager see all. `reason` filters to one of the Device Recovery
        module's three layers (Power Issue / Device Damage / Device Missing)."""
        query = InstallationRecoveryCharge.query
        if status:
            query = query.filter_by(status=status)
        if reason:
            query = query.filter_by(reason=reason)
        if self.works_device_recovery(current_user) and not self.is_supervisor(current_user):
            query = query.filter_by(assigned_officer_id=current_user.id)
        return query.order_by(InstallationRecoveryCharge.created_at.desc()).all()

    def followup_summaries(self, charges: List[InstallationRecoveryCharge]) -> dict:
        """Per-charge call history, keyed by charge id, in one query.

        The dashboard reads `charge.followups` per row, which is a query per
        row; a call sheet covering a few hundred charges cannot afford that.
        Each entry carries what an officer needs before dialling: how many
        times this customer has already been chased, when the last attempt
        was and what came of it, and whether a callback is now due.
        """
        ids = [c.id for c in charges]
        if not ids:
            return {}

        rows: List[InstallationRecoveryFollowup] = []
        for start in range(0, len(ids), 400):
            rows.extend(InstallationRecoveryFollowup.query.filter(
                InstallationRecoveryFollowup.charge_id.in_(ids[start:start + 400])
            ).order_by(InstallationRecoveryFollowup.conversation_date.desc()).all())

        summaries: dict = {}
        for row in rows:
            entry = summaries.setdefault(row.charge_id, {
                'count': 0, 'last': None, 'next_due': None,
            })
            entry['count'] += 1
            # Rows arrive newest-first, so the first one seen for a charge is
            # its most recent conversation.
            if entry['last'] is None:
                entry['last'] = row
            # The soonest callback still outstanding, whichever call set it.
            if row.follow_up_date and (entry['next_due'] is None
                                       or row.follow_up_date < entry['next_due']):
                entry['next_due'] = row.follow_up_date
        return summaries

    def mark_contacted(self, charge_id: int, notes: Optional[str] = None) -> Optional[InstallationRecoveryCharge]:
        charge = InstallationRecoveryCharge.query.get(charge_id)
        if not charge:
            return None
        charge.status = InstallationRecoveryCharge.STATUS_CONTACTED
        if notes:
            charge.notes = notes
        db.session.commit()
        return charge

    def mark_lost(self, charge_id: int, reason: str) -> Optional[InstallationRecoveryCharge]:
        """Mark a charge as unrecoverable (customer unreachable, written off,
        etc.) - a terminal state alongside RECOVERED, same as AMC's LOST."""
        charge = InstallationRecoveryCharge.query.get(charge_id)
        if not charge:
            return None
        charge.status = InstallationRecoveryCharge.STATUS_LOST
        charge.notes = reason
        db.session.commit()
        return charge

    def record_payment(self, charge_id: int, payment_method: str, reference: Optional[str],
                       proof_of_payment_path: Optional[str], notes: Optional[str] = None) -> Optional[InstallationRecoveryCharge]:
        charge = InstallationRecoveryCharge.query.get(charge_id)
        if not charge:
            return None
        charge.status = InstallationRecoveryCharge.STATUS_RECOVERED
        charge.payment_method = payment_method
        charge.payment_reference = reference
        charge.proof_of_payment_path = proof_of_payment_path
        charge.recovered_at = datetime.utcnow()
        if notes:
            charge.notes = notes
        db.session.commit()
        return charge

    def get_dashboard_stats(self, current_user: Any, reason: Optional[str] = None) -> dict:
        charges = self.get_charges_for_view(current_user, reason=reason)
        return {
            'total': len(charges),
            'pending': sum(1 for c in charges if c.status == InstallationRecoveryCharge.STATUS_PENDING),
            'contacted': sum(1 for c in charges if c.status == InstallationRecoveryCharge.STATUS_CONTACTED),
            'recovered': sum(1 for c in charges if c.status == InstallationRecoveryCharge.STATUS_RECOVERED),
            'lost': sum(1 for c in charges if c.status == InstallationRecoveryCharge.STATUS_LOST),
            'amount_outstanding': sum(c.get_outstanding() for c in charges),
            'amount_recovered': sum(c.amount for c in charges if c.status == InstallationRecoveryCharge.STATUS_RECOVERED),
        }

    def get_reason_counts(self, current_user: Any) -> dict:
        """Charge counts per Device Recovery layer (Power Issue / Device
        Damage / Device Missing), for the dashboard's reason tabs."""
        charges = self.get_charges_for_view(current_user)
        counts = {r: 0 for r in TRIGGERING_REASONS}
        for c in charges:
            if c.reason in counts:
                counts[c.reason] += 1
        return counts

    # ------------------------------------------------------------------
    # Follow-up call log (Follow-up Report)
    # ------------------------------------------------------------------

    def add_followup(self, charge_id: int, data: dict, user: Any) -> Optional[InstallationRecoveryFollowup]:
        """Log a call/WhatsApp follow-up against a charge. Also nudges the
        charge to CONTACTED if it's still sitting at PENDING, same as a
        manual "Mark Contacted" would, since a logged conversation IS
        contact having been made."""
        charge = InstallationRecoveryCharge.query.get(charge_id)
        if not charge:
            return None

        followup = InstallationRecoveryFollowup(
            charge_id=charge_id,
            conversation_type=data.get('conversation_type'),
            direction=data.get('direction'),
            contact_person=data.get('contact_person'),
            contact_number=data.get('contact_number'),
            summary=data.get('summary'),
            action_taken=data.get('action_taken'),
            follow_up_required=bool(data.get('follow_up_date')),
            follow_up_date=data.get('follow_up_date'),
            recorded_by=user.id,
            recorded_by_name=user.name or user.username,
        )
        db.session.add(followup)

        if charge.status == InstallationRecoveryCharge.STATUS_PENDING:
            charge.status = InstallationRecoveryCharge.STATUS_CONTACTED

        db.session.commit()
        return followup

    def get_followups_for_report(self, current_user: Any, status: Optional[str] = None,
                                  search: Optional[str] = None) -> List[InstallationRecoveryFollowup]:
        """Follow-up log entries for the report, scoped the same way as the
        main charge list - an officer only sees their own charges' calls."""
        query = InstallationRecoveryFollowup.query.join(
            InstallationRecoveryCharge, InstallationRecoveryFollowup.charge_id == InstallationRecoveryCharge.id
        )
        if self.works_device_recovery(current_user) and not self.is_supervisor(current_user):
            query = query.filter(InstallationRecoveryCharge.assigned_officer_id == current_user.id)
        if status:
            query = query.filter(InstallationRecoveryCharge.status == status)
        if search:
            from src.models.redo import RedoActivity
            pattern = f"%{search}%"
            query = query.join(RedoActivity, InstallationRecoveryCharge.redo_activity_id == RedoActivity.id).filter(
                db.or_(RedoActivity.registration_no.ilike(pattern), RedoActivity.customer_name.ilike(pattern))
            )
        return query.order_by(InstallationRecoveryFollowup.conversation_date.desc()).limit(500).all()
