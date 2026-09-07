# src/services/vehicle_search_service.py
"""
Vehicle Search Service - Cross-source vehicle & customer lookup.

Searches by registration number, phone/cell number, IMEI, SIM, chassis or
engine number across every vehicle data source in the system - reporting AND
non-reporting vehicles alike, including the local dump of SJ_MIS's master
roster, so every vehicle is findable whether or not SJ_MIS is reachable.
Used by the complaint logging search box and the REDO vehicle auto-pull.
"""
import queue
import re
import threading
from itertools import zip_longest
from typing import Any, Dict, List, Optional

from sqlalchemy import or_, func

from src.models.gps import NonReportingVehicle, CurrentLocation
from src.models.redo import RedoActivity
from src.models.purchase_order import PurchaseOrder
from src.models.annual_recovery import AnnualRecoveryVehicle, AnnualRecoveryClient
from src.models.vehicle_registry import VehicleRegistryEntry
from src.utils.logging import get_logger

logger = get_logger(__name__)

SEARCH_RESULT_LIMIT = 20
PER_SOURCE_CANDIDATE_LIMIT = 15
_PHONE_SEPARATORS = (' ', '-', '+', '(', ')')

# SJ_MIS live search is a bonus on top of the local cache, never a hard
# dependency - a slow/unreachable SJ_MIS server (DNS/TCP timeouts across
# several ODBC drivers) can otherwise block a single search for minutes.
# This bounds it to a few seconds so the Complaint form's live search stays
# responsive; local results are returned regardless of what SJ_MIS does.
_SJ_MIS_LIVE_SEARCH_TIMEOUT_SECONDS = 3


def _clean(val: Optional[str]) -> str:
    if not val:
        return ''
    s = str(val).strip()
    return '' if s.upper() in ('N/A', 'NULL', 'NONE', '-', '') else s


def _strip_separators(value: str) -> str:
    return re.sub(r'[\s\-+()]', '', value or '')


def _stripped_column(column):
    """SQL expression that strips common phone separators from a column so
    differently formatted numbers (0300-1234567 vs 03001234567) can still
    match, without pulling rows into Python to compare."""
    expr = column
    for sep in _PHONE_SEPARATORS:
        expr = func.replace(expr, sep, '')
    return expr


