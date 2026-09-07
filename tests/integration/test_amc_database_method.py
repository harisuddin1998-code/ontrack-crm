"""
AMC Recoveries - Database Method: a day's work, not a ledger browse.

The page used to page through every row of SJ_MIS's AMCInfo ledger. That is a
record, not a worklist: it does not say who should ring whom today, and
nobody can be held to it.

It now applies the Live AMC rule to that same ledger. AMC renews annually on
the vehicle's installation anniversary, so on any date the vehicles due are
the ones whose install date's day and month match it, across every install
year on record. Those are clubbed by customer - six vehicles is one phone
call - and the customers are round-robined across the Recovery Officers, who
each see only their own.
"""
from datetime import date, datetime

import pytest

from src.app import create_app
from src.extensions import db
from src.models.amc_database_assignment import AmcDatabaseAssignment
from src.models.amc_recovery_record import AmcRecoveryRecord
from src.models.user import User
from src.services.amc_database_recovery_service import AmcDatabaseRecoveryService

PAGE = '/live-amc/database-recoveries'
DUE = date(2026, 5, 23)

_serial = iter(range(9000, 9999))


def ledger(reg, client_id, client_name, install, from_year='2026', to_year='2027',
           receivable=8000.0, received=0.0, defaulter=False, cell1=None):
    return AmcRecoveryRecord(
        serial_id=next(_serial), registration_no=reg, client_id=client_id,
        client_name=client_name, installation_date=install,
        from_year=from_year, to_year=to_year,
        receivable_amount=receivable, received_amount=received,
        is_defaulter=defaulter, cell1=cell1, synced_at=datetime.utcnow())


@pytest.fixture(scope='module')
def crm_app():
    application = create_app('testing')
    application.config['WTF_CSRF_ENABLED'] = False
    with application.app_context():
        db.create_all()

        for username, name in (('amc_one', 'Officer One'), ('amc_two', 'Officer Two')):
            officer = User(username=username, email=f'{username}@test.local',
                           name=name, role='recovery_officer', is_active=True)
            officer.set_password('pw123456')
            db.session.add(officer)

        boss = User(username='amc_admin', email='amc_admin@test.local',
                    name='AMC Admin', role='admin', is_active=True)
        boss.set_password('pw123456')
        db.session.add(boss)

        # One customer, three vehicles, installed on the same day and month
        # in three different years.
        db.session.add(ledger('AAA-001', 501, 'Alpha Logistics', date(2019, 5, 23),
                              cell1='0300-1111111'))
        db.session.add(ledger('AAA-002', 501, 'Alpha Logistics', date(2021, 5, 23),
                              cell1='0300-1111111'))
        db.session.add(ledger('AAA-003', 501, 'Alpha Logistics', date(2024, 5, 23),
                              cell1='0300-1111111'))
        # ...and an older, settled AMC period for one of them.
        db.session.add(ledger('AAA-001', 501, 'Alpha Logistics', date(2019, 5, 23),
                              from_year='2022', to_year='2023',
                              receivable=7000.0, received=7000.0, cell1='0300-1111111'))

        db.session.add(ledger('BBB-001', 502, 'Beta Transport', date(2020, 5, 23),
                              receivable=9000.0, received=1000.0, defaulter=True,
                              cell1='0321-2222222'))

        # A customer SJ_MIS has no id for.
        db.session.add(ledger('CCC-001', None, 'Gamma Haulage', date(2018, 5, 23)))
        db.session.add(ledger('CCC-002', None, 'Gamma Haulage', date(2022, 5, 23)))

        db.session.add(ledger('ZZZ-999', 599, 'Not Today Ltd', date(2020, 5, 24)))
        db.session.add(ledger('NNN-000', 600, 'No Date Ltd', None))
        db.session.commit()

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture(scope='module')
def distributed(crm_app):
    """The 23rd of May, generated once for the whole module."""
    with crm_app.app_context():
        boss_id = User.query.filter_by(username='amc_admin').one().id
        AmcDatabaseRecoveryService().get_or_create_assignments(DUE, boss_id)
    return DUE


def signed_in(crm_app, username):
    client = crm_app.test_client()
    with crm_app.app_context():
        user_id = User.query.filter_by(username=username).one().id
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
    return client


# --------------------------------------------------------------------------
# What falls due
# --------------------------------------------------------------------------

def test_the_anniversary_rule_spans_every_install_year(crm_app):
    with crm_app.app_context():
        due = {r.registration_no for r in
               AmcDatabaseRecoveryService().get_due_records(23, 5)}

    assert due == {'AAA-001', 'AAA-002', 'AAA-003', 'BBB-001', 'CCC-001', 'CCC-002'}


