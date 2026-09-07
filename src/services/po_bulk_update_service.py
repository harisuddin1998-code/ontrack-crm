# src/services/po_bulk_update_service.py
"""
Bulk update of Purchase Orders from a Text, Excel or Word file.

The shape of the job is always the same whatever the file type: a table with
a header row, one column identifying which PO a row is about, and the rest
being fields to write. So the three readers below do one thing each - turn a
file into `(headers, rows)` - and everything after that (matching, validation,
applying) is shared. Adding a fourth format means adding a reader, nothing
else.

Two rules run through the whole module:

  * **Nothing is written until it has been checked.** `prepare()` reads,
    matches and validates without touching the database, and returns exactly
    what `apply()` will do. The user sees that plan and approves it. A file
    that is half-valid does not get half-applied by accident.
  * **A blank cell means "leave it alone", not "erase it".** Spreadsheets are
    full of empty cells that nobody meant as an instruction. Only a cell with
    a value in it can change a field, and only if the value is different from
    what is already stored.

Word files are read with the standard library (a .docx is a zip of XML)
rather than a parsing dependency - it is a dozen lines, and it means the
feature cannot break on a library that is missing from a deployment.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.etree import ElementTree

from src.models.purchase_order import PurchaseOrder
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Rows above this and the file is almost certainly not a hand-prepared update
# sheet. The cap keeps one bad upload from holding a worker for minutes.
MAX_ROWS = 2000

WORD_NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


class BulkUpdateError(Exception):
    """The file could not be read at all - wrong type, corrupt, or empty."""


# ----------------------------------------------------------------------
# Column vocabulary
# ----------------------------------------------------------------------

def _canon(header: str) -> str:
    """Reduce a header to letters and digits, lowercased.

    People write "PO Number", "po_no", "PO #" and "PO-NUMBER" for the same
    column. Matching on the canonical form means the vocabulary below stays
    short instead of listing every punctuation variant anyone might type.
    """
    return re.sub(r'[^a-z0-9]', '', (header or '').strip().lower())


# Which PO a row is about. PO number is exact; registration is a fallback for
# sheets that come from the field, where the reg is what people have.
KEY_COLUMNS: Dict[str, str] = {
    'ponumber': 'po_number', 'pono': 'po_number', 'po': 'po_number',
    'ponum': 'po_number', 'purchaseorder': 'po_number',
    'purchaseordernumber': 'po_number', 'poid': 'po_number',
    'regno': 'reg_no', 'registration': 'reg_no', 'registrationno': 'reg_no',
    'registrationnumber': 'reg_no', 'vehicleno': 'reg_no', 'vehiclenumber': 'reg_no',
}

# Fields a bulk sheet is allowed to write. Deliberately excludes po_number,
# status history, money already recovered, and the audit columns: a PO's
# identity and its financial history are not things a spreadsheet gets to
# rewrite in bulk.
#
# Every column an installation update sheet carries is here - Customer Name,
# Contact Number, Driver Contact, Registration Number (as the key), Vehicle
# Make and Model, Sales Person, Vehicle / Installation Location, Existing
# Customer Name, Existing Vehicle Number, Rates and AMC - but none of them is
# required. A sheet is read for whichever of these columns it happens to
# carry; the ones it leaves out are simply not written, because a field
# nobody stated is not a field anybody asked to change.
FIELD_COLUMNS: Dict[str, str] = {
    'status': 'status',
    'technician': 'technician_assigned', 'technicianassigned': 'technician_assigned',
    'assignedtechnician': 'technician_assigned',
    'imei': 'imei_no', 'imeino': 'imei_no', 'imeinumber': 'imei_no',
    'sim': 'sim_no', 'simno': 'sim_no', 'simnumber': 'sim_no',
    'devicetype': 'device_type',
    'devicelocation': 'device_location',
    'scheduleddate': 'scheduled_date', 'installationdate': 'scheduled_date',
    'city': 'city',
    'remarks': 'remarks', 'notes': 'remarks', 'comments': 'remarks',
    'rates': 'rates', 'rate': 'rates', 'amount': 'rates',
    'amc': 'amc', 'amccharges': 'amc',
    # Manufacturer / Brand / Year-Model is what the application now calls
    # these. The older spellings stay: a spreadsheet somebody built last
    # month still has "Make" at the top of a column, and refusing to read it
    # would be a rename that costs the user their file.
    'manufacturer': 'vehicle_make',
    'make': 'vehicle_make', 'vehiclemake': 'vehicle_make',
    'brand': 'vehicle_model',
    'model': 'vehicle_model', 'vehiclemodel': 'vehicle_model',
    'yearmodel': 'vehicle_year', 'modelyear': 'vehicle_year',
    'year': 'vehicle_year', 'vehicleyear': 'vehicle_year',
    'colour': 'vehicle_color', 'color': 'vehicle_color',
    'vehiclecolour': 'vehicle_color', 'vehiclecolor': 'vehicle_color',
    'transmission': 'transmission',
    'powercc': 'power_cc', 'power': 'power_cc', 'cc': 'power_cc',
    'enginecapacity': 'power_cc',
    'engineno': 'engine_number', 'enginenumber': 'engine_number',
    'chassisno': 'chassis_number', 'chassisnumber': 'chassis_number',
    'ownername': 'owner_name', 'customername': 'owner_name', 'customer': 'owner_name',
    'ownercontact': 'owner_contact', 'contact': 'owner_contact',
    'contactnumber': 'owner_contact', 'contactno': 'owner_contact',
    'customercontact': 'owner_contact', 'customernumber': 'owner_contact',
    'phone': 'owner_contact',
    'driver': 'contact_person_driver', 'contactperson': 'contact_person_driver',
    'contactpersondriver': 'contact_person_driver',
    'drivercontact': 'contact_person_driver', 'drivernumber': 'contact_person_driver',
    'testedby': 'tested_by',
    'fuel': 'fuel',
    'salesperson': 'sales_person_id', 'salespersonname': 'sales_person_id',
    'sales': 'sales_person_id',
    'arrangedby': 'arranged_by_sales_person',
    'arrangedbysalesperson': 'arranged_by_sales_person',
    'location': 'vehicle_availability_location',
    'vehiclelocation': 'vehicle_availability_location',
    'installationlocation': 'vehicle_availability_location',
    'vehicleinstallationlocation': 'vehicle_availability_location',
    'availabilitylocation': 'vehicle_availability_location',
    'existingcustomer': 'existing_customer_name',
    'existingcustomername': 'existing_customer_name',
    'existingvehicle': 'existing_vehicle_number',
    'existingvehicleno': 'existing_vehicle_number',
    'existingvehiclenumber': 'existing_vehicle_number',
    'existingregistrationno': 'existing_vehicle_number',
    'existingregistrationnumber': 'existing_vehicle_number',
}

VALID_STATUSES = ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')

# A PO whose status leaves work outstanding is the installation team's to do.
# Used after a bulk apply to route the updated orders to them.
OPEN_STATUSES = ('PENDING', 'IN_PROGRESS')

NUMERIC_FIELDS = {'rates', 'amc'}
DATE_FIELDS = {'scheduled_date'}
# Columns holding a person's name in the sheet but a foreign key in the
# database. Resolved against the user list rather than written through.
REFERENCE_FIELDS = {'sales_person_id'}


# ----------------------------------------------------------------------
# Readers - file bytes to (headers, rows)
# ----------------------------------------------------------------------

def _read_delimited(data: bytes) -> Tuple[List[str], List[List[str]]]:
    """Text/CSV. The delimiter is whatever the file actually uses.

    These sheets get pasted out of email and out of Excel, so they arrive
    comma-, tab-, semicolon- or pipe-separated depending on where they came
    from. Sniffing beats making the user tell us.
    """
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = data.decode('latin-1')

    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=',\t;|')
        delimiter = dialect.delimiter
    except csv.Error:
        # A single-column file gives the sniffer nothing to go on; a comma
        # reader handles that case correctly anyway.
        delimiter = ','

    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delimiter)
            if any((c or '').strip() for c in r)]
    if not rows:
        raise BulkUpdateError('The file has no rows.')
    return [str(c) for c in rows[0]], [[str(c) for c in r] for r in rows[1:]]


def _read_excel(data: bytes) -> Tuple[List[str], List[List[str]]]:
    """Excel. First worksheet, first non-empty row is the header."""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - openpyxl is a hard dep
        raise BulkUpdateError('Excel support is unavailable on this server.') from exc

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise BulkUpdateError(f'This file could not be opened as a workbook: {exc}') from exc

    ws = wb[wb.sheetnames[0]]
    rows: List[List[str]] = []
    for raw in ws.iter_rows(values_only=True):
        cells = ['' if c is None else _cell_to_text(c) for c in raw]
        if any(c.strip() for c in cells):
            rows.append(cells)
        if len(rows) > MAX_ROWS + 1:
            break
    wb.close()

    if not rows:
        raise BulkUpdateError('The workbook has no rows.')
    return rows[0], rows[1:]


def _read_word(data: bytes) -> Tuple[List[str], List[List[str]]]:
    """Word. A table if the document has one, otherwise delimited lines.

    A .docx is a zip containing word/document.xml, so this needs no third
    party library. Tables are preferred because that is how anyone actually
    lays out an update sheet in Word; the plain-text fallback covers a
    document that is just lines of "PO-1234 | COMPLETED".
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml = zf.read('word/document.xml')
    except (zipfile.BadZipFile, KeyError) as exc:
        raise BulkUpdateError(
            'This does not look like a .docx file. Save it as Word (.docx), '
            'not the older .doc format.') from exc

    root = ElementTree.fromstring(xml)

    def cell_text(node) -> str:
        return ''.join(t.text or '' for t in node.iter(f'{WORD_NS}t')).strip()

    for table in root.iter(f'{WORD_NS}tbl'):
        rows: List[List[str]] = []
        for tr in table.iter(f'{WORD_NS}tr'):
            cells = [cell_text(tc) for tc in tr.iter(f'{WORD_NS}tc')]
            if any(c for c in cells):
                rows.append(cells)
        if len(rows) >= 2:
            return rows[0], rows[1:]

    # No usable table - fall back to the paragraphs as delimited text.
    lines = [cell_text(p) for p in root.iter(f'{WORD_NS}p')]
    body = '\n'.join(line for line in lines if line.strip())
    if not body.strip():
        raise BulkUpdateError('The document has no table and no text to read.')
    return _read_delimited(body.encode('utf-8'))


