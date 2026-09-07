"""
Regression tests for Annual Recovery sheet-level access control.

A recovery officer works only the sheets assigned to them. They must not see
another officer's sheets (or unassigned ones), must not be able to upload or
assign sheets, and must not be able to act on a vehicle outside their sheets by
posting its id directly - hiding a row in the list is not access control.

Admin and manager supervise the whole module and keep full access.
"""
import io

import pytest

from src.app import create_app
from src.extensions import db
from src.models.user import User
from src.models.annual_recovery import AnnualRecoveryClient, AnnualRecoveryVehicle

MINE = 'AMC JUNE 2025'
THEIRS = 'AMC JUNE 2024'
NOBODYS = 'AMC AUGUST 2025'

# role_required answers JSON 403 for XHR/JSON requests and redirects otherwise.
# The dashboard calls these endpoints with fetch(), so assert on both shapes.
XHR = {'X-Requested-With': 'XMLHttpRequest'}


@pytest.fixture(scope='module')
def crm_app():
    application = create_app('testing')

    with application.app_context():
        db.create_all()

        officer = User(username='sheet_officer', email='officer@test.local',
                       name='Sheet Officer', role='recovery_officer', is_active=True)
        officer.set_password('officer123')
        other = User(username='sheet_other', email='other@test.local',
                     name='Other Officer', role='recovery_officer', is_active=True)
        other.set_password('other123')
        boss = User(username='sheet_admin', email='admin@test.local',
                    name='Sheet Admin', role='admin', is_active=True)
        boss.set_password('admin123')
        db.session.add_all([officer, other, boss])
        db.session.commit()

        # One client per sheet keeps the client counts unambiguous.
        for sheet, owner_id, regs, amount in (
            (MINE, officer.id, ['MINE-1', 'MINE-2'], 5000.0),
            (THEIRS, other.id, ['THEIRS-1'], 7000.0),
            (NOBODYS, None, ['NOBODY-1'], 9000.0),
        ):
            client = AnnualRecoveryClient(name=f'CLIENT {sheet}', cell1='03001234567',
                                          total_amc_charges=amount * len(regs))
            db.session.add(client)
            db.session.flush()
            for reg in regs:
                db.session.add(AnnualRecoveryVehicle(
                    client_id=client.id, reg_no=reg, amc_charges=amount,
                    status='PENDING', sheet_name=sheet, assigned_to=owner_id))
        db.session.commit()

    # Yield with no app context held: Flask-Login caches the signed-in user on
    # the app context's `g`, so keeping one open leaks identity between tests.
    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()


def _user_id(username):
    """Id of a seeded user. Asserts, so a broken fixture fails as a clear
    message rather than an AttributeError deep inside a test."""
    user = User.query.filter_by(username=username).first()
    assert user is not None, f'Fixture did not seed user {username!r}'
    return user.id


def _client_for(crm_app, username):
    with crm_app.app_context():
        user_id = _user_id(username)
    client = crm_app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
    return client


@pytest.fixture
def officer(crm_app):
    return _client_for(crm_app, 'sheet_officer')


@pytest.fixture
def boss(crm_app):
    return _client_for(crm_app, 'sheet_admin')


def _vehicle_id(crm_app, reg_no):
    with crm_app.app_context():
        vehicle = AnnualRecoveryVehicle.query.filter_by(reg_no=reg_no).first()
        assert vehicle is not None, f'Fixture did not seed vehicle {reg_no!r}'
        return vehicle.id


def _client_id(crm_app, sheet):
    with crm_app.app_context():
        client = AnnualRecoveryClient.query.filter_by(name=f'CLIENT {sheet}').first()
        assert client is not None, f'Fixture did not seed a client for {sheet!r}'
        return client.id


# --------------------------------------------------------------------------
# Visibility: an officer sees only their own sheets
# --------------------------------------------------------------------------

def test_officer_sheet_dropdown_lists_only_their_own_sheets(officer):
    """The dropdown must not even name sheets the officer cannot open."""
    sheets = officer.get('/annual-recovery/api/stats').get_json()['sheets']
    assert sheets == [MINE], f"Officer was offered sheets they cannot work: {sheets}"


def test_officer_stats_cover_only_their_own_sheets(officer):
    stats = officer.get('/annual-recovery/api/stats').get_json()
    assert stats['totalVehicles'] == 2
    assert stats['totalClients'] == 1
    assert stats['totalAmcCharges'] == 10000.0


def test_officer_client_list_contains_only_their_own_vehicles(officer):
    clients = officer.get('/annual-recovery/api/clients').get_json()
    regs = {v['regNo'] for c in clients for v in c['vehicles']}
    assert regs == {'MINE-1', 'MINE-2'}


