"""
The application says Manufacturer, Brand and Year / Model.

Not a cosmetic rename: it is the vocabulary of the system of record. SJ_MIS's
own `Vehicles` table has columns called `Manufacturer`, `Brand`, `ModelYear`,
`Color`, `Transmission` and `PowerCC` - and "model" meaning the year is how
the business says it out loud. The CRM said Make / Model / Year, so a person
reading a CRM screen and a person reading SJ_MIS were using the same words
for different things.

The stored column names are unchanged - `vehicle_make` still holds the
manufacturer - because renaming columns across six models would be churn
nobody sees. What changed is every label, every spreadsheet header, and the
keys of the record the search hands to the forms.

Transmission and Power CC are new. SJ_MIS has columns for both and barely
fills them, so they are pulled where they exist, cleaned, and recordable on
the order for vehicles we handle.
"""
from datetime import date, datetime

import pytest

from src.app import create_app
from src.extensions import db
from src.forms.po_forms import TRANSMISSION_CHOICES
from src.models.purchase_order import PurchaseOrder
from src.models.user import User
from src.models.vehicle_registry import VehicleRegistryEntry
from src.services.vehicle_search_service import VehicleSearchService

SEARCH = '/complaints/api/vehicle-search'


@pytest.fixture(scope='module')
def crm_app():
    application = create_app('testing')
    application.config['WTF_CSRF_ENABLED'] = False
    with application.app_context():
        db.create_all()

        boss = User(username='vv_admin', email='vv_admin@test.local',
                    name='Vocabulary Admin', role='admin', is_active=True)
        boss.set_password('pw123456')
        db.session.add(boss)

        # A vehicle SJ_MIS knows fully.
        db.session.add(VehicleRegistryEntry(
            registration_no='SPEC-1', sj_vehicle_id=7001,
            manufacturer='KIA', brand='STONIC', model_year='2023',
            color='SILVER', transmission='MANUAL', power_cc='1400',
            imei_no='860700000000001', customer_name='Spec Customer',
            cell1='0300-7010001', synced_at=datetime.now()))

        # A vehicle SJ_MIS knows, without transmission or capacity - which is
        # four vehicles in five.
        db.session.add(VehicleRegistryEntry(
            registration_no='SPEC-2', sj_vehicle_id=7002,
            manufacturer='TOYOTA', brand='COROLLA', model_year='2019',
            color='WHITE', imei_no='860700000000002',
            customer_name='Sparse Customer', synced_at=datetime.now()))
        db.session.commit()

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def admin(crm_app):
    client = crm_app.test_client()
    with crm_app.app_context():
        user_id = User.query.filter_by(username='vv_admin').first().id
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
    return client


def record_for(client, reg_no):
    payload = client.get(SEARCH, query_string={'q': reg_no}).get_json()
    return [r for r in payload['results'] if r['registration_no'] == reg_no][0]


# --------------------------------------------------------------------------
# The record the forms read
# --------------------------------------------------------------------------

def test_the_record_speaks_the_new_vocabulary(admin):
    record = record_for(admin, 'SPEC-1')

    assert record['manufacturer'] == 'KIA'
    assert record['brand'] == 'STONIC'
    assert record['model_year'] == '2023'
    assert record['color'] == 'SILVER'


@pytest.mark.parametrize('gone', ['make', 'model', 'year'])
def test_the_old_keys_are_gone(gone, admin):
    """Left in place they would be read by something that never got updated,
    and it would silently show a blank."""
    assert gone not in record_for(admin, 'SPEC-1')


def test_transmission_and_power_come_through(admin):
    record = record_for(admin, 'SPEC-1')

    assert record['transmission'] == 'MANUAL'
    assert record['power_cc'] == '1400'


def test_a_vehicle_without_them_says_nothing_rather_than_guessing(admin):
    record = record_for(admin, 'SPEC-2')

    assert record['transmission'] == ''
    assert record['power_cc'] == ''


# --------------------------------------------------------------------------
# What the source system holds badly
# --------------------------------------------------------------------------

@pytest.mark.parametrize('junk', ['1234', 'NLL', 'NIL', 'XXX', '0', '   ', '', None])
def test_a_placeholder_transmission_is_not_a_transmission(junk):
    """806 vehicles in SJ_MIS say "1234" and 194 say "NLL". Shown as a
    transmission, a reader cannot tell those from a real answer."""
    from src.services.db_sync_service import clean_transmission

    assert clean_transmission(junk) is None


@pytest.mark.parametrize('raw,expected', [
    ('MANUAL', 'MANUAL'),
    ('manual', 'MANUAL'),
    ('Man', 'MANUAL'),
    ('AUTO', 'AUTOMATIC'),
    ('Automatic', 'AUTOMATIC'),
    ('CVT', 'CVT'),
])
def test_a_real_transmission_survives_and_is_reconciled(raw, expected):
    """AUTO and AUTOMATIC are the same gearbox; counted apart they are two
    facts where there is one."""
    from src.services.db_sync_service import clean_transmission

    assert clean_transmission(raw) == expected


