"""The management distribution is data, not a constant in the code.

Changing who receives the month-end pack used to mean a deployment. It is now
a Settings screen backed by `report_recipients`, with the old constant kept as
the seed and as the fallback - because the failure that matters here is the
quiet one: a month-end run that goes to nobody and is only noticed when
someone asks where their report is.
"""
import pytest

from src.app import create_app
from src.extensions import db
from src.models.report_recipient import ReportRecipient
from src.models.user import User
from src.services.email_service import SENIOR_MANAGEMENT_RECIPIENTS, EmailService


@pytest.fixture
def client():
    app = create_app('testing')
    app.config['TESTING'] = True
    with app.app_context():
        db.create_all()
        admin = User(name='Admin User', username='admin',
                     email='admin@ontrack.com', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        with app.test_client() as test_client:
            test_client.post('/auth/login',
                             data={'username': 'admin', 'password': 'admin123'})
            yield test_client
        db.session.remove()
        db.drop_all()


def test_settings_page_seeds_the_built_in_list(client):
    response = client.get('/admin/report-recipients')
    assert response.status_code == 200

    body = response.data.decode()
    for address in SENIOR_MANAGEMENT_RECIPIENTS:
        assert address in body, f'{address} missing from the settings page'
    assert ReportRecipient.query.count() == len(SENIOR_MANAGEMENT_RECIPIENTS)


def test_seeding_does_not_undo_a_removal(client):
    """Re-adding the defaults on every page load would put back whoever the
    administrator just took off."""
    client.get('/admin/report-recipients')

    removed = ReportRecipient.query.first()
    removed_email = removed.email
    db.session.delete(removed)
    db.session.commit()

    client.get('/admin/report-recipients')
    assert ReportRecipient.query.filter_by(email=removed_email).first() is None


def test_adding_an_address_puts_it_on_the_distribution(client):
    client.get('/admin/report-recipients')

    client.post('/admin/report-recipients/add',
                data={'email': 'New.Person@On-Tracking.com', 'name': 'New Person'},
                follow_redirects=True)

    # Stored lowercase, so the same address cannot be added twice in
    # different case.
    assert 'new.person@on-tracking.com' in ReportRecipient.active_emails()


def test_re_adding_a_paused_address_reactivates_it(client):
    client.get('/admin/report-recipients')
    row = ReportRecipient.query.first()
    row.is_active = False
    db.session.commit()

    client.post('/admin/report-recipients/add', data={'email': row.email},
                follow_redirects=True)

    assert ReportRecipient.query.filter_by(email=row.email).first().is_active
    assert ReportRecipient.query.filter_by(email=row.email).count() == 1


def test_a_junk_address_is_refused(client):
    client.get('/admin/report-recipients')
    before = ReportRecipient.query.count()

    client.post('/admin/report-recipients/add', data={'email': 'not-an-address'},
                follow_redirects=True)

    assert ReportRecipient.query.count() == before


def test_pausing_and_resuming_keeps_the_record(client):
    client.get('/admin/report-recipients')
    row = ReportRecipient.query.order_by(ReportRecipient.email).first()

    client.post(f'/admin/report-recipients/{row.id}/toggle', follow_redirects=True)
    assert not ReportRecipient.query.get(row.id).is_active

    client.post(f'/admin/report-recipients/{row.id}/toggle', follow_redirects=True)
    assert ReportRecipient.query.get(row.id).is_active


def test_the_last_recipient_cannot_be_removed(client):
    """An empty list silently falls back to the built-in one, which looks
    like the removal did nothing."""
    client.get('/admin/report-recipients')
    rows = ReportRecipient.query.order_by(ReportRecipient.email).all()
    for row in rows[1:]:
        client.post(f'/admin/report-recipients/{row.id}/delete', follow_redirects=True)

    last = ReportRecipient.query.one()
    response = client.post(f'/admin/report-recipients/{last.id}/delete',
                           follow_redirects=True)

    assert ReportRecipient.query.count() == 1, 'the last recipient was removed'
    assert b'last active recipient' in response.data


def test_reports_go_to_the_configured_list(client):
    from unittest.mock import patch

    client.get('/admin/report-recipients')
    for row in ReportRecipient.query.all():
        db.session.delete(row)
    db.session.add(ReportRecipient(email='only.one@on-tracking.com', is_active=True))
    db.session.commit()

    with patch.object(EmailService, 'send_email', return_value=True) as send:
        EmailService().send_restricted_report('Subject', '<p>Body</p>')

    assert send.call_args.kwargs['recipients'] == ['only.one@on-tracking.com']


def test_an_empty_list_falls_back_rather_than_sending_to_nobody(client):
    from unittest.mock import patch

    assert ReportRecipient.query.count() == 0

    with patch.object(EmailService, 'send_email', return_value=True) as send:
        EmailService().send_restricted_report('Subject', '<p>Body</p>')

    assert set(send.call_args.kwargs['recipients']) == set(SENIOR_MANAGEMENT_RECIPIENTS)


def test_the_settings_page_is_admin_only(client):
    """Adding an address here hands someone every management report."""
    staff = User(name='Sales Person', username='seller',
                 email='seller@ontrack.com', role='sales')
    staff.set_password('seller123')
    db.session.add(staff)
    db.session.commit()

    client.get('/auth/logout')
    client.post('/auth/login', data={'username': 'seller', 'password': 'seller123'})

    assert client.get('/admin/report-recipients').status_code in (302, 403)
    assert client.post('/admin/report-recipients/add',
                       data={'email': 'sneaky@example.com'}).status_code in (302, 403)
    assert ReportRecipient.query.filter_by(email='sneaky@example.com').first() is None
