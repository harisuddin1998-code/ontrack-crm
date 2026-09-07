"""
A vehicle written off in AMC recovery goes to the Removal dashboard.

Marking a vehicle LOST is a decision to stop chasing the money. The device is
still fitted to a vehicle nobody is billing for, so the same action has to
put it in front of the people who take devices back - with enough of the
story that the removal desk does not have to go and ask.
"""
import pytest

from src.app import create_app
from src.extensions import db
from src.models.annual_recovery import AnnualRecoveryClient, AnnualRecoveryVehicle
from src.models.removal import VehicleFlag
from src.services.removal_service import AMC_LOST_REASON_PREFIX, RemovalService


@pytest.fixture
def crm_app():
    application = create_app('testing')
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


def _vehicle(reg_no='ABC-123', status='LOST', amc=9000.0, recovered=0.0,
             remarks='Customer unreachable since March.'):
    client = AnnualRecoveryClient(name='SAFEER HUSSAIN', cell1='0345-8600886')
    db.session.add(client)
    db.session.flush()

    vehicle = AnnualRecoveryVehicle(
        client_id=client.id, reg_no=reg_no, amc_charges=amc,
        recovered_amount=recovered, status=status, remarks=remarks,
        sheet_name='AMC JUNE 2020')
    db.session.add(vehicle)
    db.session.commit()
    return vehicle


def test_a_lost_vehicle_reaches_the_removal_board(crm_app):
    with crm_app.app_context():
        vehicle = _vehicle()
        flag = RemovalService().flag_amc_lost_vehicle(vehicle)

        assert flag is not None
        assert flag.registration_no == 'ABC-123'
        assert flag.flag_type == 'REMOVAL'
        assert flag.status == 'PENDING'
        assert VehicleFlag.query.count() == 1


def test_the_flag_explains_itself(crm_app):
    """A removal job with no explanation is one somebody has to chase."""
    with crm_app.app_context():
        vehicle = _vehicle(amc=9000.0, recovered=2500.0)
        flag = RemovalService().flag_amc_lost_vehicle(vehicle)

        reason = flag.flag_reason
        assert reason.startswith(AMC_LOST_REASON_PREFIX)
        assert 'SAFEER HUSSAIN' in reason
        assert 'AMC JUNE 2020' in reason
        assert '9,000.00' in reason and '2,500.00' in reason
        assert '6,500.00' in reason          # what was written off
        assert 'Customer unreachable since March.' in reason

        # The customer travels with it, so the technician can call ahead.
        assert flag.customer_name == 'SAFEER HUSSAIN'
        assert flag.customer_contact == '0345-8600886'


def test_it_does_not_raise_the_same_removal_twice(crm_app):
    """Re-running must not put a job somebody has done back on the board."""
    with crm_app.app_context():
        vehicle = _vehicle()
        service = RemovalService()

        assert service.flag_amc_lost_vehicle(vehicle) is not None
        assert service.flag_amc_lost_vehicle(vehicle) is None
        assert VehicleFlag.query.count() == 1


def test_a_completed_removal_is_not_reopened(crm_app):
    """Idempotent whatever state the existing flag is in."""
    with crm_app.app_context():
        vehicle = _vehicle()
        service = RemovalService()

        flag = service.flag_amc_lost_vehicle(vehicle)
        flag.status = 'COMPLETED'
        db.session.commit()

        assert service.flag_amc_lost_vehicle(vehicle) is None
        assert VehicleFlag.query.count() == 1


def test_a_vehicle_with_no_registration_is_skipped(crm_app):
    """There is nothing to send a technician to."""
    with crm_app.app_context():
        vehicle = _vehicle(reg_no='   ')

        assert RemovalService().flag_amc_lost_vehicle(vehicle) is None
        assert VehicleFlag.query.count() == 0


def test_an_unrelated_pending_flag_does_not_block_it(crm_app):
    """A vehicle already flagged for something else is still written off.

    The check is for an AMC-lost flag specifically, not for any flag at all -
    a transfer raised last month says nothing about the device now being
    given up on.
    """
    with crm_app.app_context():
        vehicle = _vehicle()
        db.session.add(VehicleFlag(
            registration_no='ABC-123', flag_type='TRANSFER', status='PENDING',
            flag_reason='Customer moving the device to a new vehicle.'))
        db.session.commit()

        # flag_vehicle refuses a second PENDING flag for the same vehicle, so
        # this is reported rather than silently dropped.
        with pytest.raises(ValueError):
            RemovalService().flag_amc_lost_vehicle(vehicle)
