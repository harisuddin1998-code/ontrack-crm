"""The MIS reports section behaves as a catalogue, not a dashboard.

The page used to render four tables of figures with a single page-wide date
range governing all of them. It is now an index: report names, and the period
each one should cover, chosen per card. These tests pin the two properties
that made the change worth making - the index carries no figures of its own,
and the period a card is set to is the period the report actually runs for.
"""
import pytest

from src.extensions import db
from src.app import create_app
from src.models.notification import UserNotification
from src.models.user import User
from src.web.admin import MIS_REPORTS, MIS_REPORT_BUILDERS


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


def test_catalogue_lists_every_report_with_its_own_dates(client):
    res = client.get('/admin/mis-reports')
    assert res.status_code == 200
    body = res.data.decode()

    for report in MIS_REPORTS:
        assert report['name'] in body, f"{report['name']} missing from the catalogue"

    # One form per report, each carrying its own pair of date inputs - a
    # single shared range was the thing that made it unclear which report a
    # date applied to.
    assert body.count('class="o_report_card"') == len(MIS_REPORTS)
    assert body.count('name="from"') == len(MIS_REPORTS)
    assert body.count('name="to"') == len(MIS_REPORTS)


def test_catalogue_shows_no_statistics(client):
    """An index has no period of its own, so a number on it has nothing to be
    true of. The figures belong in the reports."""
    body = client.get('/admin/mis-reports').data.decode()

    assert '<table' not in body, 'the catalogue is rendering data tables again'
    # base.html carries a script that resizes any `.o_stat_value` on a page,
    # so look for the class being used rather than merely named.
    assert 'class="o_stat_value"' not in body, \
        'the catalogue is rendering statistic cards again'
    assert 'class="o_stat_card' not in body


@pytest.mark.parametrize('slug', sorted(MIS_REPORT_BUILDERS))
def test_every_catalogue_report_runs(client, slug):
    res = client.get(f'/admin/mis-reports/{slug}')
    assert res.status_code == 200

    name = next(r['name'] for r in MIS_REPORTS if r['slug'] == slug)
    body = res.data.decode()
    assert name in body
    assert 'o_list_table' in body, f'{slug} rendered no table'


def test_report_runs_for_the_period_the_card_was_set_to(client):
    res = client.get('/admin/mis-reports/sales-performance'
                     '?from=2024-03-01&to=2024-03-31')
    body = res.data.decode()

    assert 'value="2024-03-01"' in body
    assert 'value="2024-03-31"' in body
    # And says so, so a printed report cannot be quoted against the wrong month.
    assert '01 Mar 2024 - 31 Mar 2024' in body


def test_unknown_report_slug_is_not_found(client):
    assert client.get('/admin/mis-reports/no-such-report').status_code == 404


def test_notification_mark_all_read_clears_every_unread(client):
    """`POST /notifications/read` with no ids marks the lot."""
    with client.application.app_context():
        me = User.query.filter_by(username='admin').first()
        for n in range(3):
            db.session.add(UserNotification(user_id=me.id, title=f'Probe {n}',
                                            is_read=False))
        db.session.commit()
        my_id = me.id

    assert client.get('/notifications/feed').get_json()['unread_count'] == 3

    res = client.post('/notifications/read', json={})
    assert res.status_code == 200
    assert res.get_json()['updated'] == 3

    assert client.get('/notifications/feed').get_json()['unread_count'] == 0
    with client.application.app_context():
        assert UserNotification.query.filter_by(user_id=my_id,
                                                is_read=False).count() == 0


def test_notification_posts_carry_a_csrf_token():
    """CSRF covers every POST in the app. The bell's fetch calls send JSON
    rather than a form, so the token has to travel as a header - without it
    the requests come back 400 and 'Mark all read' looks like a dead button.
    """
    from pathlib import Path

    base = Path(__file__).resolve().parents[1] / 'src' / 'templates' / 'base.html'
    markup = base.read_text(encoding='utf-8')

    assert "'X-CSRFToken': CSRF_TOKEN" in markup
    # Both endpoints, not just the one that was noticed.
    assert markup.count('headers: POST_HEADERS') == 2
