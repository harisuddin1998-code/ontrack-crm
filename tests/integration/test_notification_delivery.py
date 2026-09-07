"""
Every notification the CRM raises reaches a person.

There are two delivery paths. `socketio.emit` reaches whoever is connected -
except nothing in the browser ever subscribed to those events, so it reaches
nobody. A `UserNotification` row is what base.html polls and raises as a
desktop notification, and it survives a reload, a logout, and a browser that
was closed when the event happened.

Six senders only emitted: installation completed, security briefing
completed, payment received, technician assigned, vehicle stopped reporting,
and the general alert. Every one of them now stores as well, and the two that
nothing ever called are wired to the moment they describe.

A notification is a link, so each is checked against a page its recipients
can actually open.
"""
from datetime import date, datetime

import pytest

from src.app import create_app
from src.extensions import db
from src.models.gps import NonReportingVehicle
from src.models.notification import UserNotification
from src.models.payment import PaymentRecovery
from src.models.purchase_order import PurchaseOrder
from src.models.security import SecurityBriefingData
from src.models.user import User
from src.services.notification_service import (NON_REPORTING_DIGEST_THRESHOLD,
                                               NotificationService)

ROLES = ('admin', 'manager', 'sales', 'installation', 'security',
         'payment_recovery', 'redo_technician', 'inventory')


@pytest.fixture(scope='module')
def crm_app():
    application = create_app('testing')
    with application.app_context():
        db.create_all()

        for role in ROLES:
            user = User(username=f'nd_{role}', email=f'nd_{role}@test.local',
                        name=role.replace('_', ' ').title(), role=role, is_active=True)
            user.set_password('pw123456')
            db.session.add(user)
        db.session.flush()

        seller = User.query.filter_by(username='nd_sales').one()
        po = PurchaseOrder(
            po_number='PO-ND-001', owner_name='Notify Customer',
            owner_contact='0300-1112222', reg_no='ND-001',
            vehicle_make='TOYOTA', vehicle_model='COROLLA', vehicle_year='2021',
            vehicle_color='WHITE', engine_number='ENG-ND-1',
            chassis_number='CHS-ND-1', vehicle_availability_location='LAHORE',
            status='COMPLETED', sales_person_id=seller.id, scheduled_date=date.today())
        db.session.add(po)
        db.session.flush()

        db.session.add(SecurityBriefingData(
            po_id=po.id, status='COMPLETED', briefed_by='Security Officer',
            completed_at=datetime.now(), synced_from_po=True))
        db.session.add(PaymentRecovery(
            po_id=po.id, total_amount=25000.0, amount_received=10000.0,
            remaining_amount=15000.0, payment_status='PARTIAL'))
        db.session.add(NonReportingVehicle(
            registration_no='ND-001', customer_name='Notify Customer',
            imei_no='860111222333444'))
        db.session.commit()

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def clean_slate(crm_app):
    """No notifications before, none left behind."""
    with crm_app.app_context():
        UserNotification.query.delete()
        db.session.commit()
    yield
    with crm_app.app_context():
        UserNotification.query.delete()
        db.session.commit()


def delivered():
    """Who holds a notification, by username."""
    told = {}
    for note in UserNotification.query.all():
        told.setdefault(User.query.get(note.user_id).username, []).append(note)
    return told


# --------------------------------------------------------------------------
# Installation completed
# --------------------------------------------------------------------------

def test_installation_completion_reaches_the_seller_and_the_admin(crm_app, clean_slate):
    with crm_app.app_context():
        po = PurchaseOrder.query.filter_by(po_number='PO-ND-001').one()
        NotificationService().notify_completion(po)
        told = delivered()

        assert 'nd_sales' in told, 'the salesperson who raised it was not told'
        assert 'nd_admin' in told

        note = told['nd_sales'][0]
        assert 'PO-ND-001' in note.body
        assert note.url == f'/sales/pos/{po.id}'
        assert note.category == UserNotification.CATEGORY_PO


def test_completion_only_goes_to_people_who_can_open_the_order(crm_app, clean_slate):
    """The PO page is open to sales, admin and installation. A notification
    linking somewhere its reader is turned away from is worse than none."""
    with crm_app.app_context():
        po = PurchaseOrder.query.filter_by(po_number='PO-ND-001').one()
        NotificationService().notify_completion(po)

        assert 'nd_manager' not in delivered()