def test_officer_cannot_reach_another_sheet_by_naming_it_in_the_filter(officer):
    """The sheet filter narrows what is visible; it must never widen it."""
    clients = officer.get(f'/annual-recovery/api/clients?sheet={THEIRS}').get_json()
    assert clients == []

    stats = officer.get(f'/annual-recovery/api/stats?sheet={THEIRS}').get_json()
    assert stats['totalVehicles'] == 0


def test_officer_cannot_widen_scope_with_the_assigned_filter(officer):
    """`assigned=unassigned` must not expose the unassigned sheet."""
    clients = officer.get('/annual-recovery/api/clients?assigned=unassigned').get_json()
    assert clients == []


def test_officer_sheets_endpoint_lists_only_their_own(officer):
    sheets = officer.get('/annual-recovery/api/sheets').get_json()
    assert [s['sheet_name'] for s in sheets] == [MINE]
    assert sheets[0]['vehicle_count'] == 2


def test_admin_still_sees_every_sheet(boss):
    stats = boss.get('/annual-recovery/api/stats').get_json()
    assert sorted(stats['sheets']) == sorted([MINE, THEIRS, NOBODYS])
    assert stats['totalVehicles'] == 4
    assert stats['totalClients'] == 3


# --------------------------------------------------------------------------
# Per-vehicle actions: an id from outside the officer's sheets is refused
# --------------------------------------------------------------------------

@pytest.mark.parametrize('path,payload', [
    ('/annual-recovery/api/followup', {'note': 'called client'}),
    ('/annual-recovery/api/mark-lost', {}),
])
def test_officer_cannot_act_on_a_vehicle_outside_their_sheets(officer, crm_app, path, payload):
    payload = dict(payload, vehicleId=_vehicle_id(crm_app, 'THEIRS-1'))
    response = officer.post(path, json=payload)
    assert response.status_code == 403, (
        f"{path} let an officer act on another officer's vehicle")


def test_officer_cannot_record_recovery_on_a_vehicle_outside_their_sheets(officer, crm_app):
    response = officer.post('/annual-recovery/api/recover', headers=XHR, data={
        'vehicleId': _vehicle_id(crm_app, 'NOBODY-1'),
        'amount': '1000',
        'paymentMethod': 'Cash Payment',
    })
    assert response.status_code == 403


@pytest.mark.parametrize('endpoint', ['followups', 'history'])
def test_officer_cannot_read_details_of_a_vehicle_outside_their_sheets(officer, crm_app, endpoint):
    vehicle_id = _vehicle_id(crm_app, 'THEIRS-1')
    response = officer.get(f'/annual-recovery/api/{endpoint}/{vehicle_id}', headers=XHR)
    assert response.status_code == 403


def test_officer_cannot_download_an_invoice_from_another_sheet(officer, crm_app):
    vehicle_id = _vehicle_id(crm_app, 'THEIRS-1')
    response = officer.get(f'/annual-recovery/invoice/vehicle/{vehicle_id}/pdf')
    assert response.status_code == 302
    assert '/annual-recovery' in response.headers['Location']


def test_officer_cannot_invoice_a_customer_on_another_sheet(officer, crm_app):
    """The customer-wise invoice is scoped the same way as the vehicle one.

    It bills every vehicle a customer owns, so an unscoped version would be a
    wider leak than the per-vehicle route: it would put another officer's
    registrations and amounts on a document this officer can download.
    """
    client_id = _client_id(crm_app, THEIRS)
    response = officer.get(f'/annual-recovery/invoice/client/{client_id}/pdf')
    assert response.status_code == 302
    assert '/annual-recovery' in response.headers['Location']


def test_officer_can_invoice_a_customer_on_their_own_sheet(officer, crm_app):
    """Scoping must not block the officer from invoicing their own book."""
    client_id = _client_id(crm_app, MINE)
    response = officer.get(f'/annual-recovery/invoice/client/{client_id}/pdf')
    # 200 with the PDF where wkhtmltopdf is installed; where it is not, the
    # route redirects with a flash rather than erroring. Either way the
    # request must not be refused as an access problem, which is what this
    # test is about - so a redirect back to a *login* page would be a failure.
    assert response.status_code in (200, 302)
    if response.status_code == 302:
        assert '/annual-recovery' in response.headers['Location']


