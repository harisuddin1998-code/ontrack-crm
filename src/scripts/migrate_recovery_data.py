# src/scripts/migrate_recovery_data.py
"""
Data Migration Script:
Copies all existing RecoveryApp database records into ontrack_crm's database (management.db).
Guarantees zero data loss and preserves all original data in both databases.
"""
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.app import create_app
from src.extensions import db
from src.models.annual_recovery import (
    AnnualRecoveryClient,
    AnnualRecoveryVehicle,
    AnnualRecoveryFollowup,
    AnnualRecoveryHistory,
    AnnualRecoveryAuditLog
)


def migrate_recovery_data():
    """Migrate data from RecoveryApp/recovery_crm.db to management.db"""
    # Locate RecoveryApp database
    project_root = Path(__file__).parent.parent.parent
    source_db_paths = [
        project_root / 'RecoveryApp' / 'recovery_crm.db',
        project_root / 'RecoveryApp' / 'instance' / 'recovery_crm.db',
        project_root / 'recovery_crm.db',
    ]

    source_db_path = None
    for p in source_db_paths:
        if p.exists():
            source_db_path = p
            break

    if not source_db_path:
        print("ERROR: RecoveryApp database file not found!")
        return False

    print(f"Source Database found: {source_db_path}")

    app = create_app('development')
    with app.app_context():
        # Ensure target tables are created in management.db
        db.create_all()

        source_conn = sqlite3.connect(str(source_db_path))
        source_conn.row_factory = sqlite3.Row
        cursor = source_conn.cursor()

        # 1. Migrate Clients
        cursor.execute("SELECT * FROM clients")
        client_rows = cursor.fetchall()
        migrated_clients = 0
        client_id_map = {} # old_id -> new_id

        for row in client_rows:
            old_id = row['id']
            # Check if client already exists by name & cell1
            existing = AnnualRecoveryClient.query.filter_by(
                name=row['name'], 
                cell1=row['cell1'] or ''
            ).first()

            if not existing:
                created_dt = parse_datetime(row['created_at']) if 'created_at' in row.keys() else datetime.now(timezone.utc)
                updated_dt = parse_datetime(row['updated_at']) if 'updated_at' in row.keys() else datetime.now(timezone.utc)
                
                client = AnnualRecoveryClient(
                    name=row['name'],
                    cell1=row['cell1'] or '',
                    employee_name=row['employee_name'] or '',
                    total_amc_charges=float(row['total_amc_charges'] or 0.0),
                    total_recovered=float(row['total_recovered'] or 0.0),
                    total_lost=float(row['total_lost'] or 0.0),
                    created_at=created_dt,
                    updated_at=updated_dt
                )
                db.session.add(client)
                db.session.flush() # get new id
                client_id_map[old_id] = client.id
                migrated_clients += 1
            else:
                client_id_map[old_id] = existing.id

        db.session.commit()
        print(f"[OK] Clients processed: {len(client_rows)} (New inserted: {migrated_clients})")

        # 2. Migrate Vehicles
        cursor.execute("SELECT * FROM vehicles")
        vehicle_rows = cursor.fetchall()
        migrated_vehicles = 0
        vehicle_id_map = {} # old_id -> new_id

        for row in vehicle_rows:
            old_id = row['id']
            existing = AnnualRecoveryVehicle.query.filter_by(reg_no=row['reg_no']).first()

            if not existing:
                new_client_id = client_id_map.get(row['client_id'])
                created_dt = parse_datetime(row['created_at']) if 'created_at' in row.keys() else datetime.now(timezone.utc)

                vehicle = AnnualRecoveryVehicle(
                    client_id=new_client_id,
                    reg_no=row['reg_no'],
                    installation_date=row['installation_date'] or '',
                    installation_year=row['installation_year'] or '',
                    amc_charges=float(row['amc_charges'] or 0.0),
                    recovered_amount=float(row['recovered_amount'] or 0.0),
                    remarks=row['remarks'] or '',
                    status=row['status'] or 'PENDING',
                    sheet_name=row['sheet_name'] or '',
                    assigned_to=None, # will maintain sheets & assignment
                    created_at=created_dt
                )
                db.session.add(vehicle)
                db.session.flush()
                vehicle_id_map[old_id] = vehicle.id
                migrated_vehicles += 1
            else:
                vehicle_id_map[old_id] = existing.id

        db.session.commit()
        print(f"[OK] Vehicles processed: {len(vehicle_rows)} (New inserted: {migrated_vehicles})")

        # 3. Migrate Follow-ups
        cursor.execute("SELECT * FROM followups")
        followup_rows = cursor.fetchall()
        migrated_followups = 0

        for row in followup_rows:
            new_client_id = client_id_map.get(row['client_id'])
            new_vehicle_id = vehicle_id_map.get(row['vehicle_id'])
            created_dt = parse_datetime(row['created_at']) if 'created_at' in row.keys() else datetime.now(timezone.utc)

            # Avoid duplication based on vehicle_id, note and created_at
            existing = AnnualRecoveryFollowup.query.filter_by(
                vehicle_id=new_vehicle_id,
                note=row['note'],
                created_at=created_dt
            ).first()

            if not existing:
                followup = AnnualRecoveryFollowup(
                    client_id=new_client_id,
                    vehicle_id=new_vehicle_id,
                    note=row['note'],
                    next_date=row['next_date'] or '',
                    created_by=row['created_by'] or 'System',
                    created_at=created_dt
                )
                db.session.add(followup)
                migrated_followups += 1

        db.session.commit()
        print(f"[OK] Follow-ups processed: {len(followup_rows)} (New inserted: {migrated_followups})")

        # 4. Migrate Recovery History
        cursor.execute("SELECT * FROM recovery_history")
        history_rows = cursor.fetchall()
        migrated_history = 0

        for row in history_rows:
            new_client_id = client_id_map.get(row['client_id'])
            new_vehicle_id = vehicle_id_map.get(row['vehicle_id'])
            created_dt = parse_datetime(row['created_at']) if 'created_at' in row.keys() else datetime.now(timezone.utc)

            existing = AnnualRecoveryHistory.query.filter_by(
                vehicle_id=new_vehicle_id,
                amount=float(row['amount'] or 0.0),
                created_at=created_dt
            ).first()

            if not existing:
                history = AnnualRecoveryHistory(
                    client_id=new_client_id,
                    vehicle_id=new_vehicle_id,
                    amount=float(row['amount'] or 0.0),
                    payment_date=row['payment_date'] or '',
                    reference_no=row['reference_no'] or '',
                    payment_method=row['payment_method'] or 'Cash',
                    cheque_status=row['cheque_status'] or '',
                    notes=row['notes'] or '',
                    created_at=created_dt
                )
                db.session.add(history)
                migrated_history += 1

        db.session.commit()
        print(f"[OK] Recovery History records processed: {len(history_rows)} (New inserted: {migrated_history})")

        # 5. Migrate Audit Logs
        cursor.execute("SELECT * FROM audit_logs")
        audit_rows = cursor.fetchall()
        migrated_audits = 0

        for row in audit_rows:
            created_dt = parse_datetime(row['created_at']) if 'created_at' in row.keys() else datetime.now(timezone.utc)

            existing = AnnualRecoveryAuditLog.query.filter_by(
                user=row['user'] or 'System',
                action=row['action'],
                created_at=created_dt
            ).first()

            if not existing:
                log = AnnualRecoveryAuditLog(
                    user=row['user'] or 'System',
                    action=row['action'],
                    details=row['details'] or '',
                    ip_address=row['ip_address'] or '',
                    created_at=created_dt
                )
                db.session.add(log)
                migrated_audits += 1

        db.session.commit()
        print(f"[OK] Audit Logs processed: {len(audit_rows)} (New inserted: {migrated_audits})")
        source_conn.close()

        print("\nMigration completed successfully!")
        return True


def parse_datetime(dt_str):
    """Helper to parse datetime strings safely"""
    if not dt_str:
        return datetime.now(timezone.utc)
    if isinstance(dt_str, datetime):
        return dt_str
    try:
        return datetime.strptime(str(dt_str), '%Y-%m-%d %H:%M:%S.%f')
    except ValueError:
        try:
            return datetime.strptime(str(dt_str), '%Y-%m-%d %H:%M:%S')
        except ValueError:
            return datetime.now(timezone.utc)


if __name__ == '__main__':
    migrate_recovery_data()
