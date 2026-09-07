"""
Regression tests for the '/' role landing redirects.

A role missing from ROLE_LANDING_PAGES once fell through to /auth/login, which
bounces an authenticated user back to '/', producing an infinite redirect loop
(ERR_TOO_MANY_REDIRECTS). It locked every affected role out of the application
entirely and was invisible when testing as an admin.

These tests walk the real redirect chain for every role in User.ROLES, so a
role added without a landing page fails here instead of in production.
"""
import pytest

import src.app as app_module
from src.app import create_app, ROLE_LANDING_PAGES
from src.extensions import db
from src.models.user import User

REDIRECT_CODES = (301, 302, 303, 307, 308)
MAX_HOPS = 10


# Module-scoped: these tests only read, and building the app is the slow part.
@pytest.fixture(scope='module')
def crm_app():
    application = create_app('testing')

    with application.app_context():
        db.create_all()
        for role in User.ROLES:
            user = User(
                username=f'landing_{role}',
                email=f'landing_{role}@test.local',
                name=f'Landing {role}',
                role=role,
                is_active=True,
            )
            user.set_password('landing123')
            db.session.add(user)
        db.session.commit()

    # Deliberately yield with NO app context pushed. Flask-Login caches the
    # signed-in user on the app context's `g`, so holding one open for the whole
    # module leaks one test's identity into the next - which made the anonymous
    # test see the previous test's user.
    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()


def _follow(client, start='/'):
    """Walk redirects manually, returning (chain, looped)."""
    location, chain, visited = start, [], set()
    for _ in range(MAX_HOPS):
        response = client.get(location)
        chain.append((location, response.status_code))
        if response.status_code not in REDIRECT_CODES:
            return chain, False
        nxt = response.headers.get('Location')
        if not nxt:
            return chain, False
        if nxt in visited:
            chain.append((nxt, 'REVISITED'))
            return chain, True
        visited.add(location)
        location = nxt
    return chain, True


def _login_as(crm_app, client, role):
    with crm_app.app_context():
        user = User.query.filter_by(username=f'landing_{role}').first()
        user_id = user.id
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


@pytest.mark.parametrize('role', User.ROLES)
def test_every_role_reaches_a_page_without_a_redirect_loop(crm_app, role):
    """Each role must land on a real page - never loop, never 403."""
    client = crm_app.test_client()
    _login_as(crm_app, client, role)

    chain, looped = _follow(client)
    trail = ' -> '.join(f'{path}({code})' for path, code in chain)

    assert not looped, f"Redirect loop for role '{role}': {trail}"
    assert chain[-1][1] == 200, (
        f"Role '{role}' did not reach a usable page (ended {chain[-1][1]}): {trail}"
    )


@pytest.mark.parametrize('role', User.ROLES)
def test_role_is_never_redirected_to_the_login_page_while_signed_in(crm_app, role):
    """The specific bug: an authenticated user bounced to /auth/login loops."""
    client = crm_app.test_client()
    _login_as(crm_app, client, role)

    chain, _ = _follow(client)
    visited = [path for path, _ in chain]
    assert not any(path.startswith('/auth/login') for path in visited), (
        f"Signed-in '{role}' was sent to the login page: {visited}"
    )


def test_anonymous_visitor_reaches_the_login_page(crm_app):
    """The anonymous path must still work, and must not loop either."""
    client = crm_app.test_client()
    # pytest-flask pushes a request context that is shared across this
    # module-scoped fixture, so an identity set by an earlier test can still be
    # present. Start from an explicitly empty session so "anonymous" really is.
    with client.session_transaction() as session:
        session.clear()

    chain, looped = _follow(client)
    assert not looped
    assert chain[-1][0].startswith('/auth/login')
    assert chain[-1][1] == 200


def test_every_defined_role_has_a_landing_page():
    """Guards the map itself, independent of any HTTP request."""
    missing = [role for role in User.ROLES if role not in ROLE_LANDING_PAGES]
    assert not missing, (
        f"Roles missing from ROLE_LANDING_PAGES (they cannot sign in): {missing}"
    )


def test_startup_refuses_a_role_without_a_landing_page(monkeypatch):
    """A new role added without a landing page must break startup loudly."""
    incomplete = {k: v for k, v in ROLE_LANDING_PAGES.items() if k != 'recovery_officer'}
    monkeypatch.setattr(app_module, 'ROLE_LANDING_PAGES', incomplete)

    with pytest.raises(RuntimeError, match='ROLE_LANDING_PAGES'):
        create_app('testing')


def test_startup_refuses_a_landing_page_that_does_not_exist(monkeypatch):
    """A typo'd endpoint must break startup rather than 500 at runtime."""
    broken = dict(ROLE_LANDING_PAGES, sales='sales.no_such_endpoint')
    monkeypatch.setattr(app_module, 'ROLE_LANDING_PAGES', broken)

    with pytest.raises(RuntimeError, match='do not exist'):
        create_app('testing')
