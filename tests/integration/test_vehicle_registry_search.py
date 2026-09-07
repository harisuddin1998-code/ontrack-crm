"""
Every vehicle is searchable from the complaint form.

The form searched four local tables, and each of them holds only a slice of
the fleet: vehicles that went offline, vehicles this CRM installed, vehicles
that have been serviced, vehicles on the AMC books. A vehicle whose device
has simply worked since before this CRM existed was in none of them, and was
findable only while SJ_MIS itself answered - a query bounded to a few seconds
that returns nothing at all when the link is down.

`vehicle_registry` is a local dump of SJ_MIS's master roster, refreshed
nightly, and is now a fifth search source. It is read last of all: it is a
machine copy, so it fills in what nobody has typed rather than overriding
what somebody has.
"""
from datetime import datetime

import pytest

from src.app import create_app
from src.extensions import db
from src.models.gps import NonReportingVehicle
from src.models.user import User
from src.models.vehicle_registry import VehicleRegistryEntry
from src.services.vehicle_search_service import VehicleSearchService

SEARCH = '/complaints/api/vehicle-search'
FORM = '/complaints/new'


@pytest.fixture(scope='module')
def crm_app():
    application = create_app('testing')
    application.config['WTF_CSRF_ENABLED'] = False
    with application.app_context():
        db.create_all()

        agent = User(username='vr_agent', email='vr_agent@test.local',
                     name='Search Agent', role='complaint_manager', is_active=True)
        agent.set_password('pw123456')
        boss = User(username='vr_admin', email='vr_admin@test.local',
                    name='Search Admin', role='admin', is_active=True)
        boss.set_password('pw123456')
        db.session.add_all([agent, boss])

        # A vehicle nothing but the roster dump knows about - the case that
        # was unfindable before.
        db.session.add(VehicleRegistryEntry(
            registration_no='ROSTER-1', sj_vehicle_id=8001, client_id=41,
            imei_no='860500000000001', sim_no='923005550001',
            engine_no='ENG-ROSTER-1', chassis_no='CHS-ROSTER-1',
            unit_location='Behind Meter', vehicle_status='Active',
            customer_name='Quietly Working Customer',
            emergency_mobile='0300-5550001', cell1='0321-5550002',
            cell2='0333-5550003', res_phone='042-35550004',
            office_phone='042-35550005', secondary_users='Driver Kamran',
            last_signal_at=datetime.now(), synced_at=datetime.now()))

        # A vehicle both the roster and a staff-entered table know about.
        db.session.add(VehicleRegistryEntry(
            registration_no='SHARED-1', sj_vehicle_id=8002,
            customer_name='Roster Copy Of The Name',
            chassis_no='CHS-FROM-ROSTER', engine_no='ENG-FROM-ROSTER',
            imei_no='860500000000002', synced_at=datetime.now()))
        db.session.add(NonReportingVehicle(
            registration_no='SHARED-1', customer_name='Name Typed By Staff',
            customer_contact='0300-7770001', chassis_no='CHS-TYPED',
            engine_no='ENG-TYPED', imei_no='860500000000099',
            make='Toyota', model='Hilux'))
        db.session.commit()

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def agent(crm_app):
    client = crm_app.test_client()
    with crm_app.app_context():
        user_id = User.query.filter_by(username='vr_agent').first().id
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
    return client


def found(client, term):
    payload = client.get(SEARCH, query_string={'q': term}).get_json()
    return {r['registration_no'] for r in payload['results']}


# --------------------------------------------------------------------------
# A vehicle only the roster knows about
# --------------------------------------------------------------------------

@pytest.mark.parametrize('label,term', [
    ('registration', 'ROSTER-1'),
    ('IMEI', '860500000000001'),
    ('SIM', '923005550001'),
    ('chassis number', 'CHS-ROSTER-1'),
    ('engine number', 'ENG-ROSTER-1'),
    ('emergency mobile', '0300-5550001'),
    ('a second mobile', '0321-5550002'),
    ('the residence line', '042-35550004'),
    ('the office line', '042-35550005'),
])
def test_a_roster_only_vehicle_is_found_by(label, term, agent):
    assert 'ROSTER-1' in found(agent, term), f'not findable by {label}'


