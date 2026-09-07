"""Tests for the Executive role: organization-wide data and dashboard visibility,
full CRUD for complaints and suggestions, and strict write restriction on all other modules.
"""
import pytest
from src.app import create_app, ROLE_LANDING_PAGES
from src.extensions import db
from src.models.user import User
from src.models.complaint import Complaint
from src.models.suggestion import Suggestion
from src.models.technician import Technician


@pytest.fixture
def app_and_users():
    app = create_app('testing')
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False

    with app.app_context():
        db.create_all()

        admin = User(name='Admin User', username='admin',
                     email='admin@ontrack.com', role='admin')
        admin.set_password('admin123')

        executive = User(name='Executive User', username='exec',
                         email='exec@ontrack.com', role='executive')
        executive.set_password('exec123')

        sales = User(name='Sales User', username='salesperson',
                     email='sales@ontrack.com', role='sales')
        sales.set_password('sales123')

        tech = Technician(name='Karachi Tech 1', contact='03001234567', is_active=True)

        db.session.add_all([admin, executive, sales, tech])
        db.session.commit()

        yield app, admin, executive, sales, tech

        db.session.remove()
        db.drop_all()


def test_executive_model_attributes(app_and_users):
    """Verify role constants, helpers, display names, and landing page mapping."""
    app, admin, executive, sales, tech = app_and_users

    assert User.ROLE_EXECUTIVE == 'executive'
    assert 'executive' in User.ROLES

    assert executive.is_executive() is True
    assert admin.is_executive() is False
    assert sales.is_executive() is False

    assert executive.can_manage_suggestions() is True
    assert executive.get_role_display() == 'Executive'

    assert ROLE_LANDING_PAGES.get('executive') == 'admin.executive_dashboard'


def test_executive_dashboard_and_read_access(app_and_users):
    """Verify executive can access all dashboards and listings across all modules."""
    app, admin, executive, sales, tech = app_and_users

    with app.test_client() as client:
        # Sign in as executive
        resp = client.post('/auth/login', data={'username': 'exec', 'password': 'exec123'}, follow_redirects=True)
        assert resp.status_code == 200

        read_endpoints = [
            '/admin/executive-dashboard',
            '/admin/dashboard',
            '/admin/pos',
            '/admin/installation-queue',
            '/admin/fuel-invoices',
            '/admin/mis-reports',
            '/sales/dashboard',
            '/installation/dashboard',
            '/removal/dashboard',
            '/removal/transfer',
            '/removal/retained',
            '/payment/dashboard',
            '/payment/list',
            '/payment/installation-recovery',
            '/annual-recovery/',
            '/annual-recovery/api/stats',
            '/live-amc/dashboard',
            '/live-amc/database-recoveries',
            '/inventory/dashboard',
            '/inventory/stock',
            '/redo/dashboard',
            '/redo/records',
            '/redo/non-reporting',
            '/redo/non-reporting/corporate',
            '/redo/followups',
            '/redo/reports/followup',
            '/redo/reports/device-changes',
            '/security/dashboard',
            '/security/briefings',
        ]

        for ep in read_endpoints:
            r = client.get(ep)
            assert r.status_code == 200, f"Expected 200 for executive on {ep}, got {r.status_code}"


def test_executive_complaints_crud(app_and_users):
    """Verify executive has full CRUD functionality on Complaints."""
    app, admin, executive, sales, tech = app_and_users

    with app.test_client() as client:
        client.post('/auth/login', data={'username': 'exec', 'password': 'exec123'})

        # 1. View complaints dashboard
        r = client.get('/complaints/')
        assert r.status_code == 200

        # 2. Create complaint ticket (new)
        post_data = {
            'customer_name': 'Test Corp',
            'customer_contact': '03009998877',
            'reg_no': 'ABC-1234',
            'city': 'Karachi',
            'vehicle_location': 'Clifton',
            'complaint_type': 'GPS_NOT_WORKING',
            'severity': 'HIGH',
            'description': 'Device stopped pinging.',
            'technician_id': 0,
        }
        r = client.post('/complaints/new', data=post_data, follow_redirects=False)
        assert r.status_code == 302
        assert '/complaints/' in r.headers['Location']

        complaint = Complaint.query.filter_by(reg_no='ABC-1234').first()
        assert complaint is not None
        assert complaint.status == 'OPEN'

        # 3. Assign technician
        r = client.post(f'/complaints/{complaint.id}/assign', data={'technician_id': tech.id}, follow_redirects=True)
        assert r.status_code == 200
        db.session.refresh(complaint)
        assert complaint.status == 'IN_PROGRESS'
        assert complaint.technician_id == tech.id

        # 4. View detail and resolve
        r = client.get(f'/complaints/{complaint.id}')
        assert r.status_code == 200

        resolve_data = {
            'status': 'RESOLVED',
            'resolution_notes': 'Fixed wiring harness.',
        }
        r = client.post(f'/complaints/{complaint.id}', data=resolve_data, follow_redirects=True)
        assert r.status_code == 200
        db.session.refresh(complaint)
        assert complaint.status == 'RESOLVED'
        assert complaint.resolution_notes == 'Fixed wiring harness.'


