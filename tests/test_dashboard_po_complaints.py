"""
Dashboard synchronisation, PO bulk update, and complaint visibility.

Three things are pinned here, because each one is a rule that is invisible in
the code of any single file and easy to break from another:

  * the Administration and Executive dashboards are one deck of cards, not two
    that happen to agree today;
  * a bulk update never writes anything the user has not been shown first, and
    a blank cell never erases a value;
  * a user sees the complaints they raised and no others, whatever they ask
    for in the URL.
"""
import io
import re
import zipfile

import pytest

from src.app import create_app
from src.extensions import db
from src.models.complaint import Complaint
from src.models.notification import UserNotification
from src.models.purchase_order import PurchaseOrder
from src.models.user import User

WORD_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()

        admin = User(name='Admin User', username='admin',
                     email='admin@ontrack.test', role='admin')
        admin.set_password('pw')
        manager = User(name='Complaint Manager', username='cmgr',
                       email='cmgr@ontrack.test', role='complaint_manager')
        manager.set_password('pw')
        # A user with no complaint privileges at all - the one the visibility
        # rule has to hold for.
        staff = User(name='Sales Staff', username='staff',
                     email='staff@ontrack.test', role='sales')
        staff.set_password('pw')
        db.session.add_all([admin, manager, staff])
        db.session.commit()

        db.session.add(PurchaseOrder(
            po_number='PO-TEST-0001', status='PENDING', owner_name='ACME LOGISTICS',
            owner_contact='0300-1234567', reg_no='LEA-1234', vehicle_make='TOYOTA',
            vehicle_model='HILUX', vehicle_year='2023', vehicle_color='WHITE',
            engine_number='ENG-1', chassis_number='CHS-1',
            vehicle_availability_location='LAHORE', sales_person_id=admin.id,
            rates=125000.75, amc=9000.25))
        db.session.commit()

        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, username):
    return client.post('/auth/login',
                       data={'username': username, 'password': 'pw'},
                       follow_redirects=True)


def synced_values(html):
    """Every `data-sync` key on a page and the value rendered into it."""
    return dict(re.findall(r'data-sync="([a-z0-9_]+)"[^>]*>\s*([^<]*?)\s*<', html))


# ----------------------------------------------------------------------
# Dashboards
# ----------------------------------------------------------------------

def test_admin_and_executive_dashboards_show_identical_figures(client):
    """The Executive dashboard is a replica, not a second implementation."""
    login(client, 'admin')
    admin_deck = synced_values(client.get('/admin/dashboard').get_data(as_text=True))
    exec_deck = synced_values(client.get('/admin/executive-dashboard').get_data(as_text=True))

    assert admin_deck, 'the admin dashboard rendered no synced values at all'
    assert set(admin_deck) == set(exec_deck)
    assert admin_deck == exec_deck


def test_refresh_endpoint_returns_exactly_what_the_page_rendered(client):
    """A refreshed figure must not differ from the one it replaces.

    Both come from one helper, so this catches a card being added to the deck
    without being added to the map - which would leave that card frozen at its
    page-load value for as long as the tab stayed open.
    """
    login(client, 'admin')
    rendered = synced_values(client.get('/admin/dashboard').get_data(as_text=True))
    returned = client.get('/admin/api/dashboard-stats').get_json()['values']

    assert set(rendered) <= set(returned), \
        f'cards never refreshed: {set(rendered) - set(returned)}'
    assert {k: returned[k] for k in rendered} == rendered


def test_dashboards_poll_once_every_120_seconds(client):
    """One mechanism, one period, one timer per page."""
    login(client, 'admin')
    for url in ('/admin/dashboard', '/admin/executive-dashboard'):
        html = client.get(url).get_data(as_text=True)
        assert 'data-sync-seconds="120"' in html
        assert html.count('id="o_live_sync"') == 1, f'{url} has more than one sync loop'
        assert 'Refresh Now' in html, f'{url} lost its manual refresh'


def test_dashboard_money_is_rounded_to_whole_rupees(client):
    """Display only - the underlying figures keep their paisa."""
    login(client, 'admin')
    values = client.get('/admin/api/dashboard-stats').get_json()['values']
    money = {k: v for k, v in values.items() if v.startswith('PKR')}

    assert money, 'no money values on the dashboard to check'
    assert all('.' not in v for v in money.values()), \
        f'decimals left on {[k for k, v in money.items() if "." in v]}'

    # The stored value still has them: 125000.75 + 9000.25 rounds to 134,001.
    assert money['sales_value'] == 'PKR 134,001'
    with client.application.app_context():
        po = PurchaseOrder.query.filter_by(po_number='PO-TEST-0001').one()
        assert po.rates == 125000.75


