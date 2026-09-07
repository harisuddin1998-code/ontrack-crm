"""User list ordering, and the CSRF token that kept expiring mid-form."""
import re

import pytest

from src.app import create_app
from src.extensions import db
from src.models.user import User

CODE_CELL = re.compile(r'o_badge_secondary">\s*(USR-\d+)\s*</span>')


@pytest.fixture
def client():
    app = create_app('testing')
    app.config['TESTING'] = True
    with app.app_context():
        db.create_all()
        admin = User(name='Admin User', username='admin',
                     email='admin@ontrack.com', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        with app.test_client() as test_client:
            test_client.post('/auth/login',
                             data={'username': 'admin', 'password': 'admin123'})
            yield test_client
        db.session.remove()
        db.drop_all()


def test_users_are_listed_in_user_code_order(client):
    """Codes are assigned in sequence, so this is the order people expect to
    read them in - and the order they are quoted in."""
    for index in range(2, 13):
        user = User(name=f'Person {index}', username=f'person{index}',
                    email=f'p{index}@ontrack.com', role='sales')
        user.set_password('secret123')
        db.session.add(user)
    db.session.commit()

    body = client.get('/admin/users').data.decode()
    codes = CODE_CELL.findall(body)

    assert len(codes) >= 12
    numbers = [int(code.split('-')[1]) for code in codes]
    assert numbers == sorted(numbers), f'user codes out of order: {codes}'


def test_ordering_is_numeric_not_alphabetical(client):
    """'USR-0010' vs 'USR-0009' sorts the same either way; the padding hides
    the difference until it runs out. Sorting on the number does not."""
    for code, username in (('USR-9', 'nine'), ('USR-10', 'ten'), ('USR-100', 'hundred')):
        user = User(name=username, username=username,
                    email=f'{username}@ontrack.com', role='sales', user_code=code)
        user.set_password('secret123')
        db.session.add(user)
    db.session.commit()

    body = client.get('/admin/users').data.decode()
    positions = [body.index(code) for code in ('USR-9<', 'USR-10<', 'USR-100<')]

    assert positions == sorted(positions), 'USR-100 sorted before USR-9'


def test_a_user_without_a_code_is_listed_last(client):
    """An empty code must not sort to the top of the list."""
    coded = User(name='Coded', username='coded', email='c@ontrack.com', role='sales')
    coded.set_password('secret123')
    db.session.add(coded)
    db.session.commit()

    uncoded = User(name='Zed Uncoded', username='uncoded',
                   email='u@ontrack.com', role='sales')
    uncoded.set_password('secret123')
    db.session.add(uncoded)
    db.session.commit()
    uncoded.user_code = None
    db.session.commit()

    body = client.get('/admin/users').data.decode()
    assert body.index('Zed Uncoded') > body.index('Coded')


def test_csrf_tokens_last_as_long_as_the_session():
    """Flask-WTF reads WTF_CSRF_TIME_LIMIT, not the CSRF_TIME_LIMIT the config
    also defines - which is why tokens expired after the library's own default
    hour and a form left open lost what had been typed into it."""
    app = create_app('testing')

    assert app.config.get('WTF_CSRF_TIME_LIMIT') is None, (
        'a stopwatch on the token is back; the session lifetime is the '
        'control that should govern this')


def test_an_expired_token_explains_itself(client):
    """The raw message is "The CSRF token has expired", which describes the
    security library rather than anything the person can act on."""
    from flask_wtf.csrf import CSRFError

    app = client.application

    # CSRFError subclasses BadRequest, so Flask files it under code 400
    # alongside the generic handler - scan rather than assume the slot.
    registered = [handlers.get(CSRFError)
                  for by_code in app.error_handler_spec.values()
                  for handlers in by_code.values()
                  if CSRFError in handlers]
    assert registered, 'CSRF failures fall through to the generic 400'


def test_user_creation_and_password_update(client):
    """Verify creating a user, updating their password, and deactivating them."""
    # 1. Create a user
    resp = client.post('/admin/users/new', data={
        'username': 'testworker',
        'email': 'worker@ontrack.com',
        'password': 'initialpass123',
        'role': 'sales',
        'name': 'Test Worker',
        'contact': '03001234567',
        'is_active': 'True',
        'text_case': 'as_typed'
    }, follow_redirects=True)
    assert resp.status_code == 200

    created = User.query.filter_by(username='testworker').first()
    assert created is not None
    assert created.check_password('initialpass123') is True
    assert created.is_active is True

    # 2. Update password and set to inactive
    resp_edit = client.post(f'/admin/users/{created.id}/edit', data={
        'username': 'testworker',
        'email': 'worker@ontrack.com',
        'password': 'newpassword456',
        'role': 'sales',
        'name': 'Test Worker Updated',
        'contact': '03001234567',
        'is_active': 'False',
        'text_case': 'as_typed'
    }, follow_redirects=True)
    assert resp_edit.status_code == 200

    db.session.refresh(created)
    assert created.check_password('newpassword456') is True
    assert created.is_active is False

    # 3. Edit with blank password keeps existing password
    resp_blank = client.post(f'/admin/users/{created.id}/edit', data={
        'username': 'testworker',
        'email': 'worker@ontrack.com',
        'password': '',
        'role': 'sales',
        'name': 'Test Worker Updated Again',
        'contact': '03001234567',
        'is_active': 'False',
        'text_case': 'as_typed'
    }, follow_redirects=True)
    assert resp_blank.status_code == 200

    db.session.refresh(created)
    assert created.check_password('newpassword456') is True

