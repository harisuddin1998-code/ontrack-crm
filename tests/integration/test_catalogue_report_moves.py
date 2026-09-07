"""
Device Change, REDO Follow-Up and Technician Performance are catalogue
reports, not separate pages - and Individual Recovery can be run for one
officer.

These three used to have catalogue entries whose `view` jumped out to a
bespoke page, so the MIS index listed them but the catalogue did not actually
render them. They are real catalogue reports now: one period control, one
table style, and an export built from the rows on screen.

The month-end pack is checked here too, because giving those three builders
is exactly what would make the pack attach each of them twice - once by hand
and once from the loop over the catalogue.
"""
from unittest.mock import patch

import pytest

from src.app import create_app
from src.extensions import db
from src.models.user import User
from src.services.email_service import EmailService
from src.web.admin import MIS_REPORTS, MIS_REPORT_BUILDERS, MIS_REPORT_FILTERS

MOVED_SLUGS = ('device-changes', 'redo-followups', 'technician-performance')


@pytest.fixture(scope='module')
def crm_app():
    application = create_app('testing')
    with application.app_context():
        db.create_all()
        admin = User(username='cat_admin', email='cat_admin@test.local',
                     name='Catalogue Admin', role='admin', is_active=True)
        admin.set_password('admin123')
        officer = User(username='cat_officer', email='cat_officer@test.local',
                       name='Recovery Officer One', role='recovery_officer',
                       is_active=True)
        officer.set_password('officer123')
        db.session.add_all([admin, officer])
        db.session.commit()
    yield application


@pytest.fixture
def admin(crm_app):
    client = crm_app.test_client()
    with crm_app.app_context():
        user_id = User.query.filter_by(username='cat_admin').first().id
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
    return client


# --------------------------------------------------------------------------
# The three that moved
# --------------------------------------------------------------------------

@pytest.mark.parametrize('slug', MOVED_SLUGS)
def test_moved_report_is_rendered_by_the_catalogue(slug, admin):
    """Not merely listed on the index - actually rendered by it."""
    report = next(r for r in MIS_REPORTS if r['slug'] == slug)
    assert report['view'] == 'admin.mis_report_view'
    assert report['export'] == 'admin.mis_report_export'
    assert slug in MIS_REPORT_BUILDERS

    response = admin.get(f'/admin/mis-reports/{slug}?from=2020-01-01&to=2030-12-31')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert report['name'] in body
    assert 'o_list_table' in body
    # The catalogue's own period control, not a bespoke one.
    assert 'name="from"' in body and 'name="to"' in body


@pytest.mark.parametrize('slug', MOVED_SLUGS)
def test_moved_report_exports_through_the_catalogue(slug, admin):
    response = admin.get(f'/admin/mis-reports/{slug}/export'
                         '?from=2020-01-01&to=2030-12-31')
    assert response.status_code == 200
    assert 'spreadsheet' in response.headers.get('Content-Type', '')


def test_the_reports_nav_group_no_longer_lists_them(admin):
    """MIS Reports is the one way in, so the nav does not name them again."""
    body = admin.get('/admin/mis-reports').get_data(as_text=True)

    assert 'MIS Reports' in body            # the group still has its entry
    assert 'Fuel Invoices' in body          # and the working screen stays
    # The sidebar renders one o_menu_item per link; none of the three has one.
    for endpoint in ('redo.device_change_report', 'redo.followup_report',
                     'redo.technician_performance_report'):
        route = endpoint.split('.')[-1]
        assert f'o_menu_item" href="/redo/reports/{route}' not in body


# --------------------------------------------------------------------------
# Individual Recovery, user-wise
# --------------------------------------------------------------------------

def test_individual_recovery_is_in_the_catalogue(admin):
    report = next(r for r in MIS_REPORTS if r['slug'] == 'individual-recovery')
    assert report['view'] == 'admin.mis_report_view'
    assert 'individual-recovery' in MIS_REPORT_BUILDERS

    body = admin.get('/admin/mis-reports').get_data(as_text=True)
    assert report['name'] in body


def test_individual_recovery_offers_an_officer_picker(admin):
    body = admin.get('/admin/mis-reports/individual-recovery').get_data(as_text=True)

    assert 'name="user"' in body
    assert MIS_REPORT_FILTERS['individual-recovery']['all_label'] in body
    # The recovery officer seeded above is selectable even with an empty book -
    # a supervisor asking after an idle officer needs to see the empty book.
    assert 'Recovery Officer One' in body
    assert 'Per Officer' in body
    assert 'Recoveries Collected' in body


def test_choosing_an_officer_keeps_the_selection(admin, crm_app):
    with crm_app.app_context():
        officer_id = User.query.filter_by(username='cat_officer').first().id

    body = admin.get('/admin/mis-reports/individual-recovery'
                     f'?user={officer_id}').get_data(as_text=True)
    assert f'value="{officer_id}" selected' in body


@pytest.mark.parametrize('value', ['999999', 'abc', ''])
def test_a_bad_officer_id_does_not_break_the_report(value, admin):
    """The id comes off a query string, so it is whatever was typed."""
    response = admin.get(f'/admin/mis-reports/individual-recovery?user={value}')
    assert response.status_code == 200


def test_individual_recovery_runs_without_a_request(crm_app):
    """The month-end pack builds every report from the scheduler.

    The builder reads the chosen officer off the query string, so it has to
    treat "no request at all" as "no officer chosen" rather than raising.
    """
    from src.utils.date_ranges import parse_range

    with crm_app.app_context():
        built = MIS_REPORT_BUILDERS['individual-recovery'](parse_range({}))
    assert 'tables' in built


# --------------------------------------------------------------------------
# The month-end pack
# --------------------------------------------------------------------------

def test_month_end_pack_attaches_each_report_once(crm_app):
    """Giving the three builders is what would double them up.

    They were attached by hand *and* would now be picked up by the loop over
    the catalogue, sending senior management two copies of each under the
    same name.
    """
    from src.services.mis_export_service import MISExportService

    with crm_app.app_context():
        with patch.object(EmailService, 'send_email', return_value=True) as send:
            MISExportService().email_monthly_report_pack()

        attachments = send.call_args.kwargs['attachments']
        assert len(attachments) == len(MIS_REPORTS)

        names = [a['filename'] for a in attachments]
        assert len(names) == len(set(names)), f'duplicate attachments: {names}'
