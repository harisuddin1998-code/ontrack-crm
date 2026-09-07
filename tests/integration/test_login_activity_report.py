"""
The login and logout report.

Sign-ins and sign-outs are written to the activity log by the auth service;
the report reads those two actions back out of it. The value of the thing is
that it is complete, so these tests are mostly about the ways it could
quietly stop being: an event written under a different name, a path that
does not record at all, or a user who never appears because they never
signed in.
"""
import pytest

from src.app import create_app
from src.extensions import db
from src.models.activity import ActivityLog
from src.models.user import User
from src.services.auth_service import ACTION_LOGIN, ACTION_LOGOUT
from src.web.admin import MIS_REPORTS_BY_SLUG, _report_login_activity
from src.utils.date_ranges import parse_range


@pytest.fixture
def crm_app():
    application = create_app('testing')
    application.config['WTF_CSRF_ENABLED'] = False
    with application.app_context():
        db.create_all()

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()


def _user(crm_app, username, role='sales', is_active=True):
    with crm_app.app_context():
        user = User(username=username, email=f'{username}@test.local',
                    name=username.title(), role=role, is_active=is_active)
        user.set_password('pw123456')
        db.session.add(user)
        db.session.commit()
        return user.id


def _sign_in(crm_app, username, ip='10.0.0.7'):
    client = crm_app.test_client()
    client.post('/auth/login', data={'username': username, 'password': 'pw123456'},
                follow_redirects=True, environ_base={'REMOTE_ADDR': ip})
    return client


def _report(crm_app, args=None):
    with crm_app.app_context():
        return _report_login_activity(parse_range(args or {}))


def _tables(built):
    return {table['title']: table for table in built['tables']}


def test_the_report_is_in_the_catalogue():
    """It has to be reachable from the reports section, not just exist."""
    report = MIS_REPORTS_BY_SLUG.get('login-activity')

    assert report is not None
    assert report['view'] == 'admin.mis_report_view'
    assert report['export'] == 'admin.mis_report_export'


def test_signing_in_and_out_is_recorded(crm_app):
    _user(crm_app, 'aimen')
    client = _sign_in(crm_app, 'aimen')
    client.get('/auth/logout', follow_redirects=True)

    with crm_app.app_context():
        actions = [a.action for a in ActivityLog.query.order_by(ActivityLog.id).all()]
        assert actions == [ACTION_LOGIN, ACTION_LOGOUT]

        login = ActivityLog.query.filter_by(action=ACTION_LOGIN).one()
        assert login.ip_address == '10.0.0.7'
        assert login.user.username == 'aimen'


def test_the_api_records_the_same_events(crm_app):
    """One report, both doors - the service records it, not the route."""
    _user(crm_app, 'aimen')
    client = crm_app.test_client()

    client.post('/api/v1/auth/login',
                json={'username': 'aimen', 'password': 'pw123456'})
    client.post('/api/v1/auth/logout')

    with crm_app.app_context():
        actions = [a.action for a in ActivityLog.query.order_by(ActivityLog.id).all()]
        assert actions == [ACTION_LOGIN, ACTION_LOGOUT]


def test_a_failed_login_is_not_a_session(crm_app):
    _user(crm_app, 'aimen')
    client = crm_app.test_client()
    client.post('/auth/login', data={'username': 'aimen', 'password': 'wrong'},
                follow_redirects=True)

    with crm_app.app_context():
        assert ActivityLog.query.count() == 0


def test_the_log_lists_every_event_newest_first(crm_app):
    _user(crm_app, 'aimen')
    client = _sign_in(crm_app, 'aimen')
    client.get('/auth/logout', follow_redirects=True)

    log = _tables(_report(crm_app))['Login and Logout Log']
    assert [r['action'] for r in log['rows']] == ['Logout', 'Login']
    assert log['rows'][0]['username'] == 'aimen'
    assert log['rows'][1]['ip_address'] == '10.0.0.7'


def test_every_user_is_on_the_summary_even_if_they_never_signed_in(crm_app):
    """Somebody who never appeared is what an attendance report is asked about.

    An absent row reads as "no data"; a zero row reads as "did not sign in",
    and those are different facts.
    """
    _user(crm_app, 'aimen')
    _user(crm_app, 'ghost', role='security', is_active=False)
    _sign_in(crm_app, 'aimen')

    summary = _tables(_report(crm_app))['Per User']
    rows = {r['username']: r for r in summary['rows']}

    assert set(rows) == {'aimen', 'ghost'}
    assert rows['aimen']['logins'] == 1
    assert rows['ghost']['logins'] == 0
    assert rows['ghost']['first_login'] == '-'
    assert rows['ghost']['status'] == 'Inactive'


def test_a_session_left_open_shows_as_a_login_with_no_logout(crm_app):
    _user(crm_app, 'rana', role='removal')
    _sign_in(crm_app, 'rana')

    rows = {r['username']: r for r in _tables(_report(crm_app))['Per User']['rows']}
    assert rows['rana']['logins'] == 1
    assert rows['rana']['logouts'] == 0


def test_the_summary_counts_repeat_sessions(crm_app):
    _user(crm_app, 'aimen')
    for _ in range(3):
        client = _sign_in(crm_app, 'aimen')
        client.get('/auth/logout', follow_redirects=True)

    rows = {r['username']: r for r in _tables(_report(crm_app))['Per User']['rows']}
    assert rows['aimen']['logins'] == 3
    assert rows['aimen']['logouts'] == 3


def test_other_activity_is_not_mistaken_for_a_session(crm_app):
    """The log holds PO edits too; only the two session actions belong here."""
    user_id = _user(crm_app, 'aimen')
    with crm_app.app_context():
        ActivityLog.log(user_id=user_id, action='updated_po', details='PO-1')

    built = _report(crm_app)
    assert _tables(built)['Login and Logout Log']['rows'] == []
    rows = {r['username']: r for r in _tables(built)['Per User']['rows']}
    assert rows['aimen']['logins'] == 0


def test_the_period_scopes_the_report(crm_app):
    """The range on the page is the range the figures cover."""
    _user(crm_app, 'aimen')
    _sign_in(crm_app, 'aimen')

    inside = _report(crm_app, {'from': '2020-01-01', 'to': '2099-12-31'})
    outside = _report(crm_app, {'from': '2020-01-01', 'to': '2020-01-31'})

    assert _tables(inside)['Login and Logout Log']['rows'] != []
    assert _tables(outside)['Login and Logout Log']['rows'] == []
    # The roster stays whole; only the counts against it move.
    assert _tables(outside)['Per User']['rows'][0]['logins'] == 0


def test_the_report_page_and_its_workbook_both_open(crm_app):
    admin_id = _user(crm_app, 'boss', role='admin')
    _sign_in(crm_app, 'boss')

    client = crm_app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = str(admin_id)
        session['_fresh'] = True

    page = client.get('/admin/mis-reports/login-activity')
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert 'Per User' in body and 'Login and Logout Log' in body

    export = client.get('/admin/mis-reports/login-activity/export')
    assert export.status_code == 200
    assert '.xlsx' in export.headers.get('Content-Disposition', '')
