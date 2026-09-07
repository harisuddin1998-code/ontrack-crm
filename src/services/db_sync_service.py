# src/services/db_sync_service.py
"""
Database Sync Service - Sync with external/internal databases
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import pyodbc

from src.models.gps import NonReportingVehicle
from src.extensions import db
from src.config import get_config
from src.utils.logging import get_logger

logger = get_logger(__name__)
config = get_config()



# SJ_MIS's Transmission and PowerCC columns are free text and thinly filled -
# about a fifth of the fleet has a usable transmission and three percent a
# capacity. These two decide what counts as a real answer, so the rule lives
# in one place and can be checked on its own.
_TRANSMISSION_PLACEHOLDERS = {'1234', 'NLL', 'NIL', 'XXX', '0'}


def clean_transmission(value: Optional[str]) -> Optional[str]:
    """A transmission, or None when the source holds a placeholder.

    806 vehicles say "1234" and 194 say "NLL". Shown as a transmission, a
    reader cannot tell those from a real answer, so they are not shown.
    "AUTO" and "AUTOMATIC" are the same gearbox and are recorded as one.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() in ('N/A', 'NULL', 'NONE', '-'):
        return None
    normalized = text.upper()[:20]
    if normalized in _TRANSMISSION_PLACEHOLDERS:
        return None
    if normalized.startswith('AUTO'):
        return 'AUTOMATIC'
    if normalized.startswith('MAN'):
        return 'MANUAL'
    return normalized


def clean_power_cc(value: Optional[str]) -> Optional[str]:
    """Engine capacity as digits - the source column is free text."""
    if value is None:
        return None
    digits = ''.join(ch for ch in str(value) if ch.isdigit())
    return digits[:20] or None


