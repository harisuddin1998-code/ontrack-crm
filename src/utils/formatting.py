# src/utils/formatting.py
"""
Accounting-style number formatting.

Every amount shown anywhere in the CRM goes through here: a thousands
separator and exactly two decimal places, so a column of figures lines up and
reads as money rather than as a float that happened to land on a round number.

`money` is the Jinja filter (`{{ v|money }}` -> `9,000.00`); `money_pkr` adds
the currency prefix. The matching client-side helper is `window.fmtMoney` in
base.html - both must agree, since some tables are rendered by Jinja and
others by JavaScript from a JSON endpoint.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional

CURRENCY_PREFIX = 'PKR'


def to_number(value: Any) -> Optional[Decimal]:
    """Coerce anything the templates might hold to a Decimal, or None.

    Templates pass floats, Decimals, ints, strings from form data, and None
    for "no value recorded" - which must stay visually distinct from zero.
    """
    if value is None or value == '':
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).replace(',', '').strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def format_amount(value: Any, dash_if_empty: bool = True) -> str:
    """Format a number as `1,234,567.89`.

    Rounds to exactly two decimal places - never truncates, never drops a
    trailing zero, so 9000 reads as 9,000.00 and not 9,000.0 or 9000.
    """
    number = to_number(value)
    if number is None:
        return '-' if dash_if_empty else '0.00'
    return f'{number:,.2f}'


def format_money(value: Any, dash_if_empty: bool = True) -> str:
    """Same as format_amount with the currency prefix: `PKR 1,234.00`."""
    number = to_number(value)
    if number is None:
        return '-' if dash_if_empty else f'{CURRENCY_PREFIX} 0.00'
    return f'{CURRENCY_PREFIX} {number:,.2f}'


def format_money_round(value: Any, dash_if_empty: bool = True) -> str:
    """Whole rupees, no decimals: `PKR 1,250,457`.

    For headline figures - dashboard cards and summary tiles - where the
    paisa is noise: nobody reads a KPI to two decimal places, and the extra
    digits push the number out of its card. Rounds half-up rather than
    truncating, so 1,250,456.75 reads as 1,250,457 and not 1,250,456.

    Display only. Ledgers, invoices and any figure that has to reconcile
    still use `money_pkr` - a column of payments must show the paisa it was
    actually paid to.
    """
    number = to_number(value)
    if number is None:
        return '-' if dash_if_empty else f'{CURRENCY_PREFIX} 0'
    rounded = number.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    return f'{CURRENCY_PREFIX} {rounded:,}'


def format_count(value: Any) -> str:
    """Whole-number counts: separators, but no decimals (they aren't money)."""
    number = to_number(value)
    if number is None:
        return '0'
    return f'{int(number):,}'


def register_formatting_filters(app) -> None:
    """Make the formatters available to every template."""
    app.jinja_env.filters['money'] = format_amount
    app.jinja_env.filters['money_pkr'] = format_money
    app.jinja_env.filters['money_pkr_round'] = format_money_round
    app.jinja_env.filters['amount'] = format_amount
    app.jinja_env.filters['count_fmt'] = format_count