# --------------------------------------------------------------------------
# Security briefing completed
# --------------------------------------------------------------------------

def test_a_completed_briefing_reaches_the_administrator(crm_app, clean_slate):
    with crm_app.app_context():
        briefing = SecurityBriefingData.query.first()
        NotificationService().notify_security_briefing(briefing)
        told = delivered()

        assert 'nd_admin' in told
        note = told['nd_admin'][0]
        assert 'ND-001' in note.body
        assert 'briefing' in note.url
        assert note.category == UserNotification.CATEGORY_SECURITY_BRIEFING


# --------------------------------------------------------------------------
# Payment received
# --------------------------------------------------------------------------

def test_a_payment_reaches_the_recovery_team(crm_app, clean_slate):
    with crm_app.app_context():
        payment = PaymentRecovery.query.first()
        NotificationService().notify_payment_received(payment, 10000.0)
        told = delivered()

        assert 'nd_payment_recovery' in told
        assert 'nd_admin' in told
        note = told['nd_payment_recovery'][0]
        assert '10,000' in note.body
        assert note.category == UserNotification.CATEGORY_PAYMENT


def test_a_payment_notice_says_what_is_still_owed(crm_app, clean_slate):
    """The person chasing it needs to know whether to stop chasing."""
    with crm_app.app_context():
        payment = PaymentRecovery.query.first()
        NotificationService().notify_payment_received(payment, 10000.0)

        note = delivered()['nd_payment_recovery'][0]
        assert '15,000' in note.body, 'the balance is missing'
        assert 'PARTIAL' in note.body


# --------------------------------------------------------------------------
# Technician assigned
# --------------------------------------------------------------------------

def test_a_technician_assignment_reaches_the_seller(crm_app, clean_slate):
    with crm_app.app_context():
        po = PurchaseOrder.query.filter_by(po_number='PO-ND-001').one()
        NotificationService().notify_technician_assigned(po, 'TECH SALMAN')
        told = delivered()

        assert 'nd_sales' in told
        note = told['nd_sales'][0]
        assert 'TECH SALMAN' in note.body
        assert note.category == UserNotification.CATEGORY_ASSIGNMENT


def test_the_installer_who_did_it_is_not_told_they_did_it(crm_app, clean_slate):
    with crm_app.app_context():
        po = PurchaseOrder.query.filter_by(po_number='PO-ND-001').one()
        NotificationService().notify_technician_assigned(po, 'TECH SALMAN')

        assert 'nd_installation' not in delivered()


def test_putting_a_technician_on_an_order_is_what_raises_it(crm_app):
    """The sender existed and nothing ever called it."""
    import inspect

    from src.web import installation

    source = inspect.getsource(installation.update_po)
    assert 'notify_technician_assigned' in source
    assert 'previous_technician' in source, \
        're-saving an unchanged order would notify again'


# --------------------------------------------------------------------------
# Vehicles that stop reporting
# --------------------------------------------------------------------------

def test_a_silent_vehicle_reaches_the_redo_team(crm_app, clean_slate):
    with crm_app.app_context():
        vehicle = NonReportingVehicle.query.filter_by(registration_no='ND-001').one()
        NotificationService().notify_vehicle_non_reporting(vehicle)
        told = delivered()

        assert 'nd_redo_technician' in told
        assert 'nd_admin' in told
        assert told['nd_redo_technician'][0].url == '/redo/non-reporting'


def test_a_handful_of_vehicles_is_a_notification_each(crm_app, clean_slate):
    with crm_app.app_context():
        batch = []
        for index in range(3):
            vehicle = NonReportingVehicle(registration_no=f'SMALL-{index}',
                                          customer_name='Small Batch')
            db.session.add(vehicle)
            batch.append(vehicle)
        db.session.commit()

        NotificationService().notify_vehicles_non_reporting(batch)

        assert len(delivered()['nd_redo_technician']) == 3


def test_a_flood_of_vehicles_becomes_one_summary(crm_app, clean_slate):
    """The first sync after a quiet weekend can turn up hundreds. A bell that
    rings three hundred times is a bell nobody reads."""
    count = NON_REPORTING_DIGEST_THRESHOLD + 10
    with crm_app.app_context():
        batch = []
        for index in range(count):
            vehicle = NonReportingVehicle(registration_no=f'FLOOD-{index:03d}',
                                          customer_name='Flood Customer')
            db.session.add(vehicle)
            batch.append(vehicle)
        db.session.commit()

        NotificationService().notify_vehicles_non_reporting(batch)
        told = delivered()

        assert len(told['nd_redo_technician']) == 1
        assert str(count) in told['nd_redo_technician'][0].title


