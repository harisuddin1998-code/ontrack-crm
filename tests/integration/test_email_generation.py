"""
Every email the CRM can generate, generated.

An email that raises halfway through building its template is not something
anyone finds out about: `send_email` catches, logs and returns False, and the
business action it was attached to carries on regardless. So the only way to
know these work is to build them.

Nothing leaves the building: the testing config suppresses sending and
flask-mail's `record_messages` captures what would have gone out, so each
template is really rendered and each recipient list really resolved.
"""
from datetime import date, datetime

import pytest

from src.app import create_app
from src.extensions import db, mail
from src.models.payment import PaymentRecovery
from src.models.purchase_order import PurchaseOrder
from src.models.redo import RedoActivity
from src.models.security import SecurityBriefingData
from src.models.technician import Technician
from src.models.user import User
from src.services.email_service import EmailService, SENIOR_MANAGEMENT_RECIPIENTS
from src.services.mis_export_service import MISExportService


@pytest.fixture(scope='module')
def crm_app():
    application = create_app('testing')
    with application.app_context():
        db.create_all()

        seller = User(username='em_sales', email='em_sales@test.local',
                      name='Sana Sales', role='sales', is_active=True)
        seller.set_password('pw123456')
        db.session.add(seller)
        db.session.add(Technician(name='EMAIL TECH', contact='0300-1234567',
                                  is_active=True))
        db.session.flush()

        po = PurchaseOrder(
            po_number='PO-EM-001', owner_name='Email Test Customer',
            owner_contact='0300-1112222', reg_no='EM-001',
            vehicle_make='TOYOTA', vehicle_model='COROLLA', vehicle_year='2021',
            vehicle_color='WHITE', engine_number='ENG-EM-1',
            chassis_number='CHS-EM-1', vehicle_availability_location='LAHORE OFFICE',
            city='LAHORE', imei_no='860111222333444', sim_no='923001234567',
            device_type='GT06N', device_location='UNDER DASHBOARD',
            technician_assigned='EMAIL TECH', tested_by='QA',
            remarks='Nothing unusual.', status='COMPLETED',
            sales_person_id=seller.id, scheduled_date=date.today(),
            rates=25000, amc=8000)
        db.session.add(po)
        db.session.flush()

        db.session.add(SecurityBriefingData(
            po_id=po.id, status='COMPLETED', briefed_by='Security Officer',
            cnic='35202-1234567-1', address='12 Main Boulevard, Lahore',
            father_name='Father Name', segment='CORPORATE',
            secondary_user_name='Driver Bilal', secondary_user_phone='0333-1112222',
            emergency_user_name='Emergency Contact', emergency_user_phone='0344-9998888',
            sim_network='JAZZ', accessories_installed='RELAY, PANIC BUTTON',
            password_1='pw-one', password_2='pw-two', fence='Head office 500m',
            security_training_completed=True, customer_demonstration=True,
            services_explained=True, acknowledgement=True,
            completed_at=datetime.now(), synced_from_po=True))

        db.session.add(RedoActivity(
            registration_no='EM-001', customer_name='Email Test Customer',
            customer_contact='0300-1112222', redo_number='REDO-EM-1',
            activity_type='DEVICE CHANGE', status='COMPLETED',
            resolution_status='RESOLVED', make='TOYOTA', model='COROLLA',
            year='2021', color='WHITE', chassis_no='CHS-EM-1',
            engine_no='ENG-EM-1', imei_no='860111222333444',
            sim_no='923001234567', technician='EMAIL TECH',
            device_change_reason='Power Issue', scheduled_date=date.today(),
            completed_at=datetime.now(), sale_person='Sana Sales',
            arranged_by='Front Desk', city='LAHORE'))

        db.session.add(PaymentRecovery(
            po_id=po.id, total_amount=25000.0, amount_received=10000.0,
            remaining_amount=15000.0, payment_status='PARTIAL'))
        db.session.commit()

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()


def sent_by(crm_app, build):
    """Run one generator and hand back what it would have sent."""
    with crm_app.app_context():
        with mail.record_messages() as outbox:
            result = build()
        return result, list(outbox)


# --------------------------------------------------------------------------
# The operational emails
# --------------------------------------------------------------------------

def test_the_installation_completion_email_builds(crm_app):
    def build():
        po = PurchaseOrder.query.filter_by(po_number='PO-EM-001').one()
        return EmailService().send_completion_email(po)

    result, outbox = sent_by(crm_app, build)

    assert result is True
    assert len(outbox) == 1
    message = outbox[0]
    assert 'PO-EM-001' in message.subject
    assert 'Email Test Customer' in message.subject
    assert message.recipients
    assert len(message.html) > 1000


def test_the_completion_email_carries_the_installation_detail(crm_app):
    """It is the record the recipients work from, so a template that renders
    but drops the vehicle is no use."""
    def build():
        po = PurchaseOrder.query.filter_by(po_number='PO-EM-001').one()
        return EmailService().send_completion_email(po)

    _result, outbox = sent_by(crm_app, build)
    body = outbox[0].html

    for detail in ('EM-001', '860111222333444', '923001234567', 'EMAIL TECH', 'LAHORE'):
        assert detail in body, f'{detail} is missing from the completion email'


