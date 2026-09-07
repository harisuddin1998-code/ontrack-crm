"""
Personal notifications raised by the installation workflow.

The CRM emitted socket.io events for these, but nothing in the browser ever
subscribed, so the notifications went nowhere. They are now stored per user
and raised as desktop notifications from base.html, addressed to the person
by name.

Also covers the security briefing that a completed installation is supposed
to create. That step used to pass PO-derived field names straight into the
`SecurityBriefingData` constructor - names that are read through the model's
BRIEFING_MAPPING and are not columns - so SQLAlchemy rejected it, the error
was swallowed by the completion handler, and the Security wallboard never
populated itself.
"""
import pytest

from src.app import create_app
from src.extensions import db
from src.models.notification import UserNotification
from src.models.purchase_order import PurchaseOrder
from src.models.security import SecurityBriefingData
from src.models.user import User
from src.services.po_service import POService


@pytest.fixture
def crm_app():
    application = create_app('testing')
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


def _user(username, role, name):
    user = User(username=username, email=f'{username}@test.local',
                name=name, role=role, is_active=True)
    user.set_password('pw123456')
    db.session.add(user)
    db.session.commit()
    return user


def _create_po(creator, reg_no='ABC-123'):
    return POService().create_po({
        'owner_name': 'ACME LOGISTICS',
        'owner_contact': '03001234567',
        'reg_no': reg_no,
        'vehicle_make': 'TOYOTA',
        'vehicle_model': 'COROLLA',
        'vehicle_year': '2020',
        'vehicle_color': 'WHITE',
        'engine_number': 'ENG-1',
        'chassis_number': 'CHS-1',
        'sales_person_id': creator.id,
        'vehicle_availability_location': 'LAHORE',
        'rates': 10000.0,
        'amc': 5000.0,
    }, creator.id)


# ------------------------------------------------------- new PO notification

def test_new_po_notifies_each_installer_by_name(crm_app):
    with crm_app.app_context():
        admin = _user('boss', 'admin', 'Boss')
        installer = _user('imran', 'installation', 'Imran')

        _create_po(admin)

        notes = UserNotification.query.filter_by(user_id=installer.id).all()
        assert len(notes) == 1
        assert notes[0].title == 'You have a new PO, Imran'
        assert notes[0].category == UserNotification.CATEGORY_PO


def test_every_installer_gets_their_own_personalised_notification(crm_app):
    with crm_app.app_context():
        admin = _user('boss', 'admin', 'Boss')
        first = _user('imran', 'installation', 'Imran')
        second = _user('sana', 'installation', 'Sana')

        _create_po(admin)

        titles = {n.user_id: n.title for n in UserNotification.query.all()}
        assert titles[first.id] == 'You have a new PO, Imran'
        assert titles[second.id] == 'You have a new PO, Sana'


def test_new_po_notification_carries_the_po_and_a_link(crm_app):
    with crm_app.app_context():
        admin = _user('boss', 'admin', 'Boss')
        installer = _user('imran', 'installation', 'Imran')

        po = _create_po(admin)

        note = UserNotification.query.filter_by(user_id=installer.id).first()
        assert note is not None
        assert po.po_number in note.body
        assert 'ACME LOGISTICS' in note.body
        assert note.url  # clicking it must go somewhere


def test_sales_and_admin_are_not_told_a_PO_is_theirs_to_install(crm_app):
    """This is a work assignment, not an announcement."""
    with crm_app.app_context():
        admin = _user('boss', 'admin', 'Boss')
        seller = _user('sara', 'sales', 'Sara')
        _user('imran', 'installation', 'Imran')

        _create_po(admin)

        assert UserNotification.query.filter_by(user_id=admin.id).count() == 0
        assert UserNotification.query.filter_by(user_id=seller.id).count() == 0


def test_a_PO_is_still_created_when_notification_delivery_fails(crm_app):
    """Telling someone about the PO matters less than the PO existing."""
    from unittest.mock import patch
    from src.services.notification_service import NotificationService

    with crm_app.app_context():
        admin = _user('boss', 'admin', 'Boss')
        _user('imran', 'installation', 'Imran')

        with patch.object(NotificationService, 'notify_users',
                          side_effect=RuntimeError('notification backend down')):
            po = _create_po(admin)

        assert PurchaseOrder.query.get(po.id) is not None


# ------------------------------------------- briefing raised by installation