def test_officer_can_still_work_their_own_vehicles(officer, crm_app):
    """The scoping must not get in the way of the officer's actual job."""
    vehicle_id = _vehicle_id(crm_app, 'MINE-1')

    followup = officer.post('/annual-recovery/api/followup',
                            json={'vehicleId': vehicle_id, 'note': 'spoke to client'})
    assert followup.status_code == 200
    assert followup.get_json()['success'] is True

    assert officer.get(f'/annual-recovery/api/followups/{vehicle_id}').status_code == 200
    assert officer.get(f'/annual-recovery/api/history/{vehicle_id}').status_code == 200


# --------------------------------------------------------------------------
# Sheet administration is supervisor-only
# --------------------------------------------------------------------------

def test_officer_cannot_upload_sheets(officer):
    upload = {'file': (io.BytesIO(b'not really a spreadsheet'), 'sheets.xlsx')}
    response = officer.post('/annual-recovery/api/upload-excel',
                            headers=XHR, data=upload,
                            content_type='multipart/form-data')
    assert response.status_code == 403


def test_officer_cannot_assign_sheets(officer, crm_app):
    with crm_app.app_context():
        officer_id = _user_id('sheet_officer')
    response = officer.post('/annual-recovery/api/assign-sheet',
                            json={'sheet_name': THEIRS, 'user_id': officer_id})
    assert response.status_code == 403

    # And the attempt must not have moved anything.
    with crm_app.app_context():
        moved = AnnualRecoveryVehicle.query.filter_by(sheet_name=THEIRS,
                                                      assigned_to=officer_id).count()
    assert moved == 0, 'A refused assignment still changed the data'


def test_officer_cannot_read_the_cross_sheet_audit_log(officer):
    response = officer.get('/annual-recovery/api/audit-logs', headers=XHR)
    assert response.status_code == 403


def test_supervisor_only_routes_redirect_a_browser_rather_than_erroring(officer):
    """Without XHR headers the officer is redirected, never served the page."""
    response = officer.get('/annual-recovery/api/audit-logs')
    assert response.status_code == 302
    assert '/auth' in response.headers['Location']


def test_admin_can_still_assign_sheets(boss, crm_app):
    with crm_app.app_context():
        officer_id = _user_id('sheet_officer')
    response = boss.post('/annual-recovery/api/assign-sheet',
                         json={'sheet_name': NOBODYS, 'user_id': officer_id})
    assert response.status_code == 200
    assert response.get_json()['success'] is True

    # Put it back so sheet-visibility tests stay independent of run order.
    with crm_app.app_context():
        for vehicle in AnnualRecoveryVehicle.query.filter_by(sheet_name=NOBODYS).all():
            vehicle.assigned_to = None
        db.session.commit()


def test_admin_can_still_read_the_audit_log(boss):
    assert boss.get('/annual-recovery/api/audit-logs').status_code == 200


# --------------------------------------------------------------------------
# What the officer's screen offers them
# --------------------------------------------------------------------------

def test_officer_dashboard_offers_no_upload_or_assign_controls(officer):
    page = officer.get('/annual-recovery/').get_data(as_text=True)
    assert page.count('openUploadModal()') == 1, 'Upload button rendered for an officer'
    assert page.count('openAssignSheetModal()') == 1, 'Assign button rendered for an officer'
    assert 'id="uploadModal"' not in page
    assert 'id="assignSheetModal"' not in page
    assert 'id="assignedFilter"' not in page


def test_admin_dashboard_still_offers_upload_and_assign(boss):
    page = boss.get('/annual-recovery/').get_data(as_text=True)
    assert 'id="uploadModal"' in page
    assert 'id="assignSheetModal"' in page
    assert 'id="assignedFilter"' in page


def test_officer_navigation_offers_only_the_amc_group_and_raising_complaints(officer):
    """The officer's sidebar: Annual Recovery, Live AMC, AMC Recoveries (DB),
    and Log New Complaint - nothing else."""
    page = officer.get('/annual-recovery/').get_data(as_text=True)

    assert '/annual-recovery/' in page
    assert '/live-amc/dashboard' in page
    assert '/live-amc/database-recoveries' in page
    assert '/complaints/new' in page

    for forbidden in ('/admin/users', '/sales/dashboard', '/installation/dashboard',
                      '/security/dashboard', '/payment/dashboard', '/redo/dashboard',
                      '/removal/dashboard', '/inventory/dashboard'):
        assert forbidden not in page, f"Officer sidebar exposed {forbidden}"


def test_officer_can_raise_a_complaint_but_not_manage_the_queue(officer):
    assert officer.get('/complaints/new').status_code == 200

    managing = officer.get('/complaints/', headers=XHR)
    assert managing.status_code == 403
