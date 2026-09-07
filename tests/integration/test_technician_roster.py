"""
A technician offered anywhere in the CRM is a technician in Technician
Management.

Two modules got this wrong, and got it wrong in a way that was invisible on
screen. Complaints listed technicians from the roster but saved the chosen id
into a column pointing at `users`, so the name read back was whoever happened
to hold that id as a login. Removal did the mirror image: it listed logins
under a label saying "Technician", so the roster and the record could never
agree on who did the job - and the Technician Performance report, which
reconciles four job tables by name, counted a login as a technician.

Both now carry `technician_id` against `technicians`, and every picker in the
CRM reads one list: TechnicianService.get_roster().
"""
import pytest

from src.app import create_app
from src.extensions import db
from src.models.complaint import Complaint
from src.models.removal import (RemovalRetainedActivity, RemovalTransferActivity,
                                VehicleFlag)
from src.models.technician import Technician
from src.models.user import User
from src.services.technician_activity_service import TechnicianActivityService
from src.services.technician_service import TechnicianService


@pytest.fixture(scope='module')
def crm_app():
    application = create_app('testing')
    with application.app_context():
        db.create_all()

        boss = User(username='tr_admin', email='tr_admin@test.local',
                    name='Roster Admin', role='admin', is_active=True)
        boss.set_password('pw123456')
        # A login whose name could be mistaken for a technician, and whose id
        # collides with a technician's id - which is exactly how the old bug
        # showed the wrong name.
        remover = User(username='tr_removal', email='tr_removal@test.local',
                       name='Not A Technician', role='removal', is_active=True)
        remover.set_password('pw123456')
        db.session.add_all([boss, remover])

        db.session.add_all([
            Technician(name='AARON ACTIVE', contact='0300-1111111', is_active=True),
            Technician(name='BILAL ACTIVE', contact='0300-2222222', is_active=True),
            Technician(name='ZAIN RETIRED', contact='0300-3333333', is_active=False),
        ])
        db.session.commit()

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def admin(crm_app):
    client = crm_app.test_client()
    with crm_app.app_context():
        user_id = User.query.filter_by(username='tr_admin').first().id
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
    return client


# --------------------------------------------------------------------------
# One roster, read one way
# --------------------------------------------------------------------------

def test_the_roster_is_the_active_technicians(crm_app):
    with crm_app.app_context():
        names = [t.name for t in TechnicianService.get_roster()]

    assert names == ['AARON ACTIVE', 'BILAL ACTIVE'], names


def test_a_retired_technician_is_not_offered(crm_app):
    """Deactivating someone in Technician Management has to take them off
    every dropdown, or deactivating means nothing."""
    with crm_app.app_context():
        assert 'ZAIN RETIRED' not in [t.name for t in TechnicianService.get_roster()]


def test_the_roster_is_ordered_for_reading(crm_app):
    """A dropdown ordered by insertion id makes people hunt."""
    with crm_app.app_context():
        names = [t.name for t in TechnicianService.get_roster()]

    assert names == sorted(names)


def test_no_login_is_ever_on_the_roster(crm_app):
    with crm_app.app_context():
        roster = {t.name for t in TechnicianService.get_roster()}
        logins = {u.name for u in User.query.all()}

    assert not (roster & logins), 'a login is being offered as a technician'


# --------------------------------------------------------------------------
# Complaints
# --------------------------------------------------------------------------

def test_the_complaint_form_offers_only_the_roster(admin, crm_app):
    body = admin.get('/complaints/new').get_data(as_text=True)

    assert 'name="technician_id"' in body
    assert 'AARON ACTIVE' in body
    assert 'ZAIN RETIRED' not in body
    assert 'Not A Technician' not in body


def test_a_complaint_records_the_technician_not_a_login(admin, crm_app):
    with crm_app.app_context():
        technician = Technician.query.filter_by(name='BILAL ACTIVE').one()
        technician_id = technician.id

    admin.post('/complaints/new', data={
        'customer_name': 'Roster Customer', 'customer_contact': '0300-9998888',
        'reg_no': 'TR-1001', 'city': 'LAHORE',
        'complaint_type': 'GPS_NOT_WORKING', 'severity': 'HIGH',
        'description': 'Assigned from the roster.',
        'technician_id': technician_id,
    }, follow_redirects=True)

    with crm_app.app_context():
        ticket = Complaint.query.filter_by(reg_no='TR-1001').one()
        assert ticket.technician_id == technician_id
        assert ticket.technician.name == 'BILAL ACTIVE'


def test_the_ticket_shows_the_technicians_own_name(admin, crm_app):
    """The whole point of the fix: the name on the board is the name of the
    person who was chosen."""
    with crm_app.app_context():
        ticket = Complaint.query.filter_by(reg_no='TR-1001').one()
        payload = ticket.to_dict()

    assert payload['technician_name'] == 'BILAL ACTIVE'
    assert 'assigned_user_name' not in payload

    body = admin.get('/complaints/').get_data(as_text=True)
    assert 'BILAL ACTIVE' in body


