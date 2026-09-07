# src/services/notification_service.py
"""
Notification Service - Real-time and in-app notifications

Two delivery paths, deliberately:

  * `socketio.emit(...)` for anyone currently connected. This was the only
    path, and nothing in the browser ever subscribed to it, so every
    notification below was being thrown away.
  * a `UserNotification` row per recipient, which base.html polls and raises
    as a desktop notification. This is the path that actually reaches people:
    it survives a reload, and it still arrives if the user was logged out
    when the event happened.

Every sender here takes the second path. An emit on its own is not delivery,
so a notification that only emits is a notification nobody gets - which is
what several of these were.

Notifications are addressed to a named person and worded personally ("You
have a new PO, Ayesha") - the software is meant to feel like it is talking to
whoever is looking at it.
"""
from typing import Dict, Any, List, Optional

from src.extensions import db, socketio
from src.models.notification import UserNotification
from src.utils.logging import get_logger

logger = get_logger(__name__)

# A run of the non-reporting sync can turn up hundreds of newly silent
# vehicles at once - the first sync after a quiet weekend, or the first sync
# ever. Past this many, one summary is sent instead of one notification per
# vehicle: three hundred bells say less than a single line saying three
# hundred.
NON_REPORTING_DIGEST_THRESHOLD = 25


