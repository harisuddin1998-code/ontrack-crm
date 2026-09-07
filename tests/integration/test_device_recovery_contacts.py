"""
Device Recovery pulls a full contact book, and works from a follow-up sheet.

Non-Reporting has always pulled the whole contact set from the MIS - emergency
mobile, residence, office - because one number is not enough to reach a
customer who is not answering. Device Recovery had only the single
`customer_contact` copied onto the REDO activity, so an officer chasing a
device charge had one number and no fallback.

These cover the three pieces of that: the contact book itself, the officer's
Follow-Up Sheet built from it, and the catalogue report that carries it to
senior management.
"""
from datetime import date, datetime, timedelta

import pytest

from src.app import create_app
from src.extensions import db
from src.models.gps import NonReportingVehicle
from src.models.installation_recovery import (InstallationRecoveryCharge,
                                              InstallationRecoveryFollowup)
from src.models.purchase_order import PurchaseOrder
from src.models.redo import RedoActivity
from src.models.user import User
from src.services.contact_book_service import (ContactBookService, attach_contact_books,
                                               dial_key, normalize_registration)

@pytest.fixture(scope='module')
def crm_app():
    application = create_app('testing')
    with application.app_context():
        db.create_all()

        officer = User(username='cb_officer', email='cb_officer@test.local',
                       name='Contact Officer', role='device_recovery', is_active=True)
        officer.set_password('pw123456')
        boss = User(username='cb_admin', email='cb_admin@test.local',
                    name='Contact Admin', role='admin', is_active=True)
        boss.set_password('pw123456')
        db.session.add_all([officer, boss])
        db.session.commit()

        # A vehicle the CRM knows four different ways, each holding a number
        # the others do not.
        activity = RedoActivity(registration_no='CB-1001',
                                customer_name='Rich Contact Customer',
                                customer_contact='0300-1112222',
                                device_change_reason='Power Issue')
        # A vehicle known only from its service record.
        lonely = RedoActivity(registration_no='CB-2002',
                              customer_name='Single Number Customer',
                              customer_contact='0321-3334444',
                              device_change_reason='Device Missing')
        # A vehicle with nothing dialable at all.
        blank = RedoActivity(registration_no='CB-3003',
                             customer_name='No Number Customer',
                             customer_contact='N/A',
                             device_change_reason='Device Damage')
        db.session.add_all([activity, lonely, blank])
        db.session.flush()

        db.session.add(NonReportingVehicle(
            registration_no='cb 1001',            # same plate, punctuated differently
            customer_name='Rich Contact Customer',
            customer_contact='0300-1112222',      # the same line as the REDO record
            emergency_mobile='0333-5556666',
            emergency_name='Emergency Person',
            res_phone='021-35678900',
            office_phone='N/A'))                  # a placeholder, not a number
        db.session.add(PurchaseOrder(
            po_number='CB-PO-1', reg_no='CB-1001', owner_name='Registered Owner',
            owner_contact='0345-7778888', city='Karachi',
            # The order form makes every vehicle attribute mandatory; none of
            # them matter here, but the row will not save without them.
            vehicle_make='Toyota', vehicle_model='Corolla', vehicle_year='2020',
            vehicle_color='White', engine_number='ENG-CB-1',
            chassis_number='CHS-CB-1', vehicle_availability_location='Workshop'))
        db.session.flush()

        for source, owner in ((activity, officer), (lonely, officer), (blank, boss)):
            db.session.add(InstallationRecoveryCharge(
                redo_activity_id=source.id,
                reason=source.device_change_reason,
                amount=5000.0,
                status=InstallationRecoveryCharge.STATUS_PENDING,
                assigned_officer_id=owner.id))
        db.session.commit()

        charge = InstallationRecoveryCharge.query.filter_by(
            redo_activity_id=activity.id).first()
        db.session.add(InstallationRecoveryFollowup(
            charge_id=charge.id, conversation_type='PHONE_CALL', direction='OUT',
            contact_person='Rich Contact Customer', contact_number='0300-1112222',
            summary='No answer, will try the emergency number',
            conversation_date=datetime(2026, 1, 10, 11, 0),
            follow_up_date=date(2026, 1, 20),
            recorded_by=officer.id, recorded_by_name='Contact Officer'))
        db.session.commit()

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()


def _client(crm_app, username):
    with crm_app.app_context():
        user_id = User.query.filter_by(username=username).first().id
    client = crm_app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
    return client


def _book(crm_app, registration):
    with crm_app.app_context():
        return ContactBookService().for_registration(registration)