def test_every_kpi_card_opens_the_records_it_counted(client):
    """A count that opens the wrong list is worse than one that opens nothing."""
    login(client, 'admin')
    html = client.get('/admin/dashboard').get_data(as_text=True)
    links = re.findall(r'<a\s+href="([^"]+)"\s+class="o_stat_card', html)

    assert len(links) >= 17, f'only {len(links)} cards are links'
    # Every PO card is counted over the board's timeframe, so every one of
    # them carries that window into the list it opens. A card scoped to a
    # period that opened the unfiltered list would be the same defect as
    # before, just with a different filter missing.
    po_links = [u for u in links if u.startswith('/admin/pos')]
    assert len(po_links) >= 4, f'only {len(po_links)} purchase order cards'
    assert all('since=' in u for u in po_links), \
        f'a PO card does not carry the timeframe: {po_links}'
    # The three status cards split the orders the first one counts.
    for status in ('COMPLETED', 'IN_PROGRESS', 'PENDING'):
        assert any(f'status={status}' in u for u in po_links), f'no {status} PO card'
    # REDOs Done needs both filters: the wallboard hides completed work by default,
    # so status alone would open an empty page.
    assert any('status=COMPLETED' in u and 'show_completed=true' in u for u in links)
    # Briefings are split into two separate, separately-filtered cards.
    assert any('tab=completed' in u for u in links)
    assert any('tab=pending' in u for u in links)


def test_recent_purchase_orders_section_is_gone(client):
    """Removed from the dashboards; the PO module itself is untouched."""
    login(client, 'admin')
    for url in ('/admin/dashboard', '/admin/executive-dashboard'):
        assert 'Recent Purchase Order' not in client.get(url).get_data(as_text=True)
    assert client.get('/admin/pos').status_code == 200


def test_today_filter_lists_only_todays_orders(client):
    """The PO list can answer the question the card asked it."""
    login(client, 'admin')
    res = client.get('/admin/pos?created=today')
    assert res.status_code == 200
    # Seeded in this session, so it is today's.
    assert 'PO-TEST-0001' in res.get_data(as_text=True)


def test_today_means_today_in_pakistan_not_utc(client):
    """The card and the list both count the Pakistani day.

    Rows are stamped in PKT but SQLite's `current_date` is UTC, so the
    original `date(created_at) = current_date` comparison reported the
    previous day between midnight and 05:00 PKT - the "Today's POs" card
    read zero for the first five hours of every working day. This fails at
    exactly those hours if the two ever diverge again.
    """
    from datetime import timedelta

    from src.repositories.po_repository import POURepository
    from src.utils.timezone import get_current_time

    login(client, 'admin')

    with client.application.app_context():
        start, end = POURepository.today_bounds()
        local_now = get_current_time().replace(tzinfo=None)
        assert start <= local_now < end, \
            f'the day window {start}..{end} does not contain the local now {local_now}'

        # An order raised one minute into the Pakistani day counts as today's.
        db.session.add(PurchaseOrder(
            po_number='PO-TEST-DAWN', status='PENDING', owner_name='DAWN RUN',
            owner_contact='0300-0000000', reg_no='LEA-0001', vehicle_make='TOYOTA',
            vehicle_model='HIACE', vehicle_year='2024', vehicle_color='WHITE',
            engine_number='ENG-2', chassis_number='CHS-2',
            vehicle_availability_location='LAHORE',
            created_at=start + timedelta(minutes=1)))
        # One from just before midnight is yesterday's, whatever UTC says.
        db.session.add(PurchaseOrder(
            po_number='PO-TEST-YESTERDAY', status='PENDING', owner_name='LATE RUN',
            owner_contact='0300-0000001', reg_no='LEA-0002', vehicle_make='TOYOTA',
            vehicle_model='HIACE', vehicle_year='2024', vehicle_color='WHITE',
            engine_number='ENG-3', chassis_number='CHS-3',
            vehicle_availability_location='LAHORE',
            created_at=start - timedelta(minutes=1)))
        db.session.commit()

    listed = client.get('/admin/pos?created=today').get_data(as_text=True)
    assert 'PO-TEST-DAWN' in listed
    assert 'PO-TEST-YESTERDAY' not in listed

    # And the board's own "Today" timeframe agrees with that list: the order
    # raised one minute into the Pakistani day is counted, the one from just
    # before midnight is not.
    values = client.get('/admin/api/dashboard-stats?period=daily').get_json()['values']
    assert values['sales_orders'] == '2'  # the fixture's PO and the dawn one


