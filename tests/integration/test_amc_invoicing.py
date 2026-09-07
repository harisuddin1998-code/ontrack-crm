"""
Regression tests for AMC invoicing: numbering, the amount override, and the
ledger the dashboard cards and the report are built from.

The invoice number has to be unique - it identifies a financial document, and
two documents sharing one is not a display bug. The override has to record
what was conceded and why, because a discount that leaves no trace is
indistinguishable from a smaller debt.

These assert on the ledger row rather than on the bytes of the PDF - the row
is what the dashboard cards and the report actually read. The row is written
only once the document has rendered, so the whole module is skipped where
wkhtmltopdf is not installed: without it there is no invoice to have a ledger
row, and failing here would report a missing renderer as a logic error.
"""
import re

import pytest

from src.app import create_app
from src.extensions import db
from src.models.amc_invoice import AmcInvoice
from src.models.annual_recovery import AnnualRecoveryClient, AnnualRecoveryVehicle
from src.models.technician import Technician
from src.models.user import User
from src.services.pdf_service import PDFService
from src.services.technician_service import FuelReimbursementInvoiceService

SHEET = 'AMC INVOICE TEST'


def _renderer_available() -> bool:
    """Whether wkhtmltopdf can be found, without needing an app context."""
    import shutil

    if shutil.which('wkhtmltopdf'):
        return True
    import os
    for candidate in (
        os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'),
                     'wkhtmltopdf', 'bin', 'wkhtmltopdf.exe'),
        os.path.join(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
                     'wkhtmltopdf', 'bin', 'wkhtmltopdf.exe'),
        '/usr/local/bin/wkhtmltopdf',
        '/usr/bin/wkhtmltopdf',
    ):
        if os.path.exists(candidate):
            return True
    return False


# The numbering tests below stand on their own; the ones that raise an invoice
# need the renderer, because an invoice that does not render is not recorded.
requires_renderer = pytest.mark.skipif(
    not _renderer_available(),
    reason='wkhtmltopdf is not installed, so no invoice document can be produced')


@pytest.fixture(scope='module')
def crm_app():
    application = create_app('testing')

    with application.app_context():
        db.create_all()

        officer = User(username='inv_officer', email='inv_officer@test.local',
                       name='Invoice Officer', role='admin', is_active=True)
        officer.set_password('officer123')
        db.session.add(officer)
        db.session.add(Technician(name='Fuel Tech', is_active=True))
        db.session.commit()

        client = AnnualRecoveryClient(name='FLEETWAY LOGISTICS', cell1='03001234567')
        db.session.add(client)
        db.session.flush()
        # Two vehicles, 9000 owed in total, nothing recovered - the worked
        # example: bill 7000 against 9000 outstanding.
        db.session.add(AnnualRecoveryVehicle(
            client_id=client.id, reg_no='INV-1', amc_charges=5000.0,
            recovered_amount=0.0, status='PENDING', sheet_name=SHEET,
            installation_date='2020-06-15', installation_year='2020'))
        db.session.add(AnnualRecoveryVehicle(
            client_id=client.id, reg_no='INV-2', amc_charges=4000.0,
            recovered_amount=0.0, status='PENDING', sheet_name=SHEET,
            installation_date='2020-06-20', installation_year='2020'))
        db.session.commit()

    yield application


@pytest.fixture
def officer(crm_app):
    """A signed-in client. CSRF is off in the testing config."""
    client = crm_app.test_client()
    with crm_app.app_context():
        user_id = User.query.filter_by(username='inv_officer').first().id
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
    return client


@pytest.fixture(autouse=True)
def clean_ledger(crm_app):
    """Each test starts with an empty ledger and leaves one behind."""
    with crm_app.app_context():
        AmcInvoice.query.delete()
        db.session.commit()
    yield
    with crm_app.app_context():
        AmcInvoice.query.delete()
        db.session.commit()