# --------------------------------------------------------------------------
# The contact book
# --------------------------------------------------------------------------

def test_numbers_are_gathered_from_every_source(crm_app):
    """The whole point: one charge, four tables, every number found."""
    numbers = {n['number'] for n in _book(crm_app, 'CB-1001')['numbers']}

    assert '0300-1112222' in numbers, 'the service record was missed'
    assert '0333-5556666' in numbers, 'the monitoring feed was missed'
    assert '021-35678900' in numbers, 'the residence landline was missed'
    assert '0345-7778888' in numbers, 'the purchase order was missed'


def test_the_same_line_is_not_listed_twice(crm_app):
    """The REDO activity and the monitoring feed hold the same mobile."""
    numbers = [n['number'] for n in _book(crm_app, 'CB-1001')['numbers']]

    assert len(numbers) == len(set(numbers))
    assert sum(1 for n in numbers if n == '0300-1112222') == 1


def test_placeholders_are_not_offered_as_numbers(crm_app):
    """The MIS sync writes 'N/A' rather than NULL for a missing number, and a
    row of nothing to call is worse than a short list."""
    numbers = [n['number'] for n in _book(crm_app, 'CB-1001')['numbers']]
    assert 'N/A' not in numbers

    assert _book(crm_app, 'CB-3003')['numbers'] == []


def test_the_most_answerable_number_comes_first(crm_app):
    """An officer works down the list, so the order is the advice."""
    numbers = _book(crm_app, 'CB-1001')['numbers']
    assert numbers[0]['number'] == '0300-1112222'
    assert numbers[0]['label'] == 'Mobile (service record)'


def test_every_number_carries_a_distinct_label(crm_app):
    """Two rows both reading 'Mobile' tell the officer nothing about which to
    try first."""
    labels = [n['label'] for n in _book(crm_app, 'CB-1001')['numbers']]
    assert len(labels) == len(set(labels))


def test_other_names_on_file_are_kept(crm_app):
    """The emergency contact is often the person who actually answers."""
    names = {person['name'] for person in _book(crm_app, 'CB-1001')['names']}
    assert 'Emergency Person' in names
    assert 'Registered Owner' in names


@pytest.mark.parametrize('spelling', ['CB-1001', 'cb 1001', 'cb1001', ' CB1001 '])
def test_a_plate_is_matched_however_it_is_punctuated(crm_app, spelling):
    """Four sources are populated by four routes; they agree on the plate but
    not on how to write it."""
    assert _book(crm_app, spelling)['numbers'], f'{spelling!r} found nothing'


def test_an_unknown_plate_gives_an_empty_book_not_an_error(crm_app):
    with crm_app.app_context():
        book = ContactBookService().for_registration('NOT-A-PLATE')
    assert book == {'numbers': [], 'names': []}


def test_one_query_batch_serves_every_charge(crm_app):
    """A sheet of a few hundred charges cannot afford a lookup per row."""
    with crm_app.app_context():
        charges = InstallationRecoveryCharge.query.all()
        attach_contact_books(charges)

        assert all(hasattr(c, 'contact_book') for c in charges)
        rich = next(c for c in charges
                    if c.redo_activity.registration_no == 'CB-1001')
        assert len(rich.contact_book['numbers']) == 4


def test_a_charge_with_no_activity_still_gets_a_book(crm_app):
    """Empty rather than absent, so a sheet never has holes in it."""
    with crm_app.app_context():
        orphan = InstallationRecoveryCharge(redo_activity_id=None, reason='Power Issue',
                                            amount=1.0, status='PENDING')
        attach_contact_books([orphan])
        assert orphan.contact_book == {'numbers': [], 'names': []}


@pytest.mark.parametrize('one,two', [
    ('0300-1112222', '03001112222'),
    ('0300-1112222', '+92 300 1112222'),
    ('0300 111 2222', '92-300-1112222'),
])
def test_one_line_written_two_ways_shares_a_key(one, two):
    assert dial_key(one) == dial_key(two)


@pytest.mark.parametrize('value', ['', None, 'N/A', '123', '-'])
def test_nothing_dialable_has_no_key(value):
    assert dial_key(value) == ''


def test_registration_normalization():
    assert normalize_registration(' cb-1001 ') == 'CB1001'
    assert normalize_registration(None) == ''


# --------------------------------------------------------------------------
# The follow-up recording form
# --------------------------------------------------------------------------
#
# There is no separate call sheet: the contact book belongs where the call is
# actually made, which is the phone button on the Device Recovery dashboard.
# The form loads it from /contacts when it opens.

DASHBOARD = '/payment/installation-recovery'