def test_executive_suggestions_crud(app_and_users):
    """Verify executive has full CRUD functionality on Suggestions."""
    app, admin, executive, sales, tech = app_and_users

    with app.test_client() as client:
        client.post('/auth/login', data={'username': 'exec', 'password': 'exec123'})

        # 1. View wallboard
        r = client.get('/suggestions/wallboard')
        assert r.status_code == 200

        # 2. Create a suggestion
        r = client.post('/suggestions/new', data={
            'title': 'Add Export to PDF button',
            'area': 'Reporting',
            'description': 'It would help if reports could be exported with one click.',
        }, follow_redirects=True)
        assert r.status_code == 200

        suggestion = Suggestion.query.filter_by(title='Add Export to PDF button').first()
        assert suggestion is not None
        assert suggestion.status == Suggestion.STATUS_NEW

        # 3. Reply to suggestion
        r = client.post(f'/suggestions/{suggestion.id}/reply', data={
            'body': 'Executive triage: We are investigating this feature.',
        }, follow_redirects=True)
        assert r.status_code == 200

        # 4. Update status on wallboard
        r = client.post(f'/suggestions/{suggestion.id}/status', data={
            'status': Suggestion.STATUS_IN_PROGRESS,
            'remarks': 'Work scheduled for next sprint.',
        }, follow_redirects=True)
        assert r.status_code == 200
        db.session.refresh(suggestion)
        assert suggestion.status == Suggestion.STATUS_IN_PROGRESS


def test_executive_write_restrictions(app_and_users):
    """Verify executive is blocked from mutating operational data and admin settings."""
    app, admin, executive, sales, tech = app_and_users

    with app.test_client() as client:
        client.post('/auth/login', data={'username': 'exec', 'password': 'exec123'})

        # Cannot access Admin Settings (users, petrol rates, etc.)
        r = client.get('/admin/users', follow_redirects=False)
        assert r.status_code in (302, 403)
        if r.status_code == 302:
            assert 'unauthorized' in r.headers['Location'] or 'login' in r.headers['Location']

        r = client.get('/admin/petrol-rates', follow_redirects=False)
        assert r.status_code in (302, 403)

        # Cannot create Purchase Orders (sales.new_po)
        r = client.get('/sales/new', follow_redirects=False)
        assert r.status_code in (302, 403)

        r = client.post('/sales/new', data={'owner_name': 'Test'}, follow_redirects=False)
        assert r.status_code in (302, 403)

        # Cannot update installation PO
        r = client.post('/installation/po/1', data={}, follow_redirects=False)
        assert r.status_code in (302, 403)

        # Cannot flag vehicle for removal
        r = client.post('/removal/flag', data={}, follow_redirects=False)
        assert r.status_code in (302, 403)

        # Cannot record device recovery payment
        r = client.post('/payment/installation-recovery/1/record-payment', data={}, follow_redirects=False)
        assert r.status_code in (302, 403)

        # Cannot upload annual recovery sheet
        r = client.post('/annual-recovery/api/upload-excel', data={}, follow_redirects=False)
        assert r.status_code in (302, 403)


def test_executive_sidebar_navigation(app_and_users):
    """Verify sidebar in base.html renders operational dashboards for executive and hides Settings."""
    app, admin, executive, sales, tech = app_and_users

    with app.test_client() as client:
        client.post('/auth/login', data={'username': 'exec', 'password': 'exec123'})
        r = client.get('/admin/executive-dashboard')
        assert r.status_code == 200
        html = r.data.decode('utf-8')

        # Check navigation groups visible for executive
        assert 'Dashboards' in html
        assert 'Executive OPS' in html
        assert 'Administration' in html
        assert 'Sales Menu' in html
        assert 'Customer Support' in html
        assert 'Complaints & Tickets' in html
        assert 'Suggestions Wallboard' in html
        assert 'AMC / Annual Recovery' in html
        assert 'Inventory' in html
        assert 'REDO' in html
        assert 'Removal' in html

        # Check Settings group is hidden for executive
        assert '<span>Settings</span>' not in html
        assert '/admin/users' not in html