# ----------------------------------------------------------------------
# PO bulk update
# ----------------------------------------------------------------------

def upload(client, filename, payload):
    return client.post('/admin/pos/bulk-update',
                       data={'file': (io.BytesIO(payload), filename)},
                       content_type='multipart/form-data')


def test_bulk_update_previews_without_writing(client):
    login(client, 'admin')
    body = upload(client, 'u.csv',
                  b'PO Number,Remarks\nPO-TEST-0001,Checked on site\n').get_data(as_text=True)

    assert 'WILL UPDATE' in body
    # Shown in the case it will be stored in, so a re-run reports no change.
    assert 'CHECKED ON SITE' in body
    with client.application.app_context():
        assert PurchaseOrder.query.filter_by(po_number='PO-TEST-0001').one().remarks is None


def test_bulk_update_summary_agrees_with_the_rows(client):
    """The headline counts and the table have to tell the same story.

    They are read from a dict in Jinja, where `summary.update` silently
    resolves to `dict.update` - the built-in method - rather than the count.
    That rendered a confident "0" and an "Apply 0 Update(s)" button above a
    table listing two rows to update, which reads as the feature being
    broken. Asserting on the badges alone did not catch it.
    """
    login(client, 'admin')
    body = upload(client, 'u.csv',
                  b'PO Number,Remarks\n'
                  b'PO-TEST-0001,First change\n'
                  b'PO-TEST-0001,Repeat of the same PO\n'
                  b'PO-NOT-REAL,No such order\n').get_data(as_text=True)

    rows_that_will_update = body.count('WILL UPDATE')
    summary = re.search(
        r'Will Update</span>\s*<div class="o_stat_value">([\d,]+)</div>', body)
    assert summary, 'the Will Update summary card is not on the page'
    assert int(summary.group(1).replace(',', '')) == rows_that_will_update == 1

    assert 'Apply 1 Update(s)' in body


def test_bulk_update_applies_only_the_approved_plan(client):
    login(client, 'admin')
    body = upload(client, 'u.csv',
                  b'PO Number,Remarks,Technician\nPO-TEST-0001,Checked on site,Ali Raza\n'
                  ).get_data(as_text=True)
    plan = re.search(r'name="plan" value="([^"]*)"', body).group(1)

    import html as htmllib
    res = client.post('/admin/pos/bulk-update/apply',
                      data={'plan': htmllib.unescape(plan)}, follow_redirects=True)
    assert res.status_code == 200

    with client.application.app_context():
        po = PurchaseOrder.query.filter_by(po_number='PO-TEST-0001').one()
        assert po.remarks == 'CHECKED ON SITE'
        assert po.technician_assigned == 'ALI RAZA'


def test_bulk_update_blank_cell_never_erases(client):
    """The commonest way an import destroys data, and the one rule that stops it."""
    login(client, 'admin')
    with client.application.app_context():
        po = PurchaseOrder.query.filter_by(po_number='PO-TEST-0001').one()
        po.remarks = 'KEEP ME'
        db.session.commit()

    body = upload(client, 'u.csv',
                  b'PO Number,Remarks,City\nPO-TEST-0001,,LAHORE\n').get_data(as_text=True)
    assert 'remarks' not in body.split('<tbody>')[1]

    plan = re.search(r'name="plan" value="([^"]*)"', body).group(1)
    import html as htmllib
    client.post('/admin/pos/bulk-update/apply',
                data={'plan': htmllib.unescape(plan)}, follow_redirects=True)

    with client.application.app_context():
        po = PurchaseOrder.query.filter_by(po_number='PO-TEST-0001').one()
        assert po.remarks == 'KEEP ME'
        assert po.city == 'LAHORE'