def _charge_id(crm_app, registration):
    with crm_app.app_context():
        return InstallationRecoveryCharge.query.join(RedoActivity).filter(
            RedoActivity.registration_no == registration).first().id


def _contacts(crm_app, username, registration):
    charge_id = _charge_id(crm_app, registration)
    return _client(crm_app, username).get(f'{DASHBOARD}/{charge_id}/contacts')


def test_the_form_offers_every_number_for_the_vehicle(crm_app):
    """The whole point of the pull, at the moment it is needed."""
    payload = _contacts(crm_app, 'cb_admin', 'CB-1001').get_json()

    numbers = {c['number'] for c in payload['contacts']}
    assert {'0300-1112222', '0333-5556666', '021-35678900', '0345-7778888'} <= numbers
    assert all(c['label'] for c in payload['contacts']), 'a number arrived unlabelled'


def test_the_form_knows_who_it_is_calling(crm_app):
    """Name, layer and amount, so the officer opens the call knowing the ask."""
    payload = _contacts(crm_app, 'cb_admin', 'CB-1001').get_json()

    assert payload['customer_name'] == 'Rich Contact Customer'
    assert payload['reason'] == 'Power Issue'
    assert payload['amount'] == 5000.0
    assert payload['status'] == 'PENDING'
    assert any(person['name'] == 'Emergency Person' for person in payload['names'])


def test_the_form_shows_what_was_already_tried(crm_app):
    """So the officer does not repeat the last call word for word."""
    payload = _contacts(crm_app, 'cb_admin', 'CB-1001').get_json()

    assert payload['attempts'] == 1
    assert payload['last_attempt']['number'] == '0300-1112222'
    assert 'emergency number' in payload['last_attempt']['summary']
    assert payload['callback_due'] == '20/01/2026'


def test_a_charge_nobody_has_rung_reports_no_attempts(crm_app):
    payload = _contacts(crm_app, 'cb_officer', 'CB-2002').get_json()

    assert payload['attempts'] == 0
    assert payload['last_attempt'] is None
    assert payload['callback_due'] is None


def test_a_vehicle_with_no_number_says_so(crm_app):
    """An empty list, not a placeholder that looks dialable."""
    payload = _contacts(crm_app, 'cb_admin', 'CB-3003').get_json()
    assert payload['contacts'] == []


def test_the_form_is_scoped_like_the_rest_of_the_module(crm_app):
    """Contact details are customer data: an officer reads them for their own
    charges, not for a colleague's."""
    charge_id = _charge_id(crm_app, 'CB-3003')       # belongs to the admin
    response = _client(crm_app, 'cb_officer').get(
        f'{DASHBOARD}/{charge_id}/contacts',
        headers={'X-Requested-With': 'XMLHttpRequest'})
    assert response.status_code == 403


def test_only_device_recovery_reaches_the_contacts(crm_app):
    with crm_app.app_context():
        outsider = User(username='cb_sales', email='cb_sales@test.local',
                        name='Sales', role='sales', is_active=True)
        outsider.set_password('pw123456')
        db.session.add(outsider)
        db.session.commit()

    charge_id = _charge_id(crm_app, 'CB-1001')
    response = _client(crm_app, 'cb_sales').get(
        f'{DASHBOARD}/{charge_id}/contacts',
        headers={'X-Requested-With': 'XMLHttpRequest'})
    assert response.status_code == 403


def test_the_dashboard_carries_the_structured_form(crm_app):
    """Four labelled sections, not one long column of inputs."""
    body = _client(crm_app, 'cb_admin').get(DASHBOARD).get_data(as_text=True)

    assert 'id="irFuContactPanel"' in body
    for section in ('Customer &amp; Contact Details', 'The Conversation',
                    'Outcome', 'Next Step'):
        assert section in body, f'the {section} section is missing'
    assert 'id="irFuNumber"' in body and 'id="irFuPerson"' in body
    assert 'function selectFollowupNumber' in body
    assert 'o_icon_btn_save' in body, 'the save action lost its floppy disk'


def test_recording_a_follow_up_stores_the_number_that_was_rung(crm_app):
    """Picking a number in the panel fills the field, so the log says which
    line was tried rather than leaving the next officer to guess."""
    charge_id = _charge_id(crm_app, 'CB-2002')
    response = _client(crm_app, 'cb_officer').post(
        f'{DASHBOARD}/{charge_id}/followup',
        data={'conversation_type': 'PHONE_CALL', 'direction': 'OUT',
              'contact_person': 'Single Number Customer',
              'contact_number': '0321-3334444',
              'summary': 'Promised payment on Friday'},
        follow_redirects=True)
    assert response.status_code == 200

    payload = _contacts(crm_app, 'cb_officer', 'CB-2002').get_json()
    assert payload['attempts'] == 1
    assert payload['last_attempt']['number'] == '0321-3334444'