@pytest.mark.parametrize('typed', ['0300-5550001', '03005550001', '0300 555 0001'])
def test_a_number_is_found_however_it_is_punctuated(typed, agent):
    assert 'ROSTER-1' in found(agent, typed)


def test_the_record_carries_what_the_form_needs(agent):
    record = [r for r in agent.get(SEARCH, query_string={'q': 'ROSTER-1'}).get_json()['results']
              if r['registration_no'] == 'ROSTER-1'][0]

    assert record['customer_name'] == 'Quietly Working Customer'
    assert record['customer_contact'] == '0300-5550001'
    assert record['imei_no'] == '860500000000001'
    assert record['sim_no'] == '923005550001'
    assert record['chassis_no'] == 'CHS-ROSTER-1'
    assert record['engine_no'] == 'ENG-ROSTER-1'
    assert record['unit_location'] == 'Behind Meter'


def test_it_says_there_is_no_service_history(agent):
    """A vehicle known only from the roster has never been serviced through
    this CRM, and saying "N/A" would leave that ambiguous."""
    record = [r for r in agent.get(SEARCH, query_string={'q': 'ROSTER-1'}).get_json()['results']
              if r['registration_no'] == 'ROSTER-1'][0]

    assert record['last_service_by'] == 'No service recorded (SJ_MIS roster)'


# --------------------------------------------------------------------------
# Staff-entered data still wins
# --------------------------------------------------------------------------

def test_a_typed_name_beats_the_machine_copy(agent):
    record = [r for r in agent.get(SEARCH, query_string={'q': 'SHARED-1'}).get_json()['results']
              if r['registration_no'] == 'SHARED-1'][0]

    assert record['customer_name'] == 'Name Typed By Staff'


@pytest.mark.parametrize('field,expected', [
    ('chassis_no', 'CHS-TYPED'),
    ('engine_no', 'ENG-TYPED'),
    ('imei_no', '860500000000099'),
])
def test_typed_vehicle_details_beat_the_machine_copy(field, expected, agent):
    record = [r for r in agent.get(SEARCH, query_string={'q': 'SHARED-1'}).get_json()['results']
              if r['registration_no'] == 'SHARED-1'][0]

    assert record[field] == expected


def test_the_roster_still_fills_the_gaps(crm_app):
    """The point of reading it last is that it fills in, not overrides."""
    with crm_app.app_context():
        entry = VehicleRegistryEntry(registration_no='GAPS-1',
                                     customer_name='Gap Filler',
                                     unit_location='Under Dashboard',
                                     sim_no='923009990001')
        db.session.add(entry)
        db.session.add(NonReportingVehicle(registration_no='GAPS-1',
                                           customer_name='Gap Filler'))
        db.session.commit()

        record = VehicleSearchService().lookup_by_reg_no('GAPS-1')

    assert record['unit_location'] == 'Under Dashboard'
    assert record['sim_no'] == '923009990001'


def test_a_vehicle_nobody_has_ever_heard_of_returns_nothing(agent):
    assert found(agent, 'NOSUCHVEHICLE') == set()


def test_one_character_is_still_not_a_search(agent):
    """One character matches most of the fleet; the form waits for two."""
    assert agent.get(SEARCH, query_string={'q': 'R'}).get_json()['results'] == []


# --------------------------------------------------------------------------
# Saying what can be searched
# --------------------------------------------------------------------------

def test_the_form_says_how_much_of_the_fleet_it_can_see(agent):
    """"No results" reads the same whether the vehicle is not on the roster
    or the roster has never been copied. The count tells them apart."""
    body = agent.get(FORM).get_data(as_text=True)

    assert 'master roster' in body