def test_bulk_update_flags_bad_rows_without_stopping(client):
    """Every problem is reported per row, so one bad line does not void the file."""
    login(client, 'admin')
    body = upload(client, 'u.csv', b'PO Number,Status\n'
                                   b'PO-TEST-0001,COMPLETED\n'
                                   b'PO-TEST-0001,PENDING\n'
                                   b'PO-NOT-REAL,PENDING\n'
                                   b',PENDING\n').get_data(as_text=True)
    assert 'DUPLICATE' in body   # the second mention of the same PO
    assert 'NOT FOUND' in body   # no such PO
    assert 'INVALID' in body     # no identifier at all


def test_bulk_update_rejects_a_value_the_column_cannot_hold(client):
    """Checked against the column, not just parsed off the page.

    Deliberately its own file: a repeated identifier is caught before its
    values are looked at, since a row that is not going to be applied is not
    worth validating. Putting a bad value on a duplicated row would test the
    duplicate guard, not this.
    """
    login(client, 'admin')
    body = upload(client, 'u.csv',
                  b'PO Number,Status\nPO-TEST-0001,BANANA\n').get_data(as_text=True)
    assert 'is not a status' in body
    assert 'WILL UPDATE' not in body

    body = upload(client, 'u.csv',
                  b'PO Number,Rates\nPO-TEST-0001,not-a-number\n').get_data(as_text=True)
    assert 'is not a number' in body

    body = upload(client, 'u.csv',
                  b'PO Number,Scheduled Date\nPO-TEST-0001,32/13/2026\n').get_data(as_text=True)
    assert 'is not a date' in body


