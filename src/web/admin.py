# src/web/admin.py
"""
Admin Routes - Dashboard and CRUD operations
"""
from flask import (render_template, request, redirect, url_for, flash, jsonify,
                   send_file, abort, has_request_context)
from flask_login import login_required, current_user
from datetime import datetime
import json
from typing import Dict, Any, List, Optional, Callable, TypedDict

from src.web import admin_bp
from src.extensions import db
from src.services import (
    POService, UserService, CityService, VehicleMakeService, VehicleModelService,
    VehicleYearService, VehicleColorService, DeviceTypeService, TechnicianService,
    TechnicianBikeService, PetrolRateService, FuelReimbursementInvoiceService,
    GPSService, SecurityBriefingService, PaymentRecoveryService, FuelRateService
)
from src.forms.admin_forms import (
    UserForm, CityForm, VehicleMakeForm, VehicleModelForm, VehicleYearForm,
    VehicleColorForm, DeviceTypeForm, PetrolRateForm
)
from src.forms.technician_forms import TechnicianForm, TechnicianBikeForm
from src.forms.po_forms import POCreationForm
from src.utils.decorators import role_required
from src.utils.logging import get_logger
from src.scheduler import run_fuel_update

logger = get_logger(__name__)


# ============================================
# DIAGNOSTIC ROUTE
# ============================================

@admin_bp.route('/hello')
def hello():
    """Simple diagnostic route to verify admin blueprint is working"""
    return jsonify({
        'status': 'success',
        'message': 'Admin blueprint is active and working!',
        'timestamp': datetime.now().isoformat()
    }), 200


@admin_bp.route('/extract-sj-mis-data')
@login_required
@role_required('admin')
def extract_sj_mis_data():
    """Extract data from SJ_MIS database using SmartDataExtractor"""
    import subprocess
    import sys
    
    try:
        # Run the extraction script
        result = subprocess.run(
            [sys.executable, 'scripts/extract_sj_mis_data.py'],
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        if result.returncode == 0:
            flash('✅ Data extraction completed successfully! Check the SMART_DATA_* folder.', 'success')
        else:
            flash(f'❌ Extraction failed: {result.stderr}', 'danger')
        
    except subprocess.TimeoutExpired:
        flash('❌ Extraction timed out. Please try again.', 'danger')
    except Exception as e:
        flash(f'❌ Error running extraction: {str(e)}', 'danger')
    
    return redirect(url_for('admin.dashboard'))


# ============================================
# DASHBOARD
# ============================================

def _months_in_window(window: Dict[str, Any]) -> List[str]:
    """The 'YYYY-MM' periods a timeframe touches, first to last.

    The stock ledger is filed by calendar month rather than by a date column,
    so a window has to be turned into the list of months it overlaps before
    it can select anything from it. An all-time window is clamped to the
    current month backwards through the earliest month the CRM records, which
    keeps the `IN` list bounded.
    """
    start, end = window['start'], window['end']
    months: List[str] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append(f'{year:04d}-{month:02d}')
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def _compute_admin_dashboard_stats(window: Optional[Dict[str, Any]] = None):
    """Shared stats computation behind the Admin Dashboard - also used
    verbatim by the Executive Dashboard so it stays a true replica of the
    Administrator's numbers rather than a separately-maintained copy that
    can drift. Returns (stats, recent_items); never raises - individual
    steps degrade to their zero-value default on error, same as before.

    Every figure is counted over `window`, the range behind the timeframe
    chip (see `dashboard_period`). The whole deck moves together when the
    chip changes: a card left on all-time while the section under it is
    period-scoped reads as a contradiction, because on one screen it is one.
    Called with no window it reports all time.
    """
    import traceback
    from src.utils.date_ranges import dashboard_period

    window = window or dashboard_period('all')
    start_dt, end_dt = window['start_dt'], window['end_dt']

    def within(query, column):
        """Restrict a query to the timeframe, dated by `column`."""
        return query.filter(column >= start_dt, column <= end_dt)

    def dated_in_window(value) -> bool:
        """Whether an already-loaded row's date falls in the timeframe.

        For the collections that come back from a service call, where the
        service's own scoping (which officer may see which charge) has to be
        preserved rather than re-implemented in a query here.
        """
        return value is not None and start_dt <= value <= end_dt

    # Initialize empty stats to prevent template errors
    stats: Dict[str, Any] = {
        'pos': {'total': 0, 'pending': 0, 'in_progress': 0, 'completed': 0},
        'users': {'total': 0, 'active': 0},
        'technicians': {'total': 0, 'active': 0},
        'gps': {'active_vehicles': 0, 'last_sync': 'Not synced yet'},
        'total_briefings': 0,
        'pending_briefings': 0,
        'completed_briefings': 0,
        'total_amount_pending': 0,
        'pending': 0,
        'installation_income': 0,
        'amc_income': 0,
        'amc_invoices': {'count': 0, 'invoiced': 0, 'outstanding': 0,
                         'discount': 0, 'discounted_count': 0},
        'redos_total': 0,
        'redos_done': 0,
        'redos_open': 0,
        'sales_orders_total': 0,
        'sales_order_value': 0,
        'stock_shortage_count': 0,
        'device_recovery': {
            'Power Issue': {'count': 0, 'outstanding': 0},
            'Device Damage': {'count': 0, 'outstanding': 0},
            'Device Missing': {'count': 0, 'outstanding': 0},
        },
    }
    recent_items = []

    try:
        logger.info("=" * 50)
        logger.info("DASHBOARD ROUTE STARTED")
        logger.info("=" * 50)
        
        # Step 1: Import services
        logger.info("Step 1: Importing services...")
        from src.services import POService, UserService, TechnicianService
        logger.info("[OK] Services imported successfully")

        # Step 2: Create service instances
        logger.info("Step 2: Creating service instances...")
        po_service = POService()
        user_service = UserService()
        tech_service = TechnicianService()
        logger.info("[OK] Service instances created successfully")
        
        # Step 3: Get PO stats, over the timeframe.
        #
        # Every one of the four PO cards counts orders *raised* in the window
        # and splits them by status, which is exactly what the list they link
        # into (`admin.pos_list?since=`) selects. Counting completions by
        # `updated_at` instead would put a number on a card that its own link
        # cannot reproduce.
        logger.info("Step 3: Getting PO stats...")
        try:
            from src.models.purchase_order import PurchaseOrder

            def pos_in_window():
                return within(PurchaseOrder.query, PurchaseOrder.created_at)

            def pos_with_status(status: str) -> int:
                return pos_in_window().filter(PurchaseOrder.status == status).count()

            po_stats = {
                'total': pos_in_window().count(),
                'pending': pos_with_status('PENDING'),
                'in_progress': pos_with_status('IN_PROGRESS'),
                'completed': pos_with_status('COMPLETED'),
                'cancelled': pos_with_status('CANCELLED'),
            }
            logger.info(f"[OK] PO stats: {po_stats}")
            stats['pos'] = po_stats
        except Exception as e:
            logger.error(f"[ERROR] PO stats error: {e}")
            logger.error(traceback.format_exc())
        
        # Step 4: Get user stats
        logger.info("Step 4: Getting user stats...")
        try:
            user_stats = user_service.get_dashboard_stats()
            logger.info(f"[OK] User stats: {user_stats}")
            stats['users'] = user_stats
        except Exception as e:
            logger.error(f"[ERROR] User stats error: {e}")
            logger.error(traceback.format_exc())
        
        # Step 5: Get technician stats
        logger.info("Step 5: Getting technician stats...")
        try:
            tech_total = tech_service.count()
            tech_active = tech_service.count(is_active=True)
            logger.info(f"[OK] Technician stats: total={tech_total}, active={tech_active}")
            stats['technicians'] = {'total': tech_total, 'active': tech_active}
        except Exception as e:
            logger.error(f"[ERROR] Technician stats error: {e}")
            logger.error(traceback.format_exc())
        
        # Step 6: Get GPS stats - vehicles recorded as non-reporting inside
        # the timeframe. Counted as events (when the vehicle was flagged),
        # not as a live device state, so the card answers the same question
        # the rest of the deck does: what happened in this window.
        logger.info("Step 6: Getting GPS stats...")
        try:
            from src.models.gps import NonReportingVehicle
            offline_vehicles = within(NonReportingVehicle.query,
                                      NonReportingVehicle.created_at).count()
            logger.info(f"[OK] GPS stats: non_reporting_in_period={offline_vehicles}")
            stats['gps']['offline_vehicles'] = offline_vehicles
            stats['gps']['active_vehicles'] = offline_vehicles
        except Exception as e:
            logger.error(f"[ERROR] GPS stats error: {e}")
            logger.error(traceback.format_exc())

        # Step 7: Security Briefing stats, over the timeframe
        logger.info("Step 7: Getting Security Briefing stats...")
        try:
            from src.models.security import SecurityBriefingData
            briefings = within(SecurityBriefingData.query,
                               SecurityBriefingData.created_at).all()
            total_briefings = len(briefings)
            completed_briefings = sum(1 for b in briefings if b.status == 'COMPLETED')
            logger.info(f"[OK] Security stats: total={total_briefings}, completed={completed_briefings}")
            stats['total_briefings'] = total_briefings
            stats['completed_briefings'] = completed_briefings
            stats['pending_briefings'] = total_briefings - completed_briefings
        except Exception as e:
            logger.error(f"[ERROR] Security stats error: {e}")
            logger.error(traceback.format_exc())

        # Step 8: Payment Recovery stats, over the timeframe.
        #
        # Outstanding money is dated by the ledger row (when the recovery was
        # raised); income is dated by the day it was actually received. They
        # are two different events and dating both the same way would put
        # money in the wrong month for one of them.
        logger.info("Step 8: Getting Payment Recovery stats...")
        try:
            from src.models.payment import PaymentRecovery

            # The three statuses that still owe money, named rather than
            # written as "not PAID": a recovery against a cancelled PO is set
            # to CANCELLED, and nobody is chasing that - counting it would
            # put money on the card that nobody expects to receive.
            open_recoveries = within(
                PaymentRecovery.query.filter(
                    PaymentRecovery.payment_status.in_([
                        PaymentRecovery.STATUS_PENDING,
                        PaymentRecovery.STATUS_PARTIAL,
                        PaymentRecovery.STATUS_OVERDUE])),
                PaymentRecovery.created_at).all()
            stats['total_amount_pending'] = sum(p.remaining_amount or 0 for p in open_recoveries)
            stats['pending'] = len(open_recoveries)
            logger.info(f"[OK] Payment stats: pending_amount={stats['total_amount_pending']}, "
                        f"pending_count={stats['pending']}")

            received = PaymentRecovery.query.filter(
                PaymentRecovery.payment_received_date.isnot(None),
                PaymentRecovery.payment_received_date >= window['start'],
                PaymentRecovery.payment_received_date <= window['end']).all()
            stats['installation_income'] = sum(p.amount_received or 0 for p in received)
        except Exception as e:
            logger.error(f"[ERROR] Payment stats error: {e}")
            logger.error(traceback.format_exc())

        # Step 8b: AMC (Annual Monitoring) income received in the timeframe
        logger.info("Step 8b: Getting AMC income...")
        try:
            from src.models.annual_recovery import AnnualRecoveryHistory
            amc_records = within(AnnualRecoveryHistory.query,
                                 AnnualRecoveryHistory.created_at).all()
            stats['amc_income'] = sum(r.amount or 0 for r in amc_records)
        except Exception as e:
            logger.error(f"[ERROR] AMC income error: {e}")
            logger.error(traceback.format_exc())
            stats['amc_income'] = 0

        # Step 8b-ii: AMC invoices raised in the timeframe, and the discounts
        # granted on them. Read from the invoice ledger rather than recomputed
        # from the vehicles: an invoice states what was owed and what was
        # billed on the day it went out, and the vehicles have moved on since.
        logger.info("Step 8b-ii: Getting AMC invoice totals...")
        try:
            from src.models.amc_invoice import AmcInvoice
            invoices = within(AmcInvoice.query, AmcInvoice.created_at).all()
            stats['amc_invoices'] = {
                'count': len(invoices),
                'invoiced': sum(i.invoiced_amount or 0 for i in invoices),
                'outstanding': sum(i.outstanding_amount or 0 for i in invoices),
                'discount': sum(i.discount_amount or 0 for i in invoices),
                'discounted_count': sum(1 for i in invoices if (i.discount_amount or 0) > 0),
            }
        except Exception as e:
            logger.error(f"[ERROR] AMC invoice stats error: {e}")
            logger.error(traceback.format_exc())

        # Step 8c: Stock & Accessories - items running short across the months
        # the timeframe covers. The stock ledger is kept per calendar month
        # ('YYYY-MM'), so a window is translated into the months it touches
        # rather than being applied to a date column the table does not have.
        logger.info("Step 8c: Getting stock shortage count...")
        try:
            from src.models.inventory import InventoryStockItem
            months = _months_in_window(window)
            period_items = InventoryStockItem.query.filter(
                InventoryStockItem.period.in_(months)).all()
            stats['stock_shortage_count'] = sum(1 for i in period_items if i.get_remaining() < 0)
        except Exception as e:
            logger.error(f"[ERROR] Stock shortage error: {e}")
            logger.error(traceback.format_exc())
            stats['stock_shortage_count'] = 0

        # Step 8d: Device Recovery breakdown - Power Issue / Device Damage /
        # Device Missing, the same three layers as the Device Recovery
        # dashboard's tabs, so admin can jump straight into whichever is
        # backing up without visiting the module first.
        #
        # The charges still come from the service, which decides who is
        # allowed to see which of them; the timeframe is applied to what it
        # returns rather than by querying the table directly here, so the
        # card cannot end up counting charges the viewer may not open.
        logger.info("Step 8d: Getting Device Recovery breakdown...")
        try:
            from src.services.installation_recovery_service import InstallationRecoveryService, TRIGGERING_REASONS
            ir_service = InstallationRecoveryService()
            device_recovery = {}
            for reason in TRIGGERING_REASONS:
                charges = [c for c in ir_service.get_charges_for_view(current_user, reason=reason)
                           if dated_in_window(c.created_at)]
                device_recovery[reason] = {
                    'count': len(charges),
                    'outstanding': sum(c.get_outstanding() for c in charges),
                }
            stats['device_recovery'] = device_recovery
        except Exception as e:
            logger.error(f"[ERROR] Device Recovery breakdown error: {e}")
            logger.error(traceback.format_exc())

        # Step 8e: REDO totals over the timeframe
        logger.info("Step 8e: Getting REDO totals...")
        try:
            from src.models.redo import RedoActivity
            redos = within(RedoActivity.query, RedoActivity.created_at).all()
            stats['redos_total'] = len(redos)
            stats['redos_done'] = sum(1 for r in redos if r.status == 'COMPLETED')
            # Open work is everything not finished and not called off - a
            # cancelled REDO is neither outstanding nor done.
            stats['redos_open'] = sum(
                1 for r in redos if r.status not in ('COMPLETED', 'CANCELLED'))
        except Exception as e:
            logger.error(f"[ERROR] REDO totals error: {e}")
            logger.error(traceback.format_exc())

        # Step 8f: Sales - orders raised in the timeframe and what they are
        # worth. Summed in the database rather than by loading every PO.
        logger.info("Step 8f: Getting sales order totals...")
        try:
            from src.models.purchase_order import PurchaseOrder
            stats['sales_orders_total'] = stats['pos'].get('total', 0)
            stats['sales_order_value'] = within(
                db.session.query(
                    db.func.coalesce(db.func.sum(PurchaseOrder.rates), 0)
                    + db.func.coalesce(db.func.sum(PurchaseOrder.amc), 0)),
                PurchaseOrder.created_at).scalar() or 0
        except Exception as e:
            logger.error(f"[ERROR] Sales order totals error: {e}")
            logger.error(traceback.format_exc())

        # Step 9: Get recent POs - explicitly newest-first, since unordered
        # pagination returns SQLite's insertion order (oldest first on page 1),
        # which left this section showing stale, not fresh, work.
        logger.info("Step 9: Getting recent POs...")
        try:
            recent_pos = po_service.get_pos(page=1, per_page=10, order_by='created_at', desc=True)
            recent_items = recent_pos.get('items', [])
            logger.info(f"[OK] Recent POs: {len(recent_items)} items")
        except Exception as e:
            logger.error(f"[ERROR] Recent POs error: {e}")
            logger.error(traceback.format_exc())

        logger.info("[OK] Stats computed successfully")
        logger.info("=" * 50)
        logger.info("DASHBOARD STATS COMPUTED SUCCESSFULLY")
        logger.info("=" * 50)
        return stats, recent_items, None

    except Exception as e:
        logger.error("=" * 50)
        logger.error("FATAL DASHBOARD ERROR")
        logger.error(f"Error: {e}")
        logger.error(traceback.format_exc())
        logger.error("=" * 50)
        return stats, recent_items, str(e)


def dashboard_sync_values(stats: Dict[str, Any]) -> Dict[str, str]:
    """Every live number on the dashboard, already formatted for display.

    One map, two consumers: the KPI cards render `{{ sync.<key> }}` into an
    element tagged `data-sync="<key>"`, and the 120-second refresh endpoint
    returns this same map and writes each value straight back into the
    matching element. There is no second place where a dashboard figure gets
    formatted, so a refreshed number cannot come back looking different from
    the one the page was rendered with.

    Money is rounded to whole rupees here - these are headline figures, not
    a ledger (see `format_money_round`).
    """
    from src.utils.formatting import format_count, format_money_round

    pos = stats.get('pos') or {}
    gps = stats.get('gps') or {}
    devices = stats.get('device_recovery') or {}
    invoices = stats.get('amc_invoices') or {}

    def device(reason: str, key: str):
        return (devices.get(reason) or {}).get(key, 0)

    return {
        # Purchase orders raised in the timeframe, by status
        'period_completed': format_count(pos.get('completed', 0)),
        'period_in_progress': format_count(pos.get('in_progress', 0)),
        'period_pending': format_count(pos.get('pending', 0)),

        # Sales & security
        'sales_orders': format_count(stats.get('sales_orders_total', 0)),
        'sales_value': format_money_round(stats.get('sales_order_value', 0), dash_if_empty=False),
        'briefings_done': format_count(stats.get('completed_briefings', 0)),
        'briefings_pending': format_count(stats.get('pending_briefings', 0)),
        'briefings_total': format_count(stats.get('total_briefings', 0)),

        # REDOs
        'redos_total': format_count(stats.get('redos_total', 0)),
        'redos_done': format_count(stats.get('redos_done', 0)),
        'redos_open': format_count(stats.get('redos_open', 0)),

        # Device / power issues
        'power_issue': format_count(device('Power Issue', 'count')),
        'power_issue_amount': format_money_round(device('Power Issue', 'outstanding'), dash_if_empty=False),
        'device_damage': format_count(device('Device Damage', 'count')),
        'device_damage_amount': format_money_round(device('Device Damage', 'outstanding'), dash_if_empty=False),
        'device_missing': format_count(device('Device Missing', 'count')),
        'device_missing_amount': format_money_round(device('Device Missing', 'outstanding'), dash_if_empty=False),

        # Revenue & recovery
        'recovery_pending_amount': format_money_round(stats.get('total_amount_pending', 0), dash_if_empty=False),
        'recovery_pending_count': format_count(stats.get('pending', 0)),
        'installation_income': format_money_round(stats.get('installation_income', 0), dash_if_empty=False),
        'amc_income': format_money_round(stats.get('amc_income', 0), dash_if_empty=False),

        # AMC invoicing - raised, billed, and conceded
        'amc_invoices_count': format_count(invoices.get('count', 0)),
        'amc_invoiced_amount': format_money_round(invoices.get('invoiced', 0), dash_if_empty=False),
        'amc_invoice_outstanding': format_money_round(invoices.get('outstanding', 0), dash_if_empty=False),
        'amc_discount_amount': format_money_round(invoices.get('discount', 0), dash_if_empty=False),
        'amc_discounted_count': format_count(invoices.get('discounted_count', 0)),

        # Fleet & stock
        'non_reporting': format_count(gps.get('offline_vehicles', gps.get('active_vehicles', 0))),
        'stock_short': format_count(stats.get('stock_shortage_count', 0)),
    }


@admin_bp.route('/dashboard')
@login_required
@role_required('admin', 'executive')
def dashboard():
    """Administration dashboard.

    Carries the same figures as the Executive dashboard, from the same two
    helpers - the live card deck plus the period sections. The timeframe is
    read off the query string here too, so the Administrator can move the
    whole board between daily, weekly, monthly, quarterly and all time -
    the card deck included, not only the sections beneath it.
    """
    from src.utils.date_ranges import dashboard_period

    window = dashboard_period(request.args.get('period'))
    stats, recent_items, error = _compute_admin_dashboard_stats(window)

    try:
        if error:
            flash(f'⚠️ Dashboard loaded with partial data. Error: {error}', 'warning')
        return render_template('admin/dashboard.html', stats=stats,
                               sync=dashboard_sync_values(stats), recent_pos=recent_items,
                               **_period_dashboard_context(window))
    except Exception as e:
        import traceback
        # If even rendering fails, show HTML error
        error_html = f"""
        <div style="padding: 20px; font-family: Arial, sans-serif; background: #f8f9fa; min-height: 100vh;">
            <div style="max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                <h2 style="color: #dc3545; margin-top: 0;">Dashboard Error</h2>
                <div style="background: #fff3cd; padding: 15px; border-radius: 5px; margin-bottom: 20px; border-left: 4px solid #ffc107;">
                    <p style="margin: 0;"><strong>Error:</strong> {str(e)}</p>
                </div>
                <h3>Stack Trace:</h3>
                <pre style="background: #f8f9fa; padding: 15px; border-radius: 5px; overflow: auto; max-height: 500px; font-size: 12px; border: 1px solid #dee2e6;">{traceback.format_exc()}</pre>
                <p style="margin-top: 20px;">
                    <a href="{url_for('admin.dashboard')}" style="background: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Retry</a>
                    <a href="{url_for('admin.dashboard_debug')}" style="background: #6c757d; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; margin-left: 10px;">Debug</a>
                </p>
            </div>
        </div>
        """
        return error_html, 500


# ============================================
# DEBUG ROUTE
# ============================================

@admin_bp.route('/dashboard-debug')
@login_required
@role_required('admin')
def dashboard_debug():
    ...

@admin_bp.route('/api/dashboard-stats')
@login_required
@role_required('admin', 'executive')
def api_dashboard_stats():
    """Live values for the 120-second dashboard refresh.

    Serves both the Administration and the Executive dashboard - they render
    the same card deck from the same helper, so they refresh from the same
    endpoint too. It used to recompute a hand-picked three of the figures
    (POs, payments, GPS) with its own fallbacks, which meant most of the deck
    silently went stale and the three it did refresh were formatted by
    different code than the ones Jinja had rendered. Now it returns every
    card's value, already formatted, from the one helper.

    The timeframe travels with the request - the page puts its own period on
    this endpoint's URL - so a refresh recounts the window the board is
    showing rather than quietly resetting it to the default.
    """
    from src.utils.date_ranges import dashboard_period

    try:
        stats, _recent, error = _compute_admin_dashboard_stats(
            dashboard_period(request.args.get('period')))
        return jsonify({
            'success': True,
            'values': dashboard_sync_values(stats),
            'partial': bool(error),
            'timestamp': datetime.now().strftime('%H:%M:%S')
        })
    except Exception as e:
        logger.error(f"Fatal API dashboard-stats error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/dashboard-test-debug')
@login_required
def dashboard_test_debug():
    """Debug route to test dashboard components"""
    import traceback
    
    result: Dict[str, Any] = {
        'status': 'starting',
        'steps': [],
        'error': None,
        'stats': {}
    }
    
    try:
        # Step 1: Test imports
        result['steps'].append('Testing imports...')
        from src.services import POService, UserService, TechnicianService, GPSService, SecurityBriefingService, PaymentRecoveryService
        result['steps'].append('✅ Imports successful')
        
        # Step 2: Test service creation
        result['steps'].append('Creating services...')
        po_service = POService()
        user_service = UserService()
        tech_service = TechnicianService()
        gps_service = GPSService()
        result['steps'].append('✅ Services created')
        
        # Step 3: Test PO stats
        result['steps'].append('Testing PO stats...')
        try:
            po_stats = po_service.get_dashboard_stats()
            result['steps'].append(f'✅ PO stats: {po_stats}')
            result['stats']['pos'] = po_stats
        except Exception as e:
            result['steps'].append(f'❌ PO stats error: {str(e)}')
            result['steps'].append(traceback.format_exc())
        
        # Step 4: Test User stats
        result['steps'].append('Testing User stats...')
        try:
            user_stats = user_service.get_dashboard_stats()
            result['steps'].append(f'✅ User stats: {user_stats}')
            result['stats']['users'] = user_stats
        except Exception as e:
            result['steps'].append(f'❌ User stats error: {str(e)}')
            result['steps'].append(traceback.format_exc())
        
        # Step 5: Test Technician count
        result['steps'].append('Testing Technician count...')
        try:
            tech_total = tech_service.count()
            tech_active = tech_service.count(is_active=True)
            result['steps'].append(f'✅ Technician count: total={tech_total}, active={tech_active}')
            result['stats']['technicians'] = {'total': tech_total, 'active': tech_active}
        except Exception as e:
            result['steps'].append(f'❌ Technician count error: {str(e)}')
            result['steps'].append(traceback.format_exc())
        
        # Step 6: Test GPS
        result['steps'].append('Testing GPS...')
        try:
            active_vehicles = len(gps_service.get_active_vehicles())
            result['steps'].append(f'✅ GPS active vehicles: {active_vehicles}')
            result['stats']['gps'] = {'active_vehicles': active_vehicles}
        except Exception as e:
            result['steps'].append(f'❌ GPS error: {str(e)}')
            result['steps'].append(traceback.format_exc())
        
        # Step 7: Test Security Briefing
        result['steps'].append('Testing Security Briefing...')
        try:
            security_service = SecurityBriefingService()
            security_stats = security_service.get_dashboard_stats()
            result['steps'].append(f'✅ Security stats: {security_stats}')
            result['stats']['security'] = security_stats
        except Exception as e:
            result['steps'].append(f'❌ Security error: {str(e)}')
            result['steps'].append(traceback.format_exc())
        
        # Step 8: Test Payment Recovery
        result['steps'].append('Testing Payment Recovery...')
        try:
            payment_service = PaymentRecoveryService()
            payment_stats = payment_service.get_dashboard_stats()
            result['steps'].append(f'✅ Payment stats: {payment_stats}')
            result['stats']['payment'] = payment_stats
        except Exception as e:
            result['steps'].append(f'❌ Payment error: {str(e)}')
            result['steps'].append(traceback.format_exc())
        
        # Step 9: Test Recent POs
        result['steps'].append('Testing Recent POs...')
        try:
            recent_pos = po_service.get_pos(page=1, per_page=10)
            result['steps'].append(f'✅ Recent POs: {len(recent_pos.get("items", []))} items')
            result['stats']['recent_pos_count'] = len(recent_pos.get('items', []))
        except Exception as e:
            result['steps'].append(f'❌ Recent POs error: {str(e)}')
            result['steps'].append(traceback.format_exc())
        
        # Step 10: Test template rendering
        result['steps'].append('Testing template rendering...')
        try:
            # Try to render the template with minimal data
            test_stats = {
                'pos': {'total': 0, 'pending': 0, 'in_progress': 0, 'completed': 0},
                'users': {'total': 0, 'active': 0},
                'technicians': {'total': 0, 'active': 0},
                'gps': {'active_vehicles': 0, 'last_sync': 'Test'},
                'total_briefings': 0,
                'pending_briefings': 0,
                'completed_briefings': 0,
                'total_amount_pending': 0,
                'pending': 0,
            }
            render_template('admin/dashboard.html', stats=test_stats, recent_pos=[])
            result['steps'].append('✅ Template rendered successfully')
        except Exception as e:
            result['steps'].append(f'❌ Template error: {str(e)}')
            result['steps'].append(traceback.format_exc())
        
        result['status'] = 'success'
        
    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)
        result['steps'].append(f'❌ Fatal error: {str(e)}')
        result['steps'].append(traceback.format_exc())
    
    return jsonify(result)


# ============================================
# TEST ROUTES
# ============================================

@admin_bp.route('/ping')
@login_required
def ping():
    """Simple ping test to verify authentication"""
    return jsonify({
        "status": "ok",
        "user": current_user.username,
        "role": current_user.role,
        "authenticated": current_user.is_authenticated
    })


@admin_bp.route('/dashboard-test')
@login_required
def dashboard_test():
    """Simple test route for dashboard"""
    return jsonify({
        "status": "success",
        "message": "Test route is working!",
        "user": current_user.username if current_user.is_authenticated else "Not logged in"
    })


# ============================================
# PURCHASE ORDER MANAGEMENT
# ============================================

@admin_bp.route('/pos')
@login_required
@role_required('admin', 'executive')
def pos_list():
    """List all purchase orders - Admin sees ALL POs"""
    po_service = POService()

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '')
    status = request.args.get('status', '')
    sales_person_filter = request.args.get('sales_person', '')
    # `created=today` is the standalone "raised today" view. The dashboard no
    # longer links it - every card there now carries the board's timeframe as
    # `since` instead - but it stays a valid filter on this list.
    created = (request.args.get('created') or '').strip().lower()
    # `since` and `city` back every dashboard card that counts purchase
    # orders: a card that counted a period has to open that period, or the
    # number on it is one the list it leads to cannot reproduce.
    since = (request.args.get('since') or '').strip()
    city = (request.args.get('city') or '').strip()

    filters: Dict[str, Any] = {}
    if status:
        filters['status'] = status
    if sales_person_filter:
        filters['sales_person_id'] = int(sales_person_filter)

    if created == 'today':
        orders, total = _pos_created_today(status, sales_person_filter, page, per_page)
    elif since or city:
        orders, total = _pos_in_period(status, sales_person_filter, since, city,
                                       page, per_page)
    else:
        result = po_service.get_pos(filters=filters, page=page, per_page=per_page, search=search)
        orders, total = result['items'], result['total']

    sales_users = UserService().get_sales_users()

    return render_template('admin/pos.html',
                         orders=orders,
                         total=total,
                         page=page,
                         per_page=per_page,
                         search=search,
                         status=status,
                         created=created,
                         since=since,
                         city=city,
                         sales_users=sales_users,
                         sales_person_filter=sales_person_filter)


