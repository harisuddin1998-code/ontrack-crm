"""Remove the four placeholder vehicles a failed SJ_MIS sync used to invent.

Until the sync was fixed, an unreachable internal database did not report a
failure - it substituted four hardcoded vehicles, committed them to the
non-reporting list and notified the REDO team about each one. On any instance
that could not route to SJ_MIS, every run did this. The rows are still there
afterwards, indistinguishable to the eye from real ones.

    python scripts/remove_fabricated_nr_vehicles.py            # report only
    python scripts/remove_fabricated_nr_vehicles.py --delete   # remove them

Reports by default and changes nothing until --delete is passed.

A row is only ever touched when its registration, customer name AND IMEI all
match one of the four known placeholders. Any one of those alone could belong
to a real vehicle one day; all three together could not have come from
anywhere but the generator. A row that matches the registration but not the
rest is reported and left alone, for a person to look at.

Exit code is 0 when nothing fabricated remains and 1 while any is still
present, so it can be re-run to confirm.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.app import create_app  # noqa: E402
from src.extensions import db  # noqa: E402
from src.models.gps import NonReportingConversation, NonReportingVehicle  # noqa: E402

# Copied from the deleted generator (see commit that removed
# _get_fallback_non_reporting_vehicles). All three fields must match.
FABRICATED = [
    ('LEB-2021-9981', 'Pak National Logistics', '862292056620214'),
    ('ICT-2023-4510', 'Atlas Honda Distribution', '861120049982143'),
    ('KHI-2022-8871', 'Habib Metro Services', '869910023412987'),
    ('PEW-2020-3321', 'Khyber Cargo Express', '863340055112876'),
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--delete', action='store_true',
                        help='actually remove the rows (default is report only)')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        total = NonReportingVehicle.query.count()
        print('Non-reporting vehicles in this database: {}'.format(total))
        print()

        confirmed = []
        partial = []

        for reg, customer, imei in FABRICATED:
            for row in NonReportingVehicle.query.filter_by(registration_no=reg).all():
                if row.customer_name == customer and row.imei_no == imei:
                    confirmed.append(row)
                else:
                    partial.append((row, customer, imei))

        if partial:
            print('Matched a placeholder registration but NOT the rest - left alone,')
            print('because a real vehicle could legitimately carry this registration:')
            for row, customer, imei in partial:
                print('  {} | customer={!r} (placeholder says {!r})'.format(
                    row.registration_no, row.customer_name, customer))
                print('     imei={!r} (placeholder says {!r})'.format(row.imei_no, imei))
            print()

        if not confirmed:
            print('No fabricated vehicles found. Nothing to do.')
            return 0

        print('Fabricated vehicles present: {}'.format(len(confirmed)))
        for row in confirmed:
            talk = NonReportingConversation.query.filter_by(vehicle_id=row.id).count()
            note = '  ({} conversation(s) logged against it)'.format(talk) if talk else ''
            print('  {} | {}{}'.format(row.registration_no, row.customer_name, note))

        if not args.delete:
            print()
            print('Report only. Re-run with --delete to remove them.')
            return 1

        # The conversations reference a vehicle that never existed, and the
        # foreign key is not set to cascade, so they would be orphaned rather
        # than removed with it. Counted out loud: a logged conversation means
        # somebody spent time chasing this.
        removed_talk = 0
        for row in confirmed:
            for talk in NonReportingConversation.query.filter_by(vehicle_id=row.id).all():
                db.session.delete(talk)
                removed_talk += 1
            db.session.delete(row)

        db.session.commit()
        print()
        print('Removed {} fabricated vehicle(s) and {} orphaned conversation(s).'.format(
            len(confirmed), removed_talk))
        print('Non-reporting vehicles now: {}'.format(NonReportingVehicle.query.count()))
        return 0


if __name__ == '__main__':
    sys.exit(main())
