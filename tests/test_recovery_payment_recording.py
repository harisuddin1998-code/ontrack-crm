"""
Recording an AMC recovery payment.

The recovery history is immutable once written - a locked record cannot be
edited or deleted - so what gets stamped on it at the moment of writing is
the only version there will ever be. That makes two things worth pinning:
the timestamp has to be the real Pakistani wall-clock time of the payment,
and a proof-of-payment image has to actually arrive and be kept.
"""
import io
import os

import pytest

from src.app import create_app
from src.extensions import db
from src.models.annual_recovery import (
    AnnualRecoveryClient, AnnualRecoveryHistory, AnnualRecoveryVehicle)
from src.models.user import User
from src.utils.timezone import get_current_time

# The smallest valid PNG - enough for the server-side type and size checks.
PNG_BYTES = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08'
    b'\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00'
    b'\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82')


@pytest.fixture
def app(tmp_path):
    app = create_app('testing')
    # Proofs are written to disk; keep them out of the repo's upload folder.
    app.config['UPLOAD_FOLDER'] = str(tmp_path / 'uploads')
    with app.app_context():
        db.create_all()

        # An admin, not a recovery officer: an officer only reaches sheets
        # assigned to them, and that access rule is not what these tests are
        # about - they are about what gets written when a payment is recorded.
        supervisor = User(name='Recovery Supervisor', username='officer',
                          email='officer@ontrack.test', role='admin')
        supervisor.set_password('pw')
        db.session.add(supervisor)

        client_row = AnnualRecoveryClient(name='ACME LOGISTICS', cell1='0300-1234567',
                                          employee_name='', total_amc_charges=8000.0)
        db.session.add(client_row)
        db.session.flush()
        db.session.add(AnnualRecoveryVehicle(
            client_id=client_row.id, reg_no='TLJ-994', installation_date='2024-08-01',
            installation_year='2024', amc_charges=8000.0, recovered_amount=0.0,
            status='PENDING', sheet_name='TEST'))
        db.session.commit()

        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    c = app.test_client()
    c.post('/auth/login', data={'username': 'officer', 'password': 'pw'},
           follow_redirects=True)
    return c


def vehicle_id(app):
    with app.app_context():
        return AnnualRecoveryVehicle.query.filter_by(reg_no='TLJ-994').one().id


def record(client, app, **overrides):
    data = {
        'vehicleId': str(vehicle_id(app)),
        'amount': '8000',
        'paymentMethod': 'Cash Payment',
        'chequeStatus': '',
        'referenceNo': 'RCPT-001',
        'notes': 'Collected at the depot',
        'forceFullyRecovered': 'false',
    }
    data.update(overrides)
    return client.post('/annual-recovery/api/recover', data=data,
                       content_type='multipart/form-data')


def test_payment_records_the_date_and_the_time(client, app):
    """A date alone cannot tell two payments on the same day apart."""
    res = record(client, app)
    assert res.status_code == 200 and res.get_json()['success']

    with app.app_context():
        history = AnnualRecoveryHistory.query.one()
        # "YYYY-MM-DD HH:MM" - the time is the point.
        assert len(history.payment_date) == 16, history.payment_date
        assert history.payment_date[10] == ' '
        assert history.payment_date[13] == ':'
        assert history.payment_date.startswith(
            get_current_time().strftime('%Y-%m-%d'))

        # And the row's own stamp carries a time too, surfaced to the ledger.
        assert history.created_at is not None
        assert ':' in history.to_dict()['date']


def test_the_timestamp_is_pakistan_time_not_utc(client, app):
    """`utcnow` put every recovery on the ledger five hours early.

    A payment taken at 09:00 read as 04:00, and one taken after 19:00 read as
    the previous day - which also silently dropped it out of the dashboard's
    "AMC income received today", since that counts against this column from
    Pakistani midnight.
    """
    record(client, app)

    with app.app_context():
        history = AnnualRecoveryHistory.query.one()
        local_now = get_current_time().replace(tzinfo=None)
        drift = abs((local_now - history.created_at).total_seconds())
        assert drift < 120, (
            f'stamp {history.created_at} is {drift / 3600:.1f}h from Pakistani '
            f'now {local_now} - it is probably being written in UTC again')


def test_online_payment_requires_proof(client, app):
    res = record(client, app, paymentMethod='Online Payment')
    assert res.status_code == 400
    assert 'proof' in res.get_json()['message'].lower()

    with app.app_context():
        assert AnnualRecoveryHistory.query.count() == 0
        # The vehicle is untouched: a rejected payment recovers nothing.
        assert AnnualRecoveryVehicle.query.one().recovered_amount == 0.0


def test_online_payment_keeps_the_uploaded_image(client, app):
    res = client.post('/annual-recovery/api/recover', data={
        'vehicleId': str(vehicle_id(app)),
        'amount': '8000',
        'paymentMethod': 'Online Payment',
        'chequeStatus': '',
        'referenceNo': 'TRX-982341',
        'notes': '',
        'forceFullyRecovered': 'false',
        'proofFile': (io.BytesIO(PNG_BYTES), 'bank-receipt.png'),
    }, content_type='multipart/form-data')
    assert res.status_code == 200 and res.get_json()['success']

    with app.app_context():
        history = AnnualRecoveryHistory.query.one()
        assert history.proof_of_payment_path, 'no proof path was stored'
        stored = os.path.join(app.config['UPLOAD_FOLDER'], history.proof_of_payment_path)
        assert os.path.exists(stored), f'{stored} was not written to disk'
        assert open(stored, 'rb').read() == PNG_BYTES


def test_a_proof_that_is_not_an_image_is_refused(client, app):
    res = client.post('/annual-recovery/api/recover', data={
        'vehicleId': str(vehicle_id(app)),
        'amount': '8000',
        'paymentMethod': 'Online Payment',
        'chequeStatus': '',
        'referenceNo': 'TRX-1',
        'notes': '',
        'forceFullyRecovered': 'false',
        'proofFile': (io.BytesIO(b'%PDF-1.4'), 'receipt.pdf'),
    }, content_type='multipart/form-data')

    assert res.status_code == 400
    assert 'JPG or PNG' in res.get_json()['message']
    with app.app_context():
        assert AnnualRecoveryHistory.query.count() == 0


def test_a_cash_payment_may_also_carry_an_image(client, app):
    """Optional off-line, but accepted - a photographed receipt is worth keeping."""
    res = client.post('/annual-recovery/api/recover', data={
        'vehicleId': str(vehicle_id(app)),
        'amount': '4000',
        'paymentMethod': 'Cash Payment',
        'chequeStatus': '',
        'referenceNo': 'RCPT-77',
        'notes': '',
        'forceFullyRecovered': 'false',
        'proofFile': (io.BytesIO(PNG_BYTES), 'cash-receipt.png'),
    }, content_type='multipart/form-data')

    assert res.status_code == 200 and res.get_json()['success']
    with app.app_context():
        assert AnnualRecoveryHistory.query.one().proof_of_payment_path