def _pos_in_period(status: str, sales_person_filter: str, since: str, city: str,
                   page: int, per_page: int):
    """POs raised on or after `since`, optionally in one city.

    Dated by `created_at` - the day the order came in - which is what the
    dashboard's period cards counted. `_pos_created_today` above deliberately
    dates completions differently; this one has no such asymmetry because the
    period cards count raised orders throughout.
    """
    from datetime import datetime as _dt
    from src.models.purchase_order import PurchaseOrder

    query = PurchaseOrder.query
    if since:
        try:
            query = query.filter(PurchaseOrder.created_at >= _dt.strptime(since, '%Y-%m-%d'))
        except ValueError:
            pass  # a malformed date narrows nothing rather than everything
    if city:
        # Stored uppercase by sanitize_data; the card labels it in title case.
        query = query.filter(db.func.upper(PurchaseOrder.city) == city.strip().upper())
    if status:
        query = query.filter(PurchaseOrder.status == status)
    if sales_person_filter:
        query = query.filter(PurchaseOrder.sales_person_id == int(sales_person_filter))

    total = query.count()
    orders = (query.order_by(PurchaseOrder.created_at.desc())
              .offset((page - 1) * per_page).limit(per_page).all())
    return orders, total


def _pos_created_today(status: str, sales_person_filter: str, page: int, per_page: int):
    """POs whose *card* on the dashboard counted them today.

    Mirrors POURepository.get_dashboard_stats exactly, including its one
    asymmetry: "completed today" is dated by `updated_at` (the day the work
    was finished), everything else by `created_at` (the day the order came
    in). Counting one way and listing the other is how a card and its list
    drift apart, so this reads the same columns the counts do - and takes
    the day boundary from the same helper they do, rather than defining
    "today" a second time.
    """
    from src.models.purchase_order import PurchaseOrder
    from src.repositories.po_repository import POURepository

    date_col = (PurchaseOrder.updated_at if status == 'COMPLETED'
                else PurchaseOrder.created_at)
    start, end = POURepository.today_bounds()
    query = PurchaseOrder.query.filter(date_col >= start, date_col < end)
    if status:
        query = query.filter(PurchaseOrder.status == status)
    if sales_person_filter:
        query = query.filter(PurchaseOrder.sales_person_id == int(sales_person_filter))

    total = query.count()
    items = (query.order_by(PurchaseOrder.created_at.desc())
             .offset((page - 1) * per_page).limit(per_page).all())
    return items, total


# ============================================
# PURCHASE ORDER BULK UPDATE
# ============================================

def _bulk_update_scope():
    """Which orders the current user's bulk update may touch.

    None means the whole order book. That is the Administrator and the
    Executive - the same two roles that already see every PO on the Sales
    Dashboard, so this hands them nothing they could not already reach.

    A salesperson gets their own id back instead. They keep the screen, and
    the rows in their sheet that belong to a colleague come back reported and
    unwritten. Sales has never been able to open another salesperson's PO;
    arriving with it in a spreadsheet is not a way around that.
    """
    if current_user.is_admin() or current_user.is_executive():
        return None
    return current_user.id


@admin_bp.route('/pos/bulk-update', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'executive', 'sales')
def po_bulk_update():
    """Upload a Text/Excel/Word sheet of PO changes and see what it would do.

    Deliberately two steps. This one never writes: it reads the file, matches
    every row against a PO, validates the values and shows the result. The
    apply step below takes that checked plan and commits it. Splitting them
    is what makes a bad file harmless - the user finds out about the three
    unmatched registrations before anything has changed, not after.
    """
    from src.services.po_bulk_update_service import (
        POBulkUpdateService, BulkUpdateError, SUPPORTED_EXTENSIONS, MAX_ROWS)

    scope_user_id = _bulk_update_scope()

    context: Dict[str, Any] = {
        'extensions': SUPPORTED_EXTENSIONS,
        'max_rows': MAX_ROWS,
        'preview': None,
        # Drives the "your own orders only" note on the page. A salesperson
        # should be told the rule before they upload, not by a table of
        # refused rows afterwards.
        'scoped_to_own': scope_user_id is not None,
    }

    if request.method == 'POST':
        upload = request.files.get('file')
        if upload is None or not (upload.filename or '').strip():
            flash('Choose a file to upload.', 'warning')
            return render_template('admin/po_bulk_update.html', **context)

        try:
            preview = POBulkUpdateService().prepare(
                upload.filename or '', upload.read(), scope_user_id)
        except BulkUpdateError as e:
            flash(str(e), 'danger')
            return render_template('admin/po_bulk_update.html', **context)
        except Exception as e:
            logger.error(f"Bulk PO update: could not read {upload.filename}: {e}")
            flash(f'The file could not be read: {e}', 'danger')
            return render_template('admin/po_bulk_update.html', **context)

        context['preview'] = preview
        # Only what apply() needs travels to the next step. The display
        # columns stay on this page rather than making a round trip.
        context['plan_json'] = json.dumps([
            {'row_no': r['row_no'], 'po_id': r['po_id'], 'po_number': r['po_number'],
             'changes': r['changes'], 'outcome': r['outcome']}
            for r in preview['rows'] if r['outcome'] == 'update'
        ])

    return render_template('admin/po_bulk_update.html', **context)


@admin_bp.route('/pos/bulk-update/apply', methods=['POST'])
@login_required
@role_required('admin', 'executive', 'sales')
def po_bulk_update_apply():
    """Commit the plan the preview produced."""
    from src.services.po_bulk_update_service import POBulkUpdateService

    try:
        rows = json.loads(request.form.get('plan') or '[]')
    except ValueError:
        flash('That update could not be read back. Please upload the file again.', 'danger')
        return redirect(url_for('admin.po_bulk_update'))

    # Re-assert the shape rather than trusting the form: this comes back
    # through the browser, and `apply` is about to write to POs with it.
    rows = [r for r in rows
            if isinstance(r, dict) and r.get('outcome') == 'update'
            and isinstance(r.get('po_id'), int) and isinstance(r.get('changes'), dict)]

    if not rows:
        flash('Nothing to update - no valid changes were selected.', 'warning')
        return redirect(url_for('admin.po_bulk_update'))

    result = POBulkUpdateService().apply(rows, current_user.id, _bulk_update_scope())

    if result['applied']:
        flash(f"{result['applied']} purchase order(s) updated - "
              f"{result['fields']} field(s) written.", 'success')
    if result['completed']:
        flash(f"{len(result['completed'])} purchase order(s) were marked COMPLETED, "
              'which sent the completion email and raised the security briefing: '
              + ', '.join(result['completed'][:10])
              + ('...' if len(result['completed']) > 10 else ''), 'info')
    if result['routed']:
        flash(f"{len(result['routed'])} purchase order(s) still awaiting work were "
              'routed to the installation team: '
              + ', '.join(result['routed'][:10])
              + ('...' if len(result['routed']) > 10 else ''), 'info')
    if result.get('refused'):
        flash(f"{result['refused']} purchase order(s) were not written because "
              'they were raised by another salesperson.', 'warning')
    for failure in result['failed']:
        flash(f"Row {failure['row_no']} ({failure['po_number']}) failed: {failure['error']}", 'danger')
    if not result['applied'] and not result['failed']:
        flash('No changes were applied.', 'warning')

    # The admin PO list is admin/executive only, so a salesperson finishing a
    # bulk update would land on an unauthorised page. Send them where their
    # orders actually are.
    if current_user.is_admin() or current_user.is_executive():
        return redirect(url_for('admin.pos_list'))
    return redirect(url_for('sales.dashboard'))