def test_an_empty_batch_says_nothing(crm_app, clean_slate):
    with crm_app.app_context():
        NotificationService().notify_vehicles_non_reporting([])

        assert delivered() == {}


def test_the_sync_is_what_raises_it(crm_app):
    """The other sender that nothing ever called."""
    import inspect

    from src.services import db_sync_service

    source = inspect.getsource(db_sync_service.DBSyncService.sync_non_reporting_vehicles)
    assert 'notify_vehicles_non_reporting' in source
    assert source.index('db.session.commit()') < source.index('notify_vehicles_non_reporting'), \
        'vehicles are announced before they are saved'


# --------------------------------------------------------------------------
# General alerts
# --------------------------------------------------------------------------

def test_an_alert_reaches_the_role_it_is_addressed_to(crm_app, clean_slate):
    with crm_app.app_context():
        NotificationService().send_alert(
            'Scheduled maintenance', 'The CRM will be down 22:00-23:00.',
            room='inventory')
        told = delivered()

        assert set(told) == {'nd_inventory'}
        assert told['nd_inventory'][0].title == 'Scheduled maintenance'


# --------------------------------------------------------------------------
# Delivery rules that hold for all of them
# --------------------------------------------------------------------------

def test_holding_two_of_the_roles_is_still_one_notification(crm_app, clean_slate):
    with crm_app.app_context():
        dual = User(username='nd_dual', email='nd_dual@test.local', name='Dual Role',
                    role='payment_recovery', additional_roles='admin', is_active=True)
        dual.set_password('pw123456')
        db.session.add(dual)
        db.session.commit()

        payment = PaymentRecovery.query.first()
        NotificationService().notify_payment_received(payment, 500.0)

        assert len(delivered().get('nd_dual', [])) == 1

        db.session.delete(User.query.filter_by(username='nd_dual').one())
        db.session.commit()


def test_a_deactivated_user_is_not_notified(crm_app, clean_slate):
    with crm_app.app_context():
        gone = User(username='nd_gone', email='nd_gone@test.local', name='Left The Company',
                    role='payment_recovery', is_active=False)
        gone.set_password('pw123456')
        db.session.add(gone)
        db.session.commit()

        NotificationService().notify_payment_received(PaymentRecovery.query.first(), 500.0)

        assert 'nd_gone' not in delivered()

        db.session.delete(User.query.filter_by(username='nd_gone').one())
        db.session.commit()


def test_every_notification_is_addressed_by_name(crm_app, clean_slate):
    """The software is meant to feel like it is talking to whoever is looking
    at it."""
    with crm_app.app_context():
        po = PurchaseOrder.query.filter_by(po_number='PO-ND-001').one()
        service = NotificationService()
        service.notify_completion(po)
        service.notify_technician_assigned(po, 'TECH SALMAN')

        for username, notes in delivered().items():
            person = User.query.filter_by(username=username).one()
            for note in notes:
                assert person.name in note.title, f'{note.title} is addressed to nobody'


def test_a_notification_failing_never_breaks_what_raised_it(crm_app, clean_slate):
    """Creating the PO matters more than telling someone about it."""
    with crm_app.app_context():
        service = NotificationService()

        class Broken:
            po_number = 'PO-BROKEN'
            id = 1

            def __getattr__(self, name):
                raise RuntimeError('this object is broken')

        service.notify_completion(Broken())
        service.notify_technician_assigned(Broken(), 'TECH SALMAN')

        # Nothing raised, and the session is still usable.
        assert UserNotification.query.count() >= 0


@pytest.mark.parametrize('sender', [
    'notify_completion', 'notify_security_briefing', 'notify_payment_received',
    'notify_technician_assigned', 'notify_vehicle_non_reporting',
    'notify_vehicles_non_reporting', 'send_alert',
])
def test_no_sender_only_emits(sender):
    """An emit on its own is not delivery - nothing in the browser listens
    for those events."""
    import inspect

    source = inspect.getsource(getattr(NotificationService, sender))
    assert 'notify_user' in source, f'{sender} stores nothing'
