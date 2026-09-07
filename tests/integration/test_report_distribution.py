"""
Restricted report distribution and the monthly reporting period.

Three reports carry commercial and staff-performance detail and must reach
senior management only: the MIS report, the Device Change report, and the
Technician Activity report. The wider operational list
(`EmailService.default_recipients`, which includes shared mailboxes like
cs@) must never receive them.

The other half of the contract is *which month*: a report sent on the 1st
covers the month that just ended, not the one that started this morning.
"""
from datetime import date
from unittest.mock import patch

import pytest

from src.app import create_app
from src.extensions import db
from src.services.email_service import SENIOR_MANAGEMENT_RECIPIENTS, EmailService
from src.utils.date_ranges import parse_range, previous_month_bounds


EXPECTED_SENIOR_MANAGEMENT = {
    'alister@on-tracking.com',
    'shaan@on-tracking.com',
    'sharoon@on-tracking.com',
    'musarrat@on-tracking.com',
}


@pytest.fixture
def crm_app():
    application = create_app('testing')
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


# ---------------------------------------------------------------- recipients

def test_senior_management_list_is_exactly_the_named_addresses():
    assert {addr.lower() for addr in SENIOR_MANAGEMENT_RECIPIENTS} == EXPECTED_SENIOR_MANAGEMENT


def test_operational_mailboxes_are_not_on_the_restricted_list():
    """cs@, salman@, cr@ and sunita@ get operational mail, not these reports."""
    restricted = {addr.lower() for addr in SENIOR_MANAGEMENT_RECIPIENTS}
    for shared_mailbox in ('cs@on-tracking.com', 'salman@on-tracking.com',
                           'cr@on-tracking.com', 'sunita@on-tracking.com'):
        assert shared_mailbox not in restricted


def test_send_restricted_report_ignores_any_wider_list(crm_app):
    """The restriction lives in one method and cannot be widened by a caller."""
    with crm_app.app_context():
        with patch.object(EmailService, 'send_email', return_value=True) as send:
            EmailService().send_restricted_report('Subject', '<p>Body</p>')

        sent_to = {addr.lower() for addr in send.call_args.kwargs['recipients']}
        assert sent_to == EXPECTED_SENIOR_MANAGEMENT


@pytest.mark.parametrize('method_name', [
    'email_monthly_report',
    'email_monthly_device_change_report',
    'email_monthly_technician_activity_report',
])
def test_each_monthly_report_goes_only_to_senior_management(crm_app, method_name):
    from src.services.mis_export_service import MISExportService

    with crm_app.app_context():
        with patch.object(EmailService, 'send_email', return_value=True) as send:
            getattr(MISExportService(), method_name)()

        assert send.called, f'{method_name} sent nothing'
        sent_to = {addr.lower() for addr in send.call_args.kwargs['recipients']}
        assert sent_to == EXPECTED_SENIOR_MANAGEMENT, (
            f'{method_name} sent to the wrong distribution: {sent_to}')


def test_month_end_pack_carries_every_catalogue_report(crm_app):
    """The pack is built from the catalogue, so a report added to the CRM is
    in the month-end email without anyone remembering to add it here."""
    from src.services.mis_export_service import MISExportService
    from src.web.admin import MIS_REPORTS

    with crm_app.app_context():
        with patch.object(EmailService, 'send_email', return_value=True) as send:
            MISExportService().email_monthly_report_pack()

        assert send.called, 'the month-end pack sent nothing'
        body = send.call_args.kwargs['html_body']
        for report in MIS_REPORTS:
            assert report['name'] in body, f"{report['name']} missing from the pack"

        # One message with everything attached, not one message per report.
        assert len(send.call_args.kwargs['attachments']) == len(MIS_REPORTS)
        sent_to = {addr.lower() for addr in send.call_args.kwargs['recipients']}
        assert sent_to == EXPECTED_SENIOR_MANAGEMENT


def test_month_end_pack_is_scheduled_for_the_first_at_midnight():
    """The requirement is explicit about when: 1st of the month, 00:00.

    Read off the registration rather than off a trigger built here, which
    would only prove that CronTrigger works.
    """
    import inspect
    import re

    from src import scheduler as scheduler_module

    assert hasattr(scheduler_module, 'run_month_end_report_pack')

    source = inspect.getsource(scheduler_module)
    job = re.search(r'run_month_end_report_pack\(app\).*?\)\s*\n\s*\)', source, re.S)
    assert job, 'the month-end pack is not registered with the scheduler'
    assert re.search(r'CronTrigger\(day=1,\s*hour=0,\s*minute=0\)', job.group(0)), \
        'the month-end pack does not run on the 1st at 00:00'


# ------------------------------------------------------------- report period

def test_previous_month_on_the_first_of_september_is_august():
    """The example from the requirement, checked literally."""
    start, end = previous_month_bounds(date(2026, 9, 1))
    assert start == date(2026, 8, 1)
    assert end == date(2026, 8, 31)


def test_previous_month_on_the_first_of_january_is_last_december():
    start, end = previous_month_bounds(date(2026, 1, 1))
    assert start == date(2025, 12, 1)
    assert end == date(2025, 12, 31)


def test_previous_month_handles_february_length():
    start, end = previous_month_bounds(date(2026, 3, 1))
    assert (start, end) == (date(2026, 2, 1), date(2026, 2, 28))
    leap_start, leap_end = previous_month_bounds(date(2024, 3, 1))
    assert (leap_start, leap_end) == (date(2024, 2, 1), date(2024, 2, 29))


def test_monthly_email_reports_the_month_that_just_ended(crm_app):
    """A report labelled August must not be built from September's range."""
    from src.services.mis_export_service import MISExportService

    with crm_app.app_context():
        captured = {}

        def capture(self, date_range=None):
            captured['range'] = date_range
            return __import__('tempfile').NamedTemporaryFile(
                suffix='.xlsx', delete=False).name

        with patch.object(MISExportService, 'generate_mis_excel', capture), \
                patch.object(EmailService, 'send_email', return_value=True):
            MISExportService().email_monthly_report()

        expected_start, expected_end = previous_month_bounds()
        assert captured['range']['start'] == expected_start
        assert captured['range']['end'] == expected_end


# ------------------------------------------------------------- range parsing

def test_range_defaults_to_the_current_month():
    parsed = parse_range({})
    today = date.today()
    assert parsed['start'].month == today.month
    assert parsed['start'].day == 1
    assert parsed['end'] >= today


def test_range_end_covers_the_whole_of_its_last_day():
    """A record created at 4pm on the last day is inside the range."""
    parsed = parse_range({'from': '2026-08-01', 'to': '2026-08-31'})
    assert parsed['end_dt'].hour == 23
    assert parsed['end_dt'].minute == 59
    assert parsed['end_dt'].date() == date(2026, 8, 31)


def test_backwards_range_is_swapped_not_emptied():
    parsed = parse_range({'from': '2026-08-31', 'to': '2026-08-01'})
    assert parsed['start'] == date(2026, 8, 1)
    assert parsed['end'] == date(2026, 8, 31)


def test_unparseable_dates_fall_back_to_the_current_month():
    parsed = parse_range({'from': 'not-a-date', 'to': ''})
    assert parsed['start'].day == 1
    assert parsed['is_filtered'] is True
