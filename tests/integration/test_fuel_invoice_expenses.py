"""
Additional expenses on a fuel reimbursement invoice.

Field work incurs costs distance cannot predict - a mobile top-off to reach a
customer, a relay bought on site. They are reimbursed on the same invoice as
the fuel but recorded as their own lines, so the fuel figures stay derived
purely from routing and stay auditable.
"""
import pytest

from src.app import create_app
from src.extensions import db
from src.models.technician import (
    FuelInvoiceExpense, FuelReimbursementInvoice, Technician)
from src.models.user import User


@pytest.fixture
def crm_app():
    application = create_app('testing')
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def admin(crm_app):
    with crm_app.app_context():
        user = User(username='boss', email='boss@test.local', name='Boss',
                    role='admin', is_active=True)
        user.set_password('pw123456')
        db.session.add(user)
        db.session.commit()
    return 'boss'


def _invoice(total_amount=5000.0, status='PENDING', number='ONT-000001'):
    tech = Technician(name='ALI', is_active=True)
    db.session.add(tech)
    db.session.flush()
    invoice = FuelReimbursementInvoice(
        invoice_number=number, technician_id=tech.id,
        start_date=db.func.current_date(), end_date=db.func.current_date(),
        total_distance=120.0, total_fuel_liters=3.43,
        total_amount=total_amount, status=status)
    db.session.add(invoice)
    db.session.commit()
    return invoice


def _login(crm_app, username='boss'):
    client = crm_app.test_client()
    client.post('/auth/login', data={'username': username, 'password': 'pw123456'},
                follow_redirects=True)
    return client


def test_expenses_start_at_zero(crm_app):
    with crm_app.app_context():
        invoice = _invoice()
        assert invoice.additional_expenses_total() == 0.0


def test_expenses_are_added_to_the_net_payable(crm_app):
    with crm_app.app_context():
        invoice = _invoice(total_amount=5000.0)
        db.session.add(FuelInvoiceExpense(
            invoice_id=invoice.id, category=FuelInvoiceExpense.CATEGORY_RELAYS,
            description='Relay', amount=750.0))
        db.session.commit()

        assert invoice.additional_expenses_total() == 750.0
        assert invoice.net_payable == 5750.0


def test_expenses_survive_the_customer_fuel_floor(crm_app):
    """A customer over-providing fuel must not swallow a separate claim.

    The fuel side floors at zero - over-provision is not a debt - but the
    floor has to be applied before expenses are added, not after.
    """
    with crm_app.app_context():
        invoice = _invoice(total_amount=0.0)
        db.session.add(FuelInvoiceExpense(
            invoice_id=invoice.id,
            category=FuelInvoiceExpense.CATEGORY_MOBILE_TOP_OFF,
            description='Top-off', amount=500.0))
        db.session.commit()

        assert invoice.net_payable == 500.0


def test_several_expenses_sum(crm_app):
    with crm_app.app_context():
        invoice = _invoice(total_amount=1000.0)
        for amount in (250.0, 125.5, 40.25):
            db.session.add(FuelInvoiceExpense(
                invoice_id=invoice.id, category=FuelInvoiceExpense.CATEGORY_OTHER,
                description='Item', amount=amount))
        db.session.commit()

        assert invoice.additional_expenses_total() == 415.75
        assert invoice.net_payable == 1415.75


def test_the_three_requested_categories_exist():
    labels = dict(FuelInvoiceExpense.CATEGORIES)
    assert labels[FuelInvoiceExpense.CATEGORY_MOBILE_TOP_OFF] == 'Mobile Top Off'
    assert labels[FuelInvoiceExpense.CATEGORY_RELAYS] == 'Relays'
    assert labels[FuelInvoiceExpense.CATEGORY_OTHER] == 'Other Items'


def test_deleting_an_invoice_takes_its_expenses_with_it(crm_app):
    with crm_app.app_context():
        invoice = _invoice()
        db.session.add(FuelInvoiceExpense(
            invoice_id=invoice.id, category=FuelInvoiceExpense.CATEGORY_RELAYS,
            description='Relay', amount=100.0))
        db.session.commit()

        db.session.delete(invoice)
        db.session.commit()

        assert FuelInvoiceExpense.query.count() == 0, 'Orphaned expense rows left behind'


