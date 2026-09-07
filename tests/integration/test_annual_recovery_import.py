"""
Regression tests for the Annual Recovery Excel import.

Two behaviours these lock down, both learned from real uploads:

* A sheet records collection as wording ("PAID"), not as a figure. Such a row
  must import with the money recorded as recovered - it used to import labelled
  RECOVERED while still showing the full amount outstanding, so 244 clients who
  had already paid looked like they still owed.
* Operators log a follow-up payment as a second line for the same registration.
  Those lines used to be dropped as duplicates, losing the payment. They are
  merged instead: 9,000 charged + a 7,000 PAID line is one vehicle, recovered
  7,000, outstanding 2,000, marked RECOVERED.
"""
import io

import pandas as pd
import pytest

from src.app import create_app
from src.extensions import db
from src.models.user import User
from src.models.annual_recovery import (
    AnnualRecoveryClient, AnnualRecoveryVehicle, AnnualRecoveryHistory,
)

HEADERS = ['Name', 'Cell1', 'RegNo', 'InstallationDate', 'EmployeeName',
           'Amc Charges', 'Remarks', 'MAREKA REMARKS']


@pytest.fixture(scope='module')
def crm_app():
    application = create_app('testing')
    with application.app_context():
        db.create_all()
        boss = User(username='import_admin', email='import@test.local',
                    name='Import Admin', role='admin', is_active=True)
        boss.set_password('admin123')
        db.session.add(boss)
        db.session.commit()
    yield application
    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def boss(crm_app):
    with crm_app.app_context():
        user = User.query.filter_by(username='import_admin').first()
        assert user is not None
        user_id = user.id
    client = crm_app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
    return client


@pytest.fixture(autouse=True)
def clean_recovery_tables(crm_app):
    """Each test uploads its own sheet, so start from an empty module."""
    with crm_app.app_context():
        AnnualRecoveryHistory.query.delete()
        AnnualRecoveryVehicle.query.delete()
        AnnualRecoveryClient.query.delete()
        db.session.commit()
    yield


def _workbook(rows, sheet_name='AMC JULY 2025'):
    """Build an .xlsx in memory with the real sheets' column layout."""
    buffer = io.BytesIO()
    frame = pd.DataFrame(rows, columns=HEADERS)
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        frame.to_excel(writer, sheet_name=sheet_name, index=False)
    buffer.seek(0)
    return buffer


def _upload(boss, rows, sheet_name='AMC JULY 2025'):
    data = {'file': (_workbook(rows, sheet_name), 'amc.xlsx')}
    response = boss.post('/annual-recovery/api/upload-excel',
                         data=data, content_type='multipart/form-data')
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def _row(name, reg, amc, remarks, cell='0300-1234567', date='2025-07-01'):
    return [name, cell, reg, date, 'Shaan David', amc, remarks, None]


def _vehicle(crm_app, reg):
    with crm_app.app_context():
        vehicle = AnnualRecoveryVehicle.query.filter_by(reg_no=reg).first()
        assert vehicle is not None, f'{reg} was not imported'
        return {
            'amc': vehicle.amc_charges,
            'recovered': vehicle.recovered_amount,
            'outstanding': vehicle.get_outstanding(),
            'status': vehicle.status,
        }


# --------------------------------------------------------------------------
# A PAID row carries its money across
# --------------------------------------------------------------------------

@pytest.mark.parametrize('remarks', ['RECOVERED', 'PAID', 'RECEIVED'])
def test_paid_row_records_the_amc_as_recovered(boss, crm_app, remarks):
    """The sheet states collection as wording with no figure - that means the
    whole AMC. The real files use RECOVERED mostly and PAID on some sheets."""
    _upload(boss, [_row('AD KHAN TRANSPORT', 'TLG-254', 7000, remarks)])

    assert _vehicle(crm_app, 'TLG-254') == {
        'amc': 7000.0, 'recovered': 7000.0, 'outstanding': 0.0, 'status': 'RECOVERED'}


@pytest.mark.parametrize('remarks', [
    'WILL PAY TODAY', 'WILL PAY IN JAN', 'WILL PAY BY TOM', 'WILL BY TOMORROW',
    'NR', 'REMOVAL', 'SOLD OUT', 'NSM ACCOUNT', 'PENDING', 'DEVICE MISSING',
])
def test_promise_and_status_remarks_do_not_count_as_collected(boss, crm_app, remarks):
    """Real remarks from the July sheets. A promise to pay is not a payment."""
    _upload(boss, [_row('CLIENT', 'HHH-1', 9000, remarks)])

    result = _vehicle(crm_app, 'HHH-1')
    assert result['status'] != 'RECOVERED', f'{remarks!r} imported as collected'
    assert result['recovered'] == 0.0
    assert result['outstanding'] == 9000.0