def test_only_admins_and_managers_can_refresh_the_roster(agent, crm_app):
    body = agent.get(FORM).get_data(as_text=True)
    assert 'complaints/vehicles/sync' not in body

    assert agent.post('/complaints/vehicles/sync').status_code in (302, 403)

    admin_client = crm_app.test_client()
    with crm_app.app_context():
        admin_id = User.query.filter_by(username='vr_admin').first().id
    with admin_client.session_transaction() as session:
        session['_user_id'] = str(admin_id)
        session['_fresh'] = True

    assert 'complaints/vehicles/sync' in admin_client.get(FORM).get_data(as_text=True)


def test_a_failed_refresh_does_not_lose_what_is_already_there(crm_app):
    """SJ_MIS being unreachable must not empty the local copy - a stale roster
    still finds vehicles, an empty one finds none."""
    admin_client = crm_app.test_client()
    with crm_app.app_context():
        admin_id = User.query.filter_by(username='vr_admin').first().id
        before = VehicleRegistryEntry.query.count()
    with admin_client.session_transaction() as session:
        session['_user_id'] = str(admin_id)
        session['_fresh'] = True

    # No SJ_MIS in the test environment, so this exercises the failure path.
    admin_client.post('/complaints/vehicles/sync', follow_redirects=True)

    with crm_app.app_context():
        assert VehicleRegistryEntry.query.count() == before


# --------------------------------------------------------------------------
# The local dump is the source
# --------------------------------------------------------------------------

def test_a_populated_registry_stops_the_search_calling_out(crm_app, monkeypatch):
    """A registration number matches one vehicle, which is under the result
    limit, which used to send every such search off to SJ_MIS for three
    seconds before answering. With the roster copied locally there is nothing
    left to ask.
    """
    from src.services import vehicle_search_service

    called = []
    monkeypatch.setattr(vehicle_search_service.VehicleSearchService,
                        '_search_sj_mis_live_bounded',
                        lambda self, query, limit: called.append(query) or [])

    with crm_app.app_context():
        results = vehicle_search_service.VehicleSearchService().search('ROSTER-1')

    assert results, 'the vehicle was not found locally'
    assert not called, 'the search went out to SJ_MIS despite having the roster'


def test_an_empty_registry_still_falls_back_to_sj_mis(crm_app, monkeypatch):
    """Day one, before the first sync: the form has to be useful rather than
    empty."""
    from src.services import vehicle_search_service

    called = []
    monkeypatch.setattr(vehicle_search_service.VehicleSearchService,
                        '_search_sj_mis_live_bounded',
                        lambda self, query, limit: called.append(query) or [])

    with crm_app.app_context():
        saved = VehicleRegistryEntry.query.all()
        for row in saved:
            db.session.delete(row)
        db.session.commit()

        vehicle_search_service.VehicleSearchService().search('ANYTHING')

        assert called == ['ANYTHING']

        # Put the roster back for the rest of the module.
        db.session.add(VehicleRegistryEntry(
            registration_no='ROSTER-1', sj_vehicle_id=8001, client_id=41,
            imei_no='860500000000001', sim_no='923005550001',
            engine_no='ENG-ROSTER-1', chassis_no='CHS-ROSTER-1',
            unit_location='Behind Meter', vehicle_status='Active',
            customer_name='Quietly Working Customer',
            emergency_mobile='0300-5550001', cell1='0321-5550002',
            cell2='0333-5550003', res_phone='042-35550004',
            office_phone='042-35550005', secondary_users='Driver Kamran',
            last_signal_at=datetime.now(), synced_at=datetime.now()))
        db.session.commit()


def test_the_registry_is_refreshed_on_its_own(crm_app):
    """It has to keep itself current: nobody should have to press a button
    before a vehicle added yesterday can be found."""
    import inspect

    from src import scheduler

    source = inspect.getsource(scheduler.start_scheduler)
    assert "id='vehicle_registry_sync'" in source
    assert hasattr(scheduler, 'run_vehicle_registry_sync')