@pytest.mark.parametrize('raw,expected', [
    ('1800', '1800'),
    ('1800 cc', '1800'),
    ('1.8L', '18'),
    ('', None),
    (None, None),
    ('abc', None),
])
def test_power_is_read_as_digits(raw, expected):
    """The source column is free text, so what is stored is the number in
    it, or nothing."""
    from src.services.db_sync_service import clean_power_cc

    assert clean_power_cc(raw) == expected


def test_the_sync_uses_those_rules(crm_app):
    import inspect

    from src.services.db_sync_service import DBSyncService

    source = inspect.getsource(DBSyncService.sync_vehicle_registry)
    assert 'clean_transmission(transmission)' in source
    assert 'clean_power_cc(power_cc)' in source


# --------------------------------------------------------------------------
# Transmission is a fixed list
# --------------------------------------------------------------------------

def test_transmission_is_a_fixed_list(crm_app):
    values = [value for value, _label in TRANSMISSION_CHOICES if value]

    assert values == ['AUTOMATIC', 'MANUAL', 'CVT', 'HYBRID', 'OTHER']


def test_the_installation_form_offers_that_list(crm_app):
    from src.forms.po_forms import InstallationUpdateForm

    with crm_app.test_request_context():
        form = InstallationUpdateForm()
        assert [c[0] for c in form.transmission.choices] == \
            [c[0] for c in TRANSMISSION_CHOICES]
        assert form.transmission.label.text == 'Transmission'
        assert form.power_cc.label.text == 'Power CC'


@pytest.mark.parametrize('field,label', [
    ('vehicle_make', 'Manufacturer'),
    ('vehicle_model', 'Brand'),
    ('vehicle_year', 'Year / Model'),
    ('vehicle_color', 'Color'),
])
def test_the_order_forms_are_labelled_the_new_way(field, label, crm_app):
    from src.forms.po_forms import InstallationUpdateForm, POCreationForm

    with crm_app.test_request_context():
        for form_class in (POCreationForm, InstallationUpdateForm):
            form = form_class()
            assert getattr(form, field).label.text == label, form_class.__name__


# --------------------------------------------------------------------------
# An order can record what SJ_MIS does not
# --------------------------------------------------------------------------

def test_an_order_can_hold_transmission_and_power(crm_app):
    with crm_app.app_context():
        po = PurchaseOrder(
            po_number='PO-SPEC-1', owner_name='Spec Customer',
            owner_contact='0300-7010001', reg_no='SPEC-2',
            vehicle_make='TOYOTA', vehicle_model='COROLLA',
            vehicle_year='2019', vehicle_color='WHITE',
            engine_number='ENG-SPEC', chassis_number='CHS-SPEC',
            vehicle_availability_location='LAHORE',
            transmission='AUTOMATIC', power_cc='1800',
            status='COMPLETED', scheduled_date=date.today())
        db.session.add(po)
        db.session.commit()

        record = VehicleSearchService().lookup_by_reg_no('SPEC-2')

    assert record['transmission'] == 'AUTOMATIC'
    assert record['power_cc'] == '1800'


def test_the_order_beats_the_source_system(crm_app):
    """Somebody stood at the vehicle and typed it; SJ_MIS holds a column it
    barely fills."""
    with crm_app.app_context():
        po = PurchaseOrder(
            po_number='PO-SPEC-2', owner_name='Spec Customer',
            owner_contact='0300-7010001', reg_no='SPEC-1',
            vehicle_make='KIA', vehicle_model='STONIC',
            vehicle_year='2023', vehicle_color='SILVER',
            engine_number='ENG-SPEC-2', chassis_number='CHS-SPEC-2',
            vehicle_availability_location='LAHORE',
            transmission='CVT', power_cc='1600',
            status='COMPLETED', scheduled_date=date.today())
        db.session.add(po)
        db.session.commit()

        record = VehicleSearchService().lookup_by_reg_no('SPEC-1')

    assert record['transmission'] == 'CVT', 'the source system overrode the order'
    assert record['power_cc'] == '1600'


def test_the_installer_is_allowed_to_write_them(crm_app):
    from src.services.po_service import POService

    assert 'transmission' in POService.INSTALLATION_FIELDS
    assert 'power_cc' in POService.INSTALLATION_FIELDS


# --------------------------------------------------------------------------
# Spreadsheets built before the rename still import
# --------------------------------------------------------------------------

@pytest.mark.parametrize('header,field', [
    ('Manufacturer', 'vehicle_make'),
    ('Make', 'vehicle_make'),
    ('Vehicle Make', 'vehicle_make'),
    ('Brand', 'vehicle_model'),
    ('Model', 'vehicle_model'),
    ('Year / Model', 'vehicle_year'),
    ('Model Year', 'vehicle_year'),
    ('Year', 'vehicle_year'),
    ('Colour', 'vehicle_color'),
    ('Color', 'vehicle_color'),
    ('Transmission', 'transmission'),
    ('Power CC', 'power_cc'),
])
def test_a_bulk_update_reads_both_vocabularies(header, field):
    """A spreadsheet somebody built last month still says "Make" at the top
    of a column. Refusing to read it would be a rename that costs the user
    their file."""
    from src.services.po_bulk_update_service import FIELD_COLUMNS, _canon

    assert FIELD_COLUMNS.get(_canon(header)) == field, header