def test_a_vehicle_with_several_amc_periods_is_due_once(crm_app):
    """The ledger holds a row per period, so a long-standing customer's car
    is in it several times over with the same install date."""
    with crm_app.app_context():
        due = [r for r in AmcDatabaseRecoveryService().get_due_records(23, 5)
               if r.registration_no == 'AAA-001']

    assert len(due) == 1
    assert (due[0].from_year, due[0].to_year) == ('2026', '2027'), \
        'the settled 2022-2023 period was picked instead of the open one'


def test_a_vehicle_due_tomorrow_is_not_due_today(crm_app):
    with crm_app.app_context():
        due = {r.registration_no for r in
               AmcDatabaseRecoveryService().get_due_records(23, 5)}

    assert 'ZZZ-999' not in due


def test_a_ledger_row_with_no_install_date_is_never_due(crm_app):
    """Unknowable, so it cannot have an anniversary."""
    with crm_app.app_context():
        service = AmcDatabaseRecoveryService()
        all_days = set()
        for day in range(1, 32):
            all_days |= {r.registration_no for r in service.get_due_records(day, 5)}

    assert 'NNN-000' not in all_days


# --------------------------------------------------------------------------
# Clubbed by customer, round-robined by customer
# --------------------------------------------------------------------------

def test_every_due_vehicle_gets_a_follow_up(crm_app, distributed):
    with crm_app.app_context():
        rows = AmcDatabaseAssignment.query.filter_by(due_date=DUE).all()

    assert len(rows) == 6


def test_a_customer_is_one_officers_call(crm_app, distributed):
    """Distributing vehicles instead would split one customer's three cars
    across the team, and that customer would take three calls."""
    with crm_app.app_context():
        rows = AmcDatabaseAssignment.query.filter_by(due_date=DUE).all()

    per_customer = {}
    for row in rows:
        per_customer.setdefault(row.client_name, set()).add(row.assigned_officer_id)

    for name, officers in per_customer.items():
        assert len(officers) == 1, f'{name} is being rung by {len(officers)} officers'


def test_a_customer_with_no_id_is_still_clubbed(crm_app, distributed):
    with crm_app.app_context():
        rows = AmcDatabaseAssignment.query.filter_by(
            due_date=DUE, client_name='Gamma Haulage').all()

    assert len(rows) == 2
    assert len({row.assigned_officer_id for row in rows}) == 1


def test_the_work_is_spread_across_the_officers(crm_app, distributed):
    with crm_app.app_context():
        rows = AmcDatabaseAssignment.query.filter_by(due_date=DUE).all()

    assert len({row.assigned_officer_id for row in rows}) == 2


def test_a_days_list_does_not_reshuffle_once_made(crm_app, distributed):
    """An officer halfway through their calls must not have the list move."""
    with crm_app.app_context():
        service = AmcDatabaseRecoveryService()
        before = {(a.registration_no, a.assigned_officer_id)
                  for a in AmcDatabaseAssignment.query.filter_by(due_date=DUE).all()}
        again = service.get_or_create_assignments(DUE)
        after = {(a.registration_no, a.assigned_officer_id) for a in again}

    assert len(again) == 6, 'asking again created a second set'
    assert before == after


# --------------------------------------------------------------------------
# Past dates
# --------------------------------------------------------------------------

def test_a_past_date_can_be_generated_after_the_fact(crm_app):
    """The anniversary rule does not depend on when the question is asked, so
    a day that went by unworked is not lost."""
    past = date(2021, 5, 23)
    with crm_app.app_context():
        rows = AmcDatabaseRecoveryService().get_or_create_assignments(past)

        assert len(rows) == 6
        assert all(row.due_date == past for row in rows)
        assert {row.registration_no for row in rows} == {
            'AAA-001', 'AAA-002', 'AAA-003', 'BBB-001', 'CCC-001', 'CCC-002'}


def test_generating_a_future_date_is_refused(crm_app):
    """Who is on shift next month is not knowable now."""
    client = signed_in(crm_app, 'amc_admin')
    response = client.post(f'{PAGE}/generate',
                           data={'date': '2030-05-23'}, follow_redirects=True)

    assert 'has not happened yet' in response.get_data(as_text=True)
    with crm_app.app_context():
        assert AmcDatabaseAssignment.query.filter_by(due_date=date(2030, 5, 23)).count() == 0


def test_a_future_date_shows_a_count_not_a_distribution(crm_app):
    client = signed_in(crm_app, 'amc_admin')
    body = client.get(PAGE, query_string={'year': 2030, 'month': 5, 'day': 23}).get_data(as_text=True)

    assert 'This is a future date' in body


