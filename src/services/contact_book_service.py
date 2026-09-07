# src/services/contact_book_service.py
"""
Contact Book - every phone number the CRM holds for a registration number.

Non-Reporting has always pulled a full contact set from the MIS (emergency
mobile, residence, office, secondary users) because one number is not enough
to reach a customer who is not answering. Device Recovery had only the single
`customer_contact` copied onto the REDO activity, so an officer chasing a
device charge had one number and no fallback.

The numbers are already in the CRM, spread across four tables that each know
the customer for a different reason. This gathers them, de-duplicates them,
and puts the number most likely to be answered first.

Nothing here writes: it is a read-side view over what other modules already
sync. Registration numbers are matched ignoring case, spaces and dashes,
because the four sources are populated by four different routes and agree on
the plate but not on how to punctuate it.
"""
import re
from typing import Any, Dict, Iterable, List, Optional

from src.extensions import db
from src.models.annual_recovery import AnnualRecoveryClient, AnnualRecoveryVehicle
from src.models.gps import NonReportingVehicle
from src.models.purchase_order import PurchaseOrder
from src.models.redo import RedoActivity
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Values that occupy a phone column without being a phone number. The MIS sync
# writes 'N/A' rather than NULL for a missing number, so an unfiltered list
# would show an officer four rows of nothing to call.
PLACEHOLDERS = {'', '-', '.', '0', 'n/a', 'na', 'none', 'null', 'nil', 'nan', 'x'}

# A Pakistani mobile is 11 digits (0300-1234567); a landline with its city code
# is 9 or 10. Below 7 digits there is nothing dialable left.
MIN_DIGITS = 7


def normalize_registration(value: Optional[str]) -> str:
    """Registration numbers as a comparison key: no case, spaces or dashes."""
    if not value:
        return ''
    return re.sub(r'[\s\-]', '', str(value)).upper()


def _digits(value: str) -> str:
    return re.sub(r'\D', '', value)


def dial_key(value: Optional[str]) -> str:
    """The key two spellings of the same number share.

    Local and international spellings of one mobile (0300-1234567,
    +92 300 1234567) differ in their leading digits but never in their last
    nine, so that is what identifies the line. Without this the same number
    appears three times on a call sheet under three labels.
    """
    digits = _digits(str(value or ''))
    if len(digits) < MIN_DIGITS:
        return ''
    return digits[-9:] if len(digits) >= 9 else digits


