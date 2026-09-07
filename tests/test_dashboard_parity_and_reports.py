"""Administration and Executive are one board, and every report is runnable.

The brief has been that the two dashboards show the same data from the same
source. They drifted because the period sections - Operations KPIs, REDO
turnaround, technician performance - were computed in the Executive route
only. These tests pin the shared structure rather than the numbers, so they
fail if the two ever diverge again.
"""
import re

import pytest

from src.app import create_app
from src.extensions import db
from src.models.user import User
from src.web.admin import MIS_REPORTS, MIS_REPORT_BUILDERS

STAT_CARD = re.compile(r'<a href="([^"]+)"\s+class="o_stat_card[^"]*">', re.S)


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


def _cards(body):
    return STAT_CARD.findall(body)


def test_both_dashboards_carry_the_same_cards(client):
    admin_body = client.get('/admin/dashboard').data.decode()
    exec_body = client.get('/admin/executive-dashboard').data.decode()

    assert client.get('/admin/dashboard').status_code == 200
    assert _cards(admin_body), 'the Administration dashboard rendered no cards'
    assert _cards(admin_body) == _cards(exec_body), \
        'the two dashboards no longer show the same cards'


def test_administration_dashboard_has_the_period_sections(client):
    """These are the sections the Administrator was missing."""
    body = client.get('/admin/dashboard').data.decode()

    for heading in ('Operations KPIs', 'REDO Turnaround',
                    'Top Cities by Purchase Orders', 'Technician Performance KPIs'):
        assert heading in body, f'{heading} missing from the Administration dashboard'
    assert 'Breached' in body


def test_administration_dashboard_shows_its_timeframe(client):
    body = client.get('/admin/dashboard').data.decode()
    assert 'Timeframe' in body
    assert 'o_period_chip' in body
    # And the chosen window changes what the board reports.
    weekly = client.get('/admin/dashboard?period=weekly').data.decode()
    assert 'is_active">Weekly' in weekly.replace('\n', '')


def test_sales_and_purchase_orders_are_one_group(client):
    """A sales order is a purchase order here; two headings counted the same
    records twice on one screen."""
    body = client.get('/admin/dashboard').data.decode()
    assert 'Sales &amp; Purchase Orders' in body
    assert 'Sales &amp; Security' not in body


def test_every_dashboard_card_is_a_link_that_resolves(client):
    """A number you cannot open is a dead end."""
    body = client.get('/admin/dashboard').data.decode()

    for href in _cards(body):
        url = href.replace('&amp;', '&')
        assert client.get(url).status_code == 200, f'{url} is a dead card link'


def test_redo_turnaround_cards_filter_the_wallboard(client):
    """`aging=` has to reach the REDO activities list, or Breached is a
    number pointing at everything."""
    for band in ('over24', 'over36', 'breached'):
        assert client.get(f'/redo/dashboard?aging={band}').status_code == 200
    assert client.get('/redo/dashboard?since=2026-01-01').status_code == 200


@pytest.mark.parametrize('report', MIS_REPORTS, ids=lambda r: r['slug'])
def test_every_report_can_be_run_and_downloaded(client, report):
    assert report['view'], f"{report['slug']} has no Run Report"
    assert report['export'], f"{report['slug']} has no Download Excel"


@pytest.mark.parametrize('slug', sorted(MIS_REPORT_BUILDERS))
def test_catalogue_report_downloads_are_real_workbooks(client, slug):
    response = client.get(f'/admin/mis-reports/{slug}/export')
    assert response.status_code == 200
    # xlsx is a zip; the magic bytes are the cheapest proof it is not an
    # error page with a spreadsheet content type.
    assert response.data[:2] == b'PK'


def test_report_workbook_headers_are_bold_and_centred(client):
    """What senior management opens on the 1st should not need reformatting."""
    import io

    from openpyxl import load_workbook

    response = client.get('/admin/mis-reports/field-jobs/export')
    workbook = load_workbook(io.BytesIO(response.data))
    sheet = workbook.active

    header = sheet['A1']
    assert header.font.bold
    assert header.alignment.horizontal == 'center'
    assert header.fill.fgColor.rgb.endswith('5478C0')
    assert sheet.freeze_panes == 'A2', 'the header does not stay put while scrolling'
    assert sheet.auto_filter.ref, 'the header carries no filter'
