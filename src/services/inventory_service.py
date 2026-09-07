# src/services/inventory_service.py
"""
Inventory Service - Syncs the device stock (gs_objects) from SJ_MIS and
manages local assignment/installation tracking, plus cross-referencing
against the Installation (PurchaseOrder) and REDO modules by IMEI.
"""
from datetime import date
from typing import Any, Dict, List, Optional

from src.extensions import db
from src.models.inventory import InventoryDevice, InventoryStockItem, TechnicianStockIssuance
from src.services.db_sync_service import DBSyncService
from src.utils.timezone import get_current_time
from src.utils.logging import get_logger

logger = get_logger(__name__)


class InventoryService:
    """Service for inventory device operations."""

    def sync_from_sj_mis(self) -> Dict[str, int]:
        """Pull the device catalog from SJ_MIS's gs_objects table (ID, imei,
        dt_server, dt_tracker, name, sim_number, plate_number, LastUpdate)
        and upsert it into the local InventoryDevice table, keyed by IMEI.
        Devices already tracked locally keep their assignment/install state -
        only the SJ_MIS-sourced fields are refreshed."""
        sync_service = DBSyncService()
        conn = sync_service.get_internal_connection()
        if not conn:
            logger.error("Inventory sync failed: could not connect to SJ_MIS")
            return {'new': 0, 'updated': 0, 'error': 1}

        new_count = 0
        updated_count = 0
        now = get_current_time()

        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT ID, imei, dt_server, dt_tracker, name, sim_number, plate_number, LastUpdate
                FROM gs_objects
                WHERE imei IS NOT NULL AND imei != ''
            """)
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            for row in rows:
                gs_id, imei, dt_server, dt_tracker, name, sim_number, plate_number, last_update = row
                imei = str(imei).strip()
                if not imei:
                    continue

                device = InventoryDevice.query.filter_by(imei=imei).first()
                if device:
                    device.gs_object_id = str(gs_id) if gs_id is not None else device.gs_object_id
                    device.dt_server = dt_server or device.dt_server
                    device.dt_tracker = dt_tracker or device.dt_tracker
                    device.device_name = name or device.device_name
                    device.sim_number = sim_number or device.sim_number
                    device.plate_number = plate_number or device.plate_number
                    device.gs_last_update = last_update or device.gs_last_update
                    device.last_synced_at = now
                    updated_count += 1
                else:
                    device = InventoryDevice(
                        gs_object_id=str(gs_id) if gs_id is not None else None,
                        imei=imei,
                        dt_server=dt_server,
                        dt_tracker=dt_tracker,
                        device_name=name,
                        sim_number=sim_number,
                        plate_number=plate_number,
                        gs_last_update=last_update,
                        last_synced_at=now,
                        status=InventoryDevice.STATUS_IN_STOCK,
                    )
                    db.session.add(device)
                    new_count += 1

            db.session.commit()
            logger.info(f"Inventory sync complete - New: {new_count}, Updated: {updated_count}")
        except Exception as e:
            logger.error(f"Error syncing inventory from SJ_MIS: {e}")
            db.session.rollback()
            try:
                conn.close()
            except Exception:
                pass
            return {'new': new_count, 'updated': updated_count, 'error': 1}

        return {'new': new_count, 'updated': updated_count, 'error': 0}

    def get_technician_devices(self, technician_name: str) -> List[InventoryDevice]:
        """Devices currently issued to (or still in stock for) a technician -
        used to restrict the New Device/IMEI dropdown on the REDO and
        Installation forms to only what that technician actually has on
        hand, rather than the entire inventory catalog."""
        from src.models.technician import Technician

        tech = Technician.query.filter(Technician.name.ilike(technician_name.strip())).first()
        if not tech:
            return []
        return InventoryDevice.query.filter(
            InventoryDevice.assigned_technician_id == tech.id,
            InventoryDevice.status == InventoryDevice.STATUS_ASSIGNED,
        ).order_by(InventoryDevice.imei).all()

    def get_dashboard_stats(self) -> Dict[str, Any]:
        total = InventoryDevice.query.count()
        in_stock = InventoryDevice.query.filter_by(status=InventoryDevice.STATUS_IN_STOCK).count()
        assigned = InventoryDevice.query.filter_by(status=InventoryDevice.STATUS_ASSIGNED).count()
        installed = InventoryDevice.query.filter_by(status=InventoryDevice.STATUS_INSTALLED).count()
        return {
            'total': total,
            'in_stock': in_stock,
            'assigned': assigned,
            'installed': installed,
        }

    def get_linked_records(self, imei: str) -> Dict[str, Any]:
        """Cross-reference a device's IMEI against the Installation
        (PurchaseOrder) and REDO modules, so the inventory list shows exactly
        where a given unit has actually been used."""
        from src.models.purchase_order import PurchaseOrder
        from src.models.redo import RedoActivity

        po = PurchaseOrder.query.filter_by(imei_no=imei).order_by(PurchaseOrder.id.desc()).first()
        redo = RedoActivity.query.filter(
            db.or_(RedoActivity.imei_no == imei, RedoActivity.new_device == imei)
        ).order_by(RedoActivity.id.desc()).first()

        return {
            'installation_po': po,
            'redo_activity': redo,
        }

    def mark_installed_if_known(self, imei: Optional[str], registration_no: Optional[str]) -> None:
        """Called wherever a REDO/Installation record saves an IMEI - if that
        IMEI matches a known inventory device, flip it to INSTALLED so
        inventory status stays in sync with what actually happened in the
        field. No-op (not an error) if the IMEI isn't in local inventory,
        since not every device passes through the local sync."""
        if not imei or not registration_no:
            return
        device = InventoryDevice.query.filter_by(imei=imei.strip()).first()
        if device and device.status != InventoryDevice.STATUS_INSTALLED:
            device.mark_installed(registration_no)

    # ------------------------------------------------------------------
    # Stock & Accessories - non-device consumables (tape, relays, sensors,
    # converters, etc.) and old/legacy stock issue. Entered manually each
    # month rather than synced, since there's no SJ_MIS source for these.
    # ------------------------------------------------------------------

    def get_stock_items(self, period: str) -> List[InventoryStockItem]:
        """All stock items (accessories + old stock) for a given 'YYYY-MM' period."""
        return InventoryStockItem.query.filter_by(period=period).order_by(
            InventoryStockItem.category, InventoryStockItem.name
        ).all()

    def upsert_stock_item(self, name: str, category: str, period: str,
                          total_received: float, total_issued: float,
                          notes: Optional[str] = None) -> InventoryStockItem:
        """Add or update a stock item's figures for a period, keyed by
        (name, category, period) - re-submitting the same item/period just
        corrects the existing entry rather than creating a duplicate row."""
        item = InventoryStockItem.query.filter_by(name=name, category=category, period=period).first()
        if not item:
            item = InventoryStockItem(name=name, category=category, period=period)
            db.session.add(item)
        item.total_received = total_received
        item.total_issued = total_issued
        if notes is not None:
            item.notes = notes
        db.session.commit()
        return item

    def delete_stock_item(self, item_id: int) -> None:
        item = InventoryStockItem.query.get(item_id)
        if item:
            db.session.delete(item)
            db.session.commit()

    def get_technician_issuances(self, issue_date: date) -> Dict[int, TechnicianStockIssuance]:
        """Issuance records for a specific day, keyed by technician_id for
        easy lookup against the live technician roster."""
        rows = TechnicianStockIssuance.query.filter_by(issue_date=issue_date).all()
        return {r.technician_id: r for r in rows}

    def upsert_technician_issuance(self, technician_id: int, issue_date: date,
                                   quantity: float, notes: Optional[str] = None) -> TechnicianStockIssuance:
        """Add or update how many accessory units a technician was issued
        on a given day, keyed by (technician_id, issue_date)."""
        record = TechnicianStockIssuance.query.filter_by(
            technician_id=technician_id, issue_date=issue_date
        ).first()
        if not record:
            record = TechnicianStockIssuance(technician_id=technician_id, issue_date=issue_date)
            db.session.add(record)
        record.quantity = quantity
        if notes is not None:
            record.notes = notes
        db.session.commit()
        return record