def _cell_to_text(value: Any) -> str:
    """Excel cell to the string the rest of the pipeline expects.

    Dates come back as datetimes and are rendered ISO so the date parser
    below sees them the same way it sees a typed date. Whole numbers stored
    as floats are rendered without the `.0` that would otherwise turn PO
    quantities and years into "2024.0".
    """
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


READERS = {
    'csv': _read_delimited, 'txt': _read_delimited, 'tsv': _read_delimited,
    'xlsx': _read_excel, 'xlsm': _read_excel,
    'docx': _read_word,
}

SUPPORTED_EXTENSIONS = tuple(sorted(READERS))


# ----------------------------------------------------------------------
# Value coercion
# ----------------------------------------------------------------------

DATE_FORMATS = ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%m/%d/%Y', '%d %b %Y',
                '%d %B %Y', '%Y/%m/%d')


def _parse_date(raw: str) -> Optional[date]:
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _resolve_sales_person(raw: str) -> Tuple[Any, Optional[str]]:
    """Turn the sales person named in a cell into the user id a PO stores.

    Sheets carry a person, the column holds a foreign key, so the name has to
    be looked up rather than written through. Matched on username first and
    display name second, both case-insensitively, since a sheet may use
    either. Two people answering to the same name is reported rather than
    guessed at - assigning someone else's order to them is not a mistake the
    sheet can see afterwards.
    """
    from src.models.user import User

    wanted = raw.strip().upper()
    matches = User.query.filter(db_upper(User.username) == wanted).all()
    if not matches:
        matches = User.query.filter(db_upper(User.name) == wanted).all()

    if not matches:
        return None, f'no user is named "{raw.strip()}"'
    if len(matches) > 1:
        return None, (f'"{raw.strip()}" matches {len(matches)} users - '
                      'use their username instead')
    return matches[0].id, None