def test_completing_an_installation_creates_the_security_briefing(crm_app):
    """The exact step that used to fail silently."""
    with crm_app.app_context():
        admin = _user('boss', 'admin', 'Boss')
        po = _create_po(admin)

        POService().update_po(po.id, {'status': 'COMPLETED'}, admin.id)

        briefing = SecurityBriefingData.query.filter_by(po_id=po.id).first()
        assert briefing is not None, (
            'Completing an installation must populate the Security wallboard')
        assert briefing.status == 'PENDING'
        assert briefing.synced_from_po is True


def test_the_briefing_reads_its_vehicle_details_from_the_po(crm_app):
    """One copy of each fact: the briefing does not duplicate PO fields."""
    with crm_app.app_context():
        admin = _user('boss', 'admin', 'Boss')
        po = _create_po(admin, reg_no='XYZ-999')

        POService().update_po(po.id, {'status': 'COMPLETED'}, admin.id)

        briefing = SecurityBriefingData.query.filter_by(po_id=po.id).first()
        assert briefing is not None
        assert briefing.registration_no == 'XYZ-999'
        assert briefing.customer_name == 'ACME LOGISTICS'
        assert briefing.make == 'TOYOTA'


def test_security_officer_is_notified_by_name_of_the_new_briefing(crm_app):
    with crm_app.app_context():
        admin = _user('boss', 'admin', 'Boss')
        officer = _user('ajiya', 'security', 'Ajiya')
        po = _create_po(admin)

        POService().update_po(po.id, {'status': 'COMPLETED'}, admin.id)

        notes = UserNotification.query.filter_by(
            user_id=officer.id,
            category=UserNotification.CATEGORY_SECURITY_BRIEFING).all()
        assert len(notes) == 1
        assert notes[0].title == 'New security briefing for you, Ajiya'
        assert 'ABC-123' in notes[0].body


def test_a_second_completion_does_not_duplicate_the_briefing(crm_app):
    with crm_app.app_context():
        admin = _user('boss', 'admin', 'Boss')
        po = _create_po(admin)

        POService().update_po(po.id, {'status': 'COMPLETED'}, admin.id)
        POService().update_po(po.id, {'status': 'IN_PROGRESS'}, admin.id)
        POService().update_po(po.id, {'status': 'COMPLETED'}, admin.id)

        assert SecurityBriefingData.query.filter_by(po_id=po.id).count() == 1


# ----------------------------------------------------------- the feed itself

def test_the_feed_only_ever_returns_your_own_notifications(crm_app):
    with crm_app.app_context():
        admin = _user('boss', 'admin', 'Boss')
        mine = _user('imran', 'installation', 'Imran')
        theirs = _user('sana', 'installation', 'Sana')
        _create_po(admin)
        mine_id, theirs_id = mine.id, theirs.id

    client = crm_app.test_client()
    client.post('/auth/login', data={'username': 'imran', 'password': 'pw123456'},
                follow_redirects=True)
    payload = client.get('/notifications/feed').get_json()

    assert payload['unread_count'] == 1
    with crm_app.app_context():
        ids = [n['id'] for n in payload['notifications']]
        owners = {UserNotification.query.get(i).user_id for i in ids}
        assert owners == {mine_id}
        assert theirs_id not in owners


def test_marking_delivered_stops_the_same_toast_reappearing(crm_app):
    with crm_app.app_context():
        admin = _user('boss', 'admin', 'Boss')
        _user('imran', 'installation', 'Imran')
        _create_po(admin)

    client = crm_app.test_client()
    client.post('/auth/login', data={'username': 'imran', 'password': 'pw123456'},
                follow_redirects=True)

    first = client.get('/notifications/feed').get_json()
    assert len(first['undelivered']) == 1

    client.post('/notifications/delivered',
                json={'ids': [n['id'] for n in first['undelivered']]})

    second = client.get('/notifications/feed').get_json()
    assert second['undelivered'] == []
    # Still unread - delivered is not the same as read.
    assert second['unread_count'] == 1


def test_marking_read_clears_the_bell(crm_app):
    with crm_app.app_context():
        admin = _user('boss', 'admin', 'Boss')
        _user('imran', 'installation', 'Imran')
        _create_po(admin)

    client = crm_app.test_client()
    client.post('/auth/login', data={'username': 'imran', 'password': 'pw123456'},
                follow_redirects=True)

    client.post('/notifications/read', json={})
    assert client.get('/notifications/feed').get_json()['unread_count'] == 0


def test_the_feed_needs_a_login(crm_app):
    client = crm_app.test_client()
    response = client.get('/notifications/feed')
    assert response.status_code in (302, 401)