def test_pending_row_records_nothing_as_recovered(boss, crm_app):
    _upload(boss, [_row('SOME CLIENT', 'AAA-111', 9000, 'PENDING')])

    assert _vehicle(crm_app, 'AAA-111') == {
        'amc': 9000.0, 'recovered': 0.0, 'outstanding': 9000.0, 'status': 'PENDING'}


@pytest.mark.parametrize('remarks', ['UNPAID', 'NOT PAID', 'UN PAID', 'NO PAYMENT'])
def test_unpaid_wording_is_not_treated_as_paid(boss, crm_app, remarks):
    """'UNPAID' contains 'PAID' - a naive substring test would invert it."""
    _upload(boss, [_row('CLIENT', 'BBB-222', 9000, remarks)])

    result = _vehicle(crm_app, 'BBB-222')
    assert result['status'] == 'PENDING', f'{remarks!r} imported as paid'
    assert result['recovered'] == 0.0
    assert result['outstanding'] == 9000.0


def test_client_totals_include_the_recovered_money(boss, crm_app):
    _upload(boss, [
        _row('ONE CLIENT', 'CCC-1', 9000, 'PAID'),
        _row('ONE CLIENT', 'CCC-2', 9000, 'PENDING'),
    ])

    with crm_app.app_context():
        client = AnnualRecoveryClient.query.filter_by(name='ONE CLIENT').first()
        assert client is not None
        assert client.total_amc_charges == 18000.0
        assert client.total_recovered == 9000.0
        assert client.get_outstanding() == 9000.0


# --------------------------------------------------------------------------
# Repeat lines are payments, not duplicates
# --------------------------------------------------------------------------

def test_follow_up_payment_line_becomes_a_partial_recovery(boss, crm_app):
    """The real SB-3195 case: charged 9,000, later collected 7,000."""
    result = _upload(boss, [
        _row('UBAID ULLAH KHAN NIAZI', 'SB-3195', 9000, 'PENDING', date='2025-07-29'),
        _row('UBAID ULLAH KHAN NIAZI', 'SB-3195', 7000, 'PAID', date='2025-07-25'),
    ])

    assert result['count'] == 1, 'The two lines should be one vehicle'
    assert result['mergedRows'] == 1
    assert _vehicle(crm_app, 'SB-3195') == {
        'amc': 9000.0, 'recovered': 7000.0, 'outstanding': 2000.0, 'status': 'RECOVERED'}


def test_partial_recovery_is_still_marked_recovered(boss, crm_app):
    """A balance may remain; the recovery itself still happened."""
    _upload(boss, [
        _row('CLIENT', 'DDD-1', 9000, 'PENDING'),
        _row('CLIENT', 'DDD-1', 1000, 'PAID'),
    ])

    result = _vehicle(crm_app, 'DDD-1')
    assert result['status'] == 'RECOVERED'
    assert result['outstanding'] == 8000.0


def test_repeated_identical_paid_lines_do_not_over_recover(boss, crm_app):
    """The real BBR-309 case: the same payment typed three times."""
    rows = [_row('ALI HASSAN', 'BBR-309', 8000, 'PAID')] * 3
    result = _upload(boss, rows)

    assert result['count'] == 1
    assert _vehicle(crm_app, 'BBR-309') == {
        'amc': 8000.0, 'recovered': 8000.0, 'outstanding': 0.0, 'status': 'RECOVERED'}


def test_zero_value_double_line_does_not_change_the_charge(boss, crm_app):
    """The real LES-1286 case: a 0.00 line the operator marked DOUBLE."""
    _upload(boss, [
        _row('SAKHAWAT ALI', 'LES-1286', 9000, 'PENDING'),
        _row('SAKHAWAT ALI', 'LES-1286', 0, 'DOUBLE'),
    ])

    assert _vehicle(crm_app, 'LES-1286') == {
        'amc': 9000.0, 'recovered': 0.0, 'outstanding': 9000.0, 'status': 'PENDING'}


def test_instalments_add_up(boss, crm_app):
    _upload(boss, [
        _row('CLIENT', 'EEE-1', 9000, 'PENDING'),
        _row('CLIENT', 'EEE-1', 5000, 'PAID'),
        _row('CLIENT', 'EEE-1', 4000, 'PAID'),
    ])

    assert _vehicle(crm_app, 'EEE-1') == {
        'amc': 9000.0, 'recovered': 9000.0, 'outstanding': 0.0, 'status': 'RECOVERED'}


def test_the_same_registration_in_two_sheets_is_still_one_vehicle(boss, crm_app):
    """Cross-sheet duplicates keep the previous skip behaviour."""
    first = _upload(boss, [_row('CLIENT', 'FFF-1', 9000, 'PAID')], 'AMC JULY 2024')
    second = _upload(boss, [_row('CLIENT', 'FFF-1', 9000, 'PENDING')], 'AMC JULY 2025')

    assert first['count'] == 1
    assert second['count'] == 0
    assert second['skippedDuplicate'] == 1