def test_the_security_briefing_email_builds(crm_app):
    def build():
        briefing = SecurityBriefingData.query.first()
        return EmailService().send_security_completion_email(briefing)

    result, outbox = sent_by(crm_app, build)

    assert result is True
    assert 'SECURITY BRIEFING COMPLETED' in outbox[0].subject
    assert 'EM-001' in outbox[0].subject


def test_the_redo_completion_email_builds(crm_app):
    def build():
        redo = RedoActivity.query.filter_by(redo_number='REDO-EM-1').one()
        return EmailService().send_redo_completion_email(redo)

    result, outbox = sent_by(crm_app, build)

    assert result is True
    assert 'REDO-EM-1' in outbox[0].subject
    assert 'EM-001' in outbox[0].html


def test_the_password_reset_email_builds(crm_app):
    def build():
        user = User.query.filter_by(username='em_sales').one()
        return EmailService().send_password_reset_email(user, 'a-test-token')

    result, outbox = sent_by(crm_app, build)

    assert result is True
    assert outbox[0].recipients == ['em_sales@test.local']
    assert 'a-test-token' in outbox[0].html, 'the reset link carries no token'


def test_the_po_created_notice_deliberately_sends_nothing(crm_app):
    """Sales create the PO, installers handle it; a third email about the
    same order is noise. It returns True so no caller treats it as a
    failure."""
    def build():
        po = PurchaseOrder.query.filter_by(po_number='PO-EM-001').one()
        return EmailService().send_po_created_email(po)

    result, outbox = sent_by(crm_app, build)

    assert result is True
    assert outbox == []


# --------------------------------------------------------------------------
# Who they go to
# --------------------------------------------------------------------------

def test_an_email_addressed_to_nobody_is_not_sent(crm_app):
    result, outbox = sent_by(
        crm_app, lambda: EmailService().send_email('Nobody', [], '<p>x</p>'))

    assert result is False
    assert outbox == []


def test_the_management_list_is_narrower_than_the_operational_one(crm_app):
    """The month-end pack carries commercial and staff-performance detail
    that the wider operational list must not receive."""
    with crm_app.app_context():
        operational = {a.lower() for a in EmailService().default_recipients}
        management = {a.lower() for a in EmailService.report_recipients()}

    assert management
    assert len(management) < len(operational)


def test_the_management_list_falls_back_rather_than_going_nowhere(crm_app):
    """A silent no-send is the failure nobody notices until the report is
    missed."""
    with crm_app.app_context():
        from src.models.report_recipient import ReportRecipient

        ReportRecipient.query.delete()
        db.session.commit()

        assert EmailService.report_recipients() == SENIOR_MANAGEMENT_RECIPIENTS


# --------------------------------------------------------------------------
# The month-end reports
# --------------------------------------------------------------------------

@pytest.mark.parametrize('label,method', [
    ('monthly MIS report', 'email_monthly_report'),
    ('device change report', 'email_monthly_device_change_report'),
    ('technician activity report', 'email_monthly_technician_activity_report'),
])
def test_each_monthly_report_builds_and_attaches(label, method, crm_app):
    result, outbox = sent_by(crm_app, lambda: getattr(MISExportService(), method)())

    assert result is True, f'{label} did not send'
    assert len(outbox) == 1
    assert len(outbox[0].attachments) == 1, f'{label} went out with no spreadsheet'
    assert outbox[0].recipients


def test_the_month_end_pack_carries_the_whole_catalogue(crm_app):
    """One email rather than one per report: they are read together, and a
    single send cannot half-fail and leave management holding three of nine."""
    from src.web.admin import MIS_REPORTS

    result, outbox = sent_by(crm_app, lambda: MISExportService().email_monthly_report_pack())

    assert result is True
    message = outbox[0]
    assert len(message.attachments) == len(MIS_REPORTS), \
        'a catalogue report is missing from the pack'


def test_every_report_in_the_pack_actually_built(crm_app):
    """The pack names what it could not build rather than quietly shipping
    short - so if that note appears, something is broken."""
    result, outbox = sent_by(crm_app, lambda: MISExportService().email_monthly_report_pack())

    assert result is True
    assert 'could not be built' not in outbox[0].html


def test_the_pack_lists_what_it_contains(crm_app):
    from src.web.admin import MIS_REPORTS

    _result, outbox = sent_by(crm_app, lambda: MISExportService().email_monthly_report_pack())
    body = outbox[0].html

    for report in MIS_REPORTS:
        assert report['name'] in body, f"{report['name']} is attached but not listed"


def test_the_month_end_reports_stay_restricted(crm_app):
    _result, outbox = sent_by(crm_app, lambda: MISExportService().email_monthly_report_pack())

    with crm_app.app_context():
        operational = {a.lower() for a in EmailService().default_recipients}

    recipients = {a.lower() for a in outbox[0].recipients}
    assert not (recipients - {a.lower() for a in SENIOR_MANAGEMENT_RECIPIENTS}), \
        'the pack went outside senior management'
    assert 'cs@on-tracking.com' in operational, 'the operational list changed shape'
    assert 'cs@on-tracking.com' not in recipients


def test_the_pack_is_scheduled_to_send_itself(crm_app):
    import inspect

    from src import scheduler

    source = inspect.getsource(scheduler.start_scheduler)
    assert "id='month_end_report_pack'" in source
    assert 'CronTrigger(day=1, hour=0, minute=0)' in source