def test_redistributing_is_a_separate_deliberate_action(crm_app):
    """It discards the outcomes recorded against the day, so it cannot be
    what the ordinary generate button quietly does."""
    day = date(2022, 5, 23)
    with crm_app.app_context():
        service = AmcDatabaseRecoveryService()
        rows = service.get_or_create_assignments(day)
        rows[0].work_status = AmcDatabaseAssignment.STATUS_CONTACTED
        db.session.commit()

        service.get_or_create_assignments(day)
        assert AmcDatabaseAssignment.query.filter_by(
            due_date=day, work_status='CONTACTED').count() == 1, \
            'an ordinary generate wiped the day'

        service.get_or_create_assignments(day, regenerate=True)
        assert AmcDatabaseAssignment.query.filter_by(
            due_date=day, work_status='CONTACTED').count() == 0
        assert AmcDatabaseAssignment.query.filter_by(due_date=day).count() == 6


# --------------------------------------------------------------------------
# Individual logins
# --------------------------------------------------------------------------

def test_an_officer_sees_only_their_own_customers(crm_app, distributed):
    with crm_app.app_context():
        service = AmcDatabaseRecoveryService()
        one = User.query.filter_by(username='amc_one').one()
        two = User.query.filter_by(username='amc_two').one()
        boss = User.query.filter_by(username='amc_admin').one()

        mine = service.get_assignments_for_view(DUE, one)
        theirs = service.get_assignments_for_view(DUE, two)
        everything = service.get_assignments_for_view(DUE, boss)

        assert all(row.assigned_officer_id == one.id for row in mine)
        assert not ({r.id for r in mine} & {r.id for r in theirs})
        assert len(mine) + len(theirs) == len(everything) == 6


def test_the_page_scopes_to_the_officer_signed_in(crm_app, distributed):
    admin_body = signed_in(crm_app, 'amc_admin').get(
        PAGE, query_string={'year': DUE.year, 'month': DUE.month, 'day': DUE.day}
    ).get_data(as_text=True)
    officer_body = signed_in(crm_app, 'amc_one').get(
        PAGE, query_string={'year': DUE.year, 'month': DUE.month, 'day': DUE.day}
    ).get_data(as_text=True)

    assert admin_body.count('class="amc-customer"') == 3
    assert 0 < officer_body.count('class="amc-customer"') < 3


def test_an_officer_cannot_close_out_another_officers_customer(crm_app, distributed):
    with crm_app.app_context():
        service = AmcDatabaseRecoveryService()
        alpha = AmcDatabaseAssignment.query.filter_by(
            due_date=DUE, client_name='Alpha Logistics').first()
        owner_id = alpha.assigned_officer_id
        intruder = User.query.filter(User.role == 'recovery_officer',
                                     User.id != owner_id).first()

        updated = service.update_customer(DUE, 'id:501', work_status='SKIPPED',
                                          remarks='not mine', current_user=intruder)

        assert updated == 0
        assert AmcDatabaseAssignment.query.filter_by(
            due_date=DUE, client_name='Alpha Logistics',
            work_status='SKIPPED').count() == 0


# --------------------------------------------------------------------------
# Recording the call
# --------------------------------------------------------------------------

def test_the_day_is_read_customer_wise(crm_app, distributed):
    with crm_app.app_context():
        service = AmcDatabaseRecoveryService()
        boss = User.query.filter_by(username='amc_admin').one()
        groups = service.group_by_customer(service.get_assignments_for_view(DUE, boss))

    assert len(groups) == 3
    alpha = next(g for g in groups if g['client_name'] == 'Alpha Logistics')
    assert len(alpha['vehicles']) == 3
    assert alpha['contacts'] == ['0300-1111111'], \
        'the number is repeated under every vehicle'
    assert alpha['outstanding'] == 24000.0


def test_a_defaulter_is_flagged_on_the_customer(crm_app, distributed):
    with crm_app.app_context():
        service = AmcDatabaseRecoveryService()
        boss = User.query.filter_by(username='amc_admin').one()
        groups = service.group_by_customer(service.get_assignments_for_view(DUE, boss))

    beta = next(g for g in groups if g['client_name'] == 'Beta Transport')
    assert beta['is_defaulter']
    assert beta['outstanding'] == 8000.0, 'outstanding is receivable less received'


def test_one_call_closes_out_the_whole_customer(crm_app, distributed):
    with crm_app.app_context():
        service = AmcDatabaseRecoveryService()
        boss = User.query.filter_by(username='amc_admin').one()

        updated = service.update_customer(DUE, 'id:501', work_status='CONTACTED',
                                          remarks='Will pay Friday', current_user=boss)
        assert updated == 3

        rows = AmcDatabaseAssignment.query.filter_by(
            due_date=DUE, client_name='Alpha Logistics').all()
        assert all(row.work_status == 'CONTACTED' for row in rows)
        assert all(row.remarks == 'Will pay Friday' for row in rows)
        assert all(row.last_contacted_at is not None for row in rows)