class VehicleSearchService:
    """Cross-source vehicle & customer search - reg no, phone, IMEI, or SIM,
    across reporting and non-reporting vehicles alike."""

    def _match_conditions(self, raw_q: str, stripped_q: str, exact_cols: List, phone_cols: List) -> List:
        conds = [col.ilike(f"%{raw_q}%") for col in exact_cols]
        for col in phone_cols:
            conds.append(col.ilike(f"%{raw_q}%"))
            if stripped_q:
                conds.append(_stripped_column(col).ilike(f"%{stripped_q}%"))
        return conds

    def find_candidate_reg_nos(self, query: str, limit: int = PER_SOURCE_CANDIDATE_LIMIT) -> List[str]:
        """Lean, DB-level search across every vehicle/customer source.
        Returns unique registration numbers matching `query` against reg no,
        phone/contact numbers, IMEI, or SIM - case insensitive, regardless
        of current GPS reporting status.

        Results are interleaved round-robin across sources rather than
        concatenated-then-truncated: NonReportingVehicle alone can have
        thousands of rows versus a couple hundred reporting vehicles
        elsewhere, so a naive concatenation would let it fill the entire
        result quota before a reporting vehicle is ever considered. A
        complaint can be lodged against a vehicle in either state, so a
        broad query needs a fair mix of both, not whichever table is bigger.
        """
        q = (query or '').strip()
        if not q:
            return []
        stripped_q = _strip_separators(q) if re.search(r'\d', q) else ''

        nr_conds = self._match_conditions(
            q, stripped_q,
            exact_cols=[NonReportingVehicle.registration_no, NonReportingVehicle.imei_no, NonReportingVehicle.sim_no],
            phone_cols=[
                NonReportingVehicle.customer_contact, NonReportingVehicle.emergency_mobile,
                NonReportingVehicle.customer_phone2, NonReportingVehicle.customer_phone3,
                NonReportingVehicle.res_phone, NonReportingVehicle.office_phone,
            ]
        )
        nr_matches = [
            v.registration_no for v in
            NonReportingVehicle.query.filter(or_(*nr_conds)).order_by(NonReportingVehicle.id.desc()).limit(limit).all()
        ]

        redo_conds = self._match_conditions(
            q, stripped_q,
            exact_cols=[RedoActivity.registration_no, RedoActivity.imei_no, RedoActivity.sim_no],
            phone_cols=[RedoActivity.customer_contact]
        )
        redo_matches = [
            r.registration_no for r in
            RedoActivity.query.filter(or_(*redo_conds)).order_by(RedoActivity.id.desc()).limit(limit).all()
        ]

        po_conds = self._match_conditions(
            q, stripped_q,
            exact_cols=[PurchaseOrder.reg_no, PurchaseOrder.imei_no, PurchaseOrder.sim_no],
            phone_cols=[PurchaseOrder.owner_contact]
        )
        po_matches = [
            p.reg_no for p in
            PurchaseOrder.query.filter(or_(*po_conds)).order_by(PurchaseOrder.id.desc()).limit(limit).all()
        ]

        # Annual Recovery roster - the AMC client/vehicle registry. This is
        # often the ONLY local record of a vehicle that is currently
        # reporting fine (never went stale, so it never entered
        # NonReportingVehicle, and may have no install/service record either)
        # - without it, a customer whose device works perfectly could never
        # be found here even though they can still lodge a complaint.
        rec_conds = self._match_conditions(
            q, stripped_q,
            exact_cols=[AnnualRecoveryVehicle.reg_no],
            phone_cols=[AnnualRecoveryClient.cell1]
        )
        rec_matches = [
            rv.reg_no for rv in
            AnnualRecoveryVehicle.query
            .join(AnnualRecoveryClient, AnnualRecoveryVehicle.client_id == AnnualRecoveryClient.id)
            .filter(or_(*rec_conds))
            .order_by(AnnualRecoveryVehicle.id.desc())
            .limit(limit)
            .all()
        ]

        # The local dump of SJ_MIS's master roster. Every other source above
        # holds only a slice of the fleet - vehicles that went offline, that
        # this CRM installed, that have been serviced, that are on the AMC
        # books. A vehicle whose device has simply worked since before this
        # CRM existed is in none of them, and used to be findable only while
        # SJ_MIS itself was reachable.
        reg_conds = self._match_conditions(
            q, stripped_q,
            exact_cols=[VehicleRegistryEntry.registration_no, VehicleRegistryEntry.imei_no,
                        VehicleRegistryEntry.sim_no, VehicleRegistryEntry.chassis_no,
                        VehicleRegistryEntry.engine_no],
            phone_cols=[VehicleRegistryEntry.emergency_mobile, VehicleRegistryEntry.cell1,
                        VehicleRegistryEntry.cell2, VehicleRegistryEntry.res_phone,
                        VehicleRegistryEntry.office_phone, VehicleRegistryEntry.secondary_users]
        )
        registry_matches = [
            e.registration_no for e in
            VehicleRegistryEntry.query.filter(or_(*reg_conds))
            .order_by(VehicleRegistryEntry.id.desc()).limit(limit).all()
        ]

        reg_nos: List[str] = []
        seen = set()
        for row in zip_longest(nr_matches, redo_matches, po_matches, rec_matches, registry_matches):
            for reg_no in row:
                if reg_no is None:
                    continue
                key = reg_no.strip().upper()
                if key and key not in seen:
                    seen.add(key)
                    reg_nos.append(key)
            if len(reg_nos) >= SEARCH_RESULT_LIMIT:
                break

        return reg_nos[:SEARCH_RESULT_LIMIT]

    def _fetch_sources(self, reg_no: str):
        nr_v = NonReportingVehicle.query.filter(NonReportingVehicle.registration_no.ilike(reg_no)).first()
        redo_v = RedoActivity.query.filter(RedoActivity.registration_no.ilike(reg_no)).order_by(RedoActivity.id.desc()).first()
        po_v = PurchaseOrder.query.filter(PurchaseOrder.reg_no.ilike(reg_no)).order_by(PurchaseOrder.id.desc()).first()
        rec_v = AnnualRecoveryVehicle.query.filter(AnnualRecoveryVehicle.reg_no.ilike(reg_no)).order_by(AnnualRecoveryVehicle.id.desc()).first()
        reg_v = VehicleRegistryEntry.query.filter(VehicleRegistryEntry.registration_no.ilike(reg_no)).first()
        return nr_v, redo_v, po_v, rec_v, reg_v

    def build_record(self, reg_no: str, nr_v=None, redo_v=None, po_v=None, rec_v=None,
                     reg_v=None) -> Optional[Dict[str, Any]]:
        """Merge NonReportingVehicle / RedoActivity / PurchaseOrder / the
        Annual Recovery client roster into one record. PurchaseOrder/
        RedoActivity hold real, staff-entered data (chosen at install time or
        updated at the latest service visit) and win over NonReportingVehicle
        for static attributes - that table is just an auto-synced
        offline-monitoring cache. AnnualRecoveryVehicle/Client is the AMC
        billing roster - it has no vehicle spec data, but it's often the
        ONLY local record of a customer whose vehicle is currently reporting
        fine (so it never appears in NonReportingVehicle, PurchaseOrder, or
        RedoActivity) - a complaint can be lodged by that customer too.
        VehicleRegistryEntry is the local dump of SJ_MIS's master roster and
        is read last of all: it is a machine copy, so it fills in what nobody
        has typed rather than overriding what somebody has."""
        if nr_v is None and redo_v is None and po_v is None and rec_v is None and reg_v is None:
            nr_v, redo_v, po_v, rec_v, reg_v = self._fetch_sources(reg_no)
        if not (nr_v or redo_v or po_v or rec_v or reg_v):
            return None

        rec_client = rec_v.client if rec_v else None

        imei_no = ((nr_v and nr_v.imei_no) or (redo_v and redo_v.imei_no)
                   or (po_v and po_v.imei_no) or (reg_v and reg_v.imei_no) or '')

        is_reporting = nr_v is None
        reporting_status = 'REPORTING' if is_reporting else f'NOT REPORTING ({nr_v.get_aging_bucket()} offline)'
        if imei_no:
            current_loc = CurrentLocation.query.filter_by(device_imei=imei_no).first()
            if current_loc and current_loc.is_active(minutes=24 * 60):
                is_reporting = True
                reporting_status = 'REPORTING (live signal confirmed)'

        last_service_by = 'N/A'
        if redo_v and (redo_v.technician or redo_v.assigned_to_user):
            last_service_by = f"{redo_v.technician or redo_v.assigned_to_user.name} on {redo_v.created_at.strftime('%d/%m/%Y')} (Status: {redo_v.status})"
        elif po_v and po_v.technician_assigned:
            last_service_by = f"Installer {po_v.technician_assigned} on {po_v.created_at.strftime('%d/%m/%Y')}"
        elif nr_v and nr_v.assigned_technician:
            last_service_by = f"{nr_v.assigned_technician.name} (Assigned)"
        elif rec_v and rec_v.status:
            last_service_by = f"AMC: {rec_v.status.upper()} ({rec_v.installation_date or 'install date unknown'})"
        elif reg_v:
            last_service_by = 'No service recorded (SJ_MIS roster)'

        po_sales_user = po_v.sales_person if po_v else None
        sale_person = (
            _clean(po_sales_user and (po_sales_user.name or po_sales_user.username))
            or _clean(po_v and po_v.arranged_by_sales_person)
            or _clean(redo_v and redo_v.sale_person)
        )

        return {
            'registration_no': (nr_v and nr_v.registration_no) or (redo_v and redo_v.registration_no) or (po_v and po_v.reg_no) or (rec_v and rec_v.reg_no) or (reg_v and reg_v.registration_no) or reg_no,
            'customer_name': _clean(nr_v and nr_v.customer_name) or _clean(redo_v and redo_v.customer_name) or _clean(po_v and po_v.owner_name) or _clean(rec_client and rec_client.name) or _clean(reg_v and reg_v.customer_name),
            'customer_contact': _clean(nr_v and (nr_v.emergency_mobile or nr_v.customer_contact)) or _clean(redo_v and redo_v.customer_contact) or _clean(po_v and po_v.owner_contact) or _clean(rec_client and rec_client.cell1) or _clean(reg_v and (reg_v.emergency_mobile or reg_v.cell1)),
            # Manufacturer, Brand and Model Year are what SJ_MIS calls them
            # and what the business says: the marque, the vehicle, and the
            # year - "model" meaning the year in conversation here. The
            # columns underneath still carry their original names; only the
            # vocabulary the application speaks has changed.
            'manufacturer': _clean(po_v and po_v.vehicle_make) or _clean(redo_v and redo_v.make) or _clean(nr_v and nr_v.make) or _clean(reg_v and reg_v.manufacturer),
            'brand': _clean(po_v and po_v.vehicle_model) or _clean(redo_v and redo_v.model) or _clean(nr_v and nr_v.model) or _clean(reg_v and reg_v.brand),
            'model_year': _clean(po_v and po_v.vehicle_year) or _clean(redo_v and redo_v.year) or _clean(nr_v and nr_v.vehicle_year) or _clean(reg_v and reg_v.model_year),
            'color': _clean(po_v and po_v.vehicle_color) or _clean(redo_v and redo_v.color) or _clean(nr_v and nr_v.vehicle_color) or _clean(reg_v and reg_v.color),
            # Recorded on the order where we handled the vehicle; otherwise
            # whatever SJ_MIS holds, which for most of the fleet is nothing.
            'transmission': _clean(po_v and po_v.transmission) or _clean(reg_v and reg_v.transmission),
            'power_cc': _clean(po_v and po_v.power_cc) or _clean(reg_v and reg_v.power_cc),
            'chassis_no': _clean(po_v and po_v.chassis_number) or _clean(redo_v and redo_v.chassis_no) or _clean(nr_v and nr_v.chassis_no) or _clean(reg_v and reg_v.chassis_no),
            'engine_no': _clean(po_v and po_v.engine_number) or _clean(redo_v and redo_v.engine_no) or _clean(nr_v and nr_v.engine_no) or _clean(reg_v and reg_v.engine_no),
            'imei_no': imei_no,
            'sim_no': (nr_v and nr_v.sim_no) or (redo_v and redo_v.sim_no) or (po_v and po_v.sim_no) or (reg_v and reg_v.sim_no) or '',
            # Unit location (e.g. "Behind Meter", "Under Dashboard") - prefer the
            # technician-entered installation/service record over the sync
            # cache's UnitLocation, which has been seen to hold unrelated data.
            'unit_location': _clean(redo_v and redo_v.device_location) or _clean(po_v and po_v.device_location) or _clean(nr_v and (nr_v.unit_location or nr_v.device_location)) or _clean(reg_v and reg_v.unit_location),
            'city': _clean(po_v and po_v.city) or _clean(redo_v and redo_v.city) or _clean(nr_v and nr_v.city),
            # The salesperson belongs to the Purchase Order that sold the
            # vehicle - it is not a REDO attribute, and it must not be typed
            # by hand on a service form. The PO's assigned user is the
            # authority; `arranged_by_sales_person` is the free-text name
            # carried on imported/bulk-updated POs, and the last REDO's copy
            # is the final fallback for a vehicle with no PO on record.
            'sale_person': sale_person,
            # The PO this vehicle came from, so a service record can be read
            # back to the order that created it.
            'po_id': po_v.id if po_v else None,
            'po_number': _clean(po_v and po_v.po_number),
            'is_reporting': is_reporting,
            'reporting_status': reporting_status,
            'last_service_by': last_service_by,
        }

    def _search_sj_mis_live_bounded(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """Run DBSyncService.search_vehicles_live() with a hard wall-clock
        timeout - pyodbc has no built-in cancellation, and a stuck DNS/TCP
        connection attempt can hold the GIL for minutes, so we run it on a
        daemon thread and simply stop waiting past the timeout rather than
        awaiting it indefinitely. The abandoned thread cannot be killed, but
        being a daemon thread it will never block process shutdown, and it
        eventually dies on its own once the OS-level attempt gives up. Never
        raises; returns [] on timeout or error."""
        from src.services.db_sync_service import DBSyncService

        result_queue: queue.Queue = queue.Queue(maxsize=1)

        def _worker():
            try:
                result_queue.put(DBSyncService().search_vehicles_live(query, limit))
            except Exception as e:
                logger.warning(f"SJ_MIS live vehicle search failed: {e}")
                result_queue.put([])

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        try:
            return result_queue.get(timeout=_SJ_MIS_LIVE_SEARCH_TIMEOUT_SECONDS)
        except queue.Empty:
            logger.warning(f"SJ_MIS live vehicle search timed out after {_SJ_MIS_LIVE_SEARCH_TIMEOUT_SECONDS}s")
            return []

    def search(self, query: str, limit: int = SEARCH_RESULT_LIMIT) -> List[Dict[str, Any]]:
        """Multi-field live search - returns merged vehicle/customer records
        for every match, reporting or not reporting.

        Everything is answered from local tables, including
        `vehicle_registry`, the nightly dump of SJ_MIS's master roster: that
        is what makes every vehicle findable without the search depending on
        a remote server answering while somebody is typing.

        The live SJ_MIS query remains only for the case where that dump has
        never been taken - a fresh installation, before the first sync - so
        the form is useful on day one rather than empty."""
        results = []
        seen_reg_nos = set()
        for reg_no in self.find_candidate_reg_nos(query, limit=limit):
            record = self.build_record(reg_no)
            if record:
                results.append(record)
                seen_reg_nos.add(reg_no.strip().upper())

        # The live SJ_MIS probe is the fallback for a fleet this CRM has no
        # local copy of. Once the master roster has been dumped into
        # `vehicle_registry` that copy exists, and paying three seconds per
        # search to ask SJ_MIS the same question again is a stall on every
        # narrow search - a registration number matches one vehicle, which is
        # under the limit, which used to trigger the probe every time.
        if len(results) < limit and VehicleRegistryEntry.query.first() is None:
            live_vehicles = self._search_sj_mis_live_bounded(query, limit)

            for v in live_vehicles:
                reg_no = (v.get('registration_no') or '').strip().upper()
                if not reg_no or reg_no in seen_reg_nos:
                    continue
                seen_reg_nos.add(reg_no)
                results.append({
                    'registration_no': reg_no,
                    'customer_name': v.get('customer_name', ''),
                    'customer_contact': v.get('customer_contact', ''),
                    'make': '',
                    'model': '',
                    'year': '',
                    'color': '',
                    'chassis_no': v.get('chassis_no', ''),
                    'engine_no': v.get('engine_no', ''),
                    'imei_no': v.get('imei_no', ''),
                    'sim_no': v.get('sim_no', ''),
                    'unit_location': v.get('unit_location', ''),
                    'city': '',
                    'is_reporting': v.get('is_reporting', False),
                    'reporting_status': v.get('reporting_status', ''),
                    'last_service_by': 'N/A',
                })
                if len(results) >= limit:
                    break

        return results

    def lookup_by_reg_no(self, reg_no: str) -> Optional[Dict[str, Any]]:
        reg_no = (reg_no or '').strip().upper()
        if not reg_no:
            return None
        nr_v = NonReportingVehicle.query.filter(NonReportingVehicle.registration_no.ilike(f"%{reg_no}%")).first()
        redo_v = RedoActivity.query.filter(RedoActivity.registration_no.ilike(f"%{reg_no}%")).order_by(RedoActivity.id.desc()).first()
        po_v = PurchaseOrder.query.filter(PurchaseOrder.reg_no.ilike(f"%{reg_no}%")).order_by(PurchaseOrder.id.desc()).first()
        rec_v = AnnualRecoveryVehicle.query.filter(AnnualRecoveryVehicle.reg_no.ilike(f"%{reg_no}%")).order_by(AnnualRecoveryVehicle.id.desc()).first()
        reg_v = VehicleRegistryEntry.query.filter(VehicleRegistryEntry.registration_no.ilike(f"%{reg_no}%")).first()
        resolved_reg_no = (nr_v and nr_v.registration_no) or (redo_v and redo_v.registration_no) or (po_v and po_v.reg_no) or (rec_v and rec_v.reg_no) or (reg_v and reg_v.registration_no) or reg_no
        return self.build_record(resolved_reg_no, nr_v, redo_v, po_v, rec_v, reg_v)

    def lookup_by_contact(self, contact: str) -> Optional[Dict[str, Any]]:
        candidates = self.find_candidate_reg_nos(contact, limit=1)
        if not candidates:
            return None
        return self.build_record(candidates[0])
