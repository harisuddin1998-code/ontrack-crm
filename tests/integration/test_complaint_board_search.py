"""
The complaint board is a list you search, not a board you scan.

The Kanban was three columns of cards. A ticket is worked from its number,
its vehicle or the customer's phone - and none of those are things you find by
scanning cards, which is why the board had a search box that took one string
and matched three fields with an OR.

It is now a list with five fields: ticket number, registration, contact
number, and a logged-from/logged-to date window. They are AND-ed, so a date
range plus a registration means "that vehicle, in that window".
"""
from datetime import datetime, timedelta

import pytest

from src.app import create_app
from src.extensions import db
from src.models.complaint import Complaint
from src.models.user import User

BOARD = '/complaints/'


@pytest.fixture(scope='module')
def crm_app():
    application = create_app('testing')
    with application.app_context():
        db.create_all()

        manager = User(username='cb_mgr', email='cb_mgr@test.local',
                       name='Board Manager', role='complaint_manager', is_active=True)
        manager.set_password('pw123456')
        db.session.add(manager)

        now = datetime.now()
        tickets = [
            # ticket_no, customer, contact, reg, severity, status, days ago
            ('CMP-2026-9001', 'Alpha Freight', '0300-1112222', 'AAA-111', 'HIGH', 'OPEN', 0),
            ('CMP-2026-9002', 'Beta Movers', '0321 333 4444', 'BBB-222', 'CRITICAL', 'OPEN', 3),
            ('CMP-2026-9003', 'Gamma Cargo', '+92-333-5556666', 'CCC-333', 'LOW', 'RESOLVED', 30),
            ('CMP-2026-9004', 'Delta Haulage', '0300-1112222', 'DDD-444', 'MEDIUM', 'IN_PROGRESS', 200),
        ]
        for ticket_no, customer, contact, reg, severity, status, days in tickets:
            db.session.add(Complaint(
                ticket_no=ticket_no, customer_name=customer, customer_contact=contact,
                reg_no=reg, city='LAHORE', complaint_type='GPS_NOT_WORKING',
                severity=severity, status=status,
                description=f'Reported by {customer}.',
                created_at=now - timedelta(days=days)))
        db.session.commit()

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def manager(crm_app):
    client = crm_app.test_client()
    with crm_app.app_context():
        user_id = User.query.filter_by(username='cb_mgr').first().id
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
    return client


def tickets_on(body):
    """The ticket numbers a rendered board is showing.

    Matched between tags so the example number in the search box's
    placeholder is not mistaken for a result.
    """
    import re
    return set(re.findall(r'>(CMP-2026-\d{4})<', body))


# --------------------------------------------------------------------------
# The Kanban is gone
# --------------------------------------------------------------------------

def test_the_kanban_board_is_gone(manager):
    body = manager.get(BOARD).get_data(as_text=True)

    assert 'view-kanban' not in body
    assert 'kanban-column' not in body
    assert 'odoo-kanban-wrapper' not in body


def test_there_is_no_view_toggle_left(manager):
    """Removing one of two views and leaving the switch is worse than
    either."""
    body = manager.get(BOARD).get_data(as_text=True)

    assert 'switchView' not in body
    assert 'btn-kanban-view' not in body
    assert 'btn-list-view' not in body


def test_what_is_left_is_a_list(manager):
    body = manager.get(BOARD).get_data(as_text=True)

    assert 'o_list_table' in body
    assert tickets_on(body) == {'CMP-2026-9001', 'CMP-2026-9002',
                                'CMP-2026-9003', 'CMP-2026-9004'}


def test_the_list_says_when_each_ticket_was_logged(manager):
    """A date search is no use if the dates are not on screen."""
    body = manager.get(BOARD).get_data(as_text=True)

    assert '>LOGGED<' in body


# --------------------------------------------------------------------------
# The search fields
# --------------------------------------------------------------------------

@pytest.mark.parametrize('field,label', [
    ('ticket_no', 'TICKET NUMBER'),
    ('reg_no', 'REGISTRATION NUMBER'),
    ('contact', 'CONTACT NUMBER'),
    ('date_from', 'LOGGED FROM'),
    ('date_to', 'LOGGED TO'),
])
def test_every_search_field_is_on_the_board(field, label, manager):
    body = manager.get(BOARD).get_data(as_text=True)

    assert f'name="{field}"' in body, f'{label} cannot be searched'
    assert label in body, f'{label} has no label'


def test_searching_by_ticket_number(manager):
    body = manager.get(BOARD, query_string={'ticket_no': 'CMP-2026-9002'}).get_data(as_text=True)

    assert tickets_on(body) == {'CMP-2026-9002'}


def test_a_partial_ticket_number_still_finds_it(manager):
    """Nobody types a whole ticket number off a phone call."""
    body = manager.get(BOARD, query_string={'ticket_no': '9003'}).get_data(as_text=True)

    assert tickets_on(body) == {'CMP-2026-9003'}


