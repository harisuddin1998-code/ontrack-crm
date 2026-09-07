"""
Sheet scoping in Annual Recovery.

A recovery officer works the sheets assigned to them and must see nothing
from anyone else's. The vehicle rows were already scoped - but a client can
own vehicles across several sheets, and the totals printed above those rows
were read from the client record, which sums every vehicle the client has on
every sheet. So the officer saw their own three rows under a header quoting a
figure that included sheets they have no access to, and a supervisor filtering
to one sheet saw a header that ignored the filter.

The rule these tests hold to: the header and the rows underneath it are
computed from one and the same list of vehicles.
"""
import pytest

from src.app import create_app
from src.extensions import db
from src.models.annual_recovery import (
    AnnualRecoveryClient, AnnualRecoveryVehicle)
from src.models.user import User


@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()

        supervisor = User(name='Supervisor', username='super',
                          email='super@ontrack.test', role='admin')
        supervisor.set_password('pw')
        north = User(name='North Officer', username='north',
                     email='north@ontrack.test', role='recovery_officer')
        north.set_password('pw')
        south = User(name='South Officer', username='south',
                     email='south@ontrack.test', role='recovery_officer')
        south.set_password('pw')
        db.session.add_all([supervisor, north, south])
        db.session.flush()

        # One client whose vehicles straddle two sheets owned by two officers -
        # the case the client-level totals got wrong.
        client_row = AnnualRecoveryClient(
            name='ACME LOGISTICS', cell1='0300-1234567', employee_name='',
            total_amc_charges=30000.0, total_recovered=12000.0, total_lost=0.0)
        db.session.add(client_row)
        db.session.flush()

        def vehicle(reg, sheet, owner, amc, recovered, status='PENDING'):
            return AnnualRecoveryVehicle(
                client_id=client_row.id, reg_no=reg, sheet_name=sheet,
                assigned_to=owner.id, amc_charges=amc, recovered_amount=recovered,
                status=status, installation_date='2024-01-01',
                installation_year='2024')

        db.session.add_all([
            # NORTH sheet: 10,000 AMC, 4,000 recovered -> 6,000 outstanding
            vehicle('LEA-0001', 'NORTH', north, 6000.0, 2000.0),
            vehicle('LEA-0002', 'NORTH', north, 4000.0, 2000.0),
            # SOUTH sheet: 20,000 AMC, 8,000 recovered - none of North's business
            vehicle('KHI-0001', 'SOUTH', south, 20000.0, 8000.0),
        ])
        db.session.commit()

        yield app
        db.session.remove()
        db.drop_all()


def login(app, username):
    c = app.test_client()
    c.post('/auth/login', data={'username': username, 'password': 'pw'},
           follow_redirects=True)
    return c


def clients(client, **params):
    res = client.get('/annual-recovery/api/clients', query_string=params)
    assert res.status_code == 200
    return res.get_json()


def test_officer_sees_only_their_own_sheet_rows(app):
    c = login(app, 'north')
    payload = clients(c)

    assert len(payload) == 1
    regs = {v['regNo'] for v in payload[0]['vehicles']}
    assert regs == {'LEA-0001', 'LEA-0002'}, f'North can see {regs}'


def test_officer_totals_exclude_other_officers_sheets(app):
    """The header must not quote money from a sheet the officer cannot open."""
    c = login(app, 'north')
    card = clients(c)[0]

    assert card['totalAmcCharges'] == 10000.0, (
        f"header says {card['totalAmcCharges']} - the client's whole book is "
        '30,000, of which 20,000 is on South\'s sheet')
    assert card['totalRecovered'] == 4000.0
    assert card['outstanding'] == 6000.0


def test_header_totals_equal_the_rows_beneath_them(app):
    """Whatever the scope, the summary is the sum of what is displayed."""
    for username in ('north', 'south', 'super'):
        c = login(app, username)
        for card in clients(c):
            rows = card['vehicles']
            assert card['totalAmcCharges'] == pytest.approx(
                sum(v['amcCharges'] for v in rows)), f'{username}: AMC mismatch'
            assert card['totalRecovered'] == pytest.approx(
                sum(v['recoveredAmount'] for v in rows)), f'{username}: recovered mismatch'


def test_supervisor_sheet_filter_rescopes_the_header(app):
    """An admin filtering to one sheet gets that sheet's figures, not the book's."""
    c = login(app, 'super')

    unfiltered = clients(c)[0]
    assert unfiltered['totalAmcCharges'] == 30000.0, 'admin should see the whole book'

    north_only = clients(c, sheet='NORTH')[0]
    assert north_only['totalAmcCharges'] == 10000.0
    assert north_only['totalRecovered'] == 4000.0
    assert {v['regNo'] for v in north_only['vehicles']} == {'LEA-0001', 'LEA-0002'}


def test_officer_cannot_reach_another_sheet_by_asking_for_it(app):
    """Filters narrow the officer's scope; they never widen it."""
    c = login(app, 'north')

    assert clients(c, sheet='SOUTH') == []

    # Nor by naming the other officer in the assigned-user filter.
    with app.app_context():
        south_id = User.query.filter_by(username='south').one().id
    assert clients(c, assigned=str(south_id)) == []


def test_stat_cards_follow_the_same_scope(app):
    """The figures at the top of the page obey assignment too."""
    c = login(app, 'north')
    stats = c.get('/annual-recovery/api/stats').get_json()
    assert stats['totalAmcCharges'] == 10000.0
    assert stats['totalVehicles'] == 2
    assert stats['sheets'] == ['NORTH'], f"North's dropdown offers {stats['sheets']}"