def _coerce(field: str, raw: str) -> Tuple[Any, Optional[str]]:
    """Turn a cell into the value the column holds, or explain why not."""
    value = raw.strip()

    if field in REFERENCE_FIELDS:
        return _resolve_sales_person(value)

    if field in NUMERIC_FIELDS:
        try:
            return float(value.replace(',', '')), None
        except ValueError:
            return None, f'"{raw}" is not a number'

    if field in DATE_FIELDS:
        parsed = _parse_date(value)
        if parsed is None:
            return None, f'"{raw}" is not a date the system recognises (try YYYY-MM-DD)'
        return parsed, None

    if field == 'status':
        upper = value.upper().replace(' ', '_').replace('-', '_')
        if upper not in VALID_STATUSES:
            return None, f'"{raw}" is not a status ({", ".join(VALID_STATUSES)})'
        return upper, None

    # Everything else is text, and the CRM stores text uppercase - POService
    # uppercases it on the way in regardless of what we hand over. Doing it
    # here too is what makes the preview honest: compared in the case it will
    # actually be stored in, so re-running the same file correctly reports
    # "no change" instead of promising an update that writes nothing.
    return value.upper(), None


def _same(current: Any, new: Any) -> bool:
    """Would writing `new` over `current` actually change anything?

    Compared after coercion so "1000" and 1000.0 are recognised as the same
    figure - otherwise every re-run of the same sheet would report the whole
    file as changed and log an update against every PO.
    """
    if current is None:
        return new in (None, '')
    if isinstance(current, float) or isinstance(new, float):
        try:
            return abs(float(current) - float(new)) < 0.0001
        except (TypeError, ValueError):
            return False
    return str(current) == str(new)


