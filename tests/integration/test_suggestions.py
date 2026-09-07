"""
Suggestions - the two-way channel between users and the Administrator.

Anyone using the CRM can report what is wrong with it; the Administrator
triages those reports on a wallboard and answers on the same ticket. The
tests here are about the two things that make it a channel rather than a
suggestion box: the raiser can always see what became of theirs, and nobody
else can read it.
"""
import pytest

from src.app import create_app
from src.extensions import db
from src.models.suggestion import Suggestion
from src.models.user import User
from src.services.suggestion_service import SuggestionService


@pytest.fixture
def crm_app():
    """The application, with no app context left open around the tests.

    Deliberately not `with app.app_context(): yield app`. These tests act as
    more than one person, and Flask-Login caches the user it resolved on the
    app context - so a context held across several requests answers every one
    of them as the first user it saw, and a role check appears to fail for
    somebody who in fact holds the role. Data setup opens its own context;
    requests are made without one, exactly as a real request would be.
    """
    application = create_app('testing')
    with application.app_context():
        db.create_all()

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()


def _user(username, role, name=None):
    user = User(username=username, email=f'{username}@test.local',
                name=name or username.title(), role=role, is_active=True)
    user.set_password('pw123456')
    db.session.add(user)
    db.session.commit()
    return user


def _client_as(crm_app, user_id):
    """A test client already signed in as `user_id`.

    Identity is put straight on the session rather than posted to the login
    form, because these tests act as more than one person: `@anonymous_required`
    turns a second login into a redirect that leaves the first user signed in,
    so posting the form twice silently tests the same person twice.
    """
    client = crm_app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
    return client


def test_any_user_can_raise_one(crm_app):
    """Raising a suggestion needs no role - that is the point of it."""
    with crm_app.app_context():
        rana = _user('rana', 'removal').id

    client = _client_as(crm_app, rana)
    res = client.post('/suggestions/new', data={
        'title': 'Removal list needs a city column',
        'area': 'Removal',
        'description': 'I cannot tell which jobs are in the same city.',
    }, follow_redirects=True)

    assert res.status_code == 200
    with crm_app.app_context():
        suggestion = Suggestion.query.one()
        assert suggestion.status == Suggestion.STATUS_NEW
        assert suggestion.reference.startswith('SUG-')
        assert suggestion.raiser_name() == 'Rana'


def test_references_run_in_sequence_within_the_year(crm_app):
    """Each suggestion gets its own reference, numbered per year."""
    from datetime import datetime

    year = datetime.now().year
    with crm_app.app_context():
        user = _user('rana', 'removal')
        service = SuggestionService()
        references = [service.create(user, f'Idea {n}', 'Removal', 'x').reference
                      for n in range(1, 4)]

        assert references == [f'SUG-{year}-0001', f'SUG-{year}-0002', f'SUG-{year}-0003']
        assert len(set(references)) == 3


def test_the_raiser_sees_the_status_change(crm_app):
    """Completing a suggestion has to reach the person who sent it.

    The status moves, the remarks land in the thread they can read, and the
    change is on their own dashboard - being told is the whole reason the
    module is two-way.
    """
    with crm_app.app_context():
        raiser = _user('aimen', 'sales')
        admin = _user('boss', 'admin')
        service = SuggestionService()

        suggestion = service.create(raiser, 'Search by driver', 'Sales', 'Cannot find it.')
        service.set_status(suggestion, admin, Suggestion.STATUS_COMPLETED,
                           'Driver name is now searchable.')
        raiser_id = raiser.id

        assert suggestion.status == Suggestion.STATUS_COMPLETED
        assert suggestion.closed_at is not None
        assert suggestion.handled_by == admin.id

        reply = suggestion.messages[-1]
        assert reply.from_admin is True
        assert reply.status_change == Suggestion.STATUS_COMPLETED
        assert 'searchable' in reply.body

    client = _client_as(crm_app, raiser_id)
    res = client.get('/suggestions/')
    assert res.status_code == 200
    assert b'Completed' in res.data


