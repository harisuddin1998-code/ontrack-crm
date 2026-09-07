"""
Regression tests for work assigned to a deleted user.

Deleting a user used to leave assignment columns pointing at an id that no
longer existed. The work then vanished from every officer's screen - the
per-officer filter (`assigned_to == me`) matches nobody - while still counting
for admin/manager, so nothing looked broken from the top. 356 Device Recovery
charges sat unseen this way, which is why a newly created officer opened the
module and found it empty.

Deleting a user must now release their work back to the pool as explicitly
unassigned, where a supervisor can see it and hand it on.
"""
import pytest

from src.app import create_app
from src.extensions import db
from src.models.user import User
from src.models.annual_recovery import AnnualRecoveryVehicle
from src.models.installation_recovery import InstallationRecoveryCharge
from src.models.redo import RedoActivity
from src.services.installation_recovery_service import InstallationRecoveryService
from src.services.user_service import UserService


@pytest.fixture
def crm_app():
    application = create_app('testing')
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


def _make_officer(username='leaver', role='device_recovery'):
    user = User(username=username, email=f'{username}@test.local',
                name=username, role=role, is_active=True)
    user.set_password('pw123456')
    db.session.add(user)
    db.session.commit()
    return user


def _charge_for(officer, reason='Power Issue'):
    activity = RedoActivity(registration_no=f'REG-{reason[:3]}', device_change_reason=reason)
    db.session.add(activity)
    db.session.flush()
    charge = InstallationRecoveryCharge(
        redo_activity_id=activity.id, reason=reason, amount=5000.0,
        status=InstallationRecoveryCharge.STATUS_PENDING,
        assigned_officer_id=officer.id)
    db.session.add(charge)
    db.session.commit()
    return charge


def test_deleting_a_user_releases_their_device_recovery_charges(crm_app):
    with crm_app.app_context():
        officer = _make_officer()
        charge = _charge_for(officer)
        officer_id, charge_id = officer.id, charge.id

        UserService().delete(officer_id)

        released = InstallationRecoveryCharge.query.get(charge_id)
        assert released is not None, 'The charge itself must survive the user'
        assert released.assigned_officer_id is None, (
            'Charge still points at a deleted user - it is invisible to everyone')


def test_no_charge_is_left_pointing_at_a_missing_user(crm_app):
    """The exact condition that hid 356 charges."""
    with crm_app.app_context():
        officer = _make_officer()
        for reason in ('Power Issue', 'Device Damage', 'Device Missing'):
            _charge_for(officer, reason)

        UserService().delete(officer.id)

        live_ids = {u.id for u in User.query.all()}
        orphaned = [c.id for c in InstallationRecoveryCharge.query.all()
                    if c.assigned_officer_id is not None
                    and c.assigned_officer_id not in live_ids]
        assert orphaned == [], f'Charges orphaned by the delete: {orphaned}'


def test_released_charges_are_visible_to_a_supervisor(crm_app):
    """Released work must resurface so it can be handed on, not disappear."""
    with crm_app.app_context():
        officer = _make_officer()
        _charge_for(officer)
        boss = _make_officer('boss', role='admin')

        UserService().delete(officer.id)

        visible = InstallationRecoveryService().get_charges_for_view(boss)
        assert len(visible) == 1
        assert visible[0].assigned_officer_id is None


def test_annual_recovery_sheets_are_released_too(crm_app):
    """The same column shape exists on recovery vehicles."""
    with crm_app.app_context():
        officer = _make_officer('sheet_leaver', role='recovery_officer')
        vehicle = AnnualRecoveryVehicle(reg_no='REL-1', sheet_name='AMC JULY 2025',
                                        amc_charges=9000.0, assigned_to=officer.id)
        db.session.add(vehicle)
        db.session.commit()
        vehicle_id = vehicle.id

        UserService().delete(officer.id)

        released = AnnualRecoveryVehicle.query.get(vehicle_id)
        assert released is not None
        assert released.assigned_to is None


def test_other_users_assignments_are_untouched(crm_app):
    with crm_app.app_context():
        leaver = _make_officer('leaver')
        keeper = _make_officer('keeper')
        leaver_charge = _charge_for(leaver, 'Power Issue')
        keeper_charge = _charge_for(keeper, 'Device Damage')
        keeper_id, keeper_charge_id = keeper.id, keeper_charge.id

        UserService().delete(leaver.id)

        assert InstallationRecoveryCharge.query.get(leaver_charge.id).assigned_officer_id is None
        assert InstallationRecoveryCharge.query.get(keeper_charge_id).assigned_officer_id == keeper_id


def test_deleting_a_user_with_no_assigned_work_still_works(crm_app):
    with crm_app.app_context():
        officer = _make_officer('idle')
        assert UserService().delete(officer.id) is True
        assert User.query.filter_by(username='idle').first() is None