class NotificationService:
    """Service for sending notifications"""

    # ------------------------------------------------------------------
    # Persistent, per-user delivery
    # ------------------------------------------------------------------

    def notify_user(self, user, title: str, body: str = '', url: Optional[str] = None,
                    category: str = UserNotification.CATEGORY_SYSTEM) -> Optional[UserNotification]:
        """Store one notification for one user.

        Never raises: a notification failing must not roll back the business
        action that triggered it (creating the PO matters more than telling
        someone about it).
        """
        if user is None or getattr(user, 'id', None) is None:
            return None
        try:
            note = UserNotification(
                user_id=user.id, title=title, body=body, url=url, category=category)
            db.session.add(note)
            db.session.commit()
            return note
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to store notification for user {getattr(user, 'id', '?')}: {e}")
            return None

    def notify_users(self, users, title_for, body_for, url: Optional[str] = None,
                     category: str = UserNotification.CATEGORY_SYSTEM) -> int:
        """Store a personalised notification for each user in `users`.

        `title_for`/`body_for` are callables taking the user, so each person
        gets their own name in their own message rather than one broadcast
        text addressed to nobody.
        """
        sent = 0
        for user in users:
            if self.notify_user(user, title_for(user), body_for(user), url, category):
                sent += 1
        return sent

    @staticmethod
    def display_name(user) -> str:
        """How to address someone: their name, else their username."""
        return (getattr(user, 'name', None) or getattr(user, 'username', None) or 'there')

    @staticmethod
    def _users_with_any_role(roles: List[str]) -> List[Any]:
        """Active users holding any of these roles, each listed once.

        One person holding two of the roles is told once, not twice about
        the same thing.
        """
        from src.models.user import User
        found = {}
        for user in User.query.filter_by(is_active=True).all():
            if user.has_any_role(roles):
                found[user.id] = user
        return list(found.values())

    @staticmethod
    def _path_for(endpoint: str, fallback: str, **values) -> str:
        """A URL for the notification to link to.

        Notifications are raised from services, background syncs and the
        scheduler as well as from requests, and url_for needs an application
        context. The stored fallback path means a notification raised outside
        a request still lands somewhere useful rather than being dropped.
        """
        try:
            from flask import url_for
            return url_for(endpoint, **values)
        except Exception:                                  # noqa: BLE001
            return fallback

    @staticmethod
    def _installation_recipients() -> List[Any]:
        """Active users who work the installation queue.

        Admins are excluded on purpose - this is a work assignment, not an
        announcement, and admins already see every PO on their dashboard.
        """
        from src.models.user import User
        return [u for u in User.query.filter_by(is_active=True).all()
                if u.has_role('installation')]

    def notify_installers_new_po(self, po) -> None:
        """Tell each installation user, by name, that a new PO is waiting."""
        try:
            socketio.emit('new_po_notification', {
                'title': 'NEW PURCHASE ORDER',
                'message': f'PO {po.po_number} created for {po.owner_name}',
                'po_id': po.id,
                'po_number': po.po_number,
                'customer_name': po.owner_name,
                'registration': po.reg_no,
                'scheduled_date': po.scheduled_date.strftime('%d/%m/%Y') if po.scheduled_date else 'Not scheduled',
                'type': 'po_created'
            }, to='installation')
        except Exception as e:
            logger.error(f"Failed to emit PO notification: {e}")

        try:
            from flask import url_for
            try:
                target = url_for('installation.dashboard')
            except Exception:
                target = '/installation/dashboard'

            recipients = self._installation_recipients()
            sent = self.notify_users(
                recipients,
                title_for=lambda u: f'You have a new PO, {self.display_name(u)}',
                body_for=lambda u: (
                    f'{po.po_number} - {po.owner_name}'
                    + (f' ({po.reg_no})' if po.reg_no else '')
                ),
                url=target,
                category=UserNotification.CATEGORY_PO)
            logger.info(f"PO {po.po_number}: notified {sent} installation user(s)")
        except Exception as e:
            logger.error(f"Failed to store PO notifications: {e}")


    def notify_installers_po_updated(self, po) -> None:
        """Tell the installation team an existing PO now has work waiting.

        Separate from `notify_installers_new_po` because the two say
        different things: one announces an order that did not exist before,
        this one announces one whose details have just been filled in - by a
        bulk update sheet, typically - and is now theirs to schedule. Sending
        the "new PO" message for both would have installers looking for an
        order they have already seen.
        """
        try:
            from flask import url_for
            try:
                target = url_for('installation.dashboard')
            except Exception:
                target = '/installation/dashboard'

            sent = self.notify_users(
                self._installation_recipients(),
                title_for=lambda u: f'A PO was updated for you, {self.display_name(u)}',
                body_for=lambda u: (
                    f'{po.po_number} - {po.owner_name}'
                    + (f' ({po.reg_no})' if po.reg_no else '')
                    + f' is {po.status}'
                ),
                url=target,
                category=UserNotification.CATEGORY_PO)
            logger.info(f"PO {po.po_number}: notified {sent} installation user(s) of update")
        except Exception as e:
            logger.error(f"Failed to store PO update notifications: {e}")

    def notify_completion(self, po) -> None:
        """Tell the people waiting on an installation that it is done.

        The salesperson who raised the order first - it is their customer
        asking when the vehicle will be fitted - and the administrators and
        managers who answer for the queue. Both used to get a socket.io event
        that nothing in the browser listened for, so nobody was told at all.
        """
        try:
            socketio.emit('po_completed', {
                'title': 'INSTALLATION COMPLETED',
                'message': f'PO {po.po_number} - {po.owner_name} completed',
                'po_id': po.id,
                'po_number': po.po_number,
                'customer_name': po.owner_name,
                'type': 'po_completed'
            }, to='admin')
        except Exception as e:
            logger.error(f"Failed to emit completion notification: {e}")

        try:
            target = self._path_for('sales.po_detail', f'/sales/pos/{po.id}', po_id=po.id)
            detail = (f'{po.po_number} - {po.owner_name}'
                      + (f' ({po.reg_no})' if po.reg_no else '')
                      + ' is installed.')

            # Administrators, not managers: the PO page is open to sales,
            # admin and installation, and a link its reader is turned away
            # from is worse than no link at all.
            recipients = {u.id: u for u in self._users_with_any_role(['admin'])}
            seller = getattr(po, 'sales_person', None)
            if seller is not None and getattr(seller, 'is_active', False):
                recipients[seller.id] = seller

            sent = self.notify_users(
                list(recipients.values()),
                title_for=lambda u: f'Installation completed, {self.display_name(u)}',
                body_for=lambda u: detail,
                url=target,
                category=UserNotification.CATEGORY_PO)
            logger.info(f"PO {po.po_number}: completion notified to {sent} user(s)")
        except Exception as e:
            logger.error(f"Failed to store completion notifications: {e}")
    
    @staticmethod
    def _security_recipients() -> List[Any]:
        """Active users who run security briefings."""
        from src.models.user import User
        return [u for u in User.query.filter_by(is_active=True).all()
                if u.has_role('security')]

    def notify_security_briefing_created(self, briefing) -> None:
        """Tell the security briefing officer a new briefing is waiting.

        Raised the moment the installation-completion email goes out, which
        is what puts the briefing on their wallboard - so the notification
        and the work appear together rather than the work sitting unnoticed.
        """
        try:
            from flask import url_for
            try:
                target = url_for('security.dashboard', tab='new')
            except Exception:
                target = '/security/dashboard?tab=new'

            reg_no = getattr(briefing, 'registration_no', None) or 'a new vehicle'
            customer = getattr(briefing, 'customer_name', None) or 'customer'

            sent = self.notify_users(
                self._security_recipients(),
                title_for=lambda u: f'New security briefing for you, {self.display_name(u)}',
                body_for=lambda u: f'{reg_no} - {customer}. Installation completed.',
                url=target,
                category=UserNotification.CATEGORY_SECURITY_BRIEFING)
            logger.info(f"Security briefing for {reg_no}: notified {sent} security user(s)")
        except Exception as e:
            logger.error(f"Failed to store security briefing notifications: {e}")

    def notify_security_briefing(self, briefing) -> None:
        """Tell the administrators a security briefing has been completed.

        The briefing closes out an installation, so it is the last thing that
        has to happen before a job is finished - which makes "it is done" a
        fact somebody is waiting for, not a socket.io event into the void.
        Administrators only, because the briefing page is theirs and the
        security team's, and the security officer is the one who just did it.
        """
        try:
            socketio.emit('security_briefing_completed', {
                'title': 'SECURITY BRIEFING COMPLETED',
                'message': f'Briefing for {briefing.registration_no} completed',
                'briefing_id': briefing.id,
                'registration': briefing.registration_no,
                'customer': briefing.customer_name,
                'type': 'security_completed'
            }, to='admin')
        except Exception as e:
            logger.error(f"Failed to emit security briefing notification: {e}")

        try:
            target = self._path_for('security.briefing_edit',
                                    f'/security/briefing/{briefing.id}',
                                    briefing_id=briefing.id)
            reg_no = getattr(briefing, 'registration_no', None) or 'a vehicle'
            customer = getattr(briefing, 'customer_name', None) or 'customer'
            officer = getattr(briefing, 'briefed_by', None)

            sent = self.notify_users(
                self._users_with_any_role(['admin']),
                title_for=lambda u: f'Security briefing completed, {self.display_name(u)}',
                body_for=lambda u: (f'{reg_no} - {customer}.'
                                    + (f' Briefed by {officer}.' if officer else '')),
                url=target,
                category=UserNotification.CATEGORY_SECURITY_BRIEFING)
            logger.info(f"Security briefing {briefing.id}: notified {sent} user(s)")
        except Exception as e:
            logger.error(f"Failed to store security briefing notifications: {e}")
    
    @staticmethod
    def _complaint_recipients() -> List[Any]:
        """Everyone who is answerable for a complaint: the Complaint Managers
        who work them, and the Administrators who answer for them.

        Deduplicated by id - one person holding both roles gets told once,
        not twice about the same ticket.
        """
        from src.models.user import User
        seen = {}
        for user in User.query.filter_by(is_active=True).all():
            if user.has_any_role(['complaint_manager', 'admin']):
                seen[user.id] = user
        return list(seen.values())

    def notify_complaint_raised(self, complaint) -> None:
        """Tell the Complaint Managers and Administrators a ticket is in.

        Carries the ticket number, who it is about, a one-line summary and
        the status, so the notification is enough to triage from without
        opening anything.
        """
        try:
            from flask import url_for
            try:
                target = url_for('complaint.detail', complaint_id=complaint.id)
            except Exception:
                target = f'/complaints/{complaint.id}'

            summary = (complaint.description or '').strip().replace('\n', ' ')
            if len(summary) > 120:
                summary = summary[:117] + '...'
            raised = complaint.created_at.strftime('%d %b %Y %H:%M') if complaint.created_at else ''

            sent = self.notify_users(
                self._complaint_recipients(),
                title_for=lambda u: f'New complaint {complaint.ticket_no}, {self.display_name(u)}',
                body_for=lambda u: (
                    f'{complaint.customer_name}'
                    + (f' ({complaint.reg_no})' if complaint.reg_no else '')
                    + f' - {summary}'
                    + (f' | Raised {raised}' if raised else '')
                    + f' | Status: {complaint.status}'
                ),
                url=target,
                category=UserNotification.CATEGORY_COMPLAINT)
            logger.info(f"Complaint {complaint.ticket_no}: notified {sent} manager/admin user(s)")
        except Exception as e:
            logger.error(f"Failed to store complaint notifications: {e}")

    def notify_complaint_resolved(self, complaint) -> None:
        """Tell whoever raised the ticket that it has been resolved.

        Addressed to the person on `created_by` - not to a role - because
        this is a reply to them. A ticket with nobody recorded against it
        (the seeded samples, or one raised before this was tracked) simply
        has no one to reply to, and that is not an error.
        """
        try:
            from flask import url_for
            from src.models.user import User

            if not complaint.created_by:
                return
            raiser = User.query.get(complaint.created_by)
            if raiser is None or not raiser.is_active:
                return

            try:
                target = url_for('complaint.my_complaints')
            except Exception:
                target = '/complaints/my'

            resolution = (complaint.resolution_notes or '').strip().replace('\n', ' ')
            if len(resolution) > 160:
                resolution = resolution[:157] + '...'

            self.notify_user(
                raiser,
                title=f'Complaint {complaint.ticket_no} has been resolved',
                body=(f'Status: {complaint.status}.'
                      + (f' {resolution}' if resolution else '')),
                url=target,
                category=UserNotification.CATEGORY_COMPLAINT)
            logger.info(f"Complaint {complaint.ticket_no}: resolution notified to user {raiser.id}")
        except Exception as e:
            logger.error(f"Failed to store complaint resolution notification: {e}")

    def notify_payment_received(self, payment, amount: float) -> None:
        """Tell the recovery team money has come in against an order.

        Carries the amount, the order and what is still outstanding, so the
        person chasing it knows whether to stop chasing without opening
        anything.
        """
        po = getattr(payment, 'purchase_order', None)
        po_number = getattr(po, 'po_number', None) or f'payment #{payment.id}'

        try:
            socketio.emit('payment_received', {
                'title': 'PAYMENT RECEIVED',
                'message': f'Payment of PKR {amount:,.2f} received for PO {po_number}',
                'payment_id': payment.id,
                'po_number': po_number,
                'amount': amount,
                'type': 'payment_received'
            }, to='payment_recovery')
        except Exception as e:
            logger.error(f"Failed to emit payment notification: {e}")

        try:
            target = self._path_for('payment.dashboard', '/payment/dashboard')
            owner = getattr(po, 'owner_name', None)
            balance = getattr(payment, 'remaining_amount', None)
            status = getattr(payment, 'payment_status', None)

            body = (f'PKR {amount:,.2f} received against {po_number}'
                    + (f' - {owner}' if owner else '') + '.'
                    + (f' Balance PKR {balance:,.2f}.' if isinstance(balance, (int, float)) else '')
                    + (f' Now {status}.' if status else ''))

            sent = self.notify_users(
                self._users_with_any_role(['payment_recovery', 'admin']),
                title_for=lambda u: f'Payment received, {self.display_name(u)}',
                body_for=lambda u: body,
                url=target,
                category=UserNotification.CATEGORY_PAYMENT)
            logger.info(f"Payment {payment.id}: notified {sent} user(s)")
        except Exception as e:
            logger.error(f"Failed to store payment notifications: {e}")
    
    def notify_technician_assigned(self, po, technician_name: str) -> None:
        """Tell the salesperson their order now has a technician on it.

        They are the one the customer asks "when is someone coming", and the
        answer stops being "unassigned" at this moment. Administrators are
        told as well because they answer for the queue; the installation user
        is not, because they are the one who just did it.
        """
        try:
            socketio.emit('technician_assigned', {
                'title': 'TECHNICIAN ASSIGNED',
                'message': f'{technician_name} assigned to PO {po.po_number}',
                'po_id': po.id,
                'po_number': po.po_number,
                'technician': technician_name,
                'type': 'technician_assigned'
            }, to='installation')
        except Exception as e:
            logger.error(f"Failed to emit technician assignment notification: {e}")

        try:
            target = self._path_for('sales.po_detail', f'/sales/pos/{po.id}', po_id=po.id)
            scheduled = getattr(po, 'scheduled_date', None)
            body = (f'{technician_name} is on {po.po_number} - {po.owner_name}'
                    + (f' ({po.reg_no})' if po.reg_no else '') + '.'
                    + (f" Scheduled {scheduled.strftime('%d %b %Y')}." if scheduled else ''))

            recipients = {u.id: u for u in self._users_with_any_role(['admin'])}
            seller = getattr(po, 'sales_person', None)
            if seller is not None and getattr(seller, 'is_active', False):
                recipients[seller.id] = seller

            sent = self.notify_users(
                list(recipients.values()),
                title_for=lambda u: f'Technician assigned, {self.display_name(u)}',
                body_for=lambda u: body,
                url=target,
                category=UserNotification.CATEGORY_ASSIGNMENT)
            logger.info(f"PO {po.po_number}: technician assignment notified to {sent} user(s)")
        except Exception as e:
            logger.error(f"Failed to store technician assignment notifications: {e}")
    
    def notify_vehicle_non_reporting(self, vehicle) -> None:
        """Tell the REDO team a vehicle has gone silent."""
        try:
            socketio.emit('non_reporting_vehicle', {
                'title': 'VEHICLE NOT REPORTING',
                'message': f'{vehicle.registration_no} has not reported for {vehicle.get_hours_non_reporting()} hours',
                'vehicle_id': vehicle.id,
                'registration': vehicle.registration_no,
                'customer': vehicle.customer_name,
                'hours': vehicle.get_hours_non_reporting(),
                'type': 'non_reporting'
            }, to='redo_technician')
        except Exception as e:
            logger.error(f"Failed to emit non-reporting notification: {e}")

        try:
            target = self._path_for('redo.non_reporting_dashboard', '/redo/non-reporting')
            hours = vehicle.get_hours_non_reporting()
            body = (f'{vehicle.registration_no}'
                    + (f' - {vehicle.customer_name}' if vehicle.customer_name else '')
                    + f' has not reported for {hours} hours.')

            sent = self.notify_users(
                self._users_with_any_role(['redo_technician', 'admin']),
                title_for=lambda u: f'Vehicle stopped reporting, {self.display_name(u)}',
                body_for=lambda u: body,
                url=target,
                category=UserNotification.CATEGORY_SYSTEM)
            logger.info(f"{vehicle.registration_no}: non-reporting notified to {sent} user(s)")
        except Exception as e:
            logger.error(f"Failed to store non-reporting notification: {e}")

    def notify_vehicles_non_reporting(self, vehicles) -> None:
        """Tell the REDO team about a batch of newly silent vehicles.

        A sync can turn up one vehicle or three hundred. Below the digest
        threshold each gets its own notification, because each is a job.
        Above it, one line saying how many - a bell that rings three hundred
        times is a bell nobody reads.
        """
        vehicles = [v for v in (vehicles or []) if v is not None]
        if not vehicles:
            return

        if len(vehicles) <= NON_REPORTING_DIGEST_THRESHOLD:
            for vehicle in vehicles:
                self.notify_vehicle_non_reporting(vehicle)
            return

        try:
            target = self._path_for('redo.non_reporting_dashboard', '/redo/non-reporting')
            sample = ', '.join(v.registration_no for v in vehicles[:5] if v.registration_no)
            body = (f'{len(vehicles)} vehicles have stopped reporting since the last sync'
                    + (f' - including {sample}.' if sample else '.'))

            sent = self.notify_users(
                self._users_with_any_role(['redo_technician', 'admin']),
                title_for=lambda u: f'{len(vehicles)} vehicles stopped reporting, {self.display_name(u)}',
                body_for=lambda u: body,
                url=target,
                category=UserNotification.CATEGORY_SYSTEM)
            logger.info(f"Non-reporting digest ({len(vehicles)} vehicles): notified {sent} user(s)")
        except Exception as e:
            logger.error(f"Failed to store non-reporting digest: {e}")
    
    def send_alert(self, title: str, message: str, room: str = 'admin') -> None:
        """Send a general alert to everyone holding a role.

        `room` is the role the alert is for - the socket.io room names and
        the role names are the same strings, which is what lets one argument
        serve both paths.
        """
        try:
            socketio.emit('system_alert', {
                'title': title,
                'message': message,
                'timestamp': get_current_time().isoformat(),
                'type': 'alert'
            }, to=room)
        except Exception as e:
            logger.error(f"Failed to emit alert: {e}")

        try:
            sent = self.notify_users(
                self._users_with_any_role([room]),
                title_for=lambda u: title,
                body_for=lambda u: message,
                url=None,
                category=UserNotification.CATEGORY_SYSTEM)
            logger.info(f"Alert '{title}': delivered to {sent} {room} user(s)")
        except Exception as e:
            logger.error(f"Failed to store alert: {e}")


# Import for type hints
from src.utils.timezone import get_current_time 
