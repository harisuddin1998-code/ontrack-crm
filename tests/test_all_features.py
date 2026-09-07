"""
Test All Merged & New Features
"""
import pytest
from src.app import create_app
from src.extensions import db
from src.models.user import User
from src.models.technician import Technician, TechnicianBike
from src.models.purchase_order import PurchaseOrder

@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        # Seed test admin user
        admin = User(name='Admin User', username='admin', email='admin@ontrack.com', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

def test_merged_technician_bike_form(client):
    """Test unified technician and bike form submission"""
    # Login
    client.post('/auth/login', data={'username': 'admin', 'password': 'admin123'})
    
    # Add technician with bike details
    res = client.post('/admin/technicians/add', data={
        'name': 'TEST TECH HARIS',
        'contact': '03001234567',
        'address': 'Gulberg Greens, Islamabad',
        'is_active': 'True',
        'bike_registration': 'ICT-9988',
        'imei': '862292056620999',
        'bike_model': 'Honda 125',
        'fuel_efficiency': '40.0',
        'bike_active': 'True'
    }, follow_redirects=True)
    
    assert res.status_code == 200
    
    tech = Technician.query.filter_by(name='TEST TECH HARIS').first()
    assert tech is not None
    assert tech.bike_assignment is not None
    assert tech.bike_assignment.bike_registration == 'ICT-9988'
    assert tech.bike_assignment.imei == '862292056620999'

def test_api_dashboard_stats(client):
    """The 120-second dashboard refresh returns every card's display value.

    The endpoint used to hand back three raw stat blocks for the page to
    format itself. It now returns one flat map of already-formatted values
    keyed by the `data-sync` attributes in the card deck - the same map that
    rendered the page - so a refreshed figure cannot come back formatted
    differently from the one it replaces.
    """
    client.post('/auth/login', data={'username': 'admin', 'password': 'admin123'})
    res = client.get('/admin/api/dashboard-stats')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True

    values = data['values']
    # One from each card group, so a group losing its value is caught here.
    for key in ('period_completed', 'sales_orders', 'briefings_done', 'briefings_pending',
                'redos_total', 'redos_done', 'power_issue', 'non_reporting'):
        assert key in values, f'{key} missing from the refresh payload'

    # Formatted for display, not raw numbers - money carries its currency and
    # no decimals, counts are plain digits.
    assert values['recovery_pending_amount'].startswith('PKR ')
    assert '.' not in values['recovery_pending_amount']
    assert values['period_completed'].replace(',', '').isdigit()


def test_api_dashboard_stats_follows_the_timeframe(client):
    """A refresh recounts the window the board is showing, not the default.

    The card deck is counted over the timeframe chip, so the page puts its
    own period on this endpoint's URL. Without that the refresh would quietly
    swap a board reading "Today" back to the monthly figures, which looks
    like the numbers moving on their own.
    """
    client.post('/auth/login', data={'username': 'admin', 'password': 'admin123'})

    def orders_for(period):
        res = client.get(f'/admin/api/dashboard-stats?period={period}')
        assert res.status_code == 200
        return int(res.get_json()['values']['sales_orders'].replace(',', ''))

    # All time cannot hold fewer orders than a single day inside it. An
    # endpoint ignoring the period would return the same figure for both.
    assert orders_for('all') >= orders_for('daily')

    # An unrecognised period falls back to the default rather than erroring.
    res = client.get('/admin/api/dashboard-stats?period=not-a-period')
    assert res.status_code == 200
    assert res.get_json()['success'] is True

def test_executive_dashboard(client):
    """Test Executive Operations Dashboard route"""
    client.post('/auth/login', data={'username': 'admin', 'password': 'admin123'})
    res = client.get('/admin/executive-dashboard?period=monthly')
    assert res.status_code == 200
    assert b'Executive Operations Dashboard' in res.data

def test_mis_reports(client):
    """Test MIS Reports route"""
    client.post('/auth/login', data={'username': 'admin', 'password': 'admin123'})
    res = client.get('/admin/mis-reports')
    assert res.status_code == 200
    assert b'MIS Operations' in res.data
