"""
Technician activity across all four job types and every status.

Installations, REDOs, Removals and Removal Transfers each identify their
technician differently - a PO by name, a REDO by name and by user id, a
removal by roster technician id. TechnicianActivityService reconciles them so
the wallboard, the MIS page and the monthly management email report the same
numbers for the same person.
"""
from datetime import date, datetime, timedelta

import pytest

from src.app import create_app
from src.extensions import db
from src.models.purchase_order import PurchaseOrder
from src.models.redo import RedoActivity
from src.models.removal import RemovalRetainedActivity, RemovalTransferActivity
from src.models.technician import Technician
from src.models.user import User
from src.services.technician_activity_service import (
    UNASSIGNED_LABEL, TechnicianActivityService)
from src.utils.date_ranges import parse_range


@pytest.fixture
def crm_app():
    application = create_app('testing')
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


def _technician(name='ALI'):
    tech = Technician(name=name, is_active=True)
    db.session.add(tech)
    db.session.commit()
    return tech


def _user(name='ALI', username='ali'):
    user = User(username=username, email=f'{username}@test.local',
                name=name, role='redo_technician', is_active=True)
    user.set_password('pw123456')
    db.session.add(user)
    db.session.commit()
    return user


def _po(technician_name, status, reg_no='PO-1'):
    po = PurchaseOrder(po_number=f'PO-{reg_no}', owner_name='OWNER', owner_contact='1',
                       reg_no=reg_no, vehicle_make='M', vehicle_model='MM',
                       vehicle_year='2020', vehicle_color='RED', engine_number='E',
                       chassis_number='C', vehicle_availability_location='L',
                       technician_assigned=technician_name, status=status)
    db.session.add(po)
    db.session.commit()
    return po


def _redo(technician_name, status, reg_no='RD-1'):
    activity = RedoActivity(registration_no=reg_no, technician=technician_name, status=status)
    db.session.add(activity)
    db.session.commit()
    return activity


def _row_for(rows, name):
    for row in rows:
        if row['technician'] == name:
            return row
    raise AssertionError(f'No row for {name} in {[r["technician"] for r in rows]}')


def test_every_status_is_reported_per_activity_type(crm_app):
    with crm_app.app_context():
        _technician('ALI')
        _po('ALI', 'COMPLETED', 'A1')
        _po('ALI', 'PENDING', 'A2')
        _po('ALI', 'IN_PROGRESS', 'A3')
        _po('ALI', 'CANCELLED', 'A4')

        row = _row_for(TechnicianActivityService().wallboard_rows(), 'ALI')

        assert row['installations_completed'] == 1
        assert row['installations_pending'] == 1
        assert row['installations_in_progress'] == 1
        assert row['installations_cancelled'] == 1
        assert row['installations_total'] == 4


def test_all_four_activity_types_land_on_the_same_technician(crm_app):
    """The point of the service: one person, four tables, one row.

    A removal carries two people - the removal officer who owns the case, a
    login, and the technician from Technician Management who does the job.
    This report is about technicians, so it counts the second.
    """
    with crm_app.app_context():
        tech = _technician('ALI')
        officer = _user('Case Officer', 'case_officer')

        _po('ALI', 'COMPLETED', 'A1')
        _redo('ALI', 'COMPLETED', 'R1')
        db.session.add(RemovalRetainedActivity(registration_no='X1', status='COMPLETED',
                                               technician_id=tech.id,
                                               assigned_to=officer.id))
        db.session.add(RemovalTransferActivity(old_registration_no='X2',
                                               new_registration_no='X3',
                                               status='PENDING',
                                               technician_id=tech.id,
                                               assigned_to=officer.id))
        db.session.commit()

        rows = TechnicianActivityService().wallboard_rows()
        row = _row_for(rows, 'ALI')

        assert row['installations_total'] == 1
        assert row['redos_total'] == 1
        assert row['removals_total'] == 1
        assert row['transfers_total'] == 1
        assert row['total_assigned'] == 4

        # The officer who owned the case is not a technician and must not
        # appear as one - that was the whole defect.
        assert 'Case Officer' not in [r['technician'] for r in rows]