def _client_id(crm_app):
    with crm_app.app_context():
        return AnnualRecoveryClient.query.filter_by(name='FLEETWAY LOGISTICS').first().id


def _vehicle_id(crm_app, reg_no):
    with crm_app.app_context():
        return AnnualRecoveryVehicle.query.filter_by(reg_no=reg_no).first().id


# --------------------------------------------------------------------------
# Numbering
# --------------------------------------------------------------------------

def test_amc_invoice_number_carries_customer_and_timestamp(crm_app):
    with crm_app.app_context():
        number = PDFService.amc_invoice_number('FLEETWAY LOGISTICS')
    assert re.fullmatch(r'AMC_ONT_FLEE_\d{8}-\d{6}', number), number


def test_customer_code_is_always_four_characters(crm_app):
    with crm_app.app_context():
        assert PDFService.customer_code('FLEETWAY') == 'FLEE'
        # Padded, so the number keeps one shape down a column.
        assert PDFService.customer_code('AB') == 'ABXX'
        # Punctuation and spaces are not part of the code.
        assert PDFService.customer_code('A B-C D') == 'ABCD'
        assert PDFService.customer_code('') == 'CUST'


def test_amc_invoice_numbers_do_not_collide_within_one_second(crm_app):
    """Two invoices for one customer in the same second must differ.

    The number is built from a timestamp to the second, so this is the case
    that would otherwise hit the unique constraint on the column.
    """
    from datetime import datetime

    fixed = datetime(2026, 8, 24, 12, 0, 0)
    with crm_app.app_context():
        first = PDFService.amc_invoice_number('FLEETWAY LOGISTICS', now=fixed)
        db.session.add(AmcInvoice(invoice_number=first, basis='CUSTOMER',
                                  client_name='FLEETWAY LOGISTICS'))
        db.session.commit()

        second = PDFService.amc_invoice_number('FLEETWAY LOGISTICS', now=fixed)

    assert second != first
    assert second.startswith(first)


def test_fuel_invoice_number_is_unique_not_a_row_count(crm_app):
    """The fuel number used to be ONT-{count + 1}.

    Deleting any invoice dropped the count, so the next number generated was
    one already in use. This asserts the number no longer depends on how many
    rows happen to exist.
    """
    from datetime import datetime

    fixed = datetime(2026, 8, 24, 12, 0, 0)
    with crm_app.app_context():
        technician_id = Technician.query.filter_by(name='Fuel Tech').first().id
        number = FuelReimbursementInvoiceService.generate_invoice_number(
            technician_id, now=fixed)

    assert re.fullmatch(r'FUEL_ONT_FUEL_\d{8}-\d{6}', number), number


# --------------------------------------------------------------------------
# The override, and the ledger it writes
# --------------------------------------------------------------------------

@requires_renderer
def test_invoice_without_an_override_bills_the_full_balance(officer, crm_app):
    officer.post(f'/annual-recovery/invoice/client/{_client_id(crm_app)}/pdf')

    with crm_app.app_context():
        invoice = AmcInvoice.query.one()
        assert invoice.outstanding_amount == 9000.0
        assert invoice.invoiced_amount == 9000.0
        assert invoice.discount_amount == 0.0
        assert invoice.vehicle_count == 2
        assert invoice.basis == AmcInvoice.BASIS_CUSTOMER


@requires_renderer
def test_override_records_the_discount_against_the_officer(officer, crm_app):
    """The worked example: 9000 outstanding, 7000 billed, 2000 conceded."""
    officer.post(f'/annual-recovery/invoice/client/{_client_id(crm_app)}/pdf',
                 data={'override_amount': '7000',
                       'discount_reason': 'Agreed settlement'})

    with crm_app.app_context():
        invoice = AmcInvoice.query.one()
        user_id = User.query.filter_by(username='inv_officer').first().id

        assert invoice.outstanding_amount == 9000.0
        assert invoice.invoiced_amount == 7000.0
        assert invoice.discount_amount == 2000.0
        assert invoice.discount_reason == 'Agreed settlement'
        assert invoice.generated_by == user_id
        assert invoice.is_discounted