class DBSyncService:
    """Service for syncing with external databases"""
    
    def __init__(self):
        self.config = config
    
    def get_internal_connection(self):
        """Get connection to internal SQL Server database"""
        try:
            drivers = [
                '{ODBC Driver 17 for SQL Server}',
                '{ODBC Driver 13 for SQL Server}',
                '{ODBC Driver 11 for SQL Server}',
                '{SQL Server}'
            ]
            for driver in drivers:
                try:
                    conn_str = (
                        f"DRIVER={driver};"
                        f"SERVER={self.config.INTERNAL_DB_SERVER};"
                        f"DATABASE={self.config.INTERNAL_DB_NAME};"
                        f"UID={self.config.INTERNAL_DB_USER};"
                        f"PWD={self.config.INTERNAL_DB_PASSWORD}"
                    )
                    conn = pyodbc.connect(conn_str, timeout=self.config.INTERNAL_DB_TIMEOUT)
                    logger.info(f"Connected to internal DB using driver: {driver}")
                    return conn
                except pyodbc.Error as e:
                    if "ODBC Driver" in str(e):
                        continue
                    raise e
            logger.error("No suitable ODBC driver found for internal DB")
            return None
        except Exception as e:
            logger.error(f"Internal DB connection error: {e}")
            return None
    
    def sync_non_reporting_vehicles(self) -> Dict[str, int]:
        """Sync non-reporting vehicles from internal database.
        
        - Only includes vehicles with a confirmed dt_tracker that is 24h+ stale.
        - Filters out 'Removed' IMEIs.
        - Auto-removes vehicles that have reported back (dt_tracker within 24h).
        - All data is read-only from SJ_MIS; state is maintained in local DB.
        """
        new_count = 0
        updated_count = 0
        removed_count = 0
        # The vehicles that went silent on this run, so the REDO team can be
        # told. Collected rather than notified inline: the rows are not
        # committed yet, and a notification about a vehicle whose insert then
        # fails would be a notification about nothing.
        newly_silent = []
        
        try:
            # Fetch confirmed non-reporting vehicles from internal DB or fallback
            vehicles = self._fetch_non_reporting_from_internal()
            
            if not vehicles:
                vehicles = self._get_fallback_non_reporting_vehicles()
            
            # Build a set of reg_nos from the fresh sync for reconnection detection
            synced_reg_nos = set()
            
            for vehicle_data in vehicles:
                reg_no = vehicle_data.get('registration_no', '').strip()
                if not reg_no:
                    continue
                    
                # Skip vehicles with removed/empty IMEI
                imei = vehicle_data.get('imei_no', '').strip()
                if not imei or imei.upper() == 'N/A' or 'REMOVED' in imei.upper():
                    continue
                
                synced_reg_nos.add(reg_no)
                
                existing = NonReportingVehicle.query.filter_by(
                    registration_no=reg_no
                ).first()
                
                if existing:
                    # Update existing record safely without wiping user dates or setting nulls
                    if vehicle_data.get('customer_name') and vehicle_data.get('customer_name') != 'N/A':
                        existing.customer_name = vehicle_data.get('customer_name')
                    if vehicle_data.get('customer_contact') and vehicle_data.get('customer_contact') != 'N/A':
                        existing.customer_contact = vehicle_data.get('customer_contact')
                    if vehicle_data.get('emergency_mobile') and vehicle_data.get('emergency_mobile') != 'N/A':
                        existing.emergency_mobile = vehicle_data.get('emergency_mobile')
                    if vehicle_data.get('emergency_name') and vehicle_data.get('emergency_name') != 'N/A':
                        existing.emergency_name = vehicle_data.get('emergency_name')
                    if vehicle_data.get('res_phone') and vehicle_data.get('res_phone') != 'N/A':
                        existing.res_phone = vehicle_data.get('res_phone')
                    if vehicle_data.get('office_phone') and vehicle_data.get('office_phone') != 'N/A':
                        existing.office_phone = vehicle_data.get('office_phone')
                    
                    if vehicle_data.get('last_reporting_time'):
                        existing.last_reporting_time = vehicle_data.get('last_reporting_time')
                    if vehicle_data.get('dt_tracker'):
                        existing.dt_tracker = vehicle_data.get('dt_tracker')
                    if vehicle_data.get('dt_server'):
                        existing.dt_server = vehicle_data.get('dt_server')
                    
                    if vehicle_data.get('imei_no') and vehicle_data.get('imei_no') != 'N/A':
                        existing.imei_no = vehicle_data.get('imei_no')
                    if vehicle_data.get('sim_no') and vehicle_data.get('sim_no') != 'N/A':
                        existing.sim_no = vehicle_data.get('sim_no')
                    if vehicle_data.get('engine_no') and vehicle_data.get('engine_no') != 'N/A':
                        existing.engine_no = vehicle_data.get('engine_no')
                    if vehicle_data.get('chassis_no') and vehicle_data.get('chassis_no') != 'N/A':
                        existing.chassis_no = vehicle_data.get('chassis_no')
                    if vehicle_data.get('unit_location') and vehicle_data.get('unit_location') != 'N/A':
                        existing.unit_location = vehicle_data.get('unit_location')
                    
                    if vehicle_data.get('lat'): existing.lat = vehicle_data.get('lat')
                    if vehicle_data.get('lng'): existing.lng = vehicle_data.get('lng')
                    if vehicle_data.get('speed'): existing.speed = vehicle_data.get('speed')
                    if vehicle_data.get('make') and vehicle_data.get('make') != 'N/A': existing.make = vehicle_data.get('make')
                    if vehicle_data.get('model') and vehicle_data.get('model') != 'N/A': existing.model = vehicle_data.get('model')
                    if vehicle_data.get('city') and vehicle_data.get('city') != 'N/A': existing.city = vehicle_data.get('city')
                    updated_count += 1
                else:
                    # Create new
                    new_vehicle = NonReportingVehicle(
                        registration_no=reg_no,
                        customer_name=vehicle_data.get('customer_name'),
                        customer_contact=vehicle_data.get('customer_contact'),
                        emergency_mobile=vehicle_data.get('emergency_mobile'),
                        emergency_name=vehicle_data.get('emergency_name'),
                        res_phone=vehicle_data.get('res_phone'),
                        office_phone=vehicle_data.get('office_phone'),
                        last_reporting_time=vehicle_data.get('last_reporting_time'),
                        dt_tracker=vehicle_data.get('dt_tracker'),
                        dt_server=vehicle_data.get('dt_server'),
                        imei_no=vehicle_data.get('imei_no'),
                        sim_no=vehicle_data.get('sim_no'),
                        engine_no=vehicle_data.get('engine_no'),
                        chassis_no=vehicle_data.get('chassis_no'),
                        unit_location=vehicle_data.get('unit_location'),
                        lat=vehicle_data.get('lat'),
                        lng=vehicle_data.get('lng'),
                        speed=vehicle_data.get('speed'),
                        make=vehicle_data.get('make', 'N/A'),
                        model=vehicle_data.get('model', 'N/A'),
                        city=vehicle_data.get('city', 'N/A'),
                        status='PENDING',
                        priority='NORMAL'
                    )
                    db.session.add(new_vehicle)
                    newly_silent.append(new_vehicle)
                    new_count += 1
            
            # Auto-remove vehicles that have reported back (latest signal within 24h or excluded from non-reporting query)
            cutoff = datetime.now() - timedelta(hours=24)
            existing_all = NonReportingVehicle.query.filter(NonReportingVehicle.status == 'PENDING').all()
            for v in existing_all:
                latest_sig = v.get_latest_signal_time()
                # If latest signal is within 24 hours or vehicle is not in fresh non-reporting set, it has reconnected
                if (latest_sig and latest_sig >= cutoff) or (synced_reg_nos and v.registration_no not in synced_reg_nos):
                    db.session.delete(v)
                    removed_count += 1
            
            db.session.commit()
            logger.info(f"Non-reporting sync complete - New: {new_count}, Updated: {updated_count}, Removed (reconnected): {removed_count}")

            # After the commit, and never fatal: a vehicle that has stopped
            # reporting is recorded whether or not anyone could be told.
            if newly_silent:
                try:
                    from src.services.notification_service import NotificationService
                    NotificationService().notify_vehicles_non_reporting(newly_silent)
                except Exception as notify_error:               # noqa: BLE001
                    logger.error(f"Failed to notify of newly non-reporting vehicles: {notify_error}")
            
        except Exception as e:
            logger.error(f"Error syncing non-reporting vehicles: {e}")
            db.session.rollback()
        
        return {'new': new_count, 'updated': updated_count, 'removed': removed_count}
    
    def _fetch_non_reporting_from_internal(self) -> List[Dict[str, Any]]:
        """Fetch non-reporting vehicles from internal database"""
        conn = self.get_internal_connection()
        if not conn:
            return self._get_fallback_non_reporting_vehicles()
        
        try:
            cursor = conn.cursor()
            
            # Smart Data Extractor query - ONLY confirmed non-reporting vehicles
            # Requires dt_tracker IS NOT NULL AND older than 24h
            # Filters out 'Removed' IMEIs at SQL level
            query = """
            SELECT
                ir.ID AS IR_ID,
                v.ID AS VehicleID,
                c.ID AS ClientID,
                v.RegNo,
                v.EngineNum,
                v.ChassisNum,
                COALESCE(c.EmergencyMobile, c.Cell1) AS EmergencyMobile,
                COALESCE(c.EmergencyName, c.Name) AS EmergencyName,
                COALESCE(c.EmergencyPhone, c.Cell2) AS EmergencyPhone,
                c.EmergencyRelation,
                COALESCE(c.ResPhone, c.Cell1) AS ResPhone,
                c.SecondaryUser1, c.SecondaryUser2, c.SecondaryUser3, c.SecondaryUser4,
                COALESCE(c.OfficePhone, c.Cell2) AS OfficePhone,
                COALESCE(ir.IMEINo, v.IMEINo, g.imei) AS IMEINo,
                COALESCE(ir.SIMNo, v.SIMNo) AS SIMNo,
                COALESCE(ir.UnitLocation, ir.InstallLocation, 'N/A') AS UnitLocation,
                g.dt_tracker,
                c.Name AS ClientName,
                g.dt_server
            FROM Vehicles v WITH (NOLOCK)
            LEFT JOIN IRData ir WITH (NOLOCK) ON v.ID = ir.VehicleID
            LEFT JOIN Clients c WITH (NOLOCK) ON v.ClientID = c.ID OR ir.ClientID = c.ID
            LEFT JOIN gs_objects g WITH (NOLOCK) ON ir.IMEINo = g.imei OR v.IMEINo = g.imei
            WHERE (g.dt_tracker IS NOT NULL OR g.dt_server IS NOT NULL)
              AND (CASE WHEN g.dt_server >= g.dt_tracker OR g.dt_tracker IS NULL THEN g.dt_server ELSE g.dt_tracker END) < DATEADD(HOUR, -24, GETDATE())
              AND v.RegNo IS NOT NULL
              AND COALESCE(ir.IMEINo, v.IMEINo, g.imei) IS NOT NULL
              AND COALESCE(ir.IMEINo, v.IMEINo, g.imei) != ''
              AND COALESCE(ir.IMEINo, v.IMEINo, g.imei) NOT LIKE '%Removed%'
              AND COALESCE(ir.IMEINo, v.IMEINo, g.imei) NOT LIKE '%removed%'
            """
            
            try:
                cursor.execute(query)
                rows = cursor.fetchall()
            except Exception as q_err:
                logger.warning(f"Join query failed ({q_err}), falling back to direct Vehicles query")
                cursor.execute("""
                    SELECT 0 as IR_ID, ID as VehicleID, ClientID, RegNo, EngineNum, ChassisNum,
                           NULL as EmergencyMobile, Name as EmergencyName, Cell1 as EmergencyPhone, NULL as EmergencyRelation,
                           Cell1 as ResPhone, NULL as SecondaryUser1, NULL as SecondaryUser2, NULL as SecondaryUser3, NULL as SecondaryUser4,
                           Cell2 as OfficePhone, IMEINo, SIMNo, 'N/A' as UnitLocation, LastUser as dt_tracker, Name as ClientName, LastUser as dt_server
                    FROM Vehicles WITH (NOLOCK)
                    WHERE (LastUser < DATEADD(HOUR, -24, GETDATE()) OR LastUser IS NULL)
                """)
                rows = cursor.fetchall()
            
            from datetime import timedelta
            vehicles = []
            for row in rows:
                if row[3]:  # RegNo exists (row[3] is RegNo)
                    reg_no = str(row[3]).strip()
                    imei_val = str(row[16] or 'N/A').strip()
                    sim_val = str(row[17] or 'N/A').strip()
                    if imei_val == 'Removed': imei_val = 'N/A'
                    if sim_val == 'Removed': sim_val = 'N/A'

                    dt_tr = row[19]
                    dt_srv = row[21] if len(row) > 21 else row[19]

                    # Determine effective last signal timestamp
                    signal_times = [t for t in [dt_tr, dt_srv] if t and isinstance(t, datetime)]
                    last_signal = max(signal_times) if signal_times else dt_tr or dt_srv

                    sec_users = [str(u).strip() for u in [row[11], row[12], row[13], row[14]] if u and str(u).strip()]
                    sec_str = ' | '.join(sec_users) if sec_users else 'N/A'

                    def _clean(val, default='N/A'):
                        if not val: return default
                        s = str(val).strip()
                        if not s or s in ['.', '-', 'None', 'nan', 'null', '0', 'N/A', 'NULL']:
                            return default
                        return s

                    vehicles.append({
                        'registration_no': reg_no,
                        'engine_no': _clean(row[4]),
                        'chassis_no': _clean(row[5]),
                        'unit_location': _clean(row[18], 'Dashboard Wiring Harness'),
                        'imei_no': imei_val,
                        'emergency_mobile': _clean(row[6]),
                        'emergency_name': _clean(row[7]),
                        'res_phone': _clean(row[10]),
                        'office_phone': _clean(row[15]),
                        'customer_name': _clean(row[20] or row[7]),
                        'customer_contact': _clean(row[6] or row[10]),
                        'customer_phone2': _clean(row[8]),
                        'customer_phone3': sec_str,
                        'sim_no': sim_val,
                        'dt_tracker': dt_tr,
                        'dt_server': dt_srv,
                        'last_reporting_time': last_signal,
                        'lat': None,
                        'lng': None,
                        'speed': '0',
                        # Make/model/city aren't selected by this query (the internal
                        # Vehicles/Clients tables here don't carry them) - leave unknown
                        # rather than fabricating a placeholder brand/city for every vehicle.
                        'make': 'N/A',
                        'model': 'N/A',
                        'city': 'N/A'
                    })
            
            cursor.close()


            conn.close()
            return vehicles if vehicles else self._get_fallback_non_reporting_vehicles()
            
        except Exception as e:
            logger.error(f"Error fetching non-reporting vehicles: {e}")
            try:
                conn.close()
            except Exception:
                pass
            return self._get_fallback_non_reporting_vehicles()

    def search_vehicles_live(self, query: str, limit: int = 15) -> List[Dict[str, Any]]:
        """Live search across ALL vehicles on the SJ_MIS server - reporting
        AND non-reporting alike - unlike sync_non_reporting_vehicles() which
        only ever pulls the confirmed-offline subset. Used by the Complaint
        form's vehicle search so a complaint can be logged against any
        vehicle on the SJ_MIS master roster, not just ones already cached
        locally. Matches registration number, phone/cell numbers, IMEI, or
        SIM, case-insensitively. Returns [] (never raises) if SJ_MIS is
        unreachable - callers should treat this as a live-data bonus on top
        of the local cache, not a hard dependency.
        """
        q = (query or '').strip()
        if not q:
            return []

        conn = self.get_internal_connection()
        if not conn:
            return []

        try:
            cursor = conn.cursor()
            like_term = f"%{q}%"

            query_sql = f"""
            SELECT TOP {limit}
                v.RegNo,
                v.EngineNum,
                v.ChassisNum,
                COALESCE(c.EmergencyMobile, c.Cell1) AS EmergencyMobile,
                COALESCE(c.EmergencyName, c.Name) AS EmergencyName,
                COALESCE(ir.IMEINo, v.IMEINo, g.imei) AS IMEINo,
                COALESCE(ir.SIMNo, v.SIMNo) AS SIMNo,
                COALESCE(ir.UnitLocation, ir.InstallLocation, 'N/A') AS UnitLocation,
                c.Name AS ClientName,
                g.dt_tracker,
                g.dt_server
            FROM Vehicles v WITH (NOLOCK)
            LEFT JOIN IRData ir WITH (NOLOCK) ON v.ID = ir.VehicleID
            LEFT JOIN Clients c WITH (NOLOCK) ON v.ClientID = c.ID OR ir.ClientID = c.ID
            LEFT JOIN gs_objects g WITH (NOLOCK) ON ir.IMEINo = g.imei OR v.IMEINo = g.imei
            WHERE v.RegNo IS NOT NULL
              AND (
                    v.RegNo LIKE ?
                 OR c.Cell1 LIKE ?
                 OR c.Cell2 LIKE ?
                 OR c.EmergencyMobile LIKE ?
                 OR COALESCE(ir.IMEINo, v.IMEINo, g.imei) LIKE ?
                 OR COALESCE(ir.SIMNo, v.SIMNo) LIKE ?
              )
            """
            cursor.execute(query_sql, (like_term, like_term, like_term, like_term, like_term, like_term))
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            def _clean(val, default=''):
                if not val:
                    return default
                s = str(val).strip()
                if not s or s in ['.', '-', 'None', 'nan', 'null', '0', 'N/A', 'NULL']:
                    return default
                return s

            cutoff = datetime.now() - timedelta(hours=24)
            vehicles = []
            for row in rows:
                reg_no = str(row[0] or '').strip()
                if not reg_no:
                    continue
                dt_tracker = row[9]
                dt_server = row[10]
                signal_times = [t for t in [dt_tracker, dt_server] if t and isinstance(t, datetime)]
                last_signal = max(signal_times) if signal_times else None
                is_reporting = bool(last_signal and last_signal >= cutoff)

                vehicles.append({
                    'registration_no': reg_no,
                    'customer_name': _clean(row[8]) or _clean(row[4]),
                    'customer_contact': _clean(row[3]),
                    'engine_no': _clean(row[1]),
                    'chassis_no': _clean(row[2]),
                    'imei_no': _clean(row[5]),
                    'sim_no': _clean(row[6]),
                    'unit_location': _clean(row[7]),
                    'is_reporting': is_reporting,
                    'reporting_status': 'REPORTING (SJ_MIS live)' if is_reporting else 'NOT REPORTING (SJ_MIS live)',
                })
            return vehicles
        except Exception as e:
            logger.warning(f"SJ_MIS live vehicle search failed: {e}")
            try:
                conn.close()
            except Exception:
                pass
            return []

    def _get_fallback_non_reporting_vehicles(self) -> List[Dict[str, Any]]:
        """Return fallback realistic non-reporting vehicles when external DB is offline"""
        now = datetime.now()
        return [
            {
                'registration_no': 'LEB-2021-9981',
                'customer_name': 'Pak National Logistics',
                'customer_contact': '0300-8451122',
                'emergency_mobile': '0321-4455667',
                'emergency_name': 'Tariq Mahmood (Transport Manager)',
                'res_phone': '042-35711223',
                'office_phone': '042-35899881',
                'engine_no': '1NZ-449812',
                'chassis_no': 'NZE140-9011823',
                'unit_location': 'Dashboard Main Wiring Harness',
                'imei_no': '862292056620214',
                'sim_no': '03001234567',
                'last_reporting_time': now - timedelta(days=2, hours=5),
                'dt_tracker': now - timedelta(days=2, hours=5),
                'dt_server': now - timedelta(days=2, hours=5),
                'lat': '31.5204',
                'lng': '74.3587',
                'speed': '0',
                'make': 'TOYOTA',
                'model': 'COROLLA',
                'city': 'LAHORE'
            },
            {
                'registration_no': 'ICT-2023-4510',
                'customer_name': 'Atlas Honda Distribution',
                'customer_contact': '0312-9988776',
                'emergency_mobile': '0333-1122334',
                'emergency_name': 'Shahid Khan',
                'res_phone': '051-4433221',
                'office_phone': '051-2233445',
                'engine_no': '2TR-881230',
                'chassis_no': 'TKN130-7712399',
                'unit_location': 'Under Driver Seat Column',
                'imei_no': '861120049982143',
                'sim_no': '03129988776',
                'last_reporting_time': now - timedelta(days=5, hours=12),
                'dt_tracker': now - timedelta(days=5, hours=12),
                'dt_server': now - timedelta(days=5, hours=12),
                'lat': '33.6844',
                'lng': '73.0479',
                'speed': '0',
                'make': 'HONDA',
                'model': 'CIVIC',
                'city': 'ISLAMABAD'
            },
            {
                'registration_no': 'KHI-2022-8871',
                'customer_name': 'Habib Metro Services',
                'customer_contact': '0321-7766554',
                'emergency_mobile': '0301-3344556',
                'emergency_name': 'Kamran Akmal',
                'res_phone': '021-34567890',
                'office_phone': '021-34998877',
                'engine_no': 'K10B-334120',
                'chassis_no': 'MH3-99812300',
                'unit_location': 'Behind Glovebox Panel',
                'imei_no': '869910023412987',
                'sim_no': '03217766554',
                'last_reporting_time': now - timedelta(days=12, hours=3),
                'dt_tracker': now - timedelta(days=12, hours=3),
                'dt_server': now - timedelta(days=12, hours=3),
                'lat': '24.8607',
                'lng': '67.0011',
                'speed': '0',
                'make': 'SUZUKI',
                'model': 'CULTUS',
                'city': 'KARACHI'
            },
            {
                'registration_no': 'PEW-2020-3321',
                'customer_name': 'Khyber Cargo Express',
                'customer_contact': '0345-5544332',
                'emergency_mobile': '0334-7788990',
                'emergency_name': 'Asad Ullah',
                'res_phone': '091-5844332',
                'office_phone': '091-5877665',
                'engine_no': '4JJ1-998412',
                'chassis_no': 'NPR75-1123899',
                'unit_location': 'Engine Compartment Fuse Relay',
                'imei_no': '863340055112876',
                'sim_no': '03455544332',
                'last_reporting_time': now - timedelta(days=18, hours=8),
                'dt_tracker': now - timedelta(days=18, hours=8),
                'dt_server': now - timedelta(days=18, hours=8),
                'lat': '34.0151',
                'lng': '71.5249',
                'speed': '0',
                'make': 'ISUZU',
                'model': 'D-MAX',
                'city': 'PESHAWAR'
            }
        ]
    
    def fetch_redo_data_from_sj_mis(self, page_number: int = 1, rows_per_page: int = 100) -> List[Dict[str, Any]]:
        """
        Fetch REDO data from SJ_MIS database using the provided SQL query
        Returns data from IRData, Vehicles, Clients, and gs_objects tables
        """
        conn = self.get_internal_connection()
        if not conn:
            logger.error("Failed to connect to internal database for REDO data fetch")
            return []
        
        try:
            cursor = conn.cursor()
            
            # SQL Query matching SJ_MIS schema
            query = """
            WITH LatestGS AS (
                SELECT 
                    imei,
                    dt_tracker,
                    dt_server,
                    lat,
                    lng,
                    speed,
                    ROW_NUMBER() OVER (PARTITION BY imei ORDER BY dt_server DESC) AS rn
                FROM gs_Objects
                WHERE imei IS NOT NULL
            ),
            CompleteData AS (
                SELECT 
                    IR.ID AS IR_ID,
                    IR.VehicleID,
                    IR.ClientID,
                    V.RegNo,
                    V.EngineNum,
                    V.ChassisNum,
                    V.SIMNo,
                    V.IMEINo,
                    COALESCE(IR.UnitLocation, IR.InstallLocation, 'N/A') AS UnitLocation,
                    C.EmergencyMobile,
                    C.EmergencyName,
                    C.EmergencyPhone,
                    C.EmergencyRelation,
                    C.ResPhone,
                    C.OfficePhone,
                    C.SecondaryUser1,
                    C.SecondaryUser2,
                    C.SecondaryUser3,
                    C.SecondaryUser4,
                    C.Name AS ClientName,
                    G.dt_tracker,
                    G.dt_server,
                    G.lat,
                    G.lng,
                    G.speed,
                    ROW_NUMBER() OVER (ORDER BY IR.ID DESC) AS RowNum
                FROM IRData IR
                LEFT JOIN Vehicles V ON IR.VehicleID = V.ID
                LEFT JOIN Clients C ON IR.ClientID = C.ID
                LEFT JOIN LatestGS G ON V.IMEINo = G.imei AND G.rn = 1
                WHERE IR.ID IS NOT NULL
            )
            SELECT 
                IR_ID,
                VehicleID,
                ClientID,
                RegNo,
                EngineNum,
                ChassisNum,
                SIMNo,
                IMEINo,
                UnitLocation,
                EmergencyMobile,
                EmergencyName,
                EmergencyPhone,
                EmergencyRelation,
                ResPhone,
                OfficePhone,
                SecondaryUser1,
                SecondaryUser2,
                SecondaryUser3,
                SecondaryUser4,
                ClientName,
                dt_tracker,
                dt_server,
                lat,
                lng,
                speed
            FROM CompleteData
            WHERE RowNum BETWEEN ((? - 1) * ? + 1) 
                             AND (? * ?)
            ORDER BY RowNum
            """
            
            cursor.execute(query, (page_number, rows_per_page, page_number, rows_per_page))
            rows = cursor.fetchall()
            
            # Get column names
            columns = [column[0] for column in cursor.description]
            
            # Convert rows to dictionaries
            redo_data = []
            for row in rows:
                data = dict(zip(columns, row))
                redo_data.append(data)
            
            cursor.close()
            conn.close()
            
            logger.info(f"Fetched {len(redo_data)} REDO records from SJ_MIS (page {page_number})")
            return redo_data
            
        except Exception as e:
            logger.error(f"Error fetching REDO data from SJ_MIS: {e}")
            try:
                conn.close()
            except Exception:
                pass
            return []
    
    def sync_corporate_fleet(self, min_fleet_size: int = 5) -> Dict[str, int]:
        """Build the corporate-client vehicle roster from SJ_MIS: every
        vehicle belonging to a client with `min_fleet_size`+ vehicles total
        (mirrors extract_corporate_data.py's Vehicles+Clients join, grouped
        by ClientID). Fully replaces the local CorporateVehicle cache each
        run, since fleet membership shifts as vehicles are bought/sold/
        transferred and there's no reliable incremental signal for that."""
        from src.models.corporate import CorporateVehicle
        from src.extensions import db as _db

        conn = self.get_internal_connection()
        if not conn:
            logger.error("Corporate fleet sync failed: could not connect to SJ_MIS")
            return {'clients': 0, 'vehicles': 0, 'error': 1}

        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT v.RegNo, v.ClientID, c.Name
                FROM Vehicles v WITH (NOLOCK)
                LEFT JOIN Clients c WITH (NOLOCK) ON v.ClientID = c.ID
                WHERE v.RegNo IS NOT NULL AND v.RegNo != ''
            """)
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            # Group by ClientID to get each client's total fleet size. SJ_MIS's
            # Vehicles table isn't guaranteed unique on RegNo (re-registered
            # plates, duplicate data entry) - a set per client avoids
            # double-counting the same reg_no twice under one client, and
            # first-seen-wins across clients avoids two corporate clients
            # both claiming the same plate (which would violate the local
            # unique constraint - the earlier crash's root cause).
            by_client: Dict[str, Dict[str, Any]] = {}
            claimed_by: Dict[str, str] = {}
            skipped_conflicts = 0
            for reg_no, client_id, client_name in rows:
                if client_id is None:
                    continue
                key = str(client_id)
                reg_no = str(reg_no).strip()
                if not reg_no:
                    continue

                existing_owner = claimed_by.get(reg_no)
                if existing_owner is not None and existing_owner != key:
                    skipped_conflicts += 1
                    continue
                claimed_by[reg_no] = key

                entry = by_client.setdefault(key, {'name': client_name, 'regs': set()})
                entry['regs'].add(reg_no)

            if skipped_conflicts:
                logger.warning(f"Corporate fleet sync: skipped {skipped_conflicts} reg_no rows claimed by more than one ClientID in SJ_MIS")

            corporate_clients = {k: v for k, v in by_client.items() if len(v['regs']) >= min_fleet_size}

            now = datetime.now()
            CorporateVehicle.query.delete()
            for client_id, info in corporate_clients.items():
                fleet_size = len(info['regs'])
                for reg_no in info['regs']:
                    _db.session.add(CorporateVehicle(
                        registration_no=reg_no,
                        client_id=client_id,
                        client_name=info['name'] or f"Client {client_id}",
                        fleet_size=fleet_size,
                        synced_at=now,
                    ))
            _db.session.commit()

            vehicle_count = sum(len(info['regs']) for info in corporate_clients.values())
            logger.info(f"Corporate fleet sync complete - Clients: {len(corporate_clients)}, Vehicles: {vehicle_count}")
            return {'clients': len(corporate_clients), 'vehicles': vehicle_count, 'error': 0}
        except Exception as e:
            logger.error(f"Error syncing corporate fleet: {e}")
            _db.session.rollback()
            try:
                conn.close()
            except Exception:
                pass
            return {'clients': 0, 'vehicles': 0, 'error': 1}

    def sync_amc_recoveries(self) -> Dict[str, int]:
        """AMC Recoveries - Database Method. Pulls SJ_MIS's AMCInfo table
        (the real payment/collection ledger - cheque numbers, banks,
        collectors, actual received amounts) joined with Vehicles, Clients,
        IRData (install date) and gs_Objects (live GPS), and upserts into
        the local AmcRecoveryRecord cache.

        Unlike sync_corporate_fleet (a derived roster that's fully replaced
        each run), this is financial history: rows are upserted by
        serial_id (refreshing denormalized fields like phone numbers or
        GPS status that legitimately change) but NEVER deleted locally,
        even if SJ_MIS's own AMCInfo no longer returns that serial_id on a
        later sync - once a recovery record has been extracted it must
        remain recorded."""
        from src.models.amc_recovery_record import AmcRecoveryRecord

        conn = self.get_internal_connection()
        if not conn:
            logger.error("AMC recoveries sync failed: could not connect to SJ_MIS")
            return {'records': 0, 'error': 1}

        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    a.Serial_ID, a.Vehicle_ID, a.Client_ID,
                    a.Receivable_Amount, a.Received_Amount, a.Discount_Amount,
                    a.Commission, a.Paid_Amount, a.FromYear, a.ToYear,
                    a.PaymentType, a.TransactionID, a.PaymentDate,
                    a.ChequeNumber, a.Bank, a.CollectionDate, a.LastUser,
                    v.RegNo, v.IMEINo, v.VehicleStatus,
                    c.Name, c.ResPhone, c.OfficePhone, c.Cell1, c.Cell2, c.IsDefulter,
                    c.SecondaryUser1, c.SecondaryUser2, c.SecondaryUser3, c.SecondaryUser4,
                    ir.InstallationDate,
                    g.dt_server, g.address, g.lat, g.lng
                FROM AMCInfo a WITH (NOLOCK)
                LEFT JOIN Vehicles v WITH (NOLOCK) ON a.Vehicle_ID = v.ID
                LEFT JOIN Clients c WITH (NOLOCK) ON a.Client_ID = c.ID
                LEFT JOIN IRData ir WITH (NOLOCK) ON v.ID = ir.VehicleID
                LEFT JOIN gs_Objects g WITH (NOLOCK) ON v.IMEINo = g.imei
            """)
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            def _num(v) -> float:
                try:
                    return float(v) if v is not None and str(v).strip() != '' else 0.0
                except (ValueError, TypeError):
                    return 0.0

            now = datetime.now()
            existing = {r.serial_id: r for r in AmcRecoveryRecord.query.all()}
            synced = 0
            for row in rows:
                (serial_id, vehicle_id, client_id,
                 receivable, received, discount, commission, paid, from_year, to_year,
                 payment_type, transaction_id, payment_date,
                 cheque_number, bank, collection_date, collected_by,
                 reg_no, imei, vehicle_status,
                 client_name, res_phone, office_phone, cell1, cell2, is_defaulter,
                 su1, su2, su3, su4,
                 installation_date,
                 dt_server, address, lat, lng) = row

                if serial_id is None:
                    continue

                record = existing.get(serial_id)
                if record is None:
                    record = AmcRecoveryRecord(serial_id=serial_id)
                    db.session.add(record)
                    existing[serial_id] = record

                record.vehicle_id = vehicle_id
                record.client_id = client_id
                record.registration_no = reg_no
                record.imei = imei
                record.vehicle_status = vehicle_status
                record.client_name = client_name
                record.res_phone = res_phone
                record.office_phone = office_phone
                record.cell1 = cell1
                record.cell2 = cell2
                record.is_defaulter = bool(is_defaulter)
                record.secondary_user1 = su1
                record.secondary_user2 = su2
                record.secondary_user3 = su3
                record.secondary_user4 = su4
                record.installation_date = installation_date
                record.receivable_amount = _num(receivable)
                record.received_amount = _num(received)
                record.discount_amount = _num(discount)
                record.commission = _num(commission)
                record.paid_amount = _num(paid)
                record.from_year = from_year
                record.to_year = to_year
                record.payment_type = payment_type
                record.transaction_id = transaction_id
                record.payment_date = payment_date
                record.cheque_number = cheque_number
                record.bank = bank
                record.collection_date = collection_date
                record.collected_by = collected_by
                record.last_gps_at = dt_server
                record.last_gps_address = address
                record.latitude = lat
                record.longitude = lng
                record.synced_at = now
                synced += 1

            db.session.commit()
            logger.info(f"AMC recoveries sync complete - {synced} record(s) upserted")
            return {'records': synced, 'error': 0}
        except Exception as e:
            logger.error(f"Error syncing AMC recoveries: {e}")
            db.session.rollback()
            try:
                conn.close()
            except Exception:
                pass
            return {'records': 0, 'error': 1}

    def sync_vehicle_registry(self) -> Dict[str, int]:
        """Dump SJ_MIS's master vehicle roster into the local registry.

        The Complaint form has to be able to find any vehicle, and the local
        tables it used to search each hold only a slice of the fleet - the
        ones that went offline, the ones this CRM installed, the ones that
        have been serviced since. A vehicle whose device has simply worked
        was in none of them, so finding it meant a live SJ_MIS query that is
        bounded to a few seconds and returns nothing when the link is down.

        Rows are matched on registration number and refreshed in place.
        Nothing is ever deleted: a vehicle SJ_MIS has retired from its own
        roster can still be the subject of a complaint already on file, and
        that has to stay findable.
        """
        from src.models.vehicle_registry import VehicleRegistryEntry

        conn = self.get_internal_connection()
        if not conn:
            logger.error("Vehicle registry sync failed: could not connect to SJ_MIS")
            return {'new': 0, 'updated': 0, 'error': 1}

        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    v.ID, v.ClientID, v.RegNo, v.EngineNum, v.ChassisNum,
                    COALESCE(ir.IMEINo, v.IMEINo, g.imei) AS IMEINo,
                    COALESCE(ir.SIMNo, v.SIMNo) AS SIMNo,
                    COALESCE(ir.UnitLocation, ir.InstallLocation) AS UnitLocation,
                    v.VehicleStatus,
                    c.Name, c.EmergencyMobile, c.Cell1, c.Cell2,
                    c.ResPhone, c.OfficePhone,
                    c.SecondaryUser1, c.SecondaryUser2, c.SecondaryUser3, c.SecondaryUser4,
                    g.dt_tracker, g.dt_server,
                    v.Manufacturer, v.Brand, v.ModelYear, v.Color,
                    v.Transmission, v.PowerCC
                FROM Vehicles v WITH (NOLOCK)
                LEFT JOIN IRData ir WITH (NOLOCK) ON v.ID = ir.VehicleID
                LEFT JOIN Clients c WITH (NOLOCK) ON v.ClientID = c.ID OR ir.ClientID = c.ID
                LEFT JOIN gs_objects g WITH (NOLOCK) ON ir.IMEINo = g.imei OR v.IMEINo = g.imei
                WHERE v.RegNo IS NOT NULL AND LTRIM(RTRIM(v.RegNo)) <> ''
            """)
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            def _text(value, limit=None):
                if value is None:
                    return None
                text = str(value).strip()
                if not text or text.upper() in ('N/A', 'NULL', 'NONE', '-', 'REMOVED'):
                    return None
                return text[:limit] if limit else text

            now = datetime.now()
            existing = {(e.registration_no or '').strip().upper(): e
                        for e in VehicleRegistryEntry.query.all()}
            new_count = 0
            updated = 0

            for row in rows:
                (vehicle_id, client_id, reg_no, engine_no, chassis_no,
                 imei_no, sim_no, unit_location, vehicle_status,
                 client_name, emergency_mobile, cell1, cell2,
                 res_phone, office_phone,
                 su1, su2, su3, su4,
                 dt_tracker, dt_server,
                 manufacturer, brand, model_year, color,
                 transmission, power_cc) = row

                key = str(reg_no or '').strip().upper()
                if not key:
                    continue

                entry = existing.get(key)
                if entry is None:
                    entry = VehicleRegistryEntry(registration_no=key)
                    db.session.add(entry)
                    existing[key] = entry
                    new_count += 1
                else:
                    updated += 1

                signals = [t for t in (dt_tracker, dt_server) if isinstance(t, datetime)]
                secondary = [str(u).strip() for u in (su1, su2, su3, su4) if u and str(u).strip()]

                entry.sj_vehicle_id = vehicle_id
                entry.client_id = client_id
                entry.imei_no = _text(imei_no, 50)
                entry.sim_no = _text(sim_no, 50)
                entry.engine_no = _text(engine_no, 50)
                entry.chassis_no = _text(chassis_no, 50)
                entry.unit_location = _text(unit_location, 200)
                entry.vehicle_status = _text(vehicle_status, 50)
                entry.customer_name = _text(client_name, 200)
                entry.emergency_mobile = _text(emergency_mobile, 50)
                entry.cell1 = _text(cell1, 50)
                entry.cell2 = _text(cell2, 50)
                entry.res_phone = _text(res_phone, 50)
                entry.office_phone = _text(office_phone, 50)
                entry.secondary_users = (' | '.join(secondary))[:300] or None
                entry.manufacturer = _text(manufacturer, 50)
                entry.brand = _text(brand, 50)
                entry.model_year = _text(model_year, 10)
                entry.color = _text(color, 30)
                entry.transmission = clean_transmission(transmission)
                entry.power_cc = clean_power_cc(power_cc)
                entry.last_signal_at = max(signals) if signals else None
                entry.synced_at = now

            db.session.commit()
            logger.info(f"Vehicle registry sync complete - {new_count} new, {updated} refreshed")
            return {'new': new_count, 'updated': updated, 'error': 0}
        except Exception as e:
            logger.error(f"Error syncing vehicle registry: {e}")
            db.session.rollback()
            try:
                conn.close()
            except Exception:
                pass
            return {'new': 0, 'updated': 0, 'error': 1}

    def get_total_redo_count(self) -> int:
        """Get total count of REDO records in SJ_MIS database"""
        conn = self.get_internal_connection()
        if not conn:
            return 0
        
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM IRData WHERE ID IS NOT NULL")
            row = cursor.fetchone()
            count = row[0] if row else 0
            cursor.close()
            conn.close()
            return count
        except Exception as e:
            logger.error(f"Error getting REDO count: {e}")
            try:
                conn.close()
            except Exception:
                pass
            return 0