# ------------------------------------------------------------------- routes

def test_an_expense_can_be_added_through_the_page(crm_app, admin):
    with crm_app.app_context():
        invoice_id = _invoice().id

    client = _login(crm_app)
    client.post(f'/admin/fuel-invoices/{invoice_id}/expenses/add',
                data={'category': 'RELAYS', 'description': 'Relay for VAN-1',
                      'amount': '850.00'}, follow_redirects=True)

    with crm_app.app_context():
        expense = FuelInvoiceExpense.query.filter_by(invoice_id=invoice_id).one()
        assert expense.amount == 850.0
        assert expense.description == 'Relay for VAN-1'
        assert expense.added_by_name == 'Boss'


def test_a_zero_or_missing_amount_is_rejected(crm_app, admin):
    with crm_app.app_context():
        invoice_id = _invoice().id

    client = _login(crm_app)
    for amount in ('0', '', '-50'):
        client.post(f'/admin/fuel-invoices/{invoice_id}/expenses/add',
                    data={'category': 'OTHER', 'description': 'x', 'amount': amount},
                    follow_redirects=True)

    with crm_app.app_context():
        assert FuelInvoiceExpense.query.count() == 0


def test_a_paid_invoice_will_not_take_new_expenses(crm_app, admin):
    """Once paid, the claim is settled - it must not keep growing."""
    with crm_app.app_context():
        invoice_id = _invoice(status='PAID').id

    client = _login(crm_app)
    client.post(f'/admin/fuel-invoices/{invoice_id}/expenses/add',
                data={'category': 'RELAYS', 'description': 'Late claim', 'amount': '500'},
                follow_redirects=True)

    with crm_app.app_context():
        assert FuelInvoiceExpense.query.count() == 0


def test_an_expense_can_be_removed(crm_app, admin):
    with crm_app.app_context():
        invoice = _invoice()
        expense = FuelInvoiceExpense(
            invoice_id=invoice.id, category=FuelInvoiceExpense.CATEGORY_OTHER,
            description='Wrong', amount=99.0)
        db.session.add(expense)
        db.session.commit()
        expense_id = expense.id

    client = _login(crm_app)
    client.post(f'/admin/fuel-invoices/expenses/{expense_id}/delete', follow_redirects=True)

    with crm_app.app_context():
        assert FuelInvoiceExpense.query.get(expense_id) is None


def test_a_paid_invoices_expenses_are_locked(crm_app, admin):
    with crm_app.app_context():
        invoice = _invoice(status='PAID')
        expense = FuelInvoiceExpense(
            invoice_id=invoice.id, category=FuelInvoiceExpense.CATEGORY_OTHER,
            description='Settled', amount=99.0)
        db.session.add(expense)
        db.session.commit()
        expense_id = expense.id

    client = _login(crm_app)
    client.post(f'/admin/fuel-invoices/expenses/{expense_id}/delete', follow_redirects=True)

    with crm_app.app_context():
        assert FuelInvoiceExpense.query.get(expense_id) is not None


def test_the_page_reports_the_periods_totals(crm_app, admin):
    """The five figures the page exists to answer at month end."""
    with crm_app.app_context():
        invoice = _invoice(total_amount=4000.0)
        db.session.add(FuelInvoiceExpense(
            invoice_id=invoice.id, category=FuelInvoiceExpense.CATEGORY_RELAYS,
            description='Relay', amount=600.0))
        db.session.commit()

    client = _login(crm_app)
    page = client.get('/admin/fuel-invoices').data.decode('utf-8')

    for heading in ('Total Activities', 'Kilometers Billed', 'Kilometers Calculated',
                    'Fuel Calculated', 'Fuel Expense Claimed', 'Additional Expenses'):
        assert heading in page, f'Missing period total: {heading}'

    # Amounts are accounting-formatted, not raw floats.
    assert 'PKR 4,000.00' in page
    assert 'PKR 600.00' in page
