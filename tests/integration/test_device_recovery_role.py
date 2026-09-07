"""
Regression tests for the standalone `device_recovery` role.

Device Recovery (Power Issue / Device Damage / Device Missing) used to be
reachable only by holding `payment_recovery`, which also grants the Installation
Payment Recovery ledger - so it could not be handed to someone as a standalone
Additional View. It is now its own role, which must:

  * open the Device Recovery screens,
  * NOT open the PO payment ledger that payment_recovery carries,
  * see only its own assigned charges, like any other officer, and
  * be in the round-robin so charges actually reach it.
"""
import pytest

from src.app import create_app, ROLE_LANDING_PAGES
from src.extensions import db
from src.models.user import User
from src.models.installation_recovery import InstallationRecoveryCharge
from src.services.installation_recovery_service import InstallationRecoveryService

XHR = {'X-Requested-With': 'XMLHttpRequest'}

DEVICE_RECOVERY_PATHS = [
    '/payment/installation-recovery',
    '/payment/installation-recovery/followup-report',
]
PAYMENT_LEDGER_PATHS = [
    '/payment/dashboard',
    '/payment/list',
]


@pytest.fixture(scope='module')
def crm_app():
    application = create_app('testing')

    with application.app_context():
        db.create_all()
        for username, role in (
            ('dr_officer', 'device_recovery'),
            ('dr_other', 'device_recovery'),
            ('ir_officer', 'payment_recovery'),
            ('dr_admin', 'admin'),
        ):
            user = User(username=username, email=f'{username}@test.local',
                        name=username, role=role, is_active=True)
            user.set_password('pw123456')
            db.session.add(user)
        db.session.commit()

        # A charge hangs off a REDO activity, so seed one per charge.
        from src.models.redo import RedoActivity

        mine = User.query.filter_by(username='dr_officer').first()
        theirs = User.query.filter_by(username='dr_other').first()
        assert mine is not None and theirs is not None
        for reason, owner in (('Power Issue', mine), ('Device Damage', theirs)):
            activity = RedoActivity(registration_no=f'TEST-{reason[:3].upper()}',
                                    device_change_reason=reason)
            db.session.add(activity)
            db.session.flush()
            db.session.add(InstallationRecoveryCharge(
                redo_activity_id=activity.id,
                reason=reason,
                amount=5000.0,
                status=InstallationRecoveryCharge.STATUS_PENDING,
                assigned_officer_id=owner.id,
            ))
        db.session.commit()

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()


def _client(crm_app, username):
    with crm_app.app_context():
        user = User.query.filter_by(username=username).first()
        assert user is not None
        user_id = user.id
    client = crm_app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
    return client


# --------------------------------------------------------------------------
# The role exists and is offerable on the user form
# --------------------------------------------------------------------------

def test_device_recovery_is_a_known_role():
    assert 'device_recovery' in User.ROLES


def test_device_recovery_is_offered_as_an_additional_view(crm_app):
    """It must appear in Additional Views, or it cannot be granted at all."""
    from src.forms.admin_forms import UserForm

    with crm_app.test_request_context():
        form = UserForm()
        additional = [choice[0] for choice in (form.additional_roles.choices or [])]
        primary = [choice[0] for choice in (form.role.choices or [])]

    assert 'device_recovery' in additional
    assert 'device_recovery' in primary


def test_device_recovery_has_a_readable_display_name():
    """The role chip needs a name, not a slug.

    `get_role_display` feeds the compact badge next to the username, so it
    stays short like its neighbours ('Inst. Recovery', 'AMC Recovery'). The
    long form, "Device Recovery (Power/Damage/Missing)", is the sidebar and
    user-form label - a different place with room for it. What matters here
    is that the role does not fall through to a title-cased slug.
    """
    user = User(username='x', email='x@x.com', role='device_recovery')
    display = user.get_role_display()

    assert display == 'Device Recovery'
    assert display != 'Device_Recovery', 'Role fell through to the slug fallback'
    assert user.is_device_recovery() is True


def test_device_recovery_is_labelled_in_full_where_a_user_picks_it():
    """The user form and sidebar spell out what the role covers."""
    from src.forms.admin_forms import UserForm

    app = create_app('testing')
    with app.test_request_context():
        form = UserForm()
        labels = dict(form.additional_roles.choices or [])

    assert labels['device_recovery'] == 'Device Recovery (Power/Damage/Missing)'


