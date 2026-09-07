"""
Who a bulk update sheet is allowed to write.

Sales has never been able to open another salesperson's purchase order. The
bulk screen is reached with a spreadsheet rather than a URL, so the same rule
has to hold there - both when the file is previewed and again when the
approved plan comes back from the browser to be written.

The Administrator and the Executive are unscoped: they already see the whole
order book on the Sales Dashboard, so bulk update hands them nothing new.
"""
import pytest

from src.app import create_app
from src.extensions import db
from src.models.purchase_order import PurchaseOrder
from src.models.user import User
from src.services.po_bulk_update_service import POBulkUpdateService


@pytest.fixture
def crm_app():
    application = create_app('testing')
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


def _seller(username, name):
    user = User(username=username, email=f'{username}@test.local', name=name,
                role='sales', is_active=True)
    user.set_password('pw123456')
    db.session.add(user)
    db.session.flush()
    return user


def _order(po_number, reg_no, seller):
    po = PurchaseOrder(
        po_number=po_number, owner_name='OLD NAME', owner_contact='0300-0000000',
        reg_no=reg_no, vehicle_make='TOYOTA', vehicle_model='COROLLA',
        vehicle_year='2020', vehicle_color='WHITE', engine_number='E1',
        chassis_number='C1', vehicle_availability_location='OFFICE',
        sales_person_id=seller.id, status='PENDING', rates=0.0, amc=0.0)
    db.session.add(po)
    return po


@pytest.fixture
def two_sellers(crm_app):
    """Two salespeople with one order each."""
    with crm_app.app_context():
        aimen = _seller('aimen', 'Aimen Saleem')
        bilal = _seller('bilal', 'Bilal Khan')
        _order('PO-2026-0001', 'ABC-123', aimen)
        _order('PO-2026-0002', 'XYZ-789', bilal)
        db.session.commit()
        yield {'aimen': aimen.id, 'bilal': bilal.id}


SHEET = (b'PO Number,Customer Name\n'
         b'PO-2026-0001,FIRST CUSTOMER\n'
         b'PO-2026-0002,SECOND CUSTOMER\n')


def test_a_salesperson_may_update_their_own_order(crm_app, two_sellers):
    with crm_app.app_context():
        plan = POBulkUpdateService().prepare(
            'sheet.csv', SHEET, scope_user_id=two_sellers['aimen'])

        mine = plan['rows'][0]
        assert mine['po_number'] == 'PO-2026-0001'
        assert mine['outcome'] == 'update'
        assert mine['changes'] == {'owner_name': 'FIRST CUSTOMER'}


def test_another_salespersons_order_is_refused_by_name_not_hidden(crm_app, two_sellers):
    """'Not yours' and 'not found' are different answers.

    Reporting a colleague's order as unmatched would send the salesperson
    hunting for a typo that is not there.
    """
    with crm_app.app_context():
        plan = POBulkUpdateService().prepare(
            'sheet.csv', SHEET, scope_user_id=two_sellers['aimen'])

        theirs = plan['rows'][1]
        assert theirs['outcome'] == 'forbidden'
        assert theirs['po_id'] is None
        assert theirs['po_number'] == 'PO-2026-0002'
        assert 'another salesperson' in theirs['errors'][0]
        assert plan['summary']['forbidden'] == 1
        assert plan['summary']['update'] == 1


def test_an_unscoped_run_covers_the_whole_order_book(crm_app, two_sellers):
    """How the Administrator and the Executive see it."""
    with crm_app.app_context():
        plan = POBulkUpdateService().prepare('sheet.csv', SHEET)

        assert plan['summary']['update'] == 2
        assert plan['summary']['forbidden'] == 0


def test_a_tampered_plan_is_refused_at_the_write(crm_app, two_sellers):
    """The plan travels through the browser, so ownership is checked again.

    A preview-only restriction would be a restriction on the screen and
    nowhere else - this is the row the preview refused, posted back by hand.
    """
    with crm_app.app_context():
        smuggled = [{
            'row_no': 3,
            'po_id': PurchaseOrder.query.filter_by(po_number='PO-2026-0002').one().id,
            'po_number': 'PO-2026-0002',
            'changes': {'owner_name': 'TAKEN OVER'},
            'outcome': 'update',
        }]

        result = POBulkUpdateService().apply(
            smuggled, user_id=two_sellers['aimen'],
            scope_user_id=two_sellers['aimen'])

        assert result['applied'] == 0
        assert result['refused'] == 1
        untouched = PurchaseOrder.query.filter_by(po_number='PO-2026-0002').one()
        assert untouched.owner_name == 'OLD NAME'


def test_the_same_plan_is_written_for_an_unscoped_user(crm_app, two_sellers):
    """The refusal above is the scope, not a broken plan."""
    with crm_app.app_context():
        rows = [{
            'row_no': 3,
            'po_id': PurchaseOrder.query.filter_by(po_number='PO-2026-0002').one().id,
            'po_number': 'PO-2026-0002',
            'changes': {'owner_name': 'TAKEN OVER'},
            'outcome': 'update',
        }]

        result = POBulkUpdateService().apply(rows, user_id=two_sellers['aimen'])

        assert result['applied'] == 1
        assert result['refused'] == 0
