# src/scheduler.py
"""
Background Scheduler - Runs tasks within the Flask application
No external Celery or Redis required
"""
import threading
import time
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.services.fuel_rate_service import FuelRateService
from src.services.gps_service import GPSService
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Global scheduler instance
scheduler = None


def start_scheduler(app):
    """
    Start the background scheduler with app context.
    This runs inside the Flask application thread.
    """
    global scheduler
    
    if scheduler is not None:
        logger.info("Scheduler already running")
        return scheduler
    
    scheduler = BackgroundScheduler()
    
    # Schedule daily fuel rate update at midnight (00:00)
    scheduler.add_job(
        func=lambda: run_fuel_update(app),
        trigger=CronTrigger(hour=0, minute=0),
        id='daily_fuel_update',
        name='Daily Fuel Rate Update',
        replace_existing=True
    )
    
    # Schedule safety check every 6 hours (06:00, 12:00, 18:00)
    scheduler.add_job(
        func=lambda: run_fuel_check(app),
        trigger=CronTrigger(hour='*/6', minute=30),
        id='fuel_rate_check',
        name='Fuel Rate Safety Check',
        replace_existing=True
    )
    
    # Schedule GPS sync every 5 minutes
    scheduler.add_job(
        func=lambda: run_gps_sync(app),
        trigger=CronTrigger(minute='*/5'),
        id='gps_sync',
        name='GPS Location Sync',
        replace_existing=True
    )
    
    # Schedule non-reporting vehicle sync every 30 minutes
    scheduler.add_job(
        func=lambda: run_non_reporting_sync(app),
        trigger=CronTrigger(minute='*/30'),
        id='non_reporting_sync',
        name='Non-Reporting Vehicle Sync (30-min)',
        replace_existing=True
    )
    
    # Schedule the vehicle registry dump daily at 02:00. The Complaint form
    # searches this local copy of SJ_MIS's master roster, so it has to be
    # refreshed on its own - nobody should have to remember to press a
    # button before a vehicle can be found.
    scheduler.add_job(
        func=lambda: run_vehicle_registry_sync(app),
        trigger=CronTrigger(hour=2, minute=0),
        id='vehicle_registry_sync',
        name='Vehicle Registry Sync (SJ_MIS master roster)',
        replace_existing=True
    )

    # Schedule daily AMC snapshot at 01:00 AM
    scheduler.add_job(
        func=lambda: run_amc_snapshot(app),
        trigger=CronTrigger(hour=1, minute=0),
        id='daily_amc_snapshot',
        name='Daily AMC Recovery Snapshot',
        replace_existing=True
    )

    # AMC Recoveries (Database Method) at 03:00: pull SJ_MIS's AMC ledger,
    # then distribute whichever vehicles have their installation anniversary
    # today across the Recovery Officers, clubbed customer-wise. After the
    # 02:00 vehicle registry sync so the two SJ_MIS pulls do not overlap.
    scheduler.add_job(
        func=lambda: run_amc_database_recoveries(app),
        trigger=CronTrigger(hour=3, minute=0),
        id='amc_database_recoveries',
        name='AMC Recoveries - Database Method (daily fetch & round-robin)',
        replace_existing=True
    )

    # Month-end reports - every report in the catalogue, in one email, on the
    # 1st at 00:00, covering the month that just ended. One job rather than
    # one per report: they are read together, and a single send cannot
    # half-fail and leave management holding part of the pack.
    scheduler.add_job(
        func=lambda: run_month_end_report_pack(app),
        trigger=CronTrigger(day=1, hour=0, minute=0),
        id='month_end_report_pack',
        name='Month-End Report Pack Email',
        replace_existing=True
    )

    scheduler.start()
    logger.info("[OK] Background scheduler started successfully")
    logger.info("   [SCHED] Fuel rates update: Every day at 00:00")
    logger.info("   [SCHED] Fuel rates check: Every 6 hours")
    logger.info("   [SCHED] GPS sync: Every 5 minutes")
    logger.info("   [SCHED] Non-reporting sync: Every 30 minutes")
    logger.info("   [SCHED] AMC snapshot: Every day at 01:00")
    logger.info("   [SCHED] Vehicle registry sync: Every day at 02:00")
    logger.info("   [SCHED] AMC recoveries (Database Method): Every day at 03:00")
    logger.info("   [SCHED] Month-end report pack email: 1st of month at 00:00")

    return scheduler


def stop_scheduler():
    """Stop the background scheduler"""
    global scheduler
    if scheduler:
        scheduler.shutdown()
        scheduler = None
        logger.info("Background scheduler stopped")


def run_fuel_update(app):
    """Run fuel rate update within app context"""
    with app.app_context():
        try:
            logger.info("[UPDATE] Running scheduled fuel rate update...")
            result = FuelRateService.update_petrol_rate()
            if result:
                logger.info(f"[OK] Fuel rate updated to PKR {result.rate_per_liter}/liter")
            else:
                logger.warning("[WARN] Fuel rate update failed - no rate fetched")
        except Exception as e:
            logger.error(f"[ERROR] Fuel rate update error: {e}")


def run_fuel_check(app):
    """Run fuel rate safety check within app context"""
    with app.app_context():
        try:
            from src.models.technician import PetrolRate
            today = datetime.now().date()
            latest = PetrolRate.query.order_by(
                PetrolRate.effective_date.desc()
            ).first()
            
            if not latest or latest.effective_date < today:
                logger.info("[WARN] No rate found for today. Fetching from PSO...")
                run_fuel_update(app)
            else:
                logger.debug(f"[OK] Current rate {latest.rate_per_liter} from {latest.effective_date} is still valid")
        except Exception as e:
            logger.error(f"[ERROR] Fuel rate check error: {e}")