def test_the_conversation_keeps_both_sides(crm_app):
    """Replies from both sides survive, in order.

    A pair of overwritable "remarks" columns loses whichever half was
    written second, which is why the thread is a list of messages.
    """
    with crm_app.app_context():
        raiser = _user('aimen', 'sales')
        admin = _user('boss', 'admin')
        service = SuggestionService()

        suggestion = service.create(raiser, 'Search by driver', 'Sales', 'Cannot find it.')
        service.set_status(suggestion, admin, Suggestion.STATUS_IN_PROGRESS, 'Which screen?')
        service.add_message(suggestion, raiser, 'The Sales Dashboard.', from_admin=False)
        service.set_status(suggestion, admin, Suggestion.STATUS_COMPLETED, 'Done.')

        assert [(m.from_admin, m.body) for m in suggestion.messages] == [
            (True, 'Which screen?'),
            (False, 'The Sales Dashboard.'),
            (True, 'Done.'),
        ]


def test_an_empty_reply_is_not_a_message(crm_app):
    with crm_app.app_context():
        raiser = _user('aimen', 'sales')
        service = SuggestionService()
        suggestion = service.create(raiser, 'Something', 'Sales', 'x')

        assert service.add_message(suggestion, raiser, '   ', from_admin=False) is None
        assert suggestion.messages == []


def test_only_the_raiser_and_the_triage_side_can_read_one(crm_app):
    """A suggestion often describes what somebody found confusing.

    That is theirs to share, not the whole company's to browse - so an
    unrelated colleague cannot open it, however they arrive at the URL.
    """
    with crm_app.app_context():
        raiser = _user('aimen', 'sales')
        admin = _user('boss', 'admin')
        manager = _user('sug', 'suggestion_manager')
        stranger = _user('nadia', 'recovery_officer')

        suggestion = SuggestionService().create(raiser, 'Private', 'Sales', 'x')
        service = SuggestionService()

        assert service.can_view(suggestion, raiser) is True
        assert service.can_view(suggestion, admin) is True
        assert service.can_view(suggestion, manager) is True
        assert service.can_view(suggestion, stranger) is False
        suggestion_id = suggestion.id
        stranger_id = stranger.id

    client = _client_as(crm_app, stranger_id)
    res = client.get(f'/suggestions/{suggestion_id}', follow_redirects=True)
    assert b'Private' not in res.data


def test_the_wallboard_is_for_the_triage_side_only(crm_app):
    """Raising is open to everyone; answering is not."""
    with crm_app.app_context():
        sales_id = _user('aimen', 'sales').id
        manager_id = _user('sug', 'suggestion_manager').id

    # Anyone may raise one...
    assert _client_as(crm_app, sales_id).get('/suggestions/new').status_code == 200
    # ...but only the triage side may work the wallboard.
    assert _client_as(crm_app, sales_id).get('/suggestions/wallboard').status_code == 302
    assert _client_as(crm_app, manager_id).get('/suggestions/wallboard').status_code == 200


def test_the_wallboard_puts_the_longest_wait_first(crm_app):
    """Sorted newest-first, a wallboard buries the item most needing attention."""
    from datetime import datetime

    with crm_app.app_context():
        raiser = _user('aimen', 'sales')
        admin = _user('boss', 'admin')
        service = SuggestionService()

        oldest = service.create(raiser, 'Oldest', 'Sales', 'x')
        newest = service.create(raiser, 'Newest', 'Sales', 'y')
        oldest.created_at = datetime(2026, 1, 1, 9, 0)
        newest.created_at = datetime(2026, 6, 1, 9, 0)
        db.session.commit()

        assert [s.title for s in service.wallboard()] == ['Oldest', 'Newest']

        # Closed work drops below open work whatever its age.
        service.set_status(oldest, admin, Suggestion.STATUS_COMPLETED, 'Fixed.')
        assert [s.title for s in service.wallboard()] == ['Newest', 'Oldest']


def test_a_manager_reading_their_own_suggestion_is_the_raiser(crm_app):
    """Replying to yourself as the Administrator would be nonsense."""
    with crm_app.app_context():
        manager = _user('sug', 'suggestion_manager')
        manager_id = manager.id
        suggestion_id = SuggestionService().create(
            manager, 'Mine', 'Reports & MIS', 'x').id

    client = _client_as(crm_app, manager_id)
    res = client.get(f'/suggestions/{suggestion_id}')
    assert res.status_code == 200
    assert b'Update Status' not in res.data