def test_an_amount_above_the_balance_is_refused(officer, crm_app):
    """Refused, not clamped - it means the officer typed the wrong figure."""
    response = officer.post(
        f'/annual-recovery/invoice/client/{_client_id(crm_app)}/pdf',
        data={'override_amount': '15000'}, follow_redirects=True)

    assert 'cannot be more than the outstanding' in response.get_data(as_text=True)
    with crm_app.app_context():
        assert AmcInvoice.query.count() == 0


def test_a_discount_requires_a_reason(officer, crm_app):
    response = officer.post(
        f'/annual-recovery/invoice/client/{_client_id(crm_app)}/pdf',
        data={'override_amount': '7000'}, follow_redirects=True)

    assert 'Give a reason for billing below' in response.get_data(as_text=True)
    with crm_app.app_context():
        assert AmcInvoice.query.count() == 0


def test_a_non_numeric_amount_is_refused(officer, crm_app):
    response = officer.post(
        f'/annual-recovery/invoice/client/{_client_id(crm_app)}/pdf',
        data={'override_amount': 'seven thousand'}, follow_redirects=True)

    assert 'as a number' in response.get_data(as_text=True)
    with crm_app.app_context():
        assert AmcInvoice.query.count() == 0


@requires_renderer
def test_vehicle_wise_invoice_records_its_vehicle(officer, crm_app):
    vehicle_id = _vehicle_id(crm_app, 'INV-1')
    officer.post(f'/annual-recovery/invoice/vehicle/{vehicle_id}/pdf')

    with crm_app.app_context():
        invoice = AmcInvoice.query.one()
        assert invoice.basis == AmcInvoice.BASIS_VEHICLE
        assert invoice.vehicle_id == vehicle_id
        assert invoice.vehicle_count == 1
        assert invoice.invoiced_amount == 5000.0


# --------------------------------------------------------------------------
# What the ledger feeds
# --------------------------------------------------------------------------

@requires_renderer
def test_dashboard_counts_invoices_and_discounts(officer, crm_app):
    officer.post(f'/annual-recovery/invoice/client/{_client_id(crm_app)}/pdf',
                 data={'override_amount': '7000',
                       'discount_reason': 'Agreed settlement'})

    body = officer.get('/admin/dashboard').get_data(as_text=True)
    assert 'AMC Invoicing' in body
    for key in ('amc_invoices_count', 'amc_invoiced_amount',
                'amc_invoice_outstanding', 'amc_discount_amount'):
        assert f'data-sync="{key}"' in body

    # Executive is required to be a replica of Administration.
    executive = officer.get('/admin/executive-dashboard').get_data(as_text=True)
    assert 'AMC Invoicing' in executive

    values = officer.get('/admin/api/dashboard-stats').get_json()['values']
    assert values['amc_invoices_count'] == '1'
    assert values['amc_discount_amount'] == 'PKR 2,000'


@requires_renderer
def test_report_lists_the_invoice_and_its_discount(officer, crm_app):
    officer.post(f'/annual-recovery/invoice/client/{_client_id(crm_app)}/pdf',
                 data={'override_amount': '7000',
                       'discount_reason': 'Agreed settlement'})

    response = officer.get('/admin/mis-reports/amc-invoices'
                           '?from=2020-01-01&to=2030-12-31')
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'AMC_ONT_FLEE_' in body
    assert 'Agreed settlement' in body
    assert 'Invoice Officer' in body
    # Money keeps its decimals rather than being rounded like a count.
    assert '2,000.00' in body


def test_report_is_in_the_catalogue(officer):
    body = officer.get('/admin/mis-reports').get_data(as_text=True)
    assert 'AMC Invoices and Discounts' in body