@admin_bp.route('/pos/add', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def po_add():
    """Create a new purchase order"""
    form = POCreationForm()
    form = populate_form_choices(form)
    
    if form.validate_on_submit():
        po_service = POService()
        data = {
            'owner_name': form.owner_name.data.upper() if form.owner_name.data else '',
            'owner_contact': form.owner_contact.data,
            'contact_person_driver': form.contact_person_driver.data.upper() if form.contact_person_driver.data else None,
            'reg_no': form.reg_no.data.upper() if form.reg_no.data else '',
            'vehicle_make': form.vehicle_make.data.upper() if form.vehicle_make.data else '',
            'vehicle_model': form.vehicle_model.data.upper() if form.vehicle_model.data else '',
            # Vehicle year/color, engine/chassis numbers aren't collected on
            # this simplified creation form - the installer fills these in
            # when they update the PO (see installation.update_po).
            'vehicle_year': 'PENDING',
            'vehicle_color': 'PENDING',
            'engine_number': 'PENDING',
            'chassis_number': 'PENDING',
            'sales_person_id': form.sales_person_id.data,
            'city': None,
            'vehicle_availability_location': form.vehicle_availability_location.data.upper() if form.vehicle_availability_location.data else '',
            'existing_customer_name': form.existing_customer_name.data.upper() if form.existing_customer_name.data else '',
            'existing_vehicle_number': form.existing_vehicle_number.data.upper() if form.existing_vehicle_number.data else '',
            # Not collected on this simplified creation form - set during
            # installation scheduling instead.
            'scheduled_date': None,
            'rates': form.rates.data or 0.0,
            'amc': form.amc.data or 0.0,
        }

        
        try:
            po = po_service.create_po(data, current_user.id)
            flash(f'PO {po.po_number} created successfully!', 'success')
            return redirect(url_for('admin.pos_list'))
        except ValueError as e:
            flash(str(e), 'danger')
        except Exception as e:
            logger.error(f"Error creating PO: {e}")
            flash('An error occurred while creating the PO.', 'danger')
    
    return render_template('admin/po_add.html', form=form,
                           make_model_map=VehicleModelService().get_make_model_map())


@admin_bp.route('/pos/export')
@login_required
@role_required('admin')
def pos_export():
    """Export POs to CSV"""
    import csv
    import io
    
    po_service = POService()
    result = po_service.get_pos()
    pos = result['items']
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['PO Number', 'Customer Name', 'Contact', 'Registration', 'Make', 'Model', 'Year', 'Status'])
    
    for po in pos:
        writer.writerow([
            po.po_number,
            po.owner_name,
            po.owner_contact,
            po.reg_no,
            po.vehicle_make,
            po.vehicle_model,
            po.vehicle_year,
            po.status
        ])
    
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f"pos_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )


@admin_bp.route('/pos/<int:po_id>')
@login_required
@role_required('admin')
def po_detail(po_id):
    """View PO details - Admin can view ANY PO"""
    po_service = POService()
    po = po_service.get_po(po_id)
    
    if not po:
        flash('PO not found', 'danger')
        return redirect(url_for('admin.pos_list'))
    
    return render_template('admin/po_detail.html', po=po)


