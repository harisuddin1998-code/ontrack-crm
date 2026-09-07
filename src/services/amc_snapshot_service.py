# src/services/amc_snapshot_service.py
"""
AMC Snapshot Service - Creates immutable daily snapshots of recovery vehicle data
"""
from typing import Optional, List, Dict, Any
from datetime import date, datetime

from src.models.amc_snapshot import AmcSnapshot
from src.models.annual_recovery import AnnualRecoveryVehicle, AnnualRecoveryClient
from src.extensions import db
from src.utils.logging import get_logger

logger = get_logger(__name__)


class AmcSnapshotService:
    """Service for creating and querying immutable AMC data snapshots"""

    def create_daily_snapshot(self, snapshot_date: Optional[date] = None) -> Dict[str, Any]:
        """
        Create a daily snapshot of all AMC vehicle recovery data.
        Skips if a snapshot for the given date already exists.
        
        Args:
            snapshot_date: Date for the snapshot (defaults to today)
            
        Returns:
            Dict with 'created' count and 'skipped' status
        """
        if snapshot_date is None:
            snapshot_date = date.today()

        # Check if snapshot already exists for this date
        existing = AmcSnapshot.query.filter_by(snapshot_date=snapshot_date).first()
        if existing:
            logger.info(f"AMC snapshot for {snapshot_date} already exists, skipping")
            return {'created': 0, 'skipped': True, 'date': str(snapshot_date)}

        # Fetch all AMC vehicles with their client data
        vehicles = AnnualRecoveryVehicle.query.all()
        created_count = 0

        for vehicle in vehicles:
            client = vehicle.client
            snapshot = AmcSnapshot(
                snapshot_date=snapshot_date,
                vehicle_id=vehicle.id,
                reg_no=vehicle.reg_no or '',
                installation_date=vehicle.installation_date or '',
                installation_year=vehicle.installation_year or '',
                amc_charges=vehicle.amc_charges or 0.0,
                recovered_amount=vehicle.recovered_amount or 0.0,
                outstanding=vehicle.get_outstanding(),
                amc_status=vehicle.status or '',
                client_name=client.name if client else '',
                sheet_name=vehicle.sheet_name or '',
                is_locked=True
            )
            db.session.add(snapshot)
            created_count += 1

        db.session.commit()
        logger.info(f"AMC snapshot created for {snapshot_date}: {created_count} vehicle records")
        return {'created': created_count, 'skipped': False, 'date': str(snapshot_date)}

    def get_snapshot(self, snapshot_date: date) -> List[AmcSnapshot]:
        """Retrieve all snapshot records for a specific date (read-only)"""
        return AmcSnapshot.query.filter_by(snapshot_date=snapshot_date).all()

    def get_snapshot_dates(self) -> List[date]:
        """Get all available snapshot dates"""
        results = db.session.query(
            AmcSnapshot.snapshot_date
        ).distinct().order_by(AmcSnapshot.snapshot_date.desc()).all()
        return [r.snapshot_date for r in results]

    def get_snapshot_summary(self, snapshot_date: date) -> Dict[str, Any]:
        """Get summary statistics for a snapshot date"""
        snapshots = self.get_snapshot(snapshot_date)
        if not snapshots:
            return {'date': str(snapshot_date), 'total_vehicles': 0}

        total_amc = sum(s.amc_charges or 0 for s in snapshots)
        total_recovered = sum(s.recovered_amount or 0 for s in snapshots)
        total_outstanding = sum(s.outstanding or 0 for s in snapshots)

        return {
            'date': str(snapshot_date),
            'total_vehicles': len(snapshots),
            'total_amc_charges': round(total_amc, 2),
            'total_recovered': round(total_recovered, 2),
            'total_outstanding': round(total_outstanding, 2),
            'recovery_rate': round((total_recovered / total_amc * 100), 1) if total_amc > 0 else 0.0
        }