def test_assigning_a_ticket_to_someone_off_the_roster_is_refused(admin, crm_app):
    with crm_app.app_context():
        ticket_id = Complaint.query.filter_by(reg_no='TR-1001').one().id
        retired_id = Technician.query.filter_by(name='ZAIN RETIRED').one().id

    admin.post(f'/complaints/{ticket_id}/assign',
               data={'technician_id': retired_id}, follow_redirects=True)

    with crm_app.app_context():
        assert Complaint.query.get(ticket_id).technician.name == 'BILAL ACTIVE'


def test_a_ticket_can_be_reassigned_within_the_roster(admin, crm_app):
    with crm_app.app_context():
        ticket_id = Complaint.query.filter_by(reg_no='TR-1001').one().id
        aaron_id = Technician.query.filter_by(name='AARON ACTIVE').one().id

    admin.post(f'/complaints/{ticket_id}/assign',
               data={'technician_id': aaron_id}, follow_redirects=True)

    with crm_app.app_context():
        ticket = Complaint.query.get(ticket_id)
        assert ticket.technician.name == 'AARON ACTIVE'
        assert ticket.status == 'IN_PROGRESS'
        assert ticket.assigned_at is not None


# --------------------------------------------------------------------------
# Removal
# --------------------------------------------------------------------------

def test_the_removal_flag_screen_offers_only_the_roster(admin, crm_app):
    with crm_app.app_context():
        flag = VehicleFlag(registration_no='TR-2002', customer_name='Flagged Customer',
                           flag_reason='Customer ended service', flag_type='REMOVAL',
                           status='PENDING')
        db.session.add(flag)
        db.session.commit()
        flag_id = flag.id

    body = admin.get(f'/removal/flag/{flag_id}').get_data(as_text=True)

    assert 'AARON ACTIVE' in body
    assert 'Not A Technician' not in body, 'a login is offered as a technician'


def test_a_removal_records_the_technician_not_a_login(admin, crm_app):
    with crm_app.app_context():
        flag_id = VehicleFlag.query.filter_by(registration_no='TR-2002').one().id
        technician_id = Technician.query.filter_by(name='AARON ACTIVE').one().id

    admin.post(f'/removal/flag/{flag_id}/assign',
               data={'technician_id': technician_id}, follow_redirects=True)

    with crm_app.app_context():
        flag = VehicleFlag.query.get(flag_id)
        assert flag.technician_id == technician_id
        assert flag.technician.name == 'AARON ACTIVE'
        assert flag.status == 'IN_PROGRESS'


def test_the_officer_who_owns_a_case_is_still_a_login(crm_app):
    """The two are different people and both are kept: `assigned_to` is the
    removal officer whose dashboard scopes to their own work, `technician_id`
    is who physically does the job."""
    with crm_app.app_context():
        flag = VehicleFlag.query.filter_by(registration_no='TR-2002').one()
        officer = User.query.filter_by(username='tr_removal').one()

        flag.assigned_to = officer.id
        db.session.commit()

        reloaded = VehicleFlag.query.get(flag.id)
        assert reloaded.assigned_to_user.name == 'Not A Technician'
        assert reloaded.technician.name == 'AARON ACTIVE'


# --------------------------------------------------------------------------
# The report that reconciles them
# --------------------------------------------------------------------------

def test_technician_performance_counts_technicians_not_logins(crm_app):
    """Removals and transfers used to be filed under the removal officer's
    login name, which put a person who is not a technician into a report
    about technicians."""
    with crm_app.app_context():
        aaron_id = Technician.query.filter_by(name='AARON ACTIVE').one().id
        officer_id = User.query.filter_by(username='tr_removal').one().id

        db.session.add(RemovalRetainedActivity(
            registration_no='TR-3003', customer_name='Retained Customer',
            technician_id=aaron_id, assigned_to=officer_id, status='COMPLETED'))
        db.session.add(RemovalTransferActivity(
            old_registration_no='TR-4004', new_registration_no='TR-5005',
            old_customer_name='Transfer Customer',
            technician_id=aaron_id, assigned_to=officer_id, status='PENDING'))
        db.session.commit()

        rows = TechnicianActivityService().wallboard_rows()

    names = {row['technician'] for row in rows}
    assert 'AARON ACTIVE' in names
    assert 'Not A Technician' not in names, 'a login is counted as a technician'

    aaron = next(row for row in rows if row['technician'] == 'AARON ACTIVE')
    assert aaron['removals_completed'] == 1
    assert aaron['transfers_pending'] == 1


def test_every_active_technician_appears_even_with_no_work(crm_app):
    """An absent row reads as "no data"; a zero row reads as "no work"."""
    with crm_app.app_context():
        rows = TechnicianActivityService().wallboard_rows()

    bilal = next((row for row in rows if row['technician'] == 'BILAL ACTIVE'), None)
    assert bilal is not None
    assert bilal['total_assigned'] == 0