# ----------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------

class POBulkUpdateService:
    """Reads an update file, works out what it would do, then does it."""

    def prepare(self, filename: str, data: bytes) -> Dict[str, Any]:
        """Read and validate a file without writing anything.

        Returns the full plan: a verdict per row, the columns that were
        recognised and the ones that were not, and the counts to summarise
        it with. `apply()` takes the `rows` from this straight back.
        """
        extension = (filename.rsplit('.', 1)[-1] if '.' in filename else '').lower()
        reader = READERS.get(extension)
        if reader is None:
            raise BulkUpdateError(
                f'"{filename}" is a .{extension or "?"} file. Supported types are: '
                + ', '.join('.' + e for e in SUPPORTED_EXTENSIONS))

        headers, raw_rows = reader(data)
        if len(raw_rows) > MAX_ROWS:
            raise BulkUpdateError(
                f'The file has {len(raw_rows):,} rows. Split it into files of '
                f'{MAX_ROWS:,} rows or fewer.')

        key_field, field_map, ignored = self._map_columns(headers)
        if key_field is None:
            raise BulkUpdateError(
                'No column identifies which PO each row is about. Add a '
                '"PO Number" column (or "Reg No").')
        if not field_map:
            raise BulkUpdateError(
                'The file has nothing to update - only the identifying column '
                'was recognised. Add at least one field column, e.g. "Status".')

        rows = self._evaluate(raw_rows, headers, key_field, field_map)

        return {
            'filename': filename,
            'key_field': key_field,
            'columns': sorted(set(field_map.values())),
            'ignored_columns': ignored,
            'rows': rows,
            'summary': self._summarise(rows),
        }

    def _map_columns(self, headers: Sequence[str]):
        """Decide what each header column means.

        Returns the key column's field name, {column index: PO field} for the
        updatable columns, and the headers that meant nothing to us - those
        are reported rather than silently dropped, because a misspelled
        header is the most likely reason a sheet appears to do nothing.
        """
        key_field: Optional[str] = None
        key_index: Optional[int] = None
        field_map: Dict[int, str] = {}
        ignored: List[str] = []

        for index, header in enumerate(headers):
            canon = _canon(header)
            if not canon:
                continue
            # PO number wins over registration if a sheet carries both: it
            # identifies exactly one order, a registration need not.
            if canon in KEY_COLUMNS:
                candidate = KEY_COLUMNS[canon]
                if key_field is None or (candidate == 'po_number' and key_field == 'reg_no'):
                    key_field, key_index = candidate, index
                continue
            if canon in FIELD_COLUMNS:
                field_map[index] = FIELD_COLUMNS[canon]
            else:
                ignored.append(str(header).strip())

        # A registration column that lost the key role is still a column we
        # are not allowed to write, so it never becomes an update field.
        if key_index is not None:
            field_map.pop(key_index, None)

        return key_field, field_map, ignored

    def _evaluate(self, raw_rows, headers, key_field: str,
                  field_map: Dict[int, str]) -> List[Dict[str, Any]]:
        """Match and validate every row against the database."""
        results: List[Dict[str, Any]] = []
        seen_keys: Dict[str, int] = {}
        key_index = next(i for i, h in enumerate(headers)
                         if _canon(h) in KEY_COLUMNS and KEY_COLUMNS[_canon(h)] == key_field)

        for offset, raw in enumerate(raw_rows):
            # +2: the header is row 1, and spreadsheet rows are 1-based, so
            # this is the row number the user sees in Excel.
            row_no = offset + 2
            key = (raw[key_index].strip() if key_index < len(raw) else '')

            row: Dict[str, Any] = {
                'row_no': row_no, 'key': key, 'po_id': None,
                'po_number': '', 'changes': {}, 'errors': [], 'outcome': '',
            }

            if not key:
                row['outcome'] = 'invalid'
                row['errors'].append('No PO number or registration in this row')
                results.append(row)
                continue

            if key.upper() in seen_keys:
                row['outcome'] = 'duplicate'
                row['errors'].append(
                    f'{key} already appears on row {seen_keys[key.upper()]} - '
                    'this row is ignored so the first one is not overwritten')
                results.append(row)
                continue
            seen_keys[key.upper()] = row_no

            matches = self._find(key_field, key)
            if not matches:
                row['outcome'] = 'unmatched'
                row['errors'].append(f'No purchase order found for "{key}"')
                results.append(row)
                continue
            if len(matches) > 1:
                row['outcome'] = 'ambiguous'
                row['errors'].append(
                    f'"{key}" matches {len(matches)} purchase orders '
                    f'({", ".join(p.po_number for p in matches[:4])}...). '
                    'Identify the row by PO number instead.')
                results.append(row)
                continue

            po = matches[0]
            row['po_id'] = po.id
            row['po_number'] = po.po_number

            for index, field in field_map.items():
                cell = raw[index] if index < len(raw) else ''
                # Blank means "not stated", never "clear this field".
                if not str(cell).strip():
                    continue
                value, error = _coerce(field, str(cell))
                if error:
                    row['errors'].append(f'{field}: {error}')
                    continue
                if not _same(getattr(po, field, None), value):
                    row['changes'][field] = (value.isoformat()
                                             if isinstance(value, date) else value)

            if row['errors']:
                row['outcome'] = 'invalid'
            elif row['changes']:
                row['outcome'] = 'update'
            else:
                row['outcome'] = 'unchanged'
            results.append(row)

        return results

    @staticmethod
    def _find(key_field: str, key: str) -> List[PurchaseOrder]:
        """Every PO a key could mean - the caller decides what to do with more than one."""
        clean = key.strip()
        if key_field == 'po_number':
            po = PurchaseOrder.query.filter(
                db_upper(PurchaseOrder.po_number) == clean.upper()).all()
            return po
        return PurchaseOrder.query.filter(
            db_upper(PurchaseOrder.reg_no) == clean.upper()).all()

    @staticmethod
    def _summarise(rows: Sequence[Dict[str, Any]]) -> Dict[str, int]:
        counts = {'total': len(rows), 'update': 0, 'unchanged': 0,
                  'invalid': 0, 'unmatched': 0, 'ambiguous': 0, 'duplicate': 0}
        for row in rows:
            counts[row['outcome']] = counts.get(row['outcome'], 0) + 1
        counts['fields'] = sum(len(r['changes']) for r in rows)
        return counts

    def apply(self, rows: Sequence[Dict[str, Any]], user_id: int) -> Dict[str, Any]:
        """Write the rows the preview marked as updates. Nothing else.

        Each PO goes through POService.update_po rather than being written
        directly, so a bulk row that completes an installation does exactly
        what completing it on the form does - sends the completion email,
        raises the security briefing, updates payment recovery. A bulk edit
        is still an edit; it does not get to skip the consequences.

        Orders still awaiting work after the write are routed to the
        installation team, the same way a newly-raised one is. A sheet that
        fills in a customer, a location and a rate is handing over a job;
        without this the row changed and nobody was told.
        """
        from src.services.po_service import POService

        po_service = POService()
        applied, failed = 0, []
        fields_written = 0
        completed: List[str] = []
        routed: List[Any] = []

        for row in rows:
            if row.get('outcome') != 'update' or not row.get('po_id') or not row.get('changes'):
                continue
            changes = dict(row['changes'])
            try:
                updated = po_service.update_po(int(row['po_id']), changes, user_id)
                applied += 1
                fields_written += len(changes)
                if changes.get('status') == 'COMPLETED':
                    completed.append(row.get('po_number') or str(row['po_id']))
                elif updated is not None and updated.status in OPEN_STATUSES:
                    routed.append(updated)
            except Exception as exc:
                logger.error(f"Bulk PO update failed for row {row.get('row_no')}: {exc}")
                failed.append({'row_no': row.get('row_no'),
                               'po_number': row.get('po_number'),
                               'error': str(exc)})

        routed_numbers = self._route_to_installation(routed)

        logger.info(f"Bulk PO update by user {user_id}: {applied} updated, "
                    f"{fields_written} fields written, {len(failed)} failed, "
                    f"{len(routed_numbers)} routed to installation")
        return {'applied': applied, 'fields': fields_written,
                'failed': failed, 'completed': completed,
                'routed': routed_numbers}

    @staticmethod
    def _route_to_installation(orders: Sequence[Any]) -> List[str]:
        """Tell the installation team about the orders still awaiting work.

        Never raises: the sheet has already been written, and a notification
        that fails must not turn a completed bulk update into an error.
        """
        if not orders:
            return []

        from src.services.notification_service import NotificationService

        notifier = NotificationService()
        routed: List[str] = []
        for po in orders:
            try:
                notifier.notify_installers_po_updated(po)
                routed.append(po.po_number)
            except Exception as exc:
                logger.error(f"Bulk PO update: could not route {po.po_number} "
                             f"to installation: {exc}")
        return routed


def db_upper(column):
    """Case-insensitive comparison, done in SQL.

    PO numbers and registrations are stored uppercase, but files arrive with
    whatever case the person typed, and SQLite's default collation is
    case-sensitive - so "leb-2021-9981" would silently match nothing.
    """
    from src.extensions import db
    return db.func.upper(column)