def test_bulk_update_reads_excel_and_word(client):
    """Same pipeline, three front doors."""
    login(client, 'admin')

    from openpyxl import Workbook
    wb = Workbook()
    wb.active.append(['PO Number', 'Remarks'])
    wb.active.append(['PO-TEST-0001', 'From Excel'])
    buf = io.BytesIO()
    wb.save(buf)
    assert 'FROM EXCEL' in upload(client, 'u.xlsx', buf.getvalue()).get_data(as_text=True)

    def cell(text):
        return f'<w:tc><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>'

    doc = (f'<?xml version="1.0"?><w:document xmlns:w="{WORD_NS}"><w:body><w:tbl>'
           f'<w:tr>{cell("PO Number")}{cell("Remarks")}</w:tr>'
           f'<w:tr>{cell("PO-TEST-0001")}{cell("From Word")}</w:tr>'
           f'</w:tbl></w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('word/document.xml', doc)
    assert 'FROM WORD' in upload(client, 'u.docx', buf.getvalue()).get_data(as_text=True)


def test_bulk_update_rejects_an_unsupported_file(client):
    login(client, 'admin')
    assert 'Supported types are' in upload(client, 'notes.pdf', b'%PDF-1.4').get_data(as_text=True)


# ----------------------------------------------------------------------
# Complaints
# ----------------------------------------------------------------------

def raise_complaint(client, description='Device stopped reporting.'):
    return client.post('/complaints/new', data={
        'customer_name': 'ACME LOGISTICS', 'customer_contact': '0300-1234567',
        'reg_no': 'LEA-1234', 'city': 'LAHORE', 'complaint_type': 'GPS_NOT_WORKING',
        'severity': 'HIGH', 'description': description, 'technician_id': 0,
    }, follow_redirects=True)


def test_a_user_sees_only_their_own_complaints(client):
    """The scoping is the query, so no URL widens it."""
    login(client, 'staff')
    raise_complaint(client, 'Raised by staff.')
    client.get('/auth/logout', follow_redirects=True)

    login(client, 'admin')
    raise_complaint(client, 'Raised by admin.')
    client.get('/auth/logout', follow_redirects=True)

    login(client, 'staff')
    html = client.get('/complaints/my').get_data(as_text=True)
    assert 'Raised by staff.' in html
    assert 'Raised by admin.' not in html

    # And the manager's board is not reachable at all.
    assert client.get('/complaints/').status_code in (302, 403)


def test_manager_and_admin_both_see_every_complaint(client):
    login(client, 'staff')
    raise_complaint(client, 'Raised by staff.')
    client.get('/auth/logout', follow_redirects=True)

    with client.application.app_context():
        ticket_no = Complaint.query.order_by(Complaint.id.desc()).first().ticket_no

    # The board is a list of tickets, so a ticket being on it means its
    # number is on it - the description is read on the ticket itself.
    for username in ('cmgr', 'admin'):
        login(client, username)
        html = client.get('/complaints/').get_data(as_text=True)
        assert ticket_no in html, f'{username} cannot see the ticket'
        assert 'ACME LOGISTICS' in html, f'{username} cannot see the customer'
        client.get('/auth/logout', follow_redirects=True)


def test_manager_and_admin_read_the_same_figures(client):
    """Requirement: the manager's board stays in step with the administrator's."""
    login(client, 'staff')
    raise_complaint(client)
    client.get('/auth/logout', follow_redirects=True)

    login(client, 'cmgr')
    manager = client.get('/complaints/api/sync').get_json()['values']
    client.get('/auth/logout', follow_redirects=True)
    login(client, 'admin')
    administrator = client.get('/complaints/api/sync').get_json()['values']

    assert manager == administrator


def test_raising_a_complaint_notifies_managers_and_admins(client):
    login(client, 'staff')
    raise_complaint(client)

    with client.application.app_context():
        ticket = Complaint.query.order_by(Complaint.id.desc()).first()
        notes = UserNotification.query.filter_by(
            category=UserNotification.CATEGORY_COMPLAINT).all()
        told = {n.user_id for n in notes}

        staff = User.query.filter_by(username='staff').one()
        manager = User.query.filter_by(username='cmgr').one()
        admin = User.query.filter_by(username='admin').one()

        assert manager.id in told
        assert admin.id in told
        assert staff.id not in told, 'the raiser was notified of their own ticket'

        body = next(n for n in notes if n.user_id == manager.id)
        assert ticket.ticket_no in body.title
        assert 'ACME LOGISTICS' in body.body
        assert 'OPEN' in body.body


def test_resolving_notifies_the_raiser_exactly_once(client):
    """One resolution, one notice - re-saving the form must not send another."""
    login(client, 'staff')
    raise_complaint(client)
    client.get('/auth/logout', follow_redirects=True)

    with client.application.app_context():
        ticket_id = Complaint.query.order_by(Complaint.id.desc()).first().id
        staff_id = User.query.filter_by(username='staff').one().id

    login(client, 'cmgr')
    for notes in ('Relay re-calibrated on site.', 'Relay re-calibrated on site. (typo)'):
        client.post(f'/complaints/{ticket_id}',
                    data={'status': 'RESOLVED', 'resolution_notes': notes},
                    follow_redirects=True)

    with client.application.app_context():
        resolution_notices = [
            n for n in UserNotification.query.filter_by(
                user_id=staff_id, category=UserNotification.CATEGORY_COMPLAINT).all()
            if 'resolved' in n.title.lower()]
        assert len(resolution_notices) == 1, \
            f'{len(resolution_notices)} resolution notices for one resolution'
        assert 'RESOLVED' in resolution_notices[0].body
        assert 'calibrated' in resolution_notices[0].body


def test_a_resolution_reaches_the_raisers_board_without_a_reload(client):
    """What the 120-second loop on the user's wallboard picks up."""
    login(client, 'staff')
    raise_complaint(client)
    with client.application.app_context():
        ticket_id = Complaint.query.order_by(Complaint.id.desc()).first().id

    before = client.get('/complaints/my/api/sync').get_json()['values']
    assert before[f'ticket_{ticket_id}_status'] == 'OPEN'
    client.get('/auth/logout', follow_redirects=True)

    login(client, 'cmgr')
    client.post(f'/complaints/{ticket_id}',
                data={'status': 'RESOLVED', 'resolution_notes': 'Fixed on site.'},
                follow_redirects=True)
    client.get('/auth/logout', follow_redirects=True)

    login(client, 'staff')
    after = client.get('/complaints/my/api/sync').get_json()['values']
    assert after[f'ticket_{ticket_id}_status'] == 'RESOLVED'
    assert 'Fixed on site.' in after[f'ticket_{ticket_id}_resolution']
    assert after[f'ticket_{ticket_id}_resolved_at'] != '—'


def test_user_complaint_counts_are_scoped_to_that_user(client):
    """Their wallboard counts their tickets, not everyone's."""
    login(client, 'admin')
    raise_complaint(client, 'Admin ticket one.')
    raise_complaint(client, 'Admin ticket two.')
    client.get('/auth/logout', follow_redirects=True)

    login(client, 'staff')
    raise_complaint(client, 'Staff ticket.')
    values = client.get('/complaints/my/api/sync').get_json()['values']
    assert values['c_total'] == '1'

    client.get('/auth/logout', follow_redirects=True)
    login(client, 'admin')
    assert client.get('/complaints/api/sync').get_json()['values']['c_total'] == '3'