def _usable(value: Any) -> Optional[str]:
    """A trimmed number, or None if the column holds a placeholder."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in PLACEHOLDERS:
        return None
    if len(_digits(text)) < MIN_DIGITS:
        return None
    return text


class ContactBookService:
    """Every number known for a registration, best-first.

    Ordering is by how likely the line is to be answered by the person who
    owes the money, not by which table it came from: the number the
    technician wrote down at the last service visit beats a residence
    landline synced from the MIS months ago.
    """

    # (source key, attribute, label). Order is the order an officer should
    # work down the list.
    REDO_FIELDS = (('redo', 'customer_contact', 'Mobile (service record)'),)
    NR_FIELDS = (
        ('nr', 'emergency_mobile', 'Emergency Mobile'),
        ('nr', 'customer_contact', 'Mobile (monitoring)'),
        ('nr', 'customer_phone2', 'Alternate'),
        ('nr', 'customer_phone3', 'Secondary Users'),
        ('nr', 'res_phone', 'Residence'),
        ('nr', 'office_phone', 'Office'),
    )
    PO_FIELDS = (
        ('po', 'owner_contact', 'Owner (purchase order)'),
        ('po', 'contact_person_driver', 'Driver / Contact Person'),
    )
    AMC_FIELDS = (('amc', 'cell1', 'Mobile (AMC roster)'),)

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def for_registrations(self, registrations: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        """Contact books for many registrations at once, keyed by the
        normalized registration.

        Four queries in total rather than four per row: a call sheet covering
        a few hundred charges is the point of this method, and doing it a row
        at a time is a thousand round trips to show one page.
        """
        keys = {normalize_registration(r) for r in registrations if normalize_registration(r)}
        if not keys:
            return {}

        books: Dict[str, Dict[str, Any]] = {
            key: {'numbers': [], 'names': [], 'seen': set()} for key in keys
        }

        for row in self._rows_for(RedoActivity, RedoActivity.registration_no, keys,
                                  order=RedoActivity.id.desc()):
            book = books.get(normalize_registration(row.registration_no))
            if book is not None:
                self._add_fields(book, row, self.REDO_FIELDS)
                self._add_name(book, row.customer_name, 'Customer')

        for row in self._rows_for(NonReportingVehicle, NonReportingVehicle.registration_no, keys,
                                  order=NonReportingVehicle.id):
            book = books.get(normalize_registration(row.registration_no))
            if book is not None:
                self._add_fields(book, row, self.NR_FIELDS)
                self._add_name(book, row.emergency_name, 'Emergency Contact')
                self._add_name(book, row.customer_name, 'Customer')

        for row in self._rows_for(PurchaseOrder, PurchaseOrder.reg_no, keys,
                                  order=PurchaseOrder.id.desc()):
            book = books.get(normalize_registration(row.reg_no))
            if book is not None:
                self._add_fields(book, row, self.PO_FIELDS)
                self._add_name(book, row.owner_name, 'Owner')

        for vehicle, client in self._amc_rows(keys):
            book = books.get(normalize_registration(vehicle.reg_no))
            if book is not None and client is not None:
                self._add_fields(book, client, self.AMC_FIELDS)
                self._add_name(book, client.name, 'AMC Account')

        for book in books.values():
            book.pop('seen', None)
        return books

    def for_registration(self, registration: str) -> Dict[str, Any]:
        """One registration's contact book. Empty rather than missing when
        the plate is unknown, so callers never branch on None."""
        key = normalize_registration(registration)
        book = self.for_registrations([registration]).get(key)
        return book or {'numbers': [], 'names': []}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _rows_for(self, model, column, keys: set, order):
        """Rows whose normalized registration is one of `keys`.

        The normalization happens in SQL so the match is done by the database
        over an index-sized set rather than by loading the whole table; the
        source tables run to thousands of rows and only a few hundred are
        ever wanted.
        """
        normalized = db.func.upper(
            db.func.replace(db.func.replace(column, ' ', ''), '-', ''))
        rows = []
        # SQLite caps bind parameters (999 by default), and a busy month can
        # put more registrations than that on one sheet.
        key_list = list(keys)
        for start in range(0, len(key_list), 400):
            chunk = key_list[start:start + 400]
            rows.extend(model.query.filter(normalized.in_(chunk))
                        .order_by(order).all())
        return rows

    def _amc_rows(self, keys: set):
        normalized = db.func.upper(
            db.func.replace(db.func.replace(AnnualRecoveryVehicle.reg_no, ' ', ''), '-', ''))
        pairs = []
        key_list = list(keys)
        for start in range(0, len(key_list), 400):
            chunk = key_list[start:start + 400]
            pairs.extend(
                db.session.query(AnnualRecoveryVehicle, AnnualRecoveryClient)
                .outerjoin(AnnualRecoveryClient,
                           AnnualRecoveryClient.id == AnnualRecoveryVehicle.client_id)
                .filter(normalized.in_(chunk))
                .order_by(AnnualRecoveryVehicle.id).all())
        return pairs

    def _add_fields(self, book: Dict[str, Any], row: Any, fields) -> None:
        for source, attribute, label in fields:
            number = _usable(getattr(row, attribute, None))
            if not number:
                continue
            key = dial_key(number)
            if not key or key in book['seen']:
                continue
            book['seen'].add(key)
            book['numbers'].append(
                {'label': self._distinct_label(book, label), 'number': number,
                 'source': source})

    @staticmethod
    def _distinct_label(book: Dict[str, Any], label: str) -> str:
        """Keep every row on a call sheet distinguishable.

        Rows are added newest-first, so a second number carrying a label
        already used came off an older record - an earlier number for the
        same vehicle, worth trying but not first.
        """
        used = {entry['label'] for entry in book['numbers']}
        if label not in used:
            return label
        candidate = f'Earlier {label[0].lower()}{label[1:]}'
        suffix = 2
        while candidate in used:
            suffix += 1
            candidate = f'Earlier {label[0].lower()}{label[1:]} ({suffix})'
        return candidate

    @staticmethod
    def _add_name(book: Dict[str, Any], value: Any, label: str) -> None:
        name = (str(value).strip() if value else '')
        if not name or name.lower() in PLACEHOLDERS:
            return
        if any(entry['name'].lower() == name.lower() for entry in book['names']):
            return
        book['names'].append({'label': label, 'name': name})


def attach_contact_books(charges: List[Any]) -> None:
    """Hang a contact book on each Device Recovery charge, in one batch.

    Set as `charge.contact_book` so a template can read it like any other
    attribute. Charges whose REDO activity is missing get an empty book
    rather than being skipped, so a sheet never has holes in it.
    """
    registrations = [c.redo_activity.registration_no for c in charges
                     if c.redo_activity and c.redo_activity.registration_no]
    books = ContactBookService().for_registrations(registrations) if registrations else {}
    empty = {'numbers': [], 'names': []}
    for charge in charges:
        reg = charge.redo_activity.registration_no if charge.redo_activity else None
        charge.contact_book = books.get(normalize_registration(reg), empty)
