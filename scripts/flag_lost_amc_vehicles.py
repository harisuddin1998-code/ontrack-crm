"""Send every AMC vehicle already marked LOST to the Removal dashboard.

Marking a vehicle LOST in AMC recovery now also raises a removal for it, so
the device comes back rather than staying fitted to a vehicle nobody is
billing for. Vehicles written off before that was true are still sitting in
the recovery sheets with nothing on the Removal board against them - this
catches them up.

Safe to run more than once: `flag_amc_lost_vehicle` skips any vehicle that
already carries an AMC-lost flag, in whatever state, so a second run does not
put a job somebody has already done back on the board.

    python scripts/flag_lost_amc_vehicles.py            # do it
    python scripts/flag_lost_amc_vehicles.py --dry-run  # just say what it would do
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.app import create_app  # noqa: E402
from src.models.annual_recovery import AnnualRecoveryVehicle  # noqa: E402
from src.models.removal import VehicleFlag  # noqa: E402
from src.services.removal_service import AMC_LOST_REASON_PREFIX, RemovalService  # noqa: E402


def main() -> int:
    dry_run = '--dry-run' in sys.argv

    app = create_app()
    with app.app_context():
        lost = (AnnualRecoveryVehicle.query
                .filter(AnnualRecoveryVehicle.status == 'LOST')
                .order_by(AnnualRecoveryVehicle.reg_no)
                .all())

        if not lost:
            print('No AMC vehicles are marked LOST - nothing to send.')
            return 0

        print(f'{len(lost)} AMC vehicle(s) marked LOST on the current sheets.')

        service = RemovalService()
        raised, already, failed = 0, 0, 0

        for vehicle in lost:
            registration = (vehicle.reg_no or '').strip().upper()
            if not registration:
                print('  ?              skipped - no registration on the row')
                failed += 1
                continue

            existing = VehicleFlag.query.filter(
                VehicleFlag.registration_no == registration,
                VehicleFlag.flag_reason.like(f'{AMC_LOST_REASON_PREFIX}%')).first()
            if existing:
                print(f'  {registration:<15} already on the Removal board '
                      f'(flag #{existing.id}, {existing.status})')
                already += 1
                continue

            if dry_run:
                print(f'  {registration:<15} would be sent for removal')
                raised += 1
                continue

            try:
                flag = service.flag_amc_lost_vehicle(vehicle)
                if flag:
                    print(f'  {registration:<15} sent for removal (flag #{flag.id})')
                    raised += 1
                else:
                    already += 1
            except Exception as exc:
                print(f'  {registration:<15} FAILED - {exc}')
                failed += 1

        verb = 'would be sent' if dry_run else 'sent'
        print(f'\n{raised} {verb}, {already} already on the board, {failed} failed.')
        if dry_run:
            print('Dry run - nothing was written. Re-run without --dry-run to apply.')
        return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