# --------------------------------------------------------------------------
# Imported money gets a payment record behind it
# --------------------------------------------------------------------------

def _history(crm_app, reg):
    with crm_app.app_context():
        vehicle = AnnualRecoveryVehicle.query.filter_by(reg_no=reg).first()
        assert vehicle is not None
        return AnnualRecoveryHistory.query.filter_by(vehicle_id=vehicle.id).all()


def test_recovered_row_gets_a_payment_record(boss, crm_app):
    result = _upload(boss, [_row('AD KHAN TRANSPORT', 'TLG-254', 7000, 'RECOVERED')])

    assert result['recordedPayments'] == 1
    assert result['importReference'].startswith('IMPORT-')

    history = _history(crm_app, 'TLG-254')
    assert len(history) == 1
    assert history[0].amount == 7000.0
    assert history[0].payment_method == 'Imported'
    assert history[0].reference_no == result['importReference']


def test_imported_payment_carries_the_import_date_and_time(boss, crm_app):
    from datetime import datetime
    today = datetime.now().strftime('%Y-%m-%d')
    _upload(boss, [_row('CLIENT', 'III-1', 9000, 'RECOVERED')])

    record = _history(crm_app, 'III-1')[0]
    assert record.payment_date == today
    assert record.created_at is not None
    # The note must say where the figure came from, since there is no receipt.
    assert 'Imported from' in record.notes
    assert 'no receipt on file' in record.notes


def test_imported_payment_is_not_locked(boss, crm_app):
    """Unlike a real receipt, an imported figure must stay correctable."""
    _upload(boss, [_row('CLIENT', 'JJJ-1', 9000, 'RECOVERED')])

    record = _history(crm_app, 'JJJ-1')[0]
    assert record.is_locked is False

    with crm_app.app_context():
        stored = AnnualRecoveryHistory.query.get(record.id)
        assert stored is not None
        stored.amount = 8000.0
        db.session.commit()          # must not raise

        reloaded = AnnualRecoveryHistory.query.get(record.id)
        assert reloaded is not None and reloaded.amount == 8000.0


def test_pending_row_gets_no_payment_record(boss, crm_app):
    result = _upload(boss, [_row('CLIENT', 'KKK-1', 9000, 'PENDING')])

    assert result['recordedPayments'] == 0
    assert _history(crm_app, 'KKK-1') == []


def test_partial_payment_records_only_what_was_collected(boss, crm_app):
    """SB-3195 again: one record of 7,000, not 9,000."""
    _upload(boss, [
        _row('UBAID ULLAH KHAN NIAZI', 'SB-3195', 9000, 'PENDING'),
        _row('UBAID ULLAH KHAN NIAZI', 'SB-3195', 7000, 'RECOVERED'),
    ])

    history = _history(crm_app, 'SB-3195')
    assert [h.amount for h in history] == [7000.0]


def test_instalments_get_one_record_each(boss, crm_app):
    _upload(boss, [
        _row('CLIENT', 'LLL-1', 9000, 'PENDING'),
        _row('CLIENT', 'LLL-1', 5000, 'RECOVERED'),
        _row('CLIENT', 'LLL-1', 4000, 'RECOVERED'),
    ])

    history = _history(crm_app, 'LLL-1')
    assert sorted(h.amount for h in history) == [4000.0, 5000.0]


def test_the_same_payment_typed_three_times_records_once(boss, crm_app):
    """BBR-309: three identical lines must not become three payments."""
    result = _upload(boss, [_row('ALI HASSAN', 'BBR-309', 8000, 'RECOVERED')] * 3)

    assert result['recordedPayments'] == 1
    history = _history(crm_app, 'BBR-309')
    assert [h.amount for h in history] == [8000.0]


def test_payment_records_reconcile_with_the_vehicle(boss, crm_app):
    """History must always add up to the vehicle's recovered amount."""
    _upload(boss, [
        _row('CLIENT', 'MMM-1', 9000, 'RECOVERED'),
        _row('CLIENT', 'MMM-2', 9000, 'PENDING'),
        _row('CLIENT', 'MMM-3', 9000, 'PENDING'),
        _row('CLIENT', 'MMM-3', 2500, 'RECOVERED'),
    ])

    with crm_app.app_context():
        for vehicle in AnnualRecoveryVehicle.query.all():
            paid = sum(h.amount for h in
                       AnnualRecoveryHistory.query.filter_by(vehicle_id=vehicle.id).all())
            assert paid == vehicle.recovered_amount, (
                f'{vehicle.reg_no}: history {paid} != recovered {vehicle.recovered_amount}')


def test_rows_without_a_registration_are_still_skipped(boss, crm_app):
    result = _upload(boss, [
        _row('REAL CLIENT', 'GGG-1', 9000, 'PENDING'),
        _row('', '', 0, ''),
    ])

    assert result['count'] == 1
    assert result['skippedIncomplete'] == 1
