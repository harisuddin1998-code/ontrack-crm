"""
The complaint form's pulled vehicle data belongs in the form, not under the
search bar.

Picking a vehicle from the live search used to paint its details into a
scrolling strip directly beneath the search box, where they read as part of
the search result rather than as part of the ticket being written. The same
values now fill labelled fields in the form body.

They are read-only: a complaint stores the registration number, and the
vehicle's own record is the authority for everything else - so what is shown
here is a view of that record, not a copy of it to be edited.
"""
import pytest

from src.app import create_app
from src.extensions import db
from src.models.gps import NonReportingVehicle
from src.models.redo import RedoActivity
from src.models.user import User

FORM = '/complaints/new'
SEARCH = '/complaints/api/vehicle-search'

# Every key the form reads off a search result. If build_record stops
# returning one of these, a field silently goes blank on screen.
FIELDS_THE_FORM_READS = (
    'registration_no', 'customer_name', 'customer_contact', 'city',
    'unit_location', 'reporting_status', 'is_reporting',
    'manufacturer', 'brand', 'model_year', 'color', 'transmission', 'power_cc',
    'imei_no', 'sim_no', 'chassis_no', 'engine_no',
    'last_service_by',
)

# (element id, label shown above it)
# Manufacturer, Brand and Year / Model are what SJ_MIS's own Vehicles table
# calls these columns, and what the business says out loud - "model" meaning
# the year. The panel reads in that order.
DETAIL_FIELDS = (
    ('vdReportingStatus', 'REPORTING STATUS'),
    ('vdManufacturer', 'MANUFACTURER'),
    ('vdBrand', 'BRAND'),
    ('vdModelYear', 'YEAR / MODEL'),
    ('vdColor', 'COLOR'),
    ('vdTransmission', 'TRANSMISSION'),
    ('vdPowerCc', 'POWER CC'),
    ('vdImei', 'IMEI NO'),
    ('vdSim', 'SIM NO'),
    ('vdChassis', 'CHASSIS NO'),
    ('vdEngine', 'ENGINE NO'),
    ('vdLastService', 'LAST SERVICE'),
)


@pytest.fixture(scope='module')
def crm_app():
    application = create_app('testing')
    with application.app_context():
        db.create_all()

        agent = User(username='cf_agent', email='cf_agent@test.local',
                     name='Support Agent', role='complaint_manager', is_active=True)
        agent.set_password('pw123456')
        db.session.add(agent)

        db.session.add(NonReportingVehicle(
            registration_no='CF-7001', customer_name='Complaint Form Customer',
            customer_contact='0300-4445555', emergency_mobile='0333-6667777',
            imei_no='860000000000001', sim_no='923001234567',
            make='Toyota', model='Hilux', vehicle_year='2019',
            vehicle_color='White', city='Karachi',
            chassis_no='CHS-CF-7001', engine_no='ENG-CF-7001',
            unit_location='Under Dashboard'))
        db.session.add(RedoActivity(registration_no='CF-7001',
                                    customer_name='Complaint Form Customer',
                                    customer_contact='0300-4445555',
                                    device_change_reason='Power Issue'))
        db.session.commit()

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def agent(crm_app):
    client = crm_app.test_client()
    with crm_app.app_context():
        user_id = User.query.filter_by(username='cf_agent').first().id
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
    return client


# --------------------------------------------------------------------------
# The strip under the search bar is gone
# --------------------------------------------------------------------------

def test_the_strip_under_the_search_bar_is_gone(agent):
    body = agent.get(FORM).get_data(as_text=True)

    assert 'vehicleInfoBar' not in body
    assert 'vehicle-info-bar' not in body
    assert 'info-chip' not in body
    assert 'renderVehicleInfoBar' not in body


def test_the_search_itself_is_untouched(agent):
    """Only where the result is shown changed - you still have to find the
    vehicle before anything can populate."""
    body = agent.get(FORM).get_data(as_text=True)

    assert 'id="vehicleSearchInput"' in body
    assert 'id="searchResultsDropdown"' in body
    assert 'function selectVehicleResult' in body


# --------------------------------------------------------------------------
# The data has fields in the form instead
# --------------------------------------------------------------------------

@pytest.mark.parametrize('field_id,label', DETAIL_FIELDS)
def test_every_pulled_value_has_a_field_in_the_form(field_id, label, agent):
    body = agent.get(FORM).get_data(as_text=True)

    assert f'id="{field_id}"' in body, f'{label} has nowhere to land'
    assert label in body, f'{label} has no label above it'


def test_the_pulled_fields_are_read_only(agent):
    """A complaint stores the registration number; the vehicle record is the
    authority for the rest. An editable box here would promise otherwise."""
    body = agent.get(FORM).get_data(as_text=True)

    for field_id, label in DETAIL_FIELDS:
        # The ids are unique to this section, so the exact adjacency is the
        # whole check - no need to slice the section out of the document and
        # depend on where its closing tag happens to fall.
        marker = f'id="{field_id}" class="o_field_widget" readonly'
        assert marker in body, f'{label} is not read-only'


def test_the_section_says_where_the_data_came_from(agent):
    body = agent.get(FORM).get_data(as_text=True)

    assert 'VEHICLE DETAILS' in body
    assert "Pulled from the vehicle's system record" in body


def test_the_section_is_hidden_until_a_vehicle_is_picked(agent):
    """A walk-in complaint with no vehicle on file should not open onto ten
    empty boxes."""
    body = agent.get(FORM).get_data(as_text=True)

    assert 'id="vehicleDetailsSection"' in body
    marker = body.split('id="vehicleDetailsSection"', 1)[1][:120]
    assert 'display: none' in marker

    # ...and typing a fresh query empties them again.
    assert 'function clearVehicleDetails' in body
    assert 'clearVehicleDetails();' in body


def test_the_editable_customer_fields_are_still_there(agent):
    """Moving the read-only data must not disturb what is actually saved."""
    body = agent.get(FORM).get_data(as_text=True)

    for field_id in ('customerNameInput', 'customerContactInput',
                     'cityInput', 'vehicleLocationInput', 'regNoInput'):
        assert f'id="{field_id}"' in body


# --------------------------------------------------------------------------
# The contract between the search and the form
# --------------------------------------------------------------------------

def test_the_search_returns_every_key_the_form_reads(agent):
    """The fields are filled from this payload, so a renamed key shows up as
    a blank box rather than an error."""
    payload = agent.get(SEARCH, query_string={'q': 'CF-7001'}).get_json()

    assert payload['results'], 'the seeded vehicle was not found'
    record = payload['results'][0]
    missing = [key for key in FIELDS_THE_FORM_READS if key not in record]
    assert not missing, f'the form reads keys the search does not return: {missing}'


def test_the_search_carries_the_vehicle_specification(agent):
    record = agent.get(SEARCH, query_string={'q': 'CF-7001'}).get_json()['results'][0]

    assert record['registration_no'] == 'CF-7001'
    assert record['manufacturer'] == 'Toyota'
    assert record['brand'] == 'Hilux'
    assert record['imei_no'] == '860000000000001'
    assert record['chassis_no'] == 'CHS-CF-7001'
    assert record['reporting_status']


def test_a_short_query_searches_for_nothing(agent):
    """One character matches most of the fleet; the form waits for two."""
    assert agent.get(SEARCH, query_string={'q': 'C'}).get_json()['results'] == []