def run_gps_sync(app):
    """Run GPS sync within app context"""
    with app.app_context():
        try:
            gps_service = GPSService()
            count = gps_service.sync_locations()
            if count > 0:
                logger.info(f"[GPS] GPS sync complete: {count} locations updated")
        except Exception as e:
            logger.error(f"[ERROR] GPS sync error: {e}")


def run_non_reporting_sync(app):
    """Run non-reporting vehicle sync within app context"""
    with app.app_context():
        try:
            from src.services.db_sync_service import DBSyncService
            service = DBSyncService()
            result = service.sync_non_reporting_vehicles()
            if result.get('ok', True):
                logger.info(f"[SYNC] Non-reporting sync: New {result.get('new', 0)}, Updated {result.get('updated', 0)}")
            else:
                # Logged at error so it stands out in a log that is otherwise
                # a wall of successful five-minute ticks.
                logger.error(f"[SYNC] Non-reporting sync FAILED: {result.get('error')}")
        except Exception as e:
            logger.error(f"[ERROR] Non-reporting sync error: {e}")


def run_vehicle_registry_sync(app):
    """Refresh the local dump of SJ_MIS's master vehicle roster.

    This is what makes every vehicle findable from the Complaint form even
    when SJ_MIS itself is slow or unreachable.
    """
    with app.app_context():
        try:
            from src.services.db_sync_service import DBSyncService
            result = DBSyncService().sync_vehicle_registry()
            if result.get('error'):
                logger.warning("[SYNC] Vehicle registry sync failed - SJ_MIS unreachable")
            else:
                logger.info(f"[SYNC] Vehicle registry: New {result.get('new', 0)}, "
                            f"Refreshed {result.get('updated', 0)}")
        except Exception as e:
            logger.error(f"[ERROR] Vehicle registry sync error: {e}")


def run_amc_snapshot(app):
    """Run daily AMC recovery data snapshot within app context"""
    with app.app_context():
        try:
            from src.services.amc_snapshot_service import AmcSnapshotService
            service = AmcSnapshotService()
            result = service.create_daily_snapshot()
            if result.get('skipped'):
                logger.info(f"[AMC] Snapshot for {result['date']} already exists, skipped")
            else:
                logger.info(f"[AMC] Daily snapshot created: {result['created']} vehicle records for {result['date']}")
        except Exception as e:
            logger.error(f"[ERROR] AMC snapshot error: {e}")


def run_amc_database_recoveries(app):
    """Fetch SJ_MIS's AMC ledger and build today's follow-up list.

    This is what makes the Database Method a daily worklist rather than a
    browse of a ledger: by the time an officer signs in, the customers whose
    vehicles have an anniversary today are already distributed to them.
    """
    with app.app_context():
        try:
            from src.services.amc_database_recovery_service import AmcDatabaseRecoveryService
            result = AmcDatabaseRecoveryService().run_daily()
            synced = result.get('synced_records')
            logger.info(f"[AMC-DB] {result['date']}: ledger "
                        f"{synced if synced is not None else 'not refreshed'}, "
                        f"{result['assignments']} follow-up(s) distributed")
        except Exception as e:
            logger.error(f"[ERROR] AMC Database Method daily run error: {e}")


def run_month_end_report_pack(app):
    """Email every catalogue report for the month just ended, in one message.

    Restricted to senior management - see SENIOR_MANAGEMENT_RECIPIENTS.
    """
    with app.app_context():
        try:
            from src.services.mis_export_service import MISExportService
            if MISExportService().email_monthly_report_pack():
                logger.info("[MIS] Month-end report pack emailed successfully")
            else:
                logger.warning("[MIS] Month-end report pack failed to send")
        except Exception as e:
            logger.error(f"[ERROR] Month-end report pack error: {e}")


def run_monthly_mis_email(app):
    """Generate and email the complete MIS report, within app context.

    Covers the month that just ended - see MISExportService._previous_month.
    Restricted to senior management.
    """
    with app.app_context():
        try:
            from src.services.mis_export_service import MISExportService
            sent = MISExportService().email_monthly_report()
            if sent:
                logger.info("[MIS] Monthly MIS report emailed successfully")
            else:
                logger.warning("[MIS] Monthly MIS report email failed to send")
        except Exception as e:
            logger.error(f"[ERROR] Monthly MIS report error: {e}")


def run_monthly_device_change_email(app):
    """Email last month's Device Change report to senior management."""
    with app.app_context():
        try:
            from src.services.mis_export_service import MISExportService
            sent = MISExportService().email_monthly_device_change_report()
            if sent:
                logger.info("[MIS] Monthly Device Change report emailed successfully")
            else:
                logger.warning("[MIS] Monthly Device Change report email failed to send")
        except Exception as e:
            logger.error(f"[ERROR] Monthly Device Change report error: {e}")


def run_monthly_technician_activity_email(app):
    """Email last month's Technician Activity report to senior management."""
    with app.app_context():
        try:
            from src.services.mis_export_service import MISExportService
            sent = MISExportService().email_monthly_technician_activity_report()
            if sent:
                logger.info("[MIS] Monthly Technician Activity report emailed successfully")
            else:
                logger.warning("[MIS] Monthly Technician Activity report email failed to send")
        except Exception as e:
            logger.error(f"[ERROR] Monthly Technician Activity report error: {e}")