@pytest.mark.parametrize('path', [
    '/payment/installation-recovery/followup-sheet',
    '/payment/installation-recovery/followup-sheet/export/excel',
    '/payment/installation-recovery/followup-sheet/export/pdf',
])
def test_the_standalone_sheet_is_gone(crm_app, path):
    """It was a third place to look at the same charges. The contact book
    belongs in the call, and the catalogue report covers the reporting."""
    assert _client(crm_app, 'cb_admin').get(path).status_code == 404


def test_the_nav_does_not_offer_a_sheet(crm_app):
    body = _client(crm_app, 'cb_admin').get(DASHBOARD).get_data(as_text=True)
    assert 'followup-sheet' not in body


def test_the_charge_details_modal_offers_the_alternatives(crm_app):
    """The details view carries them too, for reading a charge without
    recording a call."""
    charge_id = _charge_id(crm_app, 'CB-1001')
    payload = _client(crm_app, 'cb_admin').get(
        f'{DASHBOARD}/{charge_id}/details').get_json()

    numbers = {c['number'] for c in payload['contacts']}
    assert {'0300-1112222', '0333-5556666', '0345-7778888'} <= numbers



# --------------------------------------------------------------------------
# The catalogue report
# --------------------------------------------------------------------------

def test_the_report_is_in_the_catalogue(crm_app):
    from src.web.admin import MIS_REPORTS, MIS_REPORT_BUILDERS, MIS_REPORT_FILTERS

    report = next(r for r in MIS_REPORTS if r['slug'] == 'device-recovery-followups')
    assert report['view'] == 'admin.mis_report_view'
    assert 'device-recovery-followups' in MIS_REPORT_BUILDERS
    assert MIS_REPORT_FILTERS['device-recovery-followups']['name'] == 'reason'

    index = _client(crm_app, 'cb_admin').get('/admin/mis-reports').get_data(as_text=True)
    assert report['name'] in index


def test_the_report_carries_the_numbers(crm_app):
    body = _client(crm_app, 'cb_admin').get(
        '/admin/mis-reports/device-recovery-followups',
        query_string={'from': '2020-01-01', 'to': '2030-12-31'}).get_data(as_text=True)

    assert '0333-5556666' in body
    assert 'By Layer' in body and 'Follow-Up Sheet' in body
    assert 'No number on record' in body


def test_the_report_offers_a_layer_picker(crm_app):
    body = _client(crm_app, 'cb_admin').get(
        '/admin/mis-reports/device-recovery-followups').get_data(as_text=True)

    assert 'name="reason"' in body
    assert 'All Layers' in body
    for layer in ('Power Issue', 'Device Damage', 'Device Missing'):
        assert layer in body


def test_choosing_a_layer_keeps_the_selection(crm_app):
    body = _client(crm_app, 'cb_admin').get(
        '/admin/mis-reports/device-recovery-followups',
        query_string={'reason': 'Power Issue'}).get_data(as_text=True)
    assert 'value="Power Issue" selected' in body


def test_an_unknown_layer_is_treated_as_no_choice(crm_app):
    """Filtering on a layer that does not exist would silently return an empty
    report, which reads as "nothing outstanding"."""
    response = _client(crm_app, 'cb_admin').get(
        '/admin/mis-reports/device-recovery-followups',
        query_string={'from': '2020-01-01', 'to': '2030-12-31', 'reason': 'Nonsense'})

    assert response.status_code == 200
    assert '0333-5556666' in response.get_data(as_text=True)


def test_the_report_runs_without_a_request(crm_app):
    """The month-end pack builds every report from the scheduler."""
    from src.utils.date_ranges import parse_range
    from src.web.admin import MIS_REPORT_BUILDERS

    with crm_app.app_context():
        built = MIS_REPORT_BUILDERS['device-recovery-followups'](parse_range({}))

    assert [table['title'] for table in built['tables']] == ['By Layer', 'Follow-Up Sheet']


def test_the_report_exports(crm_app):
    response = _client(crm_app, 'cb_admin').get(
        '/admin/mis-reports/device-recovery-followups/export',
        query_string={'from': '2020-01-01', 'to': '2030-12-31'})
    assert response.status_code == 200
    assert 'spreadsheet' in response.headers.get('Content-Type', '')