def test_searching_by_registration(manager):
    body = manager.get(BOARD, query_string={'reg_no': 'ccc-333'}).get_data(as_text=True)

    assert tickets_on(body) == {'CMP-2026-9003'}, 'registration search is case sensitive'


def test_searching_by_contact_number(manager):
    """One number, two tickets - both come back."""
    body = manager.get(BOARD, query_string={'contact': '0300-1112222'}).get_data(as_text=True)

    assert tickets_on(body) == {'CMP-2026-9001', 'CMP-2026-9004'}


@pytest.mark.parametrize('typed', ['0321 333 4444', '03213334444', '0321-333-4444'])
def test_a_contact_number_is_found_however_it_is_punctuated(typed, manager):
    """It is stored one way and typed another, every time."""
    body = manager.get(BOARD, query_string={'contact': typed}).get_data(as_text=True)

    assert 'CMP-2026-9002' in tickets_on(body), f'{typed} found nothing'


def test_a_plus_prefixed_number_is_found_without_it(manager):
    body = manager.get(BOARD, query_string={'contact': '923335556666'}).get_data(as_text=True)

    assert 'CMP-2026-9003' in tickets_on(body)


def test_searching_a_date_window(manager):
    """Everything logged in the last week."""
    today = datetime.now().date()
    week_ago = today - timedelta(days=7)
    body = manager.get(BOARD, query_string={
        'date_from': week_ago.isoformat(), 'date_to': today.isoformat()}).get_data(as_text=True)

    assert tickets_on(body) == {'CMP-2026-9001', 'CMP-2026-9002'}


def test_a_single_day_window_includes_the_whole_day(manager):
    """created_at is a timestamp; a date filter that stops at midnight finds
    nothing logged after it."""
    today = datetime.now().date().isoformat()
    body = manager.get(BOARD, query_string={
        'date_from': today, 'date_to': today}).get_data(as_text=True)

    assert 'CMP-2026-9001' in tickets_on(body)


def test_the_fields_narrow_each_other(manager):
    """AND, not OR: a contact that matches two tickets plus a registration
    that matches one of them returns that one."""
    body = manager.get(BOARD, query_string={
        'contact': '0300-1112222', 'reg_no': 'DDD-444'}).get_data(as_text=True)

    assert tickets_on(body) == {'CMP-2026-9004'}


def test_a_search_that_matches_nothing_says_so(manager):
    body = manager.get(BOARD, query_string={'ticket_no': 'CMP-0000-0000'}).get_data(as_text=True)

    assert not tickets_on(body)
    assert 'No ticket matches that search' in body


def test_a_malformed_date_does_not_break_the_board(manager):
    """A date typed by hand, or a stale bookmark, must not 500 the page."""
    response = manager.get(BOARD, query_string={'date_from': 'yesterday'})

    assert response.status_code == 200
    assert tickets_on(response.get_data(as_text=True)) == {
        'CMP-2026-9001', 'CMP-2026-9002', 'CMP-2026-9003', 'CMP-2026-9004'}


# --------------------------------------------------------------------------
# The search and the filters have to agree
# --------------------------------------------------------------------------

def test_a_search_stays_inside_the_status_filter(manager):
    """Searching from the "Open" board must not quietly widen back out to
    everything."""
    body = manager.get(BOARD, query_string={
        'status': 'OPEN', 'contact': '0300-1112222'}).get_data(as_text=True)

    assert tickets_on(body) == {'CMP-2026-9001'}, 'the OPEN filter was dropped'


def test_the_status_filter_survives_a_search(manager):
    body = manager.get(BOARD, query_string={'status': 'OPEN', 'reg_no': 'AAA'}).get_data(as_text=True)

    assert 'name="status" value="OPEN"' in body, 'the filter is not carried into the form'


def test_the_stat_cards_carry_the_search_with_them(manager):
    body = manager.get(BOARD, query_string={'reg_no': 'AAA-111'}).get_data(as_text=True)

    assert 'reg_no=AAA-111' in body, 'filtering by status would throw the search away'


def test_a_search_offers_a_way_back_out(manager):
    plain = manager.get(BOARD).get_data(as_text=True)
    searched = manager.get(BOARD, query_string={'reg_no': 'AAA-111'}).get_data(as_text=True)

    # Matched with its icon, because the notification bell in the page
    # chrome also has a "Mark all read" control carrying the word Clear.
    marker = '</i> Clear'
    assert marker in searched
    assert marker not in plain, 'nothing to clear when nothing was searched'


def test_the_board_still_only_opens_to_managers_and_admins(crm_app):
    """Rearranging the board must not have widened who can read it."""
    with crm_app.app_context():
        outsider = User(username='cb_outsider', email='cb_outsider@test.local',
                        name='Outsider', role='sales', is_active=True)
        outsider.set_password('pw123456')
        db.session.add(outsider)
        db.session.commit()
        outsider_id = outsider.id

    client = crm_app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = str(outsider_id)
        session['_fresh'] = True

    assert client.get(BOARD).status_code in (302, 403)
