import pytest
from src.app import create_app
from src.services.gps_service import GPSService
from src.models.annual_recovery import AnnualRecoveryClient, AnnualRecoveryVehicle

from src.extensions import db
from src.models.user import User

@pytest.fixture
def client():
    app = create_app('testing')
    app.config['TESTING'] = True
    with app.app_context():
        db.create_all()
        admin = User(name='Admin User', username='admin', email='admin@ontrack.com', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        with app.test_client() as client:
            client.post('/auth/login', data={'username': 'admin', 'password': 'admin123'})
            yield client
        db.session.remove()
        db.drop_all()

def test_annual_recovery_dashboard_rendered(client):
    res = client.get('/annual-recovery/')
    assert res.status_code == 200
    assert b'Annual Recovery Monitoring' in res.data
    assert b'ar-filter-grid' in res.data
    assert b'o_dashboard_cards' in res.data

def test_annual_recovery_api_stats(client):
    res = client.get('/annual-recovery/api/stats')
    assert res.status_code == 200
    data = res.get_json()
    assert 'totalClients' in data
    assert 'totalVehicles' in data

def test_annual_recovery_api_clients(client):
    res = client.get('/annual-recovery/api/clients')
    assert res.status_code == 200
    data = res.get_json()
    assert isinstance(data, list)

def test_gps_service_test_imei(client):
    gps_service = GPSService()
    res = gps_service.test_imei('862292056620214')
    assert isinstance(res, dict)
    assert 'imei' in res

def test_redo_wallboard_lists_activities_linearly(client):
    """The wallboard is one list, not three columns of cards.

    The board grouped by status into three lanes - one of which held every
    row while the other two sat empty - and a card could only carry five
    fields. The same activities are now rows in a single table, which shows
    more per job and puts them in one order.
    """
    res = client.get('/redo/dashboard')
    assert res.status_code == 200
    assert (b'REDO &amp; Rework Activities Wallboard' in res.data
            or b'REDO & Rework Activities Wallboard' in res.data)

    assert b'kanban-column' not in res.data, 'the kanban board is back'
    assert b'o_redo_kanban' not in res.data

    # Every field the cards showed still has a home, plus the ones they
    # could not fit.
    for header in (b'Registration', b'Customer', b'Technician Assigned',
                   b'Raised', b'Aging', b'Status'):
        assert header in res.data, f'{header!r} column missing from the list'

def test_non_reporting_sync_and_dashboard(client):
    res = client.get('/redo/non-reporting')
    assert res.status_code == 200
    assert b'Not Reporting Vehicles' in res.data

def test_complaint_module_flow(client):
    # Test dashboard rendering
    res = client.get('/complaints/')
    assert res.status_code == 200
    assert b'Customer Complaint Management' in res.data

    # Log new complaint
    res_post = client.post('/complaints/new', data={
        'customer_name': 'Pak Cargo Test',
        'customer_contact': '0300-9988776',
        'reg_no': 'LEB-2024-1122',
        'city': 'Lahore',
        'complaint_type': 'GPS_NOT_WORKING',
        'severity': 'HIGH',
        'description': 'Tracking device not responding.',
        'technician_id': 0
    }, follow_redirects=True)
    assert res_post.status_code == 200
    assert b'Pak Cargo Test' in res_post.data or b'CMP-2026' in res_post.data


def test_nr_team_role_and_activities_visibility(client):
    from datetime import datetime, timedelta
    from src.models.user import User
    from src.models.gps import NonReportingVehicle
    from src.models.technician import Technician

    # Create NR Team user and field technician
    nr_user = User(name='NR Specialist', username='nrspec', email='nrspec@ontrack.com', role='redo_technician')
    nr_user.set_password('nr123')
    db.session.add(nr_user)

    field_tech = Technician(name='Tech Zeeshan', contact='0311-1234567', is_active=True)
    db.session.add(field_tech)

    # Create a non-reporting vehicle
    vehicle = NonReportingVehicle(
        registration_no='KHI-9988',
        customer_name='Prime Logistics',
        customer_contact='0300-1122334',
        imei_no='864201009988776',
        sim_no='03001234567',
        status='PENDING',
        dt_tracker=datetime.now() - timedelta(hours=30)
    )
    db.session.add(vehicle)
    db.session.commit()

    # Verify role display is NR Team
    assert nr_user.get_role_display() == 'NR Team'
    assert nr_user.is_nr_team() is True

    # Login as NR Team member
    client.get('/auth/logout', follow_redirects=True)
    login_res = client.post('/auth/login', data={'username': 'nrspec', 'password': 'nr123'}, follow_redirects=True)
    assert login_res.status_code == 200

    # 1. Check Not Reporting Dashboard - role badge shows NR Team
    res_dash = client.get('/redo/non-reporting')
    assert res_dash.status_code == 200
    assert b'NR Team' in res_dash.data
    assert b'Not Reporting System Dashboard' in res_dash.data

    # 2. Click Action button Detail & Follow-up
    res_detail = client.get(f'/redo/non-reporting/{vehicle.id}')
    assert res_detail.status_code == 200
    assert b'NR Team' in res_detail.data
    assert b'Activities History &amp; Workload' in res_detail.data
    assert b'Assign Technician (Dropdown)' in res_detail.data
    # Technician assignment section ONLY shows technicians' names and no other users
    assert b'Tech Zeeshan' in res_detail.data
    assert b'NR Specialist (NR Team' not in res_detail.data
    # Shows Last Conversation section
    assert b'Last Conversation &amp; Interaction History' in res_detail.data

    # 3. Follow up WITHOUT technician assignment -> STAYS in state of Follow-Up
    today_str = datetime.now().strftime('%Y-%m-%d')
    res_post_followup = client.post(f'/redo/non-reporting/{vehicle.id}', data={
        'summary': 'Customer called, vehicle is currently in workshop, follow up needed today.',
        'contact_person': 'Workshop Foreman',
        'contact_number': '0300-1122334',
        'conversation_type': 'PHONE_CALL',
        'contact_outcome': 'Follow-up Required',
        'technician_name': '',
        'follow_up_date': today_str
    }, follow_redirects=True)
    assert res_post_followup.status_code == 200
    assert b'Follow-up saved in Follow-Up state' in res_post_followup.data

    # Verify vehicle stayed in FOLLOW_UP state and NO REDO activity was created
    db.session.refresh(vehicle)
    assert vehicle.status == 'FOLLOW_UP'
    assert vehicle.contact_outcome == 'Follow-up Required'

    # Re-visiting detail page now displays the Last Conversation contextual card
    res_detail_context = client.get(f'/redo/non-reporting/{vehicle.id}')
    assert res_detail_context.status_code == 200
    assert b'Workshop Foreman' in res_detail_context.data
    assert b'vehicle is currently in workshop' in res_detail_context.data

    # 4. Check Follow-Up Module and Reminders on Dashboard
    res_followups = client.get('/redo/followups')
    assert res_followups.status_code == 200
    assert b'NR Team Follow-Up Module &amp; Reminders' in res_followups.data
    assert b'KHI-9988' in res_followups.data
    assert b'Workshop Foreman' in res_followups.data
    assert b'TODAY' in res_followups.data

    # 5. Check Wallboard has Follow-up reminders and cards
    res_board = client.get('/redo/dashboard')
    assert res_board.status_code == 200
    assert b'Follow-up Scheduling Reminders' in res_board.data
    assert b'NR Team Follow-Up Module &amp; Scheduling Reminders' in res_board.data
    assert b'DB Sync Refresh' in res_board.data

    # 6. Follow up WITH technician assigned -> Creates REDO activity & shows in Activities section
    res_post_assigned = client.post(f'/redo/non-reporting/{vehicle.id}', data={
        'summary': 'Owner approved inspection, tech assigned.',
        'contact_person': 'Manager Aslam',
        'contact_number': '0300-1122334',
        'conversation_type': 'PHONE_CALL',
        'contact_outcome': 'Technician Assigned',
        'technician_name': 'Tech Zeeshan',
        'follow_up_date': today_str
    }, follow_redirects=True)
    assert res_post_assigned.status_code == 200
    assert b'REDO' in res_post_assigned.data
    assert b'Tech Zeeshan' in res_post_assigned.data

    # Visible in Activities Wallboard!
    res_activities = client.get('/redo/dashboard')
    assert res_activities.status_code == 200
    assert b'KHI-9988' in res_activities.data
    assert b'Tech Zeeshan' in res_activities.data

    # 7. Test Wallboard Search Bar
    res_search_hit = client.get('/redo/dashboard?search=KHI-9988')
    assert res_search_hit.status_code == 200
    assert b'KHI-9988' in res_search_hit.data

    res_search_miss = client.get('/redo/dashboard?search=NONEXISTENT-REG-123')
    assert res_search_miss.status_code == 200
    assert b'KHI-9988' not in res_search_miss.data

    # 8. Test DB Sync Refresh with redirect back to Activities Wallboard
    res_sync = client.get('/redo/non-reporting/sync?next=/redo/dashboard', follow_redirects=True)
    assert res_sync.status_code == 200
    # Either outcome is correct, and which one happens is a fact about the
    # machine rather than the code: SJ_MIS sits on a private address that the
    # office network can reach and a CI runner cannot. What must hold
    # everywhere is that the user is told which of the two it was - the sync
    # never finishes silently, and never claims a success it did not have.
    # This asserted the success text alone until the sync stopped inventing
    # four vehicles whenever the database was unreachable, which is what used
    # to make that text appear on a runner with no route to it at all.
    assert (b'Live SJ_MIS DB Sync complete' in res_sync.data
            or b'Sync failed' in res_sync.data)
    assert b'REDO &amp; Rework Activities Wallboard' in res_sync.data

