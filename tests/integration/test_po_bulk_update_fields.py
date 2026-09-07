"""
The columns a PO bulk update sheet may carry.

The sheets the installation team prepare hold the customer, their contact,
the driver, the vehicle, the salesperson, the location, the existing-vehicle
details and the money. Every one of those has to land on the right column -
and none of them is required, because sheets are prepared by hand and carry
whichever facts the person had.
"""
import pytest

from src.app import create_app
from src.extensions import db
from src.models.purchase_order import PurchaseOrder
from src.models.user import User
from src.services.po_bulk_update_service import (
    FIELD_COLUMNS, KEY_COLUMNS, POBulkUpdateService, _canon)


@pytest.fixture
def crm_app():
    application = create_app('testing')
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def order(crm_app):
    with crm_app.app_context():
        seller = User(username='aimen', email='aimen@test.local', name='Aimen Saleem',
                      role='sales', is_active=True)
        seller.set_password('pw123456')
        db.session.add(seller)
        db.session.flush()

        po = PurchaseOrder(
            po_number='PO-2026-0001', owner_name='OLD NAME', owner_contact='0300-0000000',
            reg_no='ABC-123', vehicle_make='TOYOTA', vehicle_model='COROLLA',
            vehicle_year='2020', vehicle_color='WHITE', engine_number='E1',
            chassis_number='C1', vehicle_availability_location='OFFICE',
            sales_person_id=seller.id, status='PENDING', rates=0.0, amc=0.0)
        db.session.add(po)
        db.session.commit()
        yield po


# The headings as they are actually written on the sheets.
SHEET_COLUMNS = {
    'Customer Name': 'owner_name',
    'Contact Number': 'owner_contact',
    'Driver Contact': 'contact_person_driver',
    'Manufacturer': 'vehicle_make',
    'Brand': 'vehicle_model',
    'Sales Person': 'sales_person_id',
    'Vehicle / Installation Location': 'vehicle_availability_location',
    'Existing Customer Name': 'existing_customer_name',
    'Existing Vehicle Number': 'existing_vehicle_number',
    'Rates': 'rates',
    'AMC': 'amc',
}


@pytest.mark.parametrize('heading,field', sorted(SHEET_COLUMNS.items()))
def test_every_sheet_column_is_recognised(heading, field):
    assert FIELD_COLUMNS.get(_canon(heading)) == field, f'{heading} is not recognised'


def test_registration_number_identifies_the_order():
    """It is the key, not a field - a sheet must not rewrite it in bulk."""
    assert KEY_COLUMNS.get(_canon('Registration Number')) == 'reg_no'


def test_a_sheet_need_not_carry_every_column(crm_app, order):
    """Sheets are prepared by hand; they carry what the person had."""
    with crm_app.app_context():
        plan = POBulkUpdateService().prepare(
            'partial.csv',
            b'PO Number,Customer Name,Rates\nPO-2026-0001,NEW NAME,4321\n')

        assert plan['summary']['update'] == 1
        assert plan['summary']['invalid'] == 0
        assert plan['rows'][0]['changes'] == {'owner_name': 'NEW NAME', 'rates': 4321.0}


def test_the_full_sheet_writes_every_column(crm_app, order):
    with crm_app.app_context():
        csv = (
            'PO Number,Customer Name,Contact Number,Driver Contact,Manufacturer,'
            'Brand,Sales Person,Vehicle / Installation Location,'
            'Existing Customer Name,Existing Vehicle Number,Rates,AMC\n'
            'PO-2026-0001,NEW NAME,0311-1111111,0322-2222222,HONDA,CIVIC,aimen,'
            'MAIN WORKSHOP,PREVIOUS OWNER,XYZ-789,15000,3000\n')
        plan = POBulkUpdateService().prepare('full.csv', csv.encode())

        assert plan['rows'][0]['errors'] == []
        changes = plan['rows'][0]['changes']
        assert changes['owner_name'] == 'NEW NAME'
        assert changes['owner_contact'] == '0311-1111111'
        assert changes['contact_person_driver'] == '0322-2222222'
        assert changes['vehicle_make'] == 'HONDA'
        assert changes['vehicle_model'] == 'CIVIC'
        assert changes['vehicle_availability_location'] == 'MAIN WORKSHOP'
        assert changes['existing_customer_name'] == 'PREVIOUS OWNER'
        assert changes['existing_vehicle_number'] == 'XYZ-789'
        assert changes['rates'] == 15000.0
        assert changes['amc'] == 3000.0


def test_a_salesperson_is_resolved_to_the_user_the_column_holds(crm_app, order):
    """The sheet names a person; the column holds a foreign key."""
    with crm_app.app_context():
        seller = User.query.filter_by(username='aimen').one()

        by_username = POBulkUpdateService().prepare(
            'sp.csv', b'PO Number,Sales Person\nPO-2026-0002,x\n')
        assert by_username['rows'][0]['outcome'] == 'unmatched'

        for named in ('aimen', 'Aimen Saleem', 'AIMEN SALEEM'):
            plan = POBulkUpdateService().prepare(
                'sp.csv', f'PO Number,Sales Person\nPO-2026-0001,{named}\n'.encode())
            row = plan['rows'][0]
            # The order already belongs to this seller, so naming them again
            # is correctly reported as no change rather than as an update.
            assert row['errors'] == []
            assert row['changes'].get('sales_person_id', seller.id) == seller.id


def test_an_unknown_salesperson_is_reported_not_guessed(crm_app, order):
    with crm_app.app_context():
        plan = POBulkUpdateService().prepare(
            'sp.csv', b'PO Number,Sales Person\nPO-2026-0001,NOBODY AT ALL\n')

        row = plan['rows'][0]
        assert row['outcome'] == 'invalid'
        assert 'no user is named "NOBODY AT ALL"' in row['errors'][0]


def test_applying_routes_open_orders_to_the_installation_team(crm_app, order):
    """A sheet that fills an order in is handing over a job.

    Without this the row changed and nobody was told.
    """
    with crm_app.app_context():
        installer = User(username='fitter', email='fitter@test.local', name='Fitter',
                         role='installation', is_active=True)
        installer.set_password('pw123456')
        db.session.add(installer)
        db.session.commit()

        plan = POBulkUpdateService().prepare(
            'sheet.csv',
            b'PO Number,Customer Name,Vehicle / Installation Location\n'
            b'PO-2026-0001,NEW NAME,MAIN WORKSHOP\n')
        result = POBulkUpdateService().apply(plan['rows'], user_id=installer.id)

        assert result['applied'] == 1
        assert result['routed'] == ['PO-2026-0001']

        from src.models.notification import UserNotification
        told = UserNotification.query.filter_by(user_id=installer.id).all()
        assert len(told) == 1
        assert 'PO-2026-0001' in (told[0].body or '')


def test_a_completed_order_is_not_routed_as_outstanding_work(crm_app, order):
    with crm_app.app_context():
        plan = POBulkUpdateService().prepare(
            'sheet.csv', b'PO Number,Status\nPO-2026-0001,COMPLETED\n')
        result = POBulkUpdateService().apply(plan['rows'], user_id=1)

        assert result['completed'] == ['PO-2026-0001']
        assert result['routed'] == []