@admin_bp.route('/pos/<int:po_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def po_edit(po_id):
    """Edit PO - Admin can edit ANY PO"""
    po_service = POService()
    po = po_service.get_po(po_id)
    
    if not po:
        flash('PO not found', 'danger')
        return redirect(url_for('admin.pos_list'))
    
    form = POCreationForm(obj=po)
    form = populate_form_choices(form)
    
    if form.validate_on_submit():
        data = {
            'owner_name': form.owner_name.data.upper() if form.owner_name.data else '',
            'owner_contact': form.owner_contact.data or '',
            'contact_person_driver': form.contact_person_driver.data.upper() if form.contact_person_driver.data else '',
            'reg_no': form.reg_no.data.upper() if form.reg_no.data else '',
            'vehicle_make': form.vehicle_make.data or po.vehicle_make,
            'vehicle_model': form.vehicle_model.data or po.vehicle_model,
            'vehicle_year': form.vehicle_year.data if form.vehicle_year.data else po.vehicle_year,
            'vehicle_color': form.vehicle_color.data if form.vehicle_color.data else po.vehicle_color,
            'engine_number': form.engine_number.data or po.engine_number,
            'chassis_number': form.chassis_number.data or po.chassis_number,
            'sales_person_id': form.sales_person_id.data,
            'city': form.city.data if form.city.data else po.city,
            'vehicle_availability_location': form.vehicle_availability_location.data or po.vehicle_availability_location,
            'existing_customer_name': form.existing_customer_name.data.upper() if form.existing_customer_name.data else '',
            'existing_vehicle_number': form.existing_vehicle_number.data.upper() if form.existing_vehicle_number.data else '',
            'scheduled_date': form.scheduled_date.data if form.scheduled_date.data else po.scheduled_date,
            'technician_assigned': form.technician_assigned.data or po.technician_assigned,
            'imei_no': form.imei_no.data or po.imei_no,
            'sim_no': form.sim_no.data or po.sim_no,
            'device_type': form.device_type.data or po.device_type,
            'device_location': form.device_location.data or po.device_location,
            'fuel': form.fuel.data or po.fuel,
            'tested_by': form.tested_by.data or po.tested_by,
            'arranged_by_sales_person': form.arranged_by_sales_person.data or po.arranged_by_sales_person,
            'remarks': form.remarks.data if form.remarks.data is not None else po.remarks,
            'status': form.status.data if form.status.data else po.status,
            'rates': form.rates.data or 0.0,
            'amc': form.amc.data or 0.0,
        }

        updated_po = po_service.update_po(po_id, data, current_user.id)
        if updated_po:
            flash(f'✅ PO {po.po_number} updated successfully!', 'success')
            return redirect(url_for('admin.po_detail', po_id=po_id))
    
    return render_template('admin/po_edit.html', form=form, po=po,
                           make_model_map=VehicleModelService().get_make_model_map())


@admin_bp.route('/pos/<int:po_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def po_delete(po_id):
    """Delete PO - Admin can delete ANY PO"""
    po_service = POService()
    success = po_service.delete(po_id)
    
    if success:
        flash(f'✅ PO deleted successfully', 'success')
    else:
        flash('PO not found', 'danger')
    
    return redirect(url_for('admin.pos_list'))


@admin_bp.route('/po/<int:po_id>/uncancel', methods=['POST'])
@login_required
@role_required('admin')
def po_uncancel(po_id):
    """Uncancel a PO"""
    po_service = POService()
    po = po_service.get_po(po_id)
    
    if po and po.status == 'CANCELLED':
        po_service.update_po(po_id, {'status': 'PENDING'}, current_user.id)
        flash(f'PO {po.po_number} uncancelled', 'success')
    else:
        flash('PO is not cancelled or not found', 'warning')
    
    return redirect(url_for('admin.installation_queue'))


# ============================================
# USER MANAGEMENT
# ============================================

@admin_bp.route('/users')
@login_required
@role_required('admin')
def users():
    """List users in user-code order.

    Sorted on the number inside the code rather than on the code as text:
    'USR-10' sorts before 'USR-9' alphabetically, and the padding only hides
    that until the hundredth user. Anyone without a code yet goes last, by
    name, rather than to the top on an empty string.
    """
    user_service = UserService()

    def by_user_code(user):
        digits = ''.join(ch for ch in (user.user_code or '').split('-')[-1]
                         if ch.isdigit())
        if digits:
            return (0, int(digits), '')
        return (1, 0, (user.name or user.username or '').upper())

    users = sorted(user_service.get_all(), key=by_user_code)
    return render_template('admin/users.html', users=users)


def _apply_text_case(text_case, username, password):
    """Apply the administrator's chosen case to a new username/password pair.
    'as_typed' leaves both untouched; 'lower'/'upper' force both - a blank
    password (unset on edit) is left as None rather than becoming ''."""
    if text_case == 'lower':
        username = username.lower() if username else username
        password = password.lower() if password else password
    elif text_case == 'upper':
        username = username.upper() if username else username
        password = password.upper() if password else password
    return username, password


@admin_bp.route('/users/new', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def user_new():
    """Create new user"""
    from wtforms.validators import DataRequired, Length
    form = UserForm()
    form.password.validators = [
        DataRequired(message='Password is required when creating a user'),
        Length(min=6, message='Password must be at least 6 characters')
    ]
    
    if form.validate_on_submit():
        user_service = UserService()
        additional = [r for r in (form.additional_roles.data or []) if r != form.role.data]
        username, password = _apply_text_case(form.text_case.data, form.username.data, form.password.data)
        data = {
            'username': username,
            'email': form.email.data,
            'password': password,
            'role': form.role.data,
            'name': form.name.data,
            'contact': form.contact.data,
            'is_active': form.is_active.data == 'True',
            'additional_roles': ','.join(additional) if additional else None
        }

        try:
            user = user_service.create_user(**data)
            flash(f'User {user.username} created successfully!', 'success')
            return redirect(url_for('admin.users'))
        except Exception as e:
            flash(str(e), 'danger')
    
    return render_template('admin/user_form.html', form=form, title='Add User')


@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def user_edit(user_id):
    """Edit user"""
    from wtforms.validators import Optional, Length
    user_service = UserService()
    user = user_service.get_by_id(user_id)
    
    if not user:
        flash('User not found', 'danger')
        return redirect(url_for('admin.users'))
    
    form = UserForm(obj=user)
    form._user_id = user.id  # lets validate_username/validate_email exclude this user's own record
    form.password.validators = [
        Optional(),
        Length(min=6, message='Password must be at least 6 characters')
    ]
    if request.method == 'GET':
        form.is_active.data = 'True' if user.is_active else 'False'
        form.additional_roles.data = user.get_additional_roles()

    if form.validate_on_submit():
        additional = [r for r in (form.additional_roles.data or []) if r != form.role.data]
        username, password = _apply_text_case(form.text_case.data, form.username.data, form.password.data)
        data = {
            'username': username,
            'email': form.email.data,
            'role': form.role.data,
            'name': form.name.data,
            'contact': form.contact.data,
            'is_active': form.is_active.data == 'True',
            'additional_roles': ','.join(additional) if additional else None
        }

        if password and str(password).strip():
            data['password'] = str(password).strip()

        try:
            updated_user = user_service.update(user_id, **data)
            username = updated_user.username if updated_user else 'User'
            flash(f'User {username} updated successfully!', 'success')
            return redirect(url_for('admin.users'))
        except Exception as e:
            flash(str(e), 'danger')
    
    return render_template('admin/user_form.html', form=form, title='Edit User', user=user)


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def user_delete(user_id):
    """Delete user"""
    if user_id == current_user.id:
        flash('Cannot delete your own account!', 'danger')
        return redirect(url_for('admin.users'))
    
    user_service = UserService()
    success = user_service.delete(user_id)
    
    if success:
        flash('User deleted successfully', 'success')
    else:
        flash('User not found', 'danger')
    
    return redirect(url_for('admin.users'))


# ============================================
# CITIES MANAGEMENT
# ============================================

# ============================================
# REPORT RECIPIENTS (SETTINGS)
# ============================================

@admin_bp.route('/report-recipients')
@login_required
@role_required('admin')
def report_recipients():
    """Who receives the month-end report pack.

    Seeded from the built-in management list the first time this is opened,
    so the page starts by showing who is on it today rather than empty.
    """
    from src.models.report_recipient import ReportRecipient
    from src.services.email_service import SENIOR_MANAGEMENT_RECIPIENTS

    ReportRecipient.ensure_seeded(SENIOR_MANAGEMENT_RECIPIENTS)
    recipients = ReportRecipient.query.order_by(
        ReportRecipient.is_active.desc(), ReportRecipient.email).all()

    return render_template('admin/report_recipients.html',
                           recipients=recipients,
                           active_count=sum(1 for r in recipients if r.is_active),
                           fallback=SENIOR_MANAGEMENT_RECIPIENTS)


@admin_bp.route('/report-recipients/add', methods=['POST'])
@login_required
@role_required('admin')
def report_recipient_add():
    from src.models.report_recipient import ReportRecipient

    email = ReportRecipient.normalize(request.form.get('email', ''))
    name = (request.form.get('name') or '').strip()

    # Deliberately light validation - the address has to look like one, and
    # the rest is the administrator's business.
    if '@' not in email or '.' not in email.split('@')[-1]:
        flash('That does not look like an email address.', 'danger')
        return redirect(url_for('admin.report_recipients'))

    existing = ReportRecipient.query.filter_by(email=email).first()
    if existing:
        # Re-adding someone who was removed reactivates them rather than
        # failing on the unique index.
        if existing.is_active:
            flash(f'{email} already receives these reports.', 'warning')
        else:
            existing.is_active = True
            db.session.commit()
            flash(f'{email} will receive these reports again.', 'success')
        return redirect(url_for('admin.report_recipients'))

    db.session.add(ReportRecipient(email=email, name=name or None, is_active=True,
                                   created_by=current_user.id))
    db.session.commit()
    logger.info(f'{current_user.username} added {email} to the report distribution')
    flash(f'{email} added to the report distribution.', 'success')
    return redirect(url_for('admin.report_recipients'))


@admin_bp.route('/report-recipients/<int:recipient_id>/toggle', methods=['POST'])
@login_required
@role_required('admin')
def report_recipient_toggle(recipient_id):
    """Turn an address on or off without losing the record of it."""
    from src.models.report_recipient import ReportRecipient

    recipient = ReportRecipient.query.get_or_404(recipient_id)
    others_active = ReportRecipient.query.filter(
        ReportRecipient.is_active.is_(True),
        ReportRecipient.id != recipient.id).count()

    if recipient.is_active and others_active == 0:
        # An empty list falls back to the built-in one, which would look like
        # the change did nothing. Say so instead.
        flash('This is the last active recipient - add another before '
              'removing this one.', 'danger')
        return redirect(url_for('admin.report_recipients'))

    recipient.is_active = not recipient.is_active
    recipient.updated_by = current_user.id
    db.session.commit()

    state = 'will receive' if recipient.is_active else 'will no longer receive'
    logger.info(f'{current_user.username} set {recipient.email} to '
                f'{"active" if recipient.is_active else "inactive"}')
    flash(f'{recipient.email} {state} these reports.', 'success')
    return redirect(url_for('admin.report_recipients'))


@admin_bp.route('/report-recipients/<int:recipient_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def report_recipient_delete(recipient_id):
    from src.models.report_recipient import ReportRecipient

    recipient = ReportRecipient.query.get_or_404(recipient_id)
    others_active = ReportRecipient.query.filter(
        ReportRecipient.is_active.is_(True),
        ReportRecipient.id != recipient.id).count()

    if recipient.is_active and others_active == 0:
        flash('This is the last active recipient - add another before '
              'removing this one.', 'danger')
        return redirect(url_for('admin.report_recipients'))

    email = recipient.email
    db.session.delete(recipient)
    db.session.commit()
    logger.info(f'{current_user.username} removed {email} from the report distribution')
    flash(f'{email} removed from the report distribution.', 'success')
    return redirect(url_for('admin.report_recipients'))


@admin_bp.route('/cities')
@login_required
@role_required('admin')
def cities():
    """List cities"""
    city_service = CityService()
    cities = city_service.get_all_cities()
    return render_template('admin/cities.html', cities=cities)


@admin_bp.route('/cities/add', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def city_add():
    """Add city"""
    form = CityForm()
    if form.validate_on_submit():
        city_service = CityService()
        try:
            city = city_service.create_city(form.name.data or '')
            flash(f'City "{city.name}" added!', 'success')
            return redirect(url_for('admin.cities'))
        except Exception as e:
            flash(str(e), 'danger')
    return render_template('admin/city_form.html', form=form, title='Add City')


@admin_bp.route('/cities/<int:city_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def city_edit(city_id):
    """Edit city"""
    city_service = CityService()
    city = city_service.get_by_id(city_id)
    
    if not city:
        flash('City not found', 'danger')
        return redirect(url_for('admin.cities'))
    
    form = CityForm(obj=city)
    if form.validate_on_submit():
        try:
            updated_city = city_service.update_city(city_id, form.name.data or '')
            city_name = updated_city.name if updated_city else ''
            flash(f'City "{city_name}" updated!', 'success')
            return redirect(url_for('admin.cities'))
        except Exception as e:
            flash(str(e), 'danger')
    
    return render_template('admin/city_form.html', form=form, title='Edit City', city=city)


@admin_bp.route('/cities/<int:city_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def city_delete(city_id):
    """Delete city"""
    city_service = CityService()
    success = city_service.delete(city_id)
    
    if success:
        flash('City deleted successfully', 'success')
    else:
        flash('City not found', 'danger')
    
    return redirect(url_for('admin.cities'))


# ============================================
# VEHICLE MAKES MANAGEMENT
# ============================================

@admin_bp.route('/makes')
@login_required
@role_required('admin')
def makes():
    """Unified vehicle makes and models view"""
    make_service = VehicleMakeService()
    model_service = VehicleModelService()
    makes_list = make_service.get_all_makes()
    models_list = model_service.get_all()
    make_form = VehicleMakeForm()
    model_form = VehicleModelForm()
    model_form.make_id.choices = [(m.id, m.name) for m in makes_list]
    return render_template('admin/makes_models.html', makes=makes_list, models=models_list, make_form=make_form, model_form=model_form)


@admin_bp.route('/models')
@login_required
@role_required('admin')
def models():
    """Redirect models route to unified makes_models view"""
    return redirect(url_for('admin.makes'))


@admin_bp.route('/makes/add', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def make_add():
    """Add vehicle make"""
    form = VehicleMakeForm()
    if request.method == 'POST':
        make_service = VehicleMakeService()
        try:
            name = (request.form.get('name') or form.name.data or '').strip().upper()
            if name:
                make = make_service.create_make(name)
                flash(f'Make "{make.name}" added successfully!', 'success')
            return redirect(url_for('admin.makes'))
        except Exception as e:
            flash(str(e), 'danger')
    return redirect(url_for('admin.makes'))


@admin_bp.route('/makes/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def make_edit(id):
    """Edit vehicle make on merged view"""
    make_service = VehicleMakeService()
    model_service = VehicleModelService()
    make = make_service.get_by_id(id)
    if not make:
        flash('Make not found', 'danger')
        return redirect(url_for('admin.makes'))
    
    if request.method == 'POST':
        try:
            name = (request.form.get('name') or '').strip().upper()
            updated_make = make_service.update_make(id, name)
            make_name = updated_make.name if updated_make else ''
            flash(f'Make "{make_name}" updated!', 'success')
            return redirect(url_for('admin.makes'))
        except Exception as e:
            flash(str(e), 'danger')
    
    makes_list = make_service.get_all_makes()
    models_list = model_service.get_all()
    make_form = VehicleMakeForm(obj=make)
    model_form = VehicleModelForm()
    model_form.make_id.choices = [(m.id, m.name) for m in makes_list]
    return render_template('admin/makes_models.html', makes=makes_list, models=models_list, make_form=make_form, model_form=model_form, editing_make=make)


@admin_bp.route('/makes/<int:id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def make_delete(id):
    """Delete vehicle make"""
    make_service = VehicleMakeService()
    success = make_service.delete(id)
    if success:
        flash('Make deleted successfully', 'success')
    else:
        flash('Make not found', 'danger')
    return redirect(url_for('admin.makes'))


@admin_bp.route('/models/add', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def model_add():
    """Add vehicle model"""
    if request.method == 'POST':
        model_service = VehicleModelService()
        try:
            name = (request.form.get('name') or '').strip().upper()
            make_id = int(request.form.get('make_id', 0))
            if name and make_id:
                model = model_service.create_model(name, make_id)
                flash(f'Model "{model.name}" added successfully!', 'success')
            return redirect(url_for('admin.makes'))
        except Exception as e:
            flash(str(e), 'danger')
    return redirect(url_for('admin.makes'))


@admin_bp.route('/models/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def model_edit(id):
    """Edit vehicle model on merged view"""
    model_service = VehicleModelService()
    make_service = VehicleMakeService()
    model = model_service.get_by_id(id)
    if not model:
        flash('Model not found', 'danger')
        return redirect(url_for('admin.makes'))
    
    if request.method == 'POST':
        try:
            name = (request.form.get('name') or '').strip().upper()
            make_id = int(request.form.get('make_id', 0))
            updated_model = model_service.update_model(id, name, make_id)
            model_name = updated_model.name if updated_model else ''
            flash(f'Model "{model_name}" updated!', 'success')
            return redirect(url_for('admin.makes'))
        except Exception as e:
            flash(str(e), 'danger')
            
    makes_list = make_service.get_all_makes()
    models_list = model_service.get_all()
    make_form = VehicleMakeForm()
    model_form = VehicleModelForm(obj=model)
    model_form.make_id.choices = [(m.id, m.name) for m in makes_list]
    return render_template('admin/makes_models.html', makes=makes_list, models=models_list, make_form=make_form, model_form=model_form, editing_model=model)


@admin_bp.route('/models/<int:id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def model_delete(id):
    """Delete vehicle model"""
    model_service = VehicleModelService()
    success = model_service.delete(id)
    if success:
        flash('Model deleted successfully', 'success')
    else:
        flash('Model not found', 'danger')
    return redirect(url_for('admin.makes'))


# ============================================
# VEHICLE YEARS MANAGEMENT
# ============================================

@admin_bp.route('/years')
@login_required
@role_required('admin')
def years():
    """List vehicle years"""
    year_service = VehicleYearService()
    years = year_service.get_all_years()
    return render_template('admin/years.html', years=years)


@admin_bp.route('/years/add', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def year_add():
    """Add vehicle year"""
    form = VehicleYearForm()
    if form.validate_on_submit():
        year_service = VehicleYearService()
        try:
            year = year_service.create_year(form.year.data or '')
            flash(f'Year "{year.year}" added!', 'success')
            return redirect(url_for('admin.years'))
        except Exception as e:
            flash(str(e), 'danger')
    return render_template('admin/year_form.html', form=form, title='Add Year')


@admin_bp.route('/years/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def year_edit(id):
    """Edit vehicle year"""
    year_service = VehicleYearService()
    year = year_service.get_by_id(id)
    
    if not year:
        flash('Year not found', 'danger')
        return redirect(url_for('admin.years'))
    
    form = VehicleYearForm(obj=year)
    if form.validate_on_submit():
        try:
            updated_year = year_service.update(id, year=form.year.data or '')
            year_val = updated_year.year if updated_year else ''
            flash(f'Year "{year_val}" updated!', 'success')
            return redirect(url_for('admin.years'))
        except Exception as e:
            flash(str(e), 'danger')
    
    return render_template('admin/year_form.html', form=form, title='Edit Year', year=year)


@admin_bp.route('/years/<int:id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def year_delete(id):
    """Delete vehicle year"""
    year_service = VehicleYearService()
    success = year_service.delete(id)
    
    if success:
        flash('Year deleted successfully', 'success')
    else:
        flash('Year not found', 'danger')
    
    return redirect(url_for('admin.years'))


# ============================================
# VEHICLE COLORS MANAGEMENT
# ============================================

@admin_bp.route('/colors')
@login_required
@role_required('admin')
def colors():
    """List vehicle colors"""
    color_service = VehicleColorService()
    colors = color_service.get_all_colors()
    return render_template('admin/colors.html', colors=colors)


@admin_bp.route('/colors/add', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def color_add():
    """Add vehicle color"""
    form = VehicleColorForm()
    if form.validate_on_submit():
        color_service = VehicleColorService()
        try:
            color = color_service.create_color(form.name.data or '', form.code.data or '')
            flash(f'Color "{color.name}" added!', 'success')
            return redirect(url_for('admin.colors'))
        except Exception as e:
            flash(str(e), 'danger')
    return render_template('admin/color_form.html', form=form, title='Add Color')


@admin_bp.route('/colors/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def color_edit(id):
    """Edit vehicle color"""
    color_service = VehicleColorService()
    color = color_service.get_by_id(id)
    
    if not color:
        flash('Color not found', 'danger')
        return redirect(url_for('admin.colors'))
    
    form = VehicleColorForm(obj=color)
    if form.validate_on_submit():
        try:
            updated_color = color_service.update_color(id, form.name.data or '', form.code.data or '')
            color_name = updated_color.name if updated_color else ''
            flash(f'Color "{color_name}" updated!', 'success')
            return redirect(url_for('admin.colors'))
        except Exception as e:
            flash(str(e), 'danger')
    
    return render_template('admin/color_form.html', form=form, title='Edit Color', color=color)


@admin_bp.route('/colors/<int:id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def color_delete(id):
    """Delete vehicle color"""
    color_service = VehicleColorService()
    success = color_service.delete(id)
    
    if success:
        flash('Color deleted successfully', 'success')
    else:
        flash('Color not found', 'danger')
    
    return redirect(url_for('admin.colors'))


# ============================================
# DEVICE TYPES MANAGEMENT
# ============================================

@admin_bp.route('/devices')
@login_required
@role_required('admin')
def devices():
    """List device types"""
    device_service = DeviceTypeService()
    devices = device_service.get_all_device_types()
    return render_template('admin/devices.html', devices=devices)


@admin_bp.route('/devices/add', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def device_add():
    """Add device type"""
    form = DeviceTypeForm()
    if form.validate_on_submit():
        device_service = DeviceTypeService()
        try:
            device = device_service.create_device_type(form.name.data or '')
            flash(f'Device Type "{device.name}" added!', 'success')
            return redirect(url_for('admin.devices'))
        except Exception as e:
            flash(str(e), 'danger')
    return render_template('admin/device_form.html', form=form, title='Add Device Type')


@admin_bp.route('/devices/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def device_edit(id):
    """Edit device type"""
    device_service = DeviceTypeService()
    device = device_service.get_by_id(id)
    
    if not device:
        flash('Device type not found', 'danger')
        return redirect(url_for('admin.devices'))
    
    form = DeviceTypeForm(obj=device)
    if form.validate_on_submit():
        try:
            updated_device = device_service.update_device_type(id, form.name.data or '')
            device_name = updated_device.name if updated_device else ''
            flash(f'Device Type "{device_name}" updated!', 'success')
            return redirect(url_for('admin.devices'))
        except Exception as e:
            flash(str(e), 'danger')
    
    return render_template('admin/device_form.html', form=form, title='Edit Device Type', device=device)


@admin_bp.route('/devices/<int:id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def device_delete(id):
    """Delete device type"""
    device_service = DeviceTypeService()
    success = device_service.delete(id)
    
    if success:
        flash('Device type deleted successfully', 'success')
    else:
        flash('Device type not found', 'danger')
    
    return redirect(url_for('admin.devices'))


# ============================================
# TECHNICIAN MANAGEMENT
# ============================================

@admin_bp.route('/technicians')
@login_required
@role_required('admin')
def technicians():
    """List technicians"""
    tech_service = TechnicianService()
    technicians = tech_service.get_all_technicians(active_only=False)
    return render_template('admin/technicians.html', technicians=technicians)


@admin_bp.route('/technicians/add', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def technician_add():
    """Add technician with bike and GPS sync option"""
    form = TechnicianForm()
    
    if request.method == 'POST' and form.sync_gps.data and form.imei_for_sync.data:
        gps_service = GPSService()
        location = gps_service.get_location_by_imei(form.imei_for_sync.data)
        
        has_location = False
        if location:
            lat = location.get('lat')
            lng = location.get('lng')
            if lat and lng and str(lat).strip() and str(lat) != '0' and str(lng) != '0':
                has_location = True
                form.address.data = location.get('address', '')
                form.home_lat.data = str(lat).strip()
                form.home_lng.data = str(lng).strip()
                flash(f'✅ GPS location found! Address: {location.get("address", "Location found")}', 'success')
            else:
                logger.warning(f"GPS location found but lat/lng missing or invalid: lat={lat}, lng={lng}")
        
        if not has_location:
            flash('⚠️ No GPS location found for this IMEI. Please enter address manually.', 'warning')
    
    if form.validate_on_submit():
        tech_service = TechnicianService()
        data = {
            'name': (form.name.data or '').upper(),
            'contact': form.contact.data,
            'address': form.address.data,
            'home_lat': form.home_lat.data,
            'home_lng': form.home_lng.data,
            'is_active': form.is_active.data == 'True'
        }
        
        try:
            tech = tech_service.create_technician(data)
            
            # Save bike details if provided
            if form.bike_registration.data and form.imei.data:
                bike_service = TechnicianBikeService()
                bike_service.assign_bike(
                    technician_id=int(getattr(tech, 'id', 0)),
                    imei=form.imei.data.strip(),
                    registration=form.bike_registration.data.strip(),
                    model=form.bike_model.data.strip() if form.bike_model.data else None,
                    fuel_efficiency=form.fuel_efficiency.data or 35.0
                )
            
            flash(f'✅ Technician "{tech.name}" added successfully!', 'success')
            return redirect(url_for('admin.technicians'))
        except Exception as e:
            flash(f'❌ Error: {str(e)}', 'danger')
    
    return render_template('admin/technician_form.html', form=form, title='Add Technician')


@admin_bp.route('/technicians/<int:tech_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def technician_edit(tech_id):
    """Edit technician and bike assignment in one unified form"""
    tech_service = TechnicianService()
    tech = tech_service.get_technician(tech_id)
    
    if not tech:
        flash('Technician not found', 'danger')
        return redirect(url_for('admin.technicians'))
    
    form = TechnicianForm(obj=tech)
    
    if request.method == 'GET':
        form.is_active.data = 'True' if tech.is_active else 'False'
        if tech.bike_assignment:
            form.bike_registration.data = tech.bike_assignment.bike_registration
            form.imei.data = tech.bike_assignment.imei
            form.bike_model.data = tech.bike_assignment.bike_model
            form.fuel_efficiency.data = tech.bike_assignment.fuel_efficiency
            form.bike_active.data = 'True' if tech.bike_assignment.is_active else 'False'
            form.imei_for_sync.data = tech.bike_assignment.imei
    
    if request.method == 'POST' and form.sync_gps.data and form.imei_for_sync.data:
        gps_service = GPSService()
        location = gps_service.get_location_by_imei(form.imei_for_sync.data)
        
        has_location = False
        if location:
            lat = location.get('lat')
            lng = location.get('lng')
            if lat and lng and str(lat).strip() and str(lat) != '0' and str(lng) != '0':
                has_location = True
                form.address.data = location.get('address', '')
                form.home_lat.data = str(lat).strip()
                form.home_lng.data = str(lng).strip()
                flash(f'✅ GPS location found! Address: {location.get("address", "Location found")}', 'success')
            else:
                logger.warning(f"GPS location found but lat/lng missing or invalid: lat={lat}, lng={lng}")
        
        if not has_location:
            flash('⚠️ No GPS location found for this IMEI. Please enter address manually.', 'warning')
    
    if form.validate_on_submit():
        data = {
            'name': (form.name.data or '').upper(),
            'contact': form.contact.data,
            'address': form.address.data,
            'home_lat': form.home_lat.data,
            'home_lng': form.home_lng.data,
            'is_active': form.is_active.data == 'True'
        }
        
        try:
            updated_tech = tech_service.update_technician(tech_id, data)
            
            # Update/Create bike assignment
            if form.bike_registration.data and form.imei.data:
                bike_service = TechnicianBikeService()
                existing_bike = tech.bike_assignment
                if existing_bike:
                    bike_data = {
                        'technician_id': tech_id,
                        'imei': form.imei.data.strip(),
                        'bike_registration': form.bike_registration.data.strip(),
                        'bike_model': form.bike_model.data.strip() if form.bike_model.data else None,
                        'fuel_efficiency': form.fuel_efficiency.data or 35.0,
                        'is_active': form.bike_active.data == 'True'
                    }
                    bike_service.update_bike(int(getattr(existing_bike, 'id', 0)), bike_data)
                else:
                    bike_service.assign_bike(
                        technician_id=tech_id,
                        imei=form.imei.data.strip(),
                        registration=form.bike_registration.data.strip(),
                        model=form.bike_model.data.strip() if form.bike_model.data else None,
                        fuel_efficiency=form.fuel_efficiency.data or 35.0
                    )
                    
            tech_name = updated_tech.name if updated_tech else 'Technician'
            flash(f'✅ Technician "{tech_name}" updated successfully!', 'success')
            return redirect(url_for('admin.technicians'))
        except Exception as e:
            flash(f'❌ Error: {str(e)}', 'danger')
    
    return render_template('admin/technician_form.html', form=form, title='Edit Technician', technician=tech)


@admin_bp.route('/technicians/sync-gps/<int:tech_id>')
@login_required
@role_required('admin')
def technician_sync_gps(tech_id):
    """AJAX endpoint to sync GPS location for a technician"""
    tech_service = TechnicianService()
    tech = tech_service.get_technician(tech_id)
    
    if not tech:
        return jsonify({'error': 'Technician not found'}), 404
    
    from src.models.technician import TechnicianBike
    bike = TechnicianBike.query.filter_by(technician_id=tech.id, is_active=True).first()
    
    if not bike or not bike.imei:
        return jsonify({'error': 'No bike or IMEI assigned to this technician'}), 400
    
    gps_service = GPSService()
    location = gps_service.get_location_by_imei(bike.imei)
    
    if location and location.get('lat') and location.get('lng'):
        tech_service.update_technician(tech_id, {
            'home_lat': str(location.get('lat')).strip(),
            'home_lng': str(location.get('lng')).strip(),
            'address': location.get('address', tech.address or '')
        })
        
        return jsonify({
            'success': True,
            'lat': str(location.get('lat')).strip(),
            'lng': str(location.get('lng')).strip(),
            'address': location.get('address'),
            'imei': bike.imei
        })
    
    return jsonify({'error': 'No GPS location found for this IMEI'}), 404


@admin_bp.route('/technicians/test-imei')
@login_required
@role_required('admin')
def test_imei():
    """Test if an IMEI exists in the GPS system and return location data."""
    imei = request.args.get('imei')
    
    if not imei:
        return jsonify({'success': False, 'error': 'No IMEI provided'}), 400
    
    imei = imei.strip()
    
    try:
        gps_service = GPSService()
        result = gps_service.test_imei(imei)
        
        if result.get('exists') and result.get('location'):
            location = result['location']
            lat = location.get('lat')
            lng = location.get('lng')
            
            if lat and lng and str(lat).strip() and str(lat) != '0' and str(lng) != '0':
                return jsonify({
                    'success': True,
                    'imei': imei,
                    'location': {
                        'lat': str(lat).strip(),
                        'lng': str(lng).strip(),
                        'address': location.get('address', 'Location found'),
                        'speed': location.get('speed'),
                        'name': location.get('name')
                    }
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'IMEI found but no valid GPS coordinates available'
                })
        else:
            error_msg = result.get('error', 'IMEI not found in GPS system or not reporting')
            return jsonify({'success': False, 'error': error_msg})
            
    except Exception as e:
        logger.error(f"Error testing IMEI {imei}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/technicians/<int:tech_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def technician_delete(tech_id):
    """Delete technician"""
    tech_service = TechnicianService()
    success = tech_service.delete(tech_id)
    
    if success:
        flash('Technician deleted successfully', 'success')
    else:
        flash('Technician not found', 'danger')
    
    return redirect(url_for('admin.technicians'))


# ============================================
# TECHNICIAN BIKES MANAGEMENT
# ============================================

@admin_bp.route('/technician-bikes')
@admin_bp.route('/technician-bikes/add', methods=['GET', 'POST'])
@admin_bp.route('/technician-bikes/<int:id>/edit', methods=['GET', 'POST'])
@admin_bp.route('/technician-bikes/<int:id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def technician_bikes(id=None):
    """Redirect deprecated standalone bike routes to unified Technicians view"""
    return redirect(url_for('admin.technicians'))


# ============================================
# PETROL RATES MANAGEMENT
# ============================================

@admin_bp.route('/petrol-rates')
@login_required
@role_required('admin')
def petrol_rates():
    """List petrol rates"""
    rate_service = PetrolRateService()
    rates = rate_service.get_all(order_by='effective_date', desc=True)
    current_rate = PetrolRateService.get_current_rate()
    return render_template('admin/petrol_rates.html', rates=rates, current_rate=current_rate)


@admin_bp.route('/petrol-rates/add', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def petrol_rate_add():
    """Add petrol rate"""
    form = PetrolRateForm()
    
    if form.validate_on_submit():
        rate_service = PetrolRateService()
        try:
            rate = rate_service.set_rate(form.rate_per_liter.data or 0.0, form.effective_date.data)

            flash(f'✅ Petrol rate of PKR {rate.rate_per_liter}/liter set for {rate.effective_date}', 'success')
            return redirect(url_for('admin.petrol_rates'))
        except Exception as e:
            flash(f'❌ Error: {str(e)}', 'danger')
    
    return render_template('admin/petrol_rate_form.html', form=form, title='Add Petrol Rate')


@admin_bp.route('/petrol-rates/<int:id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def petrol_rate_delete(id):
    """Delete petrol rate"""
    try:
        rate_service = PetrolRateService()
        success = rate_service.delete(id)
        
        if success:
            flash('✅ Petrol rate deleted successfully', 'success')
        else:
            flash('❌ Rate not found', 'danger')
    except Exception as e:
        logger.error(f"Error deleting petrol rate: {e}")
        flash(f'❌ Error deleting rate: {str(e)}', 'danger')
    
    return redirect(url_for('admin.petrol_rates'))


# ============================================
# FUEL RATE UPDATE ROUTES
# ============================================

@admin_bp.route('/fuel/update-rate', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manual_fuel_rate_update():
    """Admin endpoint to manually trigger a fuel rate update from PSO."""
    
    if request.method == 'GET':
        flash('Please use the button on the Petrol Rates page to update fuel rates.', 'info')
        return redirect(url_for('admin.petrol_rates'))
    
    try:
        result = FuelRateService.update_petrol_rate()
        
        if result:
            flash(f'✅ Fuel rate updated to PKR {result.rate_per_liter}/liter from PSO.', 'success')
        else:
            flash('❌ Failed to update fuel rate from PSO. Please check logs.', 'danger')
            
    except Exception as e:
        logger.error(f"Manual fuel rate update error: {e}")
        flash(f'❌ Error updating fuel rate: {str(e)}', 'danger')
    
    return redirect(url_for('admin.petrol_rates'))


@admin_bp.route('/fuel/force-update', methods=['POST'])
@login_required
@role_required('admin')
def force_fuel_update():
    """Force immediate fuel rate update (runs in background)."""
    try:
        from flask import current_app
        import threading
        thread = threading.Thread(target=run_fuel_update, args=(getattr(current_app, '_get_current_object')(),))
        thread.daemon = True
        thread.start()
        flash('✅ Fuel rate update started in background!', 'success')
    except Exception as e:
        logger.error(f"Force fuel update error: {e}")
        flash(f'❌ Error starting update: {str(e)}', 'danger')
    
    return redirect(url_for('admin.petrol_rates'))


@admin_bp.route('/fuel/rate-history')
@login_required
@role_required('admin')
def fuel_rate_history():
    """View fuel rate history"""
    days = request.args.get('days', 30, type=int)
    history = FuelRateService.get_rate_history(days)
    current_rate = FuelRateService.get_current_rate()
    
    return render_template('admin/fuel_rate_history.html', 
                         history=history, 
                         current_rate=current_rate,
                         days=days)


# ============================================
# FUEL INVOICES MANAGEMENT
# ============================================

@admin_bp.route('/fuel-invoices')
@login_required
@role_required('admin', 'executive')
def fuel_invoices():
    """Fuel invoices, with the selected period's totals.

    The totals answer the questions asked of this page at month end: how many
    field activities were billed, how far the technicians actually travelled
    (point A to point B, resolved by the system) against how far was invoiced,
    how much fuel that works out to, and what was claimed for it. Those are
    period figures, so they follow the From/To range.

    The invoice list below them deliberately does not. Every invoice that has
    been generated stays listed, pending and paid alike, because an invoice
    does not stop existing when the reporting window moves off it - and an
    unpaid one that has scrolled out of view is exactly the one somebody
    needed to find. The technician and status controls narrow that list; the
    date range does not touch it.
    """
    from src.models.technician import FuelInvoiceExpense, FuelReimbursementInvoice, TechnicianTrip
    from src.utils.date_ranges import apply_range, parse_range

    date_range = parse_range(request.args)

    technicians = TechnicianService().get_all_technicians()

    technician_filter = request.args.get('technician_id', type=int)
    status_filter = (request.args.get('status') or '').strip().upper()

    def by_technician(query):
        if technician_filter:
            return query.filter(FuelReimbursementInvoice.technician_id == technician_filter)
        return query

    # An invoice belongs to the period its billing window starts in - a
    # single invoice is one billing period, so splitting it across two
    # reporting windows would double-count the same journeys.
    period_query = by_technician(FuelReimbursementInvoice.query)
    if date_range.get('start'):
        period_query = period_query.filter(FuelReimbursementInvoice.start_date >= date_range['start'])
    if date_range.get('end'):
        period_query = period_query.filter(FuelReimbursementInvoice.start_date <= date_range['end'])
    period_invoices = period_query.all()

    # Every invoice on record, newest first. Status is a filter on this list
    # rather than a scope on it: PENDING and PAID are both shown by default,
    # since the section's job is to be the full record of what was generated.
    #
    # Split in Python from one query so the counts beside the filter options
    # and the rows those options select are decided by the same rule -
    # "pending" means "not paid", so an invoice in any other state is on the
    # unpaid side rather than in neither.
    listed_all = (by_technician(FuelReimbursementInvoice.query)
                  .order_by(FuelReimbursementInvoice.created_at.desc()).all())

    def is_paid(invoice) -> bool:
        return invoice.status == 'PAID'

    if status_filter == 'PAID':
        invoices = [inv for inv in listed_all if is_paid(inv)]
    elif status_filter == 'PENDING':
        invoices = [inv for inv in listed_all if not is_paid(inv)]
    else:
        invoices = listed_all

    # Trips are the activities themselves - the point-A-to-point-B legs the
    # system routed and costed. Scoped by the trip's own date so "kilometers
    # calculated" describes travel in the period, not travel on an invoice.
    trip_query = apply_range(
        TechnicianTrip.query.filter(TechnicianTrip.status == 'COMPLETED'),
        TechnicianTrip.start_time, date_range)
    if technician_filter:
        trip_query = trip_query.filter(TechnicianTrip.technician_id == technician_filter)
    trips = trip_query.all()

    expense_total = sum(inv.additional_expenses_total() for inv in period_invoices)

    totals = {
        'activities': len(trips),
        'km_billed': round(sum(inv.total_distance or 0.0 for inv in period_invoices), 2),
        'km_calculated': round(sum(t.distance_km or 0.0 for t in trips), 2),
        'fuel_calculated': round(sum(t.fuel_used_liters or 0.0 for t in trips), 2),
        'fuel_claimed': round(sum(inv.total_amount or 0.0 for inv in period_invoices), 2),
        'additional_expenses': round(expense_total, 2),
        'net_payable': round(sum(inv.net_payable for inv in period_invoices), 2),
        'invoices': len(period_invoices),
    }

    # Counts for the status control, over the same list it filters, so the
    # numbers beside the options describe what picking them will show.
    invoice_counts = {
        'all': len(listed_all),
        'pending': sum(1 for inv in listed_all if not is_paid(inv)),
        'paid': sum(1 for inv in listed_all if is_paid(inv)),
    }

    return render_template('admin/fuel_invoices.html',
                         invoices=invoices,
                         technicians=technicians,
                         totals=totals,
                         invoice_counts=invoice_counts,
                         date_range=date_range,
                         technician_filter=technician_filter,
                         status_filter=status_filter,
                         # Which invoice's expense panel to re-open, and
                         # whether to ask if the user has finished adding to
                         # it - see `fuel_invoice_expense_add`.
                         open_expenses=request.args.get('expenses', type=int),
                         just_added=request.args.get('added', type=int),
                         expense_categories=FuelInvoiceExpense.CATEGORIES)


def _back_to_fuel_invoices(invoice_id: Optional[int] = None,
                           just_added: bool = False):
    """Back to the fuel invoices page, exactly as the user had it.

    Adding expenses is a run of entries, not a single action: a top-off, a
    relay, a sundry, all against the same invoice. Returning to a bare
    `/fuel-invoices` threw away the technician and date range the user had
    searched on and closed the panel they were working in, so every line
    meant setting the search up again.

    The search comes back off the form the expense was submitted from, so it
    survives without being re-typed. `expenses` re-opens the panel, and
    `added` tells the page to ask whether the user has finished.
    """
    params: Dict[str, Any] = {}
    for key in ('technician_id', 'from', 'to', 'status'):
        value = (request.form.get(key) or '').strip()
        if value:
            params[key] = value
    if invoice_id:
        params['expenses'] = invoice_id
        if just_added:
            params['added'] = invoice_id
    return redirect(url_for('admin.fuel_invoices', **params))


@admin_bp.route('/fuel-invoices/<int:invoice_id>/expenses/add', methods=['POST'])
@login_required
@role_required('admin')
def fuel_invoice_expense_add(invoice_id):
    """Add a non-fuel item (mobile top-off, relay, other) to an invoice."""
    from src.models.technician import FuelInvoiceExpense, FuelReimbursementInvoice

    invoice = FuelReimbursementInvoice.query.get(invoice_id)
    if not invoice:
        flash('Invoice not found', 'danger')
        return _back_to_fuel_invoices()

    if invoice.status == 'PAID':
        flash('This invoice is already paid - expenses can no longer be added to it.', 'warning')
        return _back_to_fuel_invoices()

    category = request.form.get('category') or FuelInvoiceExpense.CATEGORY_OTHER
    description = (request.form.get('description') or '').strip()
    amount = request.form.get('amount', type=float)

    if not amount or amount <= 0:
        flash('Enter an amount greater than zero for the expense.', 'danger')
        # Still a run in progress: back to the same panel, not out of it.
        return _back_to_fuel_invoices(invoice_id)

    db.session.add(FuelInvoiceExpense(
        invoice_id=invoice.id,
        category=category,
        description=description or FuelInvoiceExpense.category_label(category),
        amount=round(amount, 2),
        added_by_name=current_user.name or current_user.username))
    db.session.commit()

    flash(f'Added {FuelInvoiceExpense.category_label(category)} of PKR {amount:,.2f} '
          f'to {invoice.invoice_number}.', 'success')
    return _back_to_fuel_invoices(invoice_id, just_added=True)


@admin_bp.route('/fuel-invoices/expenses/<int:expense_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def fuel_invoice_expense_delete(expense_id):
    """Remove an additional expense line from an invoice."""
    from src.models.technician import FuelInvoiceExpense

    expense = FuelInvoiceExpense.query.get(expense_id)
    if not expense:
        flash('Expense not found', 'danger')
        return _back_to_fuel_invoices()

    if expense.invoice and expense.invoice.status == 'PAID':
        flash('This invoice is already paid - its expenses can no longer be changed.', 'warning')
        return _back_to_fuel_invoices(expense.invoice_id)

    invoice_id = expense.invoice_id
    db.session.delete(expense)
    db.session.commit()
    flash('Expense removed', 'success')
    return _back_to_fuel_invoices(invoice_id)


@admin_bp.route('/fuel-invoices/generate', methods=['POST'])
@login_required
@role_required('admin')
def fuel_invoice_generate():
    """Generate fuel reimbursement invoice"""
    technician_id = request.form.get('technician_id', type=int)
    start_date_str = request.form.get('start_date')
    end_date_str = request.form.get('end_date')
    
    if not technician_id or not start_date_str or not end_date_str:
        flash('Technician, start date, and end date are required', 'danger')
        return redirect(url_for('admin.fuel_invoices'))
        
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        invoice_service = FuelReimbursementInvoiceService()
        invoice = invoice_service.create_invoice(
            technician_id=technician_id,
            start_date=start_date,
            end_date=end_date,
            user_id=current_user.id
        )
        # Link straight to the document. "Generated successfully" on its own
        # left people looking for a PDF that was only ever behind a small icon
        # further down the page.
        from markupsafe import Markup, escape
        pdf_url = url_for('admin.fuel_invoice_pdf', invoice_id=invoice.id)
        flash(Markup(
            f'Invoice {escape(invoice.invoice_number)} generated. '
            f'<a href="{pdf_url}" target="_blank" rel="noopener"><strong>View PDF</strong></a> '
            f'&middot; <a href="{pdf_url}?download=1">Download</a>'
        ), 'success')
    except Exception as e:
        logger.error(f"Error generating fuel invoice: {e}")
        flash(f'Error generating invoice: {str(e)}', 'danger')
        
    return redirect(url_for('admin.fuel_invoices'))


@admin_bp.route('/fuel-invoices/<int:invoice_id>/pdf')
@login_required
@role_required('admin', 'executive')
def fuel_invoice_pdf(invoice_id):
    """Show the invoice PDF, or download it with `?download=1`.

    Inline by default: "show me the invoice" is the common request, and an
    attachment answers it with a file in the downloads folder that the person
    then has to go and find. The browser's own viewer still offers a save
    button for when they do want the file.
    """
    import os
    from flask import send_file
    from src.services.pdf_service import PDFService

    try:
        pdf_service = PDFService()
        filepath = pdf_service.generate_invoice_pdf(invoice_id)

        if filepath and os.path.exists(filepath):
            wants_file = request.args.get('download') == '1'
            return send_file(filepath, mimetype='application/pdf',
                             as_attachment=wants_file,
                             download_name=f"invoice_{invoice_id}.pdf")

        flash('❌ PDF generation failed for this invoice. Please verify invoice data.', 'danger')
        return redirect(url_for('admin.fuel_invoices'))
    except Exception as e:
        logger.error(f"Error in fuel_invoice_pdf route: {e}")
        flash(f'❌ Error generating PDF: {str(e)}', 'danger')
        return redirect(url_for('admin.fuel_invoices'))



@admin_bp.route('/fuel-invoices/<int:invoice_id>/mark-paid', methods=['POST'])
@login_required
@role_required('admin')
def fuel_invoice_mark_paid(invoice_id):
    """Mark fuel invoice as paid"""
    invoice_service = FuelReimbursementInvoiceService()
    invoice = invoice_service.mark_paid(invoice_id)
    
    if invoice:
        flash(f'Invoice {invoice.invoice_number} marked as PAID', 'success')
    else:
        flash('Invoice not found', 'danger')
    
    return redirect(url_for('admin.fuel_invoices'))


@admin_bp.route('/fuel-invoices/<int:invoice_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def fuel_invoice_delete(invoice_id):
    """Delete fuel invoice"""
    invoice_service = FuelReimbursementInvoiceService()
    success = invoice_service.delete(invoice_id)
    
    if success:
        flash('Invoice deleted', 'success')
    else:
        flash('Invoice not found', 'danger')
    
    return redirect(url_for('admin.fuel_invoices'))


# ============================================
# EXECUTIVE OPERATIONS DASHBOARD & MIS REPORTS
# ============================================

def _period_dashboard_context(window):
    """Every period-scoped figure both dashboards show.

    Administration and Executive are meant to be the same board. That only
    holds if the period sections come from here rather than from one route
    that has them and one that does not - which is what let the Administrator
    end up without Operations KPIs, REDO Turnaround or the breach count.

    `window` is the timeframe chip's range (`dashboard_period`), the same
    object the card deck above these sections was counted over.
    """
    from src.models.purchase_order import PurchaseOrder
    from src.models.redo import RedoActivity
    from src.models.annual_recovery import AnnualRecoveryHistory, AnnualRecoveryVehicle
    from src.models.removal import VehicleFlag
    from src.models.technician import Technician
    from src.models.complaint import Complaint
    from src.models.payment import PaymentRecovery
    from src.models.gps import NonReportingVehicle
    from src.services.technician_activity_service import (
        UNASSIGNED_LABEL, TechnicianActivityService)

    now = datetime.now()
    start_date, end_date = window['start_dt'], window['end_dt']

    def within(query, column):
        return query.filter(column >= start_date, column <= end_date)

    # 1. Fresh Installations
    fresh_installations = within(PurchaseOrder.query, PurchaseOrder.created_at).all()
    completed_installations = [p for p in fresh_installations if p.status == 'COMPLETED']

    # 2. REDO Activities with SLA Analysis
    redo_activities = within(RedoActivity.query, RedoActivity.created_at).all()
    completed_redos = [r for r in redo_activities if r.status == 'COMPLETED']
    
    # REDO SLA Metrics - 24h TAT Wall Board
    redo_pending = [r for r in redo_activities if r.status == 'PENDING']
    redo_in_progress = [r for r in redo_activities if r.status == 'IN_PROGRESS']
    
    # Calculate SLA breaches (age > 24 hours)
    sla_breached = []
    sla_warning = []  # 24-36 hours
    sla_critical = []  # 36-48 hours
    
    for redo in redo_activities:
        # Cancelled work is off the board too - the wallboard these cards link
        # into shows neither, so counting one and listing the other would put
        # a number on a card that its own link cannot reproduce.
        if redo.status in ('COMPLETED', 'CANCELLED'):
            continue
        age_hours = (now - redo.created_at).total_seconds() / 3600.0
        if age_hours > 48:
            sla_breached.append(redo)
        elif age_hours > 36:
            sla_critical.append(redo)
        elif age_hours > 24:
            sla_warning.append(redo)
    
    # 3. AMC Monitoring & Recovery. The money recovered is dated by the
    # payment that recovered it, not by when the vehicle was added to a
    # sheet - a recovery taken this week against a vehicle loaded last year
    # belongs to this week, and dating both sides the same way put it in
    # neither.
    amc_vehicles = within(AnnualRecoveryVehicle.query,
                          AnnualRecoveryVehicle.created_at).all()
    total_amc_amount = sum(v.amc_charges or 0 for v in amc_vehicles)
    recovered_amc_amount = sum(
        r.amount or 0 for r in
        within(AnnualRecoveryHistory.query, AnnualRecoveryHistory.created_at).all())

    # 4. Removals
    removals = within(VehicleFlag.query, VehicleFlag.created_at).all()
    completed_removals = [rm for rm in removals if rm.status == 'COMPLETED']

    # 4b. Installation Recovery - income actually received within the period
    period_payments = PaymentRecovery.query.filter(
        PaymentRecovery.payment_received_date.isnot(None),
        PaymentRecovery.payment_received_date >= window['start'],
        PaymentRecovery.payment_received_date <= window['end']
    ).all()
    installation_recovery_income = sum(p.amount_received or 0 for p in period_payments)

    # 4c. Non-Reporting - vehicles recorded as non-reporting inside the
    # period, counted as events like everything else on the board rather
    # than as a live device state that ignores the timeframe above it.
    non_reporting_count = within(NonReportingVehicle.query,
                                 NonReportingVehicle.created_at).count()

    # 4d. Stock & Accessories - shortages across the months the period
    # covers. The stock ledger is filed by calendar month, so the window is
    # translated into months (see `_months_in_window`).
    from src.models.inventory import InventoryStockItem
    period_stock_items = InventoryStockItem.query.filter(
        InventoryStockItem.period.in_(_months_in_window(window))).all()
    stock_shortage_count = sum(1 for i in period_stock_items if i.get_remaining() < 0)

    # 5. Complaints Statistics
    complaints = within(Complaint.query, Complaint.created_at).all()
    total_complaints = len(complaints)
    open_complaints = sum(1 for c in complaints if c.status == 'OPEN')
    resolved_complaints = sum(1 for c in complaints if c.status == 'RESOLVED')

    # 6. Technician Performance KPIs, activity by activity.
    #
    # Installations, REDOs, Removals and Transfers each live in their own
    # table and each records its technician differently - a PO holds a name,
    # a REDO holds a name and a user id, a removal holds only a user id.
    # TechnicianActivityService is the one place that reconciles them, and
    # already backs the MIS page, the performance wallboard and the monthly
    # management email; the board reads from it too so all four report the
    # same numbers for the same person over the same window.
    activity_rows = TechnicianActivityService().wallboard_rows(
        {'start_dt': start_date, 'end_dt': end_date})

    # The bike is the one thing the activity rows do not carry - they are
    # keyed on the technician's name, which is all four tables have in common.
    bikes = {(t.name or '').strip().upper():
             (t.bike.bike_registration if t.bike else 'No Bike')
             for t in Technician.query.filter_by(is_active=True).all()}

    tech_kpis = [{
        'name': row['technician'],
        'bike': bikes.get(row['technician'].strip().upper(), 'No Bike'),
        'installations': row['installations_completed'],
        'redos': row['redos_completed'],
        'removals': row['removals_completed'],
        'transfers': row['transfers_completed'],
        # Every column counts completed work, so the four add up to this.
        'total_jobs': row['completed'],
    } for row in activity_rows if row['technician'] != UNASSIGNED_LABEL]
    tech_kpis.sort(key=lambda x: x['total_jobs'], reverse=True)

    # 7. Top cities by purchase orders raised in the period. Three, because
    # the point of the card is where the work is concentrated, not a
    # directory of every city on the books.
    city_counts = {}
    for po in fresh_installations:
        name = (po.city or 'Not Recorded').strip().title()
        city_counts[name] = city_counts.get(name, 0) + 1
    top_cities = [{'city': city, 'count': count} for city, count in
                  sorted(city_counts.items(), key=lambda kv: kv[1], reverse=True)[:3]]

    return {
        'period': window['period'],
        'period_label': window['label'],
        'period_range_label': window['range_label'],
        'period_start_str': window['start_str'],
        # Both ends, because a card that links to a report has to hand it a
        # range - parse_range reads `from` and `to`, and a start with no end
        # would open the report on a different period from the card.
        'period_end_str': window['end_str'],
        'total_fresh': len(fresh_installations),
        'completed_fresh': len(completed_installations),
        'total_redos': len(redo_activities),
        'completed_redos': len(completed_redos),
        'total_amc_amount': total_amc_amount,
        'recovered_amc_amount': recovered_amc_amount,
        'total_removals': len(removals),
        'completed_removals': len(completed_removals),
        'installation_recovery_income': installation_recovery_income,
        'non_reporting_count': non_reporting_count,
        'stock_shortage_count': stock_shortage_count,
        'tech_kpis': tech_kpis,
        'top_cities': top_cities,
        # REDO SLA metrics
        'redo_pending': len(redo_pending),
        'redo_in_progress': len(redo_in_progress),
        'sla_breached': len(sla_breached),
        'sla_warning': len(sla_warning),
        'sla_critical': len(sla_critical),
        # Complaint metrics
        'total_complaints': total_complaints,
        'open_complaints': open_complaints,
        'resolved_complaints': resolved_complaints,
    }


@admin_bp.route('/executive-dashboard')
@login_required
@role_required('admin', 'executive')
def executive_dashboard():
    """Executive Operations Dashboard for Head of Operations.

    Identical to the Administration dashboard - same card deck, same period
    sections, same refresh - because the brief is that the two show the same
    data from the same source. What differs is only the heading.
    """
    from src.utils.date_ranges import dashboard_period

    window = dashboard_period(request.args.get('period'))
    admin_stats, admin_recent_pos, _admin_error = _compute_admin_dashboard_stats(window)

    return render_template('admin/executive_dashboard.html',
                           admin_stats=admin_stats,
                           sync=dashboard_sync_values(admin_stats),
                           admin_recent_pos=admin_recent_pos,
                           **_period_dashboard_context(window))


# --- MIS report catalogue -------------------------------------------------
# The reports landing page is an index, not a dashboard: it lists what can be
# run and lets you pick the period, and nothing more. Every entry lives here
# rather than in the template, so the catalogue, the slug the detail view
# accepts, and the report's own heading can never drift apart.
#
# `view` is the endpoint that renders the report, `export` the one that
# downloads it - a report may have either or both. `builder` names the
# function on this module that produces its rows.
MIS_REPORTS = [
    {
        'slug': 'monthly-mis',
        'name': 'Monthly MIS',
        'icon': 'file-spreadsheet',
        'summary': 'Activities, Installation, Removal and Transfer records in one '
                   'multi-sheet workbook. Emailed to senior management on the 1st '
                   'of every month, covering the month just ended.',
        'view': 'admin.mis_report_view',
        'export': 'admin.mis_reports_export',
    },
    {
        'slug': 'sales-performance',
        'name': 'Sales Performance Report',
        'icon': 'chart-pie',
        'summary': 'Per sales person: purchase orders raised, and how many of them '
                   'completed, are in progress, or are still pending.',
        'view': 'admin.mis_report_view',
        'export': 'admin.mis_report_export',
    },
    {
        'slug': 'field-jobs',
        'name': 'Field Jobs Completed',
        'icon': 'wrench',
        'summary': 'Jobs each technician finished in the period - installations, '
                   'REDOs, removals and removal transfers.',
        'view': 'admin.mis_report_view',
        'export': 'admin.mis_report_export',
    },
    {
        'slug': 'retained-cases',
        'name': 'Retained Cases',
        'icon': 'archive',
        'summary': 'Devices removed and retained: where each one is stored, whether '
                   'it came back, and who is handling the case.',
        'view': 'admin.mis_report_view',
        'export': 'admin.mis_report_export',
    },
    {
        'slug': 'installations-by-city',
        'name': 'Vehicles Installed by City',
        'icon': 'map-pin',
        'summary': 'Which cities the fleet is growing in - vehicles installed per '
                   'city, ranked, against the orders raised there.',
        'view': 'admin.mis_report_view',
        'export': 'admin.mis_report_export',
    },
    {
        'slug': 'technician-load',
        'name': 'Technician Assignment Load',
        'icon': 'user-cog',
        'summary': 'Every job handed to a technician in the period, whatever its '
                   'status now - the workload picture behind the completions.',
        'view': 'admin.mis_report_view',
        'export': 'admin.technician_activity_export',
    },
    {
        'slug': 'technician-performance',
        'name': 'Technician Performance Wallboard',
        'icon': 'user-check',
        'summary': 'The full grid: four activity types by four statuses per '
                   'technician, with completion rate. Emailed monthly to senior '
                   'management.',
        'view': 'admin.mis_report_view',
        'export': 'admin.mis_report_export',
    },
    {
        'slug': 'device-changes',
        'name': 'Device Change Report',
        'icon': 'cpu',
        'summary': 'Date-wise record of every device swapped out in the field. '
                   'Emailed monthly to senior management.',
        'view': 'admin.mis_report_view',
        'export': 'admin.mis_report_export',
    },
    {
        'slug': 'login-activity',
        # "and" rather than "&": this name is data, not markup. It is printed
        # into HTML (where an ampersand becomes &amp; and no longer matches
        # the name), into an Excel sheet title, and into a download filename
        # (where " & " became "___"). The plain word survives all three.
        'name': 'Login and Logout Report',
        'icon': 'log-in',
        'summary': 'Every user\'s sign-ins and sign-outs - who, when, and from '
                   'which address - with a per-user count for the period.',
        'view': 'admin.mis_report_view',
        'export': 'admin.mis_report_export',
    },
    {
        'slug': 'redo-followups',
        'name': 'REDO Follow-Up Report',
        'icon': 'phone-call',
        'summary': 'Follow-ups logged against REDO activities, with the user who '
                   'scheduled each one.',
        'view': 'admin.mis_report_view',
        'export': 'admin.mis_report_export',
    },
    {
        'slug': 'amc-invoices',
        'name': 'AMC Invoices and Discounts',
        'icon': 'receipt',
        'summary': 'Every Annual Recovery invoice raised in the period: what '
                   'the customer owed, what they were billed, and the discount '
                   'allowed - with the officer who granted it and their reason.',
        'view': 'admin.mis_report_view',
        'export': 'admin.mis_report_export',
    },
    {
        'slug': 'individual-recovery',
        'name': 'Individual Recovery Report',
        'icon': 'user-check',
        'summary': 'One recovery officer\'s AMC book: vehicles assigned, what is '
                   'outstanding, what they collected in the period, follow-ups '
                   'logged, and the invoices and discounts they raised.',
        'view': 'admin.mis_report_view',
        'export': 'admin.mis_report_export',
        # Reports may declare one extra picker beyond the period; see
        # MIS_REPORT_FILTERS.
        'filter': 'user',
    },
    {
        'slug': 'device-recovery-followups',
        'name': 'Device Recovery Follow-Up Report',
        'icon': 'clipboard-list',
        'summary': 'Power Issue, Device Damage and Device Missing charges with '
                   'every contact number on record for the vehicle, how many '
                   'times the customer has been chased, and what came of it.',
        'view': 'admin.mis_report_view',
        'export': 'admin.mis_report_export',
        'filter': 'reason',
    },
]

MIS_REPORTS_BY_SLUG = {report['slug']: report for report in MIS_REPORTS}


def _with_urls(report):
    """Resolve a catalogue entry's endpoints to URLs.

    The generic detail view is one endpoint serving several reports, so it
    needs its slug to build; the reports that live on their own pages take
    no arguments. Doing this here keeps that difference out of the template.
    """
    # The two generic endpoints serve several reports each, so they need the
    # slug to build; the reports that live on their own pages take no
    # arguments.
    SLUG_ENDPOINTS = {'admin.mis_report_view', 'admin.mis_report_export'}

    def build(endpoint):
        if not endpoint:
            return None
        if endpoint in SLUG_ENDPOINTS:
            return url_for(endpoint, slug=report['slug'])
        return url_for(endpoint)

    return dict(report, view_url=build(report['view']), export_url=build(report['export']))


def _report_sales_performance(date_range):
    """Purchase orders raised per sales person, split by where they got to."""
    from src.models.purchase_order import PurchaseOrder
    from src.utils.date_ranges import apply_range

    period_pos = apply_range(PurchaseOrder.query, PurchaseOrder.created_at, date_range).all()
    by_sales_person = {}
    for po in period_pos:
        by_sales_person.setdefault(po.sales_person_id, []).append(po)

    rows = []
    for s_user in UserService().get_sales_users():
        user_pos = by_sales_person.get(s_user.id, [])
        rows.append({
            'name': s_user.name or s_user.username,
            'total_pos': len(user_pos),
            'completed_pos': sum(1 for p in user_pos if p.status == 'COMPLETED'),
            'in_progress_pos': sum(1 for p in user_pos if p.status == 'IN_PROGRESS'),
            'pending_pos': sum(1 for p in user_pos if p.status == 'PENDING'),
        })
    rows.sort(key=lambda x: x['total_pos'], reverse=True)

    return {
        'rows': rows,
        'columns': [
            {'label': 'Sales Person', 'key': 'name', 'strong': True},
            {'label': 'POs Raised', 'key': 'total_pos', 'align': 'amount'},
            {'label': 'Completed', 'key': 'completed_pos', 'align': 'amount', 'badge': 'success'},
            {'label': 'In Progress', 'key': 'in_progress_pos', 'align': 'amount', 'badge': 'info'},
            {'label': 'Pending', 'key': 'pending_pos', 'align': 'amount', 'badge': 'warning'},
        ],
        'empty': 'No POs raised in this period',
    }


def _report_field_jobs(date_range):
    """What each technician finished. Same rows as the wallboard, so the two
    reports can never disagree about a completion."""
    from src.services.technician_activity_service import TechnicianActivityService

    rows = [{
        'name': row['technician'],
        'installations': row['installations_completed'],
        'redos': row['redos_completed'],
        'removals': row['removals_completed'],
        'transfers': row['transfers_completed'],
        'total_completed': row['completed'],
    } for row in TechnicianActivityService().wallboard_rows(date_range)]
    rows.sort(key=lambda x: x['total_completed'], reverse=True)

    return {
        'rows': rows,
        'columns': [
            {'label': 'Technician', 'key': 'name', 'strong': True},
            {'label': 'Installs', 'key': 'installations', 'align': 'amount'},
            {'label': 'REDOs', 'key': 'redos', 'align': 'amount'},
            {'label': 'Removals', 'key': 'removals', 'align': 'amount'},
            {'label': 'Transfers', 'key': 'transfers', 'align': 'amount'},
            {'label': 'Total Completed', 'key': 'total_completed', 'align': 'amount',
             'badge': 'primary'},
        ],
        'empty': 'No completed field jobs in this period',
    }


def _report_login_activity(date_range):
    """Who signed in and out, when, and from where.

    Two tables over the same events, because the question is asked two ways.
    The log answers "what happened, in order" - the one place a specific
    sign-in can be found. The summary answers "who was on the system in this
    period", which a 900-row log cannot be read for.

    Covers every user, not only those who signed in: somebody who never
    appeared at all is exactly what an attendance report is asked about, and
    an absent row reads as "no data" where a zero row reads as "did not sign
    in".
    """
    from src.models.activity import ActivityLog
    from src.models.user import User
    from src.services.auth_service import ACTION_LOGIN, ACTION_LOGOUT
    from src.utils.date_ranges import apply_range

    events = apply_range(
        ActivityLog.query.filter(ActivityLog.action.in_([ACTION_LOGIN, ACTION_LOGOUT])),
        ActivityLog.created_at, date_range
    ).order_by(ActivityLog.created_at.desc()).all()

    def describe(user) -> str:
        if not user:
            return 'Deleted user'
        return user.name or user.username

    log_rows = [{
        'user': describe(event.user),
        'username': event.user.username if event.user else '-',
        'role': event.user.get_role_display() if event.user else '-',
        'action': 'Login' if event.action == ACTION_LOGIN else 'Logout',
        'when': event.created_at.strftime('%d %b %Y, %H:%M:%S') if event.created_at else '-',
        'ip_address': event.ip_address or '-',
    } for event in events]

    # Per user. Keyed on the user id rather than the name, so two people who
    # share a display name are not summed into one row.
    tally: Dict[int, Dict[str, Any]] = {}
    for event in events:
        if not event.user:
            continue
        entry = tally.setdefault(event.user.id, {'logins': 0, 'logouts': 0,
                                                 'first': None, 'last': None})
        if event.action == ACTION_LOGIN:
            entry['logins'] += 1
        else:
            entry['logouts'] += 1
        when = event.created_at
        if when:
            if entry['first'] is None or when < entry['first']:
                entry['first'] = when
            if entry['last'] is None or when > entry['last']:
                entry['last'] = when

    summary_rows = []
    for user in User.query.order_by(User.username).all():
        entry = tally.get(user.id, {'logins': 0, 'logouts': 0, 'first': None, 'last': None})
        summary_rows.append({
            'user': describe(user),
            'username': user.username,
            'role': user.get_role_display(),
            'status': 'Active' if user.is_active else 'Inactive',
            'logins': entry['logins'],
            'logouts': entry['logouts'],
            'first_login': entry['first'].strftime('%d %b %Y, %H:%M') if entry['first'] else '-',
            'last_activity': entry['last'].strftime('%d %b %Y, %H:%M') if entry['last'] else '-',
        })
    # Busiest first, then alphabetically - and everyone who never signed in
    # collects at the bottom, which is where that list is useful.
    summary_rows.sort(key=lambda r: (-r['logins'], r['user'].upper()))

    return {
        'tables': [
            {
                'title': 'Per User',
                'icon': 'users',
                'columns': [
                    {'label': 'User', 'key': 'user', 'strong': True},
                    {'label': 'Username', 'key': 'username'},
                    {'label': 'Role', 'key': 'role'},
                    {'label': 'Account', 'key': 'status'},
                    {'label': 'Logins', 'key': 'logins', 'align': 'amount', 'badge': 'success'},
                    {'label': 'Logouts', 'key': 'logouts', 'align': 'amount', 'badge': 'info'},
                    {'label': 'First Login', 'key': 'first_login'},
                    {'label': 'Last Activity', 'key': 'last_activity'},
                ],
                'rows': summary_rows,
                'empty': 'No users on record',
            },
            {
                'title': 'Login and Logout Log',
                'icon': 'log-in',
                'columns': [
                    {'label': 'User', 'key': 'user', 'strong': True},
                    {'label': 'Username', 'key': 'username'},
                    {'label': 'Role', 'key': 'role'},
                    {'label': 'Event', 'key': 'action'},
                    {'label': 'Date & Time', 'key': 'when'},
                    {'label': 'IP Address', 'key': 'ip_address'},
                ],
                'rows': log_rows,
                'empty': 'No logins or logouts recorded in this period',
            },
        ],
        'note': 'Sessions are recorded from the moment this report was added, so '
                'earlier sign-ins are not on it. A login with no matching logout '
                'means the session was left open rather than signed out.',
    }


def _report_retained_cases(date_range):
    """Devices removed and held, one row per case."""
    from src.models.removal import RemovalRetainedActivity
    from src.utils.date_ranges import apply_range

    query = apply_range(RemovalRetainedActivity.query,
                        RemovalRetainedActivity.created_at, date_range)
    cases = query.order_by(RemovalRetainedActivity.created_at.desc()).all()

    rows = [{
        'registration_no': case.registration_no or '-',
        'customer_name': case.customer_name or '-',
        'removal_date': case.removal_date.strftime('%d %b %Y') if case.removal_date else '-',
        'retained_by': case.retained_by or '-',
        'storage_location': case.storage_location or '-',
        'device_returned': 'Returned' if case.device_returned else 'Held',
        'technician': (case.assigned_to_user.name if case.assigned_to_user else 'Unassigned'),
        'status': (case.status or '').replace('_', ' ').title(),
    } for case in cases]

    return {
        'rows': rows,
        'columns': [
            {'label': 'Registration', 'key': 'registration_no', 'strong': True},
            {'label': 'Customer', 'key': 'customer_name'},
            {'label': 'Removed On', 'key': 'removal_date'},
            {'label': 'Retained By', 'key': 'retained_by'},
            {'label': 'Storage Location', 'key': 'storage_location'},
            {'label': 'Device', 'key': 'device_returned'},
            {'label': 'Technician', 'key': 'technician'},
            {'label': 'Status', 'key': 'status', 'badge': 'secondary'},
        ],
        'empty': 'No retained cases in this period',
    }


def _report_installations_by_city(date_range):
    """Where the vehicles actually went in. Ranked on installed vehicles -
    completed orders - rather than on orders raised, because an order that
    has not been fitted has not put a vehicle on the road."""
    from src.models.purchase_order import PurchaseOrder
    from src.utils.date_ranges import apply_range

    period_pos = apply_range(PurchaseOrder.query, PurchaseOrder.created_at, date_range).all()

    cities = {}
    for po in period_pos:
        entry = cities.setdefault(po.city or 'Not Recorded', {'installed': 0, 'ordered': 0})
        entry['ordered'] += 1
        if po.status == 'COMPLETED':
            entry['installed'] += 1

    ranked = sorted(cities.items(), key=lambda kv: kv[1]['installed'], reverse=True)
    top = ranked[0][1]['installed'] if ranked else 0

    rows = [{
        'city': city,
        'installed': counts['installed'],
        'ordered': counts['ordered'],
        # Bar length is relative to the busiest city, so the leader fills the
        # track and everything else reads as a fraction of it.
        'share': round(counts['installed'] / top * 100, 1) if top else 0,
        'is_top': index == 0 and counts['installed'] > 0,
    } for index, (city, counts) in enumerate(ranked)]

    return {
        'rows': rows,
        'columns': [
            {'label': 'City', 'key': 'city', 'strong': True, 'flag': 'is_top',
             'flag_label': 'Top City'},
            {'label': 'Vehicles Installed', 'key': 'installed', 'align': 'amount',
             'badge': 'success'},
            {'label': 'Orders Raised', 'key': 'ordered', 'align': 'amount'},
            {'label': 'Share', 'key': 'share', 'bar': True},
        ],
        'empty': 'No installations recorded in this period',
    }


def _report_technician_load(date_range):
    """Everything assigned in the period, regardless of where it stands now."""
    from src.services.technician_activity_service import TechnicianActivityService

    return {
        'rows': TechnicianActivityService().wallboard_rows(date_range),
        'columns': [
            {'label': 'Technician', 'key': 'technician', 'strong': True},
            {'label': 'Installations', 'key': 'installations_total', 'align': 'amount',
             'badge': 'info'},
            {'label': 'REDOs', 'key': 'redos_total', 'align': 'amount', 'badge': 'warning'},
            {'label': 'Removals', 'key': 'removals_total', 'align': 'amount',
             'badge': 'secondary'},
            {'label': 'Transfers', 'key': 'transfers_total', 'align': 'amount',
             'badge': 'secondary'},
            {'label': 'Total Assigned', 'key': 'total_assigned', 'align': 'amount',
             'badge': 'primary'},
        ],
        'note': 'Every job handed to a technician in this period - installations, '
                'REDOs, removals and removal transfers - regardless of current status.',
        'empty': 'No assignments in this period',
    }


def _report_monthly_mis(date_range):
    """What the monthly workbook contains, on screen.

    The download has been a black box: you picked a period and got a file.
    This runs the same four record sets the workbook's sheets are built from,
    so the contents can be checked before anything is mailed to senior
    management.
    """
    from src.models.purchase_order import PurchaseOrder
    from src.models.redo import RedoActivity
    from src.models.removal import RemovalRetainedActivity, RemovalTransferActivity
    from src.utils.date_ranges import apply_range

    def scoped(model, limit=500):
        return (apply_range(model.query, model.created_at, date_range)
                .order_by(model.created_at.desc()).limit(limit).all())

    def status_of(record):
        return (getattr(record, 'status', '') or '').replace('_', ' ').title()

    def when(record):
        created = getattr(record, 'created_at', None)
        return created.strftime('%d %b %Y') if created else '-'

    vehicle_columns = [
        {'label': 'Registration', 'key': 'registration_no', 'strong': True},
        {'label': 'Customer', 'key': 'customer_name'},
        {'label': 'City', 'key': 'city'},
        {'label': 'Technician', 'key': 'technician'},
        {'label': 'Raised', 'key': 'raised'},
        {'label': 'Status', 'key': 'status', 'badge': 'secondary'},
    ]

    def vehicle_rows(records, technician_of):
        return [{
            'registration_no': getattr(r, 'registration_no', None) or '-',
            'customer_name': getattr(r, 'customer_name', None) or '-',
            'city': getattr(r, 'city', None) or '-',
            'technician': technician_of(r) or 'Unassigned',
            'raised': when(r),
            'status': status_of(r),
        } for r in records]

    def assignee(record):
        user = getattr(record, 'assigned_to_user', None)
        return user.name if user else None

    return {
        'tables': [
            {'title': 'Activities (REDO)', 'icon': 'rotate-cw',
             'columns': vehicle_columns,
             'rows': vehicle_rows(scoped(RedoActivity),
                                  lambda r: r.technician or assignee(r)),
             'empty': 'No REDO activities in this period'},
            {'title': 'Installation (Purchase Orders)', 'icon': 'hammer',
             'columns': vehicle_columns,
             'rows': vehicle_rows(scoped(PurchaseOrder),
                                  lambda r: r.technician_assigned),
             'empty': 'No purchase orders in this period'},
            {'title': 'Removal (Retained)', 'icon': 'archive',
             'columns': vehicle_columns,
             'rows': vehicle_rows(scoped(RemovalRetainedActivity), assignee),
             'empty': 'No removals in this period'},
            {'title': 'Transfer', 'icon': 'repeat',
             'columns': vehicle_columns,
             'rows': vehicle_rows(scoped(RemovalTransferActivity), assignee),
             'empty': 'No transfers in this period'},
        ],
        'note': 'The most recent 500 records per sheet. The download carries '
                'the full period with every column.',
    }


def _report_amc_invoices(date_range):
    """AMC invoices raised, and what was conceded on them.

    Two tables over the same ledger. The list is the audit trail - one row per
    invoice, with the officer and the reason attached to every discount. The
    per-officer summary answers the question the list cannot be read for: who
    is discounting, and how much.

    Figures come from the invoice rows, not from the vehicles they covered. An
    invoice records what was owed on the day it was raised; the vehicles have
    been paid down since, and recomputing from them would quietly restate
    history every time this report is run.
    """
    from src.models.amc_invoice import AmcInvoice
    from src.utils.date_ranges import apply_range

    invoices = apply_range(
        AmcInvoice.query, AmcInvoice.created_at, date_range
    ).order_by(AmcInvoice.created_at.desc()).all()

    def officer_of(invoice) -> str:
        user = invoice.generated_by_user
        if not user:
            return 'Deleted user'
        return user.name or user.username

    invoice_rows = [{
        'invoice_number': inv.invoice_number,
        'raised': inv.created_at.strftime('%d %b %Y, %H:%M') if inv.created_at else '-',
        'customer': inv.client_name or '-',
        'basis': inv.basis_label,
        'vehicles': inv.vehicle_count or 0,
        'outstanding': inv.outstanding_amount or 0.0,
        'invoiced': inv.invoiced_amount or 0.0,
        'discount': inv.discount_amount or 0.0,
        'reason': inv.discount_reason or ('-' if not inv.is_discounted else 'Not stated'),
        'officer': officer_of(inv),
    } for inv in invoices]

    # Per officer. Keyed on the user id so two people sharing a display name
    # are not summed into one row; invoices raised by a since-deleted user
    # collect under a single row rather than disappearing.
    tally: Dict[Any, Dict[str, Any]] = {}
    for inv in invoices:
        key = inv.generated_by or 0
        entry = tally.setdefault(key, {
            'officer': officer_of(inv), 'invoices': 0, 'discounted': 0,
            'outstanding': 0.0, 'invoiced': 0.0, 'discount': 0.0,
        })
        entry['invoices'] += 1
        entry['outstanding'] += inv.outstanding_amount or 0.0
        entry['invoiced'] += inv.invoiced_amount or 0.0
        entry['discount'] += inv.discount_amount or 0.0
        if inv.is_discounted:
            entry['discounted'] += 1

    officer_rows = sorted(tally.values(),
                          key=lambda r: (-r['discount'], -r['invoiced']))

    money = {'align': 'amount', 'money': True}

    return {
        'tables': [
            {
                'title': 'Per Officer',
                'icon': 'users',
                'columns': [
                    {'label': 'Officer', 'key': 'officer', 'strong': True},
                    {'label': 'Invoices', 'key': 'invoices', 'align': 'amount', 'badge': 'info'},
                    {'label': 'Discounted', 'key': 'discounted', 'align': 'amount', 'badge': 'warning'},
                    dict({'label': 'Outstanding', 'key': 'outstanding'}, **money),
                    dict({'label': 'Invoiced', 'key': 'invoiced'}, **money),
                    dict({'label': 'Discount Given', 'key': 'discount'}, **money),
                ],
                'rows': officer_rows,
                'empty': 'No AMC invoices were raised in this period',
            },
            {
                'title': 'Invoices Raised',
                'icon': 'receipt',
                'columns': [
                    {'label': 'Invoice No.', 'key': 'invoice_number', 'strong': True},
                    {'label': 'Raised', 'key': 'raised'},
                    {'label': 'Customer', 'key': 'customer'},
                    {'label': 'Basis', 'key': 'basis'},
                    {'label': 'Vehicles', 'key': 'vehicles', 'align': 'amount'},
                    dict({'label': 'Outstanding', 'key': 'outstanding'}, **money),
                    dict({'label': 'Invoiced', 'key': 'invoiced'}, **money),
                    dict({'label': 'Discount', 'key': 'discount'}, **money),
                    {'label': 'Discount Reason', 'key': 'reason'},
                    {'label': 'Raised By', 'key': 'officer'},
                ],
                'rows': invoice_rows,
                'empty': 'No AMC invoices were raised in this period',
            },
        ],
        'note': 'Discount is the outstanding balance less the amount actually '
                'invoiced, recorded when the invoice was raised. Invoices are '
                'recorded from the moment this ledger was added, so documents '
                'produced before that are not on it.',
    }


def _report_technician_performance(date_range):
    """The full technician grid: four activity types by four statuses.

    Reads TechnicianActivityService, the one reconciler across the four
    tables that each identify their technician differently - so this report,
    the dashboard's technician section and the monthly management email are
    all counting the same jobs.
    """
    from src.services.technician_activity_service import (
        ACTIVITY_TYPES, STATUSES, TechnicianActivityService)

    service = TechnicianActivityService()
    rows = service.wallboard_rows(date_range)
    totals = service.totals(rows)

    # Per activity type, so the grid can be read one job kind at a time
    # without counting across sixteen columns.
    activity_labels = {'installations': 'Installations', 'redos': 'REDOs',
                       'removals': 'Removals', 'transfers': 'Transfers'}
    summary_rows = [{
        'activity': activity_labels[activity],
        'total': totals.get(f'{activity}_total', 0),
        'completed': sum(r.get(f'{activity}_completed', 0) for r in rows),
        'pending': sum(r.get(f'{activity}_pending', 0) for r in rows),
        'in_progress': sum(r.get(f'{activity}_in_progress', 0) for r in rows),
        'cancelled': sum(r.get(f'{activity}_cancelled', 0) for r in rows),
    } for activity in ACTIVITY_TYPES]

    status_columns = [
        {'label': 'Completed', 'key': 'completed', 'align': 'amount', 'badge': 'success'},
        {'label': 'Pending', 'key': 'pending', 'align': 'amount', 'badge': 'warning'},
        {'label': 'In Progress', 'key': 'in_progress', 'align': 'amount', 'badge': 'info'},
        {'label': 'Cancelled', 'key': 'cancelled', 'align': 'amount'},
    ]

    return {
        'tables': [
            {
                'title': 'By Activity Type',
                'icon': 'layers',
                'columns': [{'label': 'Activity', 'key': 'activity', 'strong': True},
                            {'label': 'Assigned', 'key': 'total', 'align': 'amount'}]
                           + status_columns,
                'rows': summary_rows,
                'empty': 'No work was assigned in this period',
            },
            {
                'title': 'Per Technician',
                'icon': 'user-check',
                'columns': [
                    {'label': 'Technician', 'key': 'technician', 'strong': True},
                    {'label': 'Assigned', 'key': 'total_assigned', 'align': 'amount'},
                    {'label': 'Installations', 'key': 'installations_total', 'align': 'amount'},
                    {'label': 'REDOs', 'key': 'redos_total', 'align': 'amount'},
                    {'label': 'Removals', 'key': 'removals_total', 'align': 'amount'},
                    {'label': 'Transfers', 'key': 'transfers_total', 'align': 'amount'},
                ] + status_columns + [
                    {'label': 'Completion %', 'key': 'completion_rate', 'align': 'amount'},
                ],
                'rows': rows,
                'empty': 'No technician activity in this period',
            },
        ],
        'note': 'A technician with nothing in the period is still listed, at zero - '
                'an absent row reads as "no data" where a zero row reads as "no work". '
                'Completion % is completed jobs over jobs assigned.',
    }


def _report_device_changes(date_range):
    """Every device or SIM swapped out in the field, and why.

    Historical rows saved under retired labels ("Device Burnt", "Water
    Damage") are normalized into Device Damage for both the summary and the
    list - they are the same condition under two names, and counting them
    apart understates the real figure.
    """
    from src.models.installation_recovery import normalize_device_change_reason
    from src.models.redo import RedoActivity
    from src.utils.date_ranges import apply_range

    is_device_change = db.or_(
        db.and_(RedoActivity.new_device.isnot(None), RedoActivity.new_device != ''),
        db.and_(RedoActivity.new_sim.isnot(None), RedoActivity.new_sim != ''),
    )

    changes = apply_range(
        RedoActivity.query.filter(is_device_change),
        RedoActivity.created_at, date_range
    ).order_by(RedoActivity.created_at.desc()).all()

    reason_counts: Dict[str, int] = {}
    for change in changes:
        normalized = normalize_device_change_reason(change.device_change_reason)
        reason_counts[normalized or 'Not Specified'] = \
            reason_counts.get(normalized or 'Not Specified', 0) + 1

    summary_rows = [{'reason': reason, 'changes': count}
                    for reason, count in sorted(reason_counts.items(),
                                                key=lambda kv: -kv[1])]

    change_rows = [{
        'redo_number': change.redo_number or f'REDO-{change.id}',
        'when': change.created_at.strftime('%d %b %Y') if change.created_at else '-',
        'registration_no': change.registration_no or '-',
        'customer': change.customer_name or '-',
        'reason': normalize_device_change_reason(change.device_change_reason)
                  or 'Not Specified',
        'old_imei': change.old_imei_no or '-',
        'new_imei': change.new_device or '-',
        'old_sim': change.old_sim_no or '-',
        'new_sim': change.new_sim or '-',
        'technician': change.technician or (change.assigned_to_user.name
                                            if change.assigned_to_user else 'Unassigned'),
        'status': (change.status or '').replace('_', ' '),
    } for change in changes]

    return {
        'tables': [
            {
                'title': 'By Reason',
                'icon': 'pie-chart',
                'columns': [
                    {'label': 'Reason', 'key': 'reason', 'strong': True},
                    {'label': 'Devices Changed', 'key': 'changes', 'align': 'amount',
                     'badge': 'info'},
                ],
                'rows': summary_rows,
                'empty': 'No devices were changed in this period',
            },
            {
                'title': 'Device Changes',
                'icon': 'cpu',
                'columns': [
                    {'label': 'REDO ID', 'key': 'redo_number', 'strong': True},
                    {'label': 'Date', 'key': 'when'},
                    {'label': 'Registration', 'key': 'registration_no'},
                    {'label': 'Customer', 'key': 'customer'},
                    {'label': 'Reason', 'key': 'reason'},
                    {'label': 'Previous IMEI', 'key': 'old_imei'},
                    {'label': 'New IMEI', 'key': 'new_imei'},
                    {'label': 'Previous SIM', 'key': 'old_sim'},
                    {'label': 'New SIM', 'key': 'new_sim'},
                    {'label': 'Technician', 'key': 'technician'},
                    {'label': 'Status', 'key': 'status'},
                ],
                'rows': change_rows,
                'empty': 'No devices were changed in this period',
            },
        ],
        'note': 'A row appears here when a REDO recorded a New Device or a New SIM. '
                '"Device Burnt" and "Water Damage" from older records are counted as '
                'Device Damage.',
    }


def _report_redo_followups(date_range):
    """Follow-up calls made on non-reporting vehicles, and who scheduled the
    REDO each one is chasing.

    The scheduler matters because the report exists to chase work: the first
    question asked of a row is whose it was.
    """
    from src.models.gps import NonReportingConversation, NonReportingVehicle
    from src.utils.date_ranges import apply_range
    from src.web.redo import _redo_scheduler_names

    conversations = apply_range(
        NonReportingConversation.query.join(
            NonReportingVehicle,
            NonReportingConversation.vehicle_id == NonReportingVehicle.id),
        NonReportingConversation.conversation_date, date_range
    ).order_by(NonReportingConversation.conversation_date.desc()).all()

    scheduled = _redo_scheduler_names(conversations)

    outcome_counts: Dict[str, int] = {}
    for conversation in conversations:
        vehicle = conversation.vehicle
        outcome = (vehicle.contact_outcome if vehicle else None) or 'Not Yet Contacted'
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1

    summary_rows = [{'outcome': outcome, 'conversations': count}
                    for outcome, count in sorted(outcome_counts.items(),
                                                 key=lambda kv: -kv[1])]

    followup_rows = []
    for conversation in conversations:
        vehicle = conversation.vehicle
        reg_no = vehicle.registration_no if vehicle else '-'
        redo = scheduled.get(reg_no, {})
        followup_rows.append({
            'when': (conversation.conversation_date.strftime('%d %b %Y, %H:%M')
                     if conversation.conversation_date else '-'),
            'registration_no': reg_no,
            'customer': (vehicle.customer_name if vehicle else '') or '-',
            'type': conversation.conversation_type or '-',
            'direction': 'Inbound' if conversation.direction == 'IN' else 'Outbound',
            'contact_person': conversation.contact_person or '-',
            'outcome': (vehicle.contact_outcome if vehicle else None) or 'Not Yet Contacted',
            'summary': conversation.summary or '-',
            'action_taken': conversation.action_taken or '-',
            'recorded_by': conversation.recorded_by_name or '-',
            'redo_number': redo.get('redo_number') or '-',
            'scheduled_by': redo.get('scheduled_by') or 'No REDO raised',
        })

    return {
        'tables': [
            {
                'title': 'By Contact Outcome',
                'icon': 'pie-chart',
                'columns': [
                    {'label': 'Outcome', 'key': 'outcome', 'strong': True},
                    {'label': 'Conversations', 'key': 'conversations', 'align': 'amount',
                     'badge': 'info'},
                ],
                'rows': summary_rows,
                'empty': 'No follow-ups were logged in this period',
            },
            {
                'title': 'Follow-Up Conversations',
                'icon': 'phone-call',
                'columns': [
                    {'label': 'Date & Time', 'key': 'when', 'strong': True},
                    {'label': 'Registration', 'key': 'registration_no'},
                    {'label': 'Customer', 'key': 'customer'},
                    {'label': 'Type', 'key': 'type'},
                    {'label': 'Direction', 'key': 'direction'},
                    {'label': 'Spoke To', 'key': 'contact_person'},
                    {'label': 'Outcome', 'key': 'outcome'},
                    {'label': 'Summary', 'key': 'summary'},
                    {'label': 'Action Taken', 'key': 'action_taken'},
                    {'label': 'Logged By', 'key': 'recorded_by'},
                    {'label': 'REDO', 'key': 'redo_number'},
                    {'label': 'Scheduled By', 'key': 'scheduled_by'},
                ],
                'rows': followup_rows,
                'empty': 'No follow-ups were logged in this period',
            },
        ],
        'note': 'The outcome shown is the vehicle\'s current contact outcome, not a '
                'per-call result - a vehicle called several times carries the same '
                'outcome on each of its rows. "Scheduled By" is whoever raised the '
                'most recent REDO for that vehicle.',
    }


def _recovery_officer_choices():
    """Who the Individual Recovery Report can be run for.

    Everyone who holds AMC vehicles, plus anyone with the recovery officer
    role who currently holds none - a supervisor asking after an officer with
    an empty book needs to see the empty book, not an absent name.
    """
    from src.models.annual_recovery import AnnualRecoveryVehicle
    from src.models.user import User

    assigned_ids = {row[0] for row in db.session.query(
        AnnualRecoveryVehicle.assigned_to).distinct().all() if row[0]}

    officers = User.query.filter(
        db.or_(User.id.in_(assigned_ids) if assigned_ids else db.false(),
               User.role == 'recovery_officer')
    ).order_by(User.name, User.username).all()

    return [(str(user.id), user.name or user.username) for user in officers]


def _report_individual_recovery(date_range):
    """One recovery officer's AMC book, or everyone's side by side.

    Scoped the way the module itself scopes work - by the officer a vehicle
    is assigned to - so the figures here match what that officer sees on
    their own dashboard rather than a second, differently-drawn version of
    the same question.

    Money collected is dated by when the payment was recorded, not by the
    sheet the vehicle came from, so the period means the same thing here as
    it does on the dashboard's AMC income card.
    """
    from src.models.amc_invoice import AmcInvoice
    from src.models.annual_recovery import (AnnualRecoveryFollowup,
                                            AnnualRecoveryHistory,
                                            AnnualRecoveryVehicle)
    from src.models.user import User
    from src.utils.date_ranges import apply_range

    # The month-end pack builds every catalogue report from the scheduler,
    # where there is no request to read a selection from. No request means no
    # officer was chosen, which is the whole-team view - not an error.
    selected = ''
    if has_request_context():
        selected = (request.args.get('user') or '').strip()
    selected_id = int(selected) if selected.isdigit() else None

    vehicles = AnnualRecoveryVehicle.query
    if selected_id:
        vehicles = vehicles.filter(AnnualRecoveryVehicle.assigned_to == selected_id)
    vehicles = vehicles.all()

    # Vehicle id -> officer id, so every payment, follow-up and invoice can be
    # attributed without a query each.
    officer_of_vehicle = {v.id: v.assigned_to for v in vehicles}
    vehicle_ids = set(officer_of_vehicle)

    names = {user.id: (user.name or user.username)
             for user in User.query.all()}

    def blank(officer_id):
        return {
            'officer': names.get(officer_id, 'Unassigned'),
            'vehicles': 0, 'charges': 0.0, 'recovered_total': 0.0,
            'outstanding': 0.0, 'lost': 0,
            'collected': 0.0, 'payments': 0, 'followups': 0,
            'invoices': 0, 'invoiced': 0.0, 'discount': 0.0,
        }

    tally: Dict[Any, Dict[str, Any]] = {}
    for vehicle in vehicles:
        entry = tally.setdefault(vehicle.assigned_to, blank(vehicle.assigned_to))
        entry['vehicles'] += 1
        entry['charges'] += vehicle.amc_charges or 0.0
        entry['recovered_total'] += vehicle.recovered_amount or 0.0
        entry['outstanding'] += max(0.0, (vehicle.amc_charges or 0.0)
                                    - (vehicle.recovered_amount or 0.0))
        if (vehicle.status or '').upper() == 'LOST':
            entry['lost'] += 1

    def only_these_vehicles(query, column):
        """Restrict a query to the vehicles in scope.

        With no officer chosen every vehicle is in scope, so the filter is
        skipped rather than expressed as an IN clause holding every vehicle id
        in the database - a couple of thousand bind parameters to say
        "no restriction".
        """
        if selected_id is None:
            return query
        if not vehicle_ids:
            return query.filter(db.false())
        return query.filter(column.in_(vehicle_ids))

    payments = apply_range(
        only_these_vehicles(AnnualRecoveryHistory.query,
                            AnnualRecoveryHistory.vehicle_id),
        AnnualRecoveryHistory.created_at, date_range
    ).order_by(AnnualRecoveryHistory.created_at.desc()).all()

    for payment in payments:
        officer_id = officer_of_vehicle.get(payment.vehicle_id)
        entry = tally.setdefault(officer_id, blank(officer_id))
        entry['collected'] += payment.amount or 0.0
        entry['payments'] += 1

    followups = apply_range(
        only_these_vehicles(AnnualRecoveryFollowup.query,
                            AnnualRecoveryFollowup.vehicle_id),
        AnnualRecoveryFollowup.created_at, date_range).all()
    for followup in followups:
        officer_id = officer_of_vehicle.get(followup.vehicle_id)
        entry = tally.setdefault(officer_id, blank(officer_id))
        entry['followups'] += 1

    # Invoices are attributed to whoever raised them, which is a user id on
    # the invoice itself - not to the vehicle's officer, since a supervisor
    # may invoice against somebody else's sheet.
    invoices = apply_range(AmcInvoice.query, AmcInvoice.created_at, date_range)
    if selected_id:
        invoices = invoices.filter(AmcInvoice.generated_by == selected_id)
    for invoice in invoices.all():
        entry = tally.setdefault(invoice.generated_by, blank(invoice.generated_by))
        entry['invoices'] += 1
        entry['invoiced'] += invoice.invoiced_amount or 0.0
        entry['discount'] += invoice.discount_amount or 0.0

    officer_rows = sorted(tally.values(), key=lambda r: (-r['collected'], r['officer']))

    vehicle_of = {v.id: v for v in vehicles}
    payment_rows = [{
        'when': (payment.created_at.strftime('%d %b %Y, %H:%M')
                 if payment.created_at else '-'),
        'officer': names.get(officer_of_vehicle.get(payment.vehicle_id), 'Unassigned'),
        'registration_no': (vehicle_of[payment.vehicle_id].reg_no
                            if payment.vehicle_id in vehicle_of else '-'),
        'sheet': (vehicle_of[payment.vehicle_id].sheet_name
                  if payment.vehicle_id in vehicle_of else '') or '-',
        'amount': payment.amount or 0.0,
        'method': payment.payment_method or '-',
        'reference': payment.reference_no or '-',
        'notes': payment.notes or '-',
    } for payment in payments]

    money = {'align': 'amount', 'money': True}

    return {
        'tables': [
            {
                'title': 'Per Officer',
                'icon': 'user-check',
                'columns': [
                    {'label': 'Officer', 'key': 'officer', 'strong': True},
                    {'label': 'Vehicles', 'key': 'vehicles', 'align': 'amount'},
                    dict({'label': 'AMC Charges', 'key': 'charges'}, **money),
                    dict({'label': 'Outstanding', 'key': 'outstanding'}, **money),
                    dict({'label': 'Collected in Period', 'key': 'collected'}, **money),
                    {'label': 'Payments', 'key': 'payments', 'align': 'amount',
                     'badge': 'success'},
                    {'label': 'Follow-ups', 'key': 'followups', 'align': 'amount',
                     'badge': 'info'},
                    {'label': 'Written Off', 'key': 'lost', 'align': 'amount'},
                    {'label': 'Invoices', 'key': 'invoices', 'align': 'amount'},
                    dict({'label': 'Invoiced', 'key': 'invoiced'}, **money),
                    dict({'label': 'Discount Given', 'key': 'discount'}, **money),
                ],
                'rows': officer_rows,
                'empty': 'No recovery work is assigned for this selection',
            },
            {
                'title': 'Recoveries Collected',
                'icon': 'banknote',
                'columns': [
                    {'label': 'Date & Time', 'key': 'when', 'strong': True},
                    {'label': 'Officer', 'key': 'officer'},
                    {'label': 'Registration', 'key': 'registration_no'},
                    {'label': 'Sheet', 'key': 'sheet'},
                    dict({'label': 'Amount', 'key': 'amount'}, **money),
                    {'label': 'Method', 'key': 'method'},
                    {'label': 'Reference', 'key': 'reference'},
                    {'label': 'Notes', 'key': 'notes'},
                ],
                'rows': payment_rows,
                'empty': 'No recoveries were collected in this period',
            },
        ],
        'note': 'Vehicles, charges and outstanding are the officer\'s whole book as '
                'it stands now; collected, follow-ups and invoices are the period '
                'only. Vehicles on no officer\'s sheet are grouped as Unassigned.',
    }


# The extra picker a report can carry beyond its period. One entry per report
# that needs one; the view renders it into the same form as the dates, so both
# Apply and Download Excel carry the selection.
def _report_device_recovery_followups(date_range):
    """Device Recovery charges with the contact book behind each one.

    The other follow-up reports list conversations that have happened. This
    one is built the other way round - a row per charge, with every number on
    record for the vehicle and the state of the chase - because the question
    it answers is "who still has to be rung, and on what number", not "who
    was rung last month".

    Runs from the scheduler as part of the month-end pack, so the layer is
    read from the query string only when there is a request to read it from.
    """
    from src.models.installation_recovery import InstallationRecoveryCharge
    from src.services.contact_book_service import attach_contact_books
    from src.services.installation_recovery_service import (
        InstallationRecoveryService, TRIGGERING_REASONS)
    from src.utils.date_ranges import apply_range

    selected_layer = ''
    if has_request_context():
        candidate = (request.args.get('reason') or '').strip()
        # An unknown layer would silently return an empty report; treat it as
        # no choice at all, the same as arriving without one.
        if candidate in TRIGGERING_REASONS:
            selected_layer = candidate

    query = InstallationRecoveryCharge.query
    if selected_layer:
        query = query.filter(InstallationRecoveryCharge.reason == selected_layer)
    charges = apply_range(query, InstallationRecoveryCharge.created_at,
                          date_range).order_by(
        InstallationRecoveryCharge.created_at.desc()).all()

    attach_contact_books(charges)
    summaries = InstallationRecoveryService().followup_summaries(charges)

    layer_rows = []
    for reason in TRIGGERING_REASONS:
        in_layer = [c for c in charges if c.reason == reason]
        if not in_layer:
            continue
        reachable = sum(1 for c in in_layer if c.contact_book['numbers'])
        layer_rows.append({
            'layer': reason,
            'charges': len(in_layer),
            'outstanding': f"PKR {sum(c.get_outstanding() for c in in_layer):,.0f}",
            'reachable': reachable,
            'unreachable': len(in_layer) - reachable,
            'chased': sum(1 for c in in_layer if summaries.get(c.id)),
        })

    charge_rows = []
    for charge in charges:
        activity = charge.redo_activity
        numbers = charge.contact_book['numbers']
        entry = summaries.get(charge.id)
        last = entry['last'] if entry else None
        charge_rows.append({
            'registration_no': (activity.registration_no if activity else '-') or '-',
            'customer': (activity.customer_name if activity else '') or '-',
            'layer': charge.reason or '-',
            'amount': f"PKR {charge.amount:,.0f}",
            'status': charge.status,
            'officer': (charge.assigned_officer.name
                        if charge.assigned_officer else 'Unassigned'),
            # Every number on one line, labelled - the row is read to decide
            # who to ring next, so the alternatives have to be visible.
            'numbers': ' | '.join(f"{n['label']}: {n['number']}"
                                  for n in numbers) or 'No number on record',
            'calls': entry['count'] if entry else 0,
            'last_attempt': (last.conversation_date.strftime('%d %b %Y')
                             if last and last.conversation_date else 'Not yet contacted'),
            'last_outcome': (last.summary if last and last.summary else '-'),
            'callback_due': (entry['next_due'].strftime('%d %b %Y')
                             if entry and entry['next_due'] else '-'),
        })

    return {
        'tables': [
            {
                'title': 'By Layer',
                'icon': 'layers',
                'columns': [
                    {'label': 'Layer', 'key': 'layer', 'strong': True},
                    {'label': 'Charges', 'key': 'charges', 'align': 'amount',
                     'badge': 'info'},
                    {'label': 'Outstanding', 'key': 'outstanding', 'align': 'amount'},
                    {'label': 'Reachable', 'key': 'reachable', 'align': 'amount'},
                    {'label': 'No Number', 'key': 'unreachable', 'align': 'amount'},
                    {'label': 'Chased', 'key': 'chased', 'align': 'amount'},
                ],
                'rows': layer_rows,
                'empty': 'No Device Recovery charges were raised in this period',
            },
            {
                'title': 'Follow-Up Sheet',
                'icon': 'clipboard-list',
                'columns': [
                    {'label': 'Registration', 'key': 'registration_no', 'strong': True},
                    {'label': 'Customer', 'key': 'customer'},
                    {'label': 'Layer', 'key': 'layer'},
                    {'label': 'Amount', 'key': 'amount', 'align': 'amount'},
                    {'label': 'Status', 'key': 'status'},
                    {'label': 'Officer', 'key': 'officer'},
                    {'label': 'Numbers to Try', 'key': 'numbers'},
                    {'label': 'Calls', 'key': 'calls', 'align': 'amount'},
                    {'label': 'Last Attempt', 'key': 'last_attempt'},
                    {'label': 'Last Outcome', 'key': 'last_outcome'},
                    {'label': 'Callback Due', 'key': 'callback_due'},
                ],
                'rows': charge_rows,
                'empty': 'No Device Recovery charges were raised in this period',
            },
        ],
        'note': ('Contact numbers are gathered from the monitoring feed, the '
                 'service record, the purchase order and the AMC roster, '
                 'de-duplicated and ordered most-likely-to-answer first.'),
    }


def _device_recovery_layer_choices():
    """The three Device Recovery layers, as the module defines them.

    Read from the service rather than repeated here, so a fourth triggering
    reason appears in the picker the day it is added.
    """
    from src.services.installation_recovery_service import TRIGGERING_REASONS
    return [(reason, reason) for reason in TRIGGERING_REASONS]


class ReportFilterSpec(TypedDict):
    name: str
    label: str
    all_label: str
    options: Callable[[], List[Any]]


MIS_REPORT_FILTERS: Dict[str, ReportFilterSpec] = {
    'individual-recovery': {
        'name': 'user',
        'label': 'Recovery Officer',
        'all_label': 'All Officers',
        'options': _recovery_officer_choices,
    },
    'device-recovery-followups': {
        'name': 'reason',
        'label': 'Layer',
        'all_label': 'All Layers',
        'options': _device_recovery_layer_choices,
    },
}


MIS_REPORT_BUILDERS = {
    'monthly-mis': _report_monthly_mis,
    'sales-performance': _report_sales_performance,
    'field-jobs': _report_field_jobs,
    'retained-cases': _report_retained_cases,
    'installations-by-city': _report_installations_by_city,
    'technician-load': _report_technician_load,
    'login-activity': _report_login_activity,
    'amc-invoices': _report_amc_invoices,
    'technician-performance': _report_technician_performance,
    'device-changes': _report_device_changes,
    'redo-followups': _report_redo_followups,
    'individual-recovery': _report_individual_recovery,
    'device-recovery-followups': _report_device_recovery_followups,
}


@admin_bp.route('/mis-reports')
@login_required
@role_required('admin', 'executive')
def mis_reports():
    """The reports index: what can be run, and over which period.

    Deliberately carries no figures of its own. A number on an index is a
    number with no period attached to it, which is how a reader ends up
    quoting last month's total for this month - so the period is chosen
    here and the figures appear in the report itself.
    """
    from src.utils.date_ranges import parse_range

    # The shared default fills every card's date inputs, so a user who wants
    # the same period from several reports sets it once per card rather than
    # discovering each one opened on a different range.
    date_range = parse_range(request.args)

    return render_template('admin/mis_reports.html',
                           reports=[_with_urls(report) for report in MIS_REPORTS],
                           date_range=date_range)


@admin_bp.route('/mis-reports/<slug>')
@login_required
@role_required('admin', 'executive')
def mis_report_view(slug):
    """Render one catalogue report over the requested period."""
    from src.utils.date_ranges import parse_range

    report = MIS_REPORTS_BY_SLUG.get(slug)
    builder = MIS_REPORT_BUILDERS.get(slug)
    if report is None or builder is None:
        abort(404)

    date_range = parse_range(request.args)
    built = builder(date_range)
    return render_template('admin/mis_report_detail.html',
                           report=_with_urls(report),
                           date_range=date_range,
                           report_filter=_report_filter(slug),
                           tables=_report_tables(built),
                           note=built.get('note'))


def _report_filter(slug):
    """The extra picker this report carries, already resolved for rendering.

    Returns None for the reports that only take a period, which is most of
    them. The options are read at request time rather than at import, because
    they come from the database - a recovery officer added this morning has to
    appear in the list this morning.
    """
    spec = MIS_REPORT_FILTERS.get(slug)
    if not spec:
        return None
    options_fn = spec['options']
    filter_name = str(spec['name'])
    return {
        'name': filter_name,
        'label': spec['label'],
        'all_label': spec['all_label'],
        'options': options_fn() if callable(options_fn) else [],
        'selected': (request.args.get(filter_name) or '').strip(),
    }


def _report_tables(built) -> "list[Dict[str, Any]]":
    """Normalise a builder's output to a list of tables.

    Most reports are one table and say so with plain `columns`/`rows`; a few
    (the monthly workbook) are several. The template only ever sees a list,
    so it does not need to know which kind it was handed.
    """
    if 'tables' in built:
        return built['tables']
    return [{'title': None, 'columns': built['columns'], 'rows': built['rows'],
             'empty': built.get('empty', 'Nothing recorded for this period')}]


@admin_bp.route('/mis-reports/<slug>/export')
@login_required
@role_required('admin', 'executive')
def mis_report_export(slug):
    """Download a catalogue report as a styled workbook.

    Built from the same rows the page rendered, so the file matches what was
    on screen - including the period, which travels on the same `from`/`to`
    parameters the Run Report button uses.
    """
    import os
    from src.services.mis_export_service import MISExportService
    from src.utils.date_ranges import parse_range

    report = MIS_REPORTS_BY_SLUG.get(slug)
    builder = MIS_REPORT_BUILDERS.get(slug)
    if report is None or builder is None:
        abort(404)

    built = builder(parse_range(request.args))
    tables = _report_tables(built)

    service = MISExportService()
    if len(tables) == 1:
        filepath = service.generate_report_excel(
            report['name'], tables[0]['columns'], tables[0]['rows'])
    else:
        filepath = service.generate_multi_sheet_report_excel(report['name'], tables)

    return send_file(filepath, as_attachment=True,
                     download_name=os.path.basename(filepath))


@admin_bp.route('/mis-reports/export')
@login_required
@role_required('admin', 'executive')
def mis_reports_export():
    """Download the complete MIS report (Activities, Installation, Removal,
    Transfer) as a single multi-sheet Excel workbook.

    Honours the same FROM/TO parameters as the page, so the file matches the
    period on screen. With no dates it falls back to everything on record.
    """
    import os
    from flask import send_file
    from src.services.mis_export_service import MISExportService
    from src.utils.date_ranges import parse_range

    date_range = parse_range(request.args, default_to_current_month=False)
    filepath = MISExportService().generate_mis_excel(date_range)
    return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))


@admin_bp.route('/mis-reports/technician-activity/export')
@login_required
@role_required('admin', 'executive')
def technician_activity_export():
    """Download the Technician Activity report for the selected period.

    Built from the same rows the wallboard renders, so the spreadsheet and
    the screen cannot disagree.
    """
    import os
    from flask import send_file
    from src.services.mis_export_service import MISExportService
    from src.services.technician_activity_service import TechnicianActivityService
    from src.utils.date_ranges import parse_range

    date_range = parse_range(request.args)
    rows = TechnicianActivityService().wallboard_rows(date_range)
    filepath = MISExportService().generate_technician_activity_excel(rows)
    return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))


# ============================================
# INSTALLATION QUEUE
# ============================================

@admin_bp.route('/installation-queue')
@login_required
@role_required('admin', 'executive')
def installation_queue():
    """Installation Queue - mirrors the Installation Team's own dashboard
    (search/filter, full order list with technician & status) so admin sees
    the same view installers do, not a stripped-down pending-only list."""
    po_service = POService()

    status_filter = request.args.get('status', '')
    search = request.args.get('search', '')

    filters = {}
    if status_filter:
        filters['status'] = status_filter

    result = po_service.get_pos(filters=filters, search=search)
    orders = result['items']

    stats = po_service.get_dashboard_stats()

    return render_template('admin/installation_queue.html',
                         orders=orders,
                         stats=stats,
                         search=search,
                         status_filter=status_filter)


# ============================================
# GPS MANAGEMENT
# ============================================

@admin_bp.route('/gps/sync', methods=['POST'])
@login_required
@role_required('admin')
def gps_sync():
    """Sync GPS locations"""
    gps_service = GPSService()
    count = gps_service.sync_locations()
    flash(f'GPS sync complete! {count} locations updated.', 'success')
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/gps/diagnose')
@login_required
@role_required('admin')
def gps_diagnose():
    """Diagnose GPS API"""
    gps_service = GPSService()
    results = gps_service.diagnose_api()
    return jsonify(results)


# ============================================
# HELPER FUNCTIONS
# ============================================

def populate_form_choices(form):
    """Populate form choices from database"""
    from src.services.vehicle_service import (
        VehicleMakeService, VehicleModelService, VehicleYearService,
        VehicleColorService, CityService
    )
    from src.services.user_service import UserService
    
    if hasattr(form, 'vehicle_make'):
        form.vehicle_make.choices = [('', 'Select Make')] + [(m.name, m.name) for m in VehicleMakeService().get_all_makes()]
    if hasattr(form, 'vehicle_model'):
        form.vehicle_model.choices = [('', 'Select Model')] + [(m.name, m.name) for m in VehicleModelService().get_all()]
    if hasattr(form, 'vehicle_year'):
        form.vehicle_year.choices = [('', 'Select Year')] + VehicleYearService().get_year_choices()
    if hasattr(form, 'vehicle_color'):
        form.vehicle_color.choices = [('', 'Select Color')] + [(c.name, c.name) for c in VehicleColorService().get_all_colors()]
    if hasattr(form, 'city'):
        form.city.choices = [('', 'Select City')] + [(c.name, c.name) for c in CityService().get_all_cities()]
    if hasattr(form, 'sales_person_id'):
        form.sales_person_id.choices = [('', 'Select Sales Person')] + [(u.id, u.name or u.username) for u in UserService().get_sales_users()]
    
    return form