def test_device_recovery_has_a_landing_page():
    assert ROLE_LANDING_PAGES['device_recovery'] == 'payment.installation_recovery_dashboard'


# --------------------------------------------------------------------------
# What the role opens, and what it must not
# --------------------------------------------------------------------------

@pytest.mark.parametrize('path', DEVICE_RECOVERY_PATHS)
def test_role_opens_the_device_recovery_screens(crm_app, path):
    assert _client(crm_app, 'dr_officer').get(path).status_code == 200


@pytest.mark.parametrize('path', PAYMENT_LEDGER_PATHS)
def test_role_does_not_open_the_installation_payment_ledger(crm_app, path):
    """The whole point of splitting it out: Device Recovery without the PO
    payment ledger that payment_recovery also carries."""
    response = _client(crm_app, 'dr_officer').get(path, headers=XHR)
    assert response.status_code == 403, f'{path} was reachable by device_recovery'


def test_installation_recovery_officer_still_opens_both(crm_app):
    officer = _client(crm_app, 'ir_officer')
    for path in DEVICE_RECOVERY_PATHS + PAYMENT_LEDGER_PATHS:
        assert officer.get(path).status_code == 200, f'{path} broke for payment_recovery'


def test_landing_redirect_reaches_device_recovery_without_a_loop(crm_app):
    client = _client(crm_app, 'dr_officer')

    response = client.get('/')
    assert response.status_code == 302
    assert '/payment/installation-recovery' in response.headers['Location']
    assert client.get(response.headers['Location']).status_code == 200


def test_dashboard_redirect_does_not_send_the_role_to_login(crm_app):
    """The old /auth/dashboard-redirect chain named neither role and fell
    through to the login page - the start of the redirect loop."""
    response = _client(crm_app, 'dr_officer').get('/auth/dashboard-redirect')
    assert response.status_code == 302
    assert '/auth/login' not in response.headers['Location']
    assert '/payment/installation-recovery' in response.headers['Location']


# --------------------------------------------------------------------------
# Scoping: an officer sees only their own charges
# --------------------------------------------------------------------------

def test_role_sees_only_its_own_assigned_charges(crm_app):
    """Without this the role matched no scoping branch and saw everything."""
    with crm_app.app_context():
        user = User.query.filter_by(username='dr_officer').first()
        charges = InstallationRecoveryService().get_charges_for_view(user)

    assert [c.reason for c in charges] == ['Power Issue']


def test_admin_still_sees_every_charge(crm_app):
    with crm_app.app_context():
        boss = User.query.filter_by(username='dr_admin').first()
        charges = InstallationRecoveryService().get_charges_for_view(boss)

    assert len(charges) == 2


def test_role_cannot_read_another_officers_charge(crm_app):
    with crm_app.app_context():
        theirs = InstallationRecoveryCharge.query.filter_by(reason='Device Damage').first()
        assert theirs is not None
        charge_id = theirs.id

    response = _client(crm_app, 'dr_officer').get(
        f'/payment/installation-recovery/{charge_id}/details', headers=XHR)
    assert response.status_code == 403


def test_role_is_in_the_charge_assignment_rotation(crm_app):
    """Granting the role must also make the user assignable, or they get a
    permanently empty screen."""
    with crm_app.app_context():
        officers = InstallationRecoveryService().get_officers()
        usernames = {u.username for u in officers}

    assert {'dr_officer', 'dr_other'} <= usernames
    assert 'ir_officer' in usernames, 'Existing officers must stay in the rotation'


# --------------------------------------------------------------------------
# Reassignment: a supervisor can move a charge between officers
# --------------------------------------------------------------------------
#
# Round-robin only assigns at creation time, so an officer added after the
# backlog was raised owns none of it and opens a permanently empty screen -
# which reads as a permissions fault but is not one. Reassignment is the way
# out, and it belongs to supervisors: an officer clearing their own list, or
# pushing work onto a colleague, is not their call to make.


def _open_charge_of(crm_app, username):
    with crm_app.app_context():
        owner = User.query.filter_by(username=username).first()
        charge = InstallationRecoveryCharge.query.filter_by(
            assigned_officer_id=owner.id).first()
        assert charge is not None
        return charge.id, owner.id