def test_totals_add_up_across_statuses(crm_app):
    with crm_app.app_context():
        _technician('ALI')
        _po('ALI', 'COMPLETED', 'A1')
        _redo('ALI', 'PENDING', 'R1')
        _redo('ALI', 'SOMETHING_ELSE', 'R2')

        row = _row_for(TechnicianActivityService().wallboard_rows(), 'ALI')

        parts = row['completed'] + row['pending'] + row['in_progress'] \
            + row['cancelled'] + row['other']
        assert parts == row['total_assigned'] == 3
        assert row['other'] == 1, 'An unrecognised status must still be counted'


def test_an_idle_technician_is_shown_at_zero_not_omitted(crm_app):
    """An absent row reads as "no data"; a zero row reads as "no work"."""
    with crm_app.app_context():
        _technician('IDLE')

        row = _row_for(TechnicianActivityService().wallboard_rows(), 'IDLE')
        assert row['total_assigned'] == 0
        assert row['completion_rate'] == 0.0


def test_work_under_an_unknown_name_is_kept_visible(crm_app):
    with crm_app.app_context():
        _technician('ALI')
        _po('SOMEONE ELSE', 'COMPLETED', 'A1')

        rows = TechnicianActivityService().wallboard_rows()
        names = [r['technician'] for r in rows]
        assert 'SOMEONE ELSE' in names


def test_the_catch_all_row_only_appears_when_it_holds_something(crm_app):
    with crm_app.app_context():
        _technician('ALI')
        _po('ALI', 'COMPLETED', 'A1')

        rows = TechnicianActivityService().wallboard_rows()
        assert UNASSIGNED_LABEL not in [r['technician'] for r in rows]


def test_unassigned_work_is_collected_rather_than_dropped(crm_app):
    with crm_app.app_context():
        _technician('ALI')
        _po(None, 'PENDING', 'A1')

        row = _row_for(TechnicianActivityService().wallboard_rows(), UNASSIGNED_LABEL)
        assert row['installations_pending'] == 1


def test_the_period_filter_excludes_work_outside_it(crm_app):
    with crm_app.app_context():
        _technician('ALI')
        recent = _po('ALI', 'COMPLETED', 'A1')
        old = _po('ALI', 'COMPLETED', 'A2')
        old.created_at = datetime.now() - timedelta(days=400)
        db.session.commit()

        this_month = parse_range({})
        row = _row_for(TechnicianActivityService().wallboard_rows(this_month), 'ALI')
        assert row['installations_total'] == 1, 'Last year\'s job must not count this month'

        all_time = _row_for(TechnicianActivityService().wallboard_rows(), 'ALI')
        assert all_time['installations_total'] == 2
        assert recent.id != old.id


def test_completion_rate_is_completed_over_everything_assigned(crm_app):
    with crm_app.app_context():
        _technician('ALI')
        _po('ALI', 'COMPLETED', 'A1')
        _po('ALI', 'COMPLETED', 'A2')
        _po('ALI', 'PENDING', 'A3')
        _po('ALI', 'CANCELLED', 'A4')

        row = _row_for(TechnicianActivityService().wallboard_rows(), 'ALI')
        assert row['completion_rate'] == 50.0


def test_totals_helper_sums_the_columns(crm_app):
    with crm_app.app_context():
        _technician('ALI')
        _technician('SARA')
        _po('ALI', 'COMPLETED', 'A1')
        _po('SARA', 'PENDING', 'A2')

        service = TechnicianActivityService()
        rows = service.wallboard_rows()
        totals = service.totals(rows)

        assert totals['total_assigned'] == 2
        assert totals['completed'] == 1
        assert totals['pending'] == 1


def test_the_wallboard_and_the_export_report_the_same_rows(crm_app):
    """The spreadsheet is built from the wallboard's rows, not a re-query."""
    with crm_app.app_context():
        _technician('ALI')
        _po('ALI', 'COMPLETED', 'A1')

        rows = TechnicianActivityService().wallboard_rows()

        from src.services.mis_export_service import MISExportService
        import pandas as pd

        path = MISExportService().generate_technician_activity_excel(rows)
        frame = pd.read_excel(path)

        assert len(frame) == len(rows)
        assert frame.iloc[0]['technician'] == 'ALI'
        assert frame.iloc[0]['installations_completed'] == 1
