"""
The greeting a user is met with when they sign in.

Arriving on time is greeted, arriving after 10:30 is noted, and arriving late
several days running is named as a habit. The rules are about the *first*
sign-in of a day, which is the only one that says anything about when
somebody actually started.
"""
from datetime import datetime

import pytest

from src.app import create_app
from src.extensions import db
from src.models.user import User
from src.services.auth_service import AuthService, HABITUAL_AFTER_DAYS


@pytest.fixture
def crm_app():
    application = create_app('testing')
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def worker(crm_app):
    with crm_app.app_context():
        user = User(username='aimen', email='aimen@test.local', name='Aimen',
                    role='sales', is_active=True)
        user.set_password('pw123456')
        db.session.add(user)
        db.session.commit()
        yield user


def _arrive(service, user, when):
    service.record_attendance(user, when)
    return service.greeting(user, when)


def test_on_time_is_greeted_by_name(crm_app, worker):
    service = AuthService()
    greeting = _arrive(service, worker, datetime(2026, 8, 10, 9, 5))

    assert greeting == 'Good morning, Aimen — hope you are doing well.'
    assert worker.late_login_streak == 0


def test_the_greeting_follows_the_time_of_day(crm_app, worker):
    service = AuthService()
    assert service.greeting(worker, datetime(2026, 8, 10, 8, 0)).startswith('Good morning')
    assert service.greeting(worker, datetime(2026, 8, 10, 13, 0)).startswith('Good afternoon')
    assert service.greeting(worker, datetime(2026, 8, 10, 19, 0)).startswith('Good evening')


def test_after_half_past_ten_is_late(crm_app, worker):
    service = AuthService()
    greeting = _arrive(service, worker, datetime(2026, 8, 10, 10, 31))

    assert greeting == 'Good morning, Aimen — you are late today.'
    assert worker.late_login_streak == 1


def test_half_past_ten_exactly_is_not_late(crm_app, worker):
    """The rule is 'after 10:30', so 10:30 itself is on time."""
    service = AuthService()
    greeting = _arrive(service, worker, datetime(2026, 8, 10, 10, 30))

    assert 'late' not in greeting
    assert worker.late_login_streak == 0


def test_signing_in_again_the_same_day_is_not_a_second_arrival(crm_app, worker):
    """Somebody who starts at 09:00 and signs in after lunch arrived once.

    Judging every sign-in would make almost everybody late by mid-afternoon.
    """
    service = AuthService()
    _arrive(service, worker, datetime(2026, 8, 10, 9, 0))
    greeting = _arrive(service, worker, datetime(2026, 8, 10, 15, 45))

    assert worker.late_login_streak == 0
    assert greeting == 'Good afternoon, Aimen — hope you are doing well.'


def test_three_late_days_running_is_a_habit(crm_app, worker):
    service = AuthService()

    greetings = [_arrive(service, worker, datetime(2026, 8, day, 11, 0))
                 for day in (10, 11, 12)]

    assert worker.late_login_streak == HABITUAL_AFTER_DAYS
    assert greetings[0].endswith('you are late today.')
    assert greetings[1].endswith('you are late today.')
    assert greetings[2] == ('Good morning, Aimen — you have become habitual. '
                            'Please improve your timings.')


def test_an_on_time_day_clears_the_habit(crm_app, worker):
    """The streak measures a habit, not a lifetime tally of late mornings."""
    service = AuthService()
    for day in (10, 11, 12):
        _arrive(service, worker, datetime(2026, 8, day, 11, 0))
    assert worker.late_login_streak == 3

    greeting = _arrive(service, worker, datetime(2026, 8, 13, 9, 30))
    assert worker.late_login_streak == 0
    assert greeting == 'Good morning, Aimen — hope you are doing well.'

    # And the next late day starts counting again from one, not from four.
    _arrive(service, worker, datetime(2026, 8, 14, 11, 0))
    assert worker.late_login_streak == 1


def test_yesterdays_lateness_is_not_todays(crm_app, worker):
    """A late Monday must not make Tuesday morning read as late."""
    service = AuthService()
    _arrive(service, worker, datetime(2026, 8, 10, 11, 0))

    assert 'late' not in service.greeting(worker, datetime(2026, 8, 11, 9, 0))


def test_signing_in_records_the_arrival(crm_app, worker):
    """The greeting is built from what signing in stored, not recomputed."""
    with crm_app.app_context():
        user = AuthService().authenticate('aimen', 'pw123456', ip_address='127.0.0.1')

        assert user is not None
        assert user.last_login_day is not None
        assert user.last_login is not None