def test_one_vehicle_can_still_be_recorded_on_its_own(crm_app, distributed):
    with crm_app.app_context():
        service = AmcDatabaseRecoveryService()
        row = AmcDatabaseAssignment.query.filter_by(
            due_date=DUE, registration_no='BBB-001').one()

        service.update_assignment(row.id, work_status='ESCALATED',
                                  remarks='Disputes the amount')

        refreshed = AmcDatabaseAssignment.query.get(row.id)
        assert refreshed.work_status == 'ESCALATED'
        assert refreshed.remarks == 'Disputes the amount'


def test_an_unknown_work_status_is_ignored(crm_app, distributed):
    with crm_app.app_context():
        service = AmcDatabaseRecoveryService()
        row = AmcDatabaseAssignment.query.filter_by(
            due_date=DUE, registration_no='BBB-001').one()

        service.update_assignment(row.id, work_status='NONSENSE')

        assert AmcDatabaseAssignment.query.get(row.id).work_status == 'ESCALATED'


# --------------------------------------------------------------------------
# The page
# --------------------------------------------------------------------------

def test_the_page_is_no_longer_a_ledger_browse(crm_app, distributed):
    body = signed_in(crm_app, 'amc_admin').get(
        PAGE, query_string={'year': DUE.year, 'month': DUE.month, 'day': DUE.day}
    ).get_data(as_text=True)

    assert 'Sync from SJ_MIS' not in body
    assert 'defaulters_only' not in body


def test_the_page_states_the_rule_it_follows(crm_app, distributed):
    body = signed_in(crm_app, 'amc_admin').get(PAGE).get_data(as_text=True)

    assert 'installation anniversary' in body


def test_the_page_summarises_the_day(crm_app, distributed):
    body = signed_in(crm_app, 'amc_admin').get(
        PAGE, query_string={'year': DUE.year, 'month': DUE.month, 'day': DUE.day}
    ).get_data(as_text=True)

    assert 'Customers To Call' in body
    assert 'Vehicles Due' in body
    assert 'RECORD ONE CALL AGAINST' in body


def test_the_calendar_counts_vehicles_not_ledger_rows(crm_app):
    with crm_app.app_context():
        matrix = AmcDatabaseRecoveryService().get_month_matrix(2026, 5)

    counts = {cell['day']: cell['count'] for cell in matrix if cell['count']}
    assert counts.get(23) == 6, 'the four AAA-001 ledger rows were counted separately'
    assert counts.get(24) == 1


def test_it_runs_itself_daily(crm_app):
    """"Fetch daily on its own" is the requirement - an officer signing in
    should already have their customers."""
    import inspect

    from src import scheduler

    source = inspect.getsource(scheduler.start_scheduler)
    assert "id='amc_database_recoveries'" in source
    assert hasattr(scheduler, 'run_amc_database_recoveries')


def test_the_daily_run_survives_sj_mis_being_unreachable(crm_app, monkeypatch):
    """A stale ledger still knows which vehicles have an anniversary today;
    no list at all helps nobody.

    The sync is stubbed rather than left to chance: whether SJ_MIS answers
    from the machine running the tests is not something a test should
    depend on, and a test suite must not reach out to a production server.
    """
    from src.services import db_sync_service

    monkeypatch.setattr(db_sync_service.DBSyncService, 'sync_amc_recoveries',
                        lambda self: {'records': 0, 'error': 1})

    with crm_app.app_context():
        result = AmcDatabaseRecoveryService().run_daily(
            target_date=date(2023, 5, 23), sync_first=True)

    assert result['synced_records'] is None, 'a failed sync should read as unknown'
    assert result['assignments'] == 6, 'the list was not built from the ledger on file'


def test_the_daily_run_refreshes_the_ledger_before_distributing(crm_app, monkeypatch):
    """A list built from a stale ledger misses a vehicle installed last
    week, so the two halves are one operation."""
    from src.services import db_sync_service

    calls = []
    monkeypatch.setattr(db_sync_service.DBSyncService, 'sync_amc_recoveries',
                        lambda self: calls.append(1) or {'records': 12, 'error': 0})

    with crm_app.app_context():
        result = AmcDatabaseRecoveryService().run_daily(
            target_date=date(2024, 5, 23), sync_first=True)

    assert calls, 'the ledger was not refreshed'
    assert result['synced_records'] == 12
    assert result['assignments'] == 6