def test_supervisor_can_move_a_charge_to_another_officer(crm_app):
    charge_id, _ = _open_charge_of(crm_app, 'dr_officer')
    with crm_app.app_context():
        target = User.query.filter_by(username='dr_other').first().id

        moved = InstallationRecoveryService().reassign_charge(charge_id, target)
        assert moved is not None
        assert moved.assigned_officer_id == target
        assert moved.assigned_at is not None

        # It leaves the old officer's list and joins the new one's.
        mine = User.query.filter_by(username='dr_officer').first()
        theirs = User.query.filter_by(username='dr_other').first()
        service = InstallationRecoveryService()
        assert charge_id not in [c.id for c in service.get_charges_for_view(mine)]
        assert charge_id in [c.id for c in service.get_charges_for_view(theirs)]

        # put it back for the tests that follow
        InstallationRecoveryService().reassign_charge(charge_id, mine.id)


def test_a_charge_cannot_be_assigned_to_someone_outside_device_recovery(crm_app):
    """Every officer's list is filtered to their own id, so parking a charge
    on a user who works something else hides it from all of them at once."""
    charge_id, owner_id = _open_charge_of(crm_app, 'dr_officer')
    with crm_app.app_context():
        outsider = User(username='dr_outsider', email='dr_outsider@test.local',
                        name='Outsider', role='sales', is_active=True)
        outsider.set_password('pw123456')
        db.session.add(outsider)
        db.session.commit()

        assert InstallationRecoveryService().reassign_charge(charge_id, outsider.id) is None
        assert InstallationRecoveryCharge.query.get(charge_id).assigned_officer_id == owner_id


def test_a_charge_cannot_be_assigned_to_a_deactivated_officer(crm_app):
    charge_id, owner_id = _open_charge_of(crm_app, 'dr_officer')
    with crm_app.app_context():
        retired = User(username='dr_retired', email='dr_retired@test.local',
                       name='Retired', role='device_recovery', is_active=False)
        retired.set_password('pw123456')
        db.session.add(retired)
        db.session.commit()

        assert InstallationRecoveryService().reassign_charge(charge_id, retired.id) is None
        assert InstallationRecoveryCharge.query.get(charge_id).assigned_officer_id == owner_id


def test_an_unknown_charge_is_refused(crm_app):
    with crm_app.app_context():
        target = User.query.filter_by(username='dr_other').first().id
        assert InstallationRecoveryService().reassign_charge(999999, target) is None


def test_only_supervisors_reach_the_assign_route(crm_app):
    charge_id, _ = _open_charge_of(crm_app, 'dr_officer')
    with crm_app.app_context():
        target = User.query.filter_by(username='dr_other').first().id

    for username in ('dr_officer', 'ir_officer'):
        response = _client(crm_app, username).post(
            f'/payment/installation-recovery/{charge_id}/assign',
            data={'officer_id': target}, headers=XHR)
        assert response.status_code == 403, f'{username} could reassign a charge'

    with crm_app.app_context():
        unchanged = InstallationRecoveryCharge.query.get(charge_id)
        assert unchanged.assigned_officer_id != target


def test_the_assign_control_is_shown_to_supervisors_only(crm_app):
    """The button and its modal are rendered off the officer roster, which
    the view hands to supervisors only."""
    boss = _client(crm_app, 'dr_admin').get('/payment/installation-recovery')
    officer = _client(crm_app, 'dr_officer').get('/payment/installation-recovery')

    assert 'openAssignModal(' in boss.get_data(as_text=True)
    assert 'id="irAssignModal"' in boss.get_data(as_text=True)
    assert 'id="irAssignModal"' not in officer.get_data(as_text=True)


def test_the_device_recovery_screen_offers_no_way_into_the_payment_ledger(crm_app):
    """The screen carried an unguarded 'Installation Payment Recovery' back
    button, so the role was shown a door it would be turned away from."""
    officer = _client(crm_app, 'dr_officer').get('/payment/installation-recovery')
    boss = _client(crm_app, 'ir_officer').get('/payment/installation-recovery')

    assert 'href="/payment/dashboard"' not in officer.get_data(as_text=True)
    assert 'href="/payment/dashboard"' in boss.get_data(as_text=True)
