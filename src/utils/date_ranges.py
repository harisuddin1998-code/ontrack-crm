# src/utils/date_ranges.py
"""
FROM/TO date range parsing shared by every report screen and download.

Reports default to the current month and can be pointed at any other range
with a `from`/`to` pair on the query string. Keeping one parser means the
page, its section filters, and the file it downloads always interpret the
same two parameters the same way - which is what stops a download quietly
covering a different period from the table it was launched from.
"""
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional, Tuple

DATE_FORMAT = '%Y-%m-%d'

# The timeframe chips the Administration and Executive dashboards are driven
# by. Kept here, beside the report range parser, because a dashboard chip and
# a report range are the same idea - a window everything on the screen is
# counted over - and because both boards plus every card on them have to read
# the same window from the same place. A card computing its own idea of
# "monthly" is exactly how a number ends up disagreeing with the chip above it.
DASHBOARD_PERIODS = ('daily', 'weekly', 'monthly', 'quarterly', 'all')

DASHBOARD_PERIOD_LABELS = {
    'daily': 'Today',
    'weekly': 'This Week',
    'monthly': 'Monthly',
    'quarterly': 'Quarterly',
    'all': 'All Time',
}

# How many whole days each rolling chip covers, counting today as day one.
# Whole days rather than "now minus N x 24h": a board opened at 09:00 and the
# same board opened at 17:00 must cover the same set of days, or the figures
# move without anything having happened.
DASHBOARD_PERIOD_DAYS = {'daily': 1, 'weekly': 7, 'monthly': 30, 'quarterly': 90}

# Where "all time" starts - earlier than any record the CRM holds, so an
# all-time window is a window like any other and needs no special case in the
# queries it feeds.
ALL_TIME_START = datetime(2020, 1, 1)


def _parse_one(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), DATE_FORMAT).date()
    except (ValueError, AttributeError):
        return None


def month_bounds(any_day: date) -> Tuple[date, date]:
    """First and last day of the month `any_day` falls in."""
    first = any_day.replace(day=1)
    last = any_day.replace(day=monthrange(any_day.year, any_day.month)[1])
    return first, last


def previous_month_bounds(today: Optional[date] = None) -> Tuple[date, date]:
    """First and last day of the month before `today`.

    This is what the monthly report emails cover: run on 1 September, the
    report is August's. Derived by stepping back one day from the 1st rather
    than by subtracting 30, so it is right in February and across new year.
    """
    today = today or date.today()
    last_day_of_previous = today.replace(day=1) - timedelta(days=1)
    return month_bounds(last_day_of_previous)


def format_range_label(start: date, end: date) -> str:
    """Human label for a range, e.g. '01 Aug 2026 - 31 Aug 2026'."""
    return f"{start.strftime('%d %b %Y')} - {end.strftime('%d %b %Y')}"


def parse_range(args: Dict[str, Any], default_to_current_month: bool = True
                ) -> Dict[str, Any]:
    """Read `from`/`to` off a request's args into a usable range.

    Returns start/end as dates, `start_dt`/`end_dt` as datetimes covering the
    whole of both days (end is 23:59:59.999999, so a record created at 4pm on
    the last day is inside the range rather than just outside it), plus the
    raw strings for re-filling the form inputs.

    With no parameters and `default_to_current_month`, the range is the
    current month - reports open showing this month, and the user toggles
    from there.
    """
    raw_from = (args.get('from') or '').strip()
    raw_to = (args.get('to') or '').strip()

    start = _parse_one(raw_from)
    end = _parse_one(raw_to)

    if start is None and end is None and default_to_current_month:
        start, end = month_bounds(date.today())
    elif start is not None and end is None:
        end = month_bounds(start)[1]
    elif start is None and end is not None:
        start = month_bounds(end)[0]

    # A backwards range is a typo, not a request for nothing - swap it rather
    # than silently returning an empty report.
    if start and end and start > end:
        start, end = end, start

    return {
        'start': start,
        'end': end,
        'start_dt': datetime.combine(start, datetime.min.time()) if start else None,
        'end_dt': datetime.combine(end, datetime.max.time()) if end else None,
        'from_str': start.strftime(DATE_FORMAT) if start else '',
        'to_str': end.strftime(DATE_FORMAT) if end else '',
        'label': format_range_label(start, end) if start and end else 'All time',
        'is_filtered': bool(start and end),
    }


def dashboard_period(period: Optional[str], now: Optional[datetime] = None
                     ) -> Dict[str, Any]:
    """The window a dashboard timeframe chip stands for.

    Returns both bounds. The end is the end of today rather than the current
    moment, so a record written at 16:00 is inside a window read at 09:00 -
    an open-ended "since midnight" and a closed "today" only agree until
    tomorrow, and a dashboard is read all day.

    An unrecognised (or missing) chip falls back to monthly, which is what
    both boards open on.
    """
    now = now or datetime.now()
    key = (period or '').strip().lower()
    if key not in DASHBOARD_PERIODS:
        key = 'monthly'

    end_dt = datetime.combine(now.date(), datetime.max.time())
    if key == 'all':
        start_dt = ALL_TIME_START
    else:
        span = DASHBOARD_PERIOD_DAYS[key]
        start_dt = datetime.combine(now.date() - timedelta(days=span - 1),
                                    datetime.min.time())

    return {
        'period': key,
        'label': DASHBOARD_PERIOD_LABELS[key],
        'start_dt': start_dt,
        'end_dt': end_dt,
        'start': start_dt.date(),
        'end': end_dt.date(),
        # What a card's link puts on the query string so the list it opens
        # covers the period the card counted.
        'start_str': start_dt.strftime(DATE_FORMAT),
        'end_str': end_dt.strftime(DATE_FORMAT),
        # Spelled out so a screenshot of the board is still readable a week
        # later - "Monthly" alone does not say which thirty days.
        'range_label': ('All time on record' if key == 'all' else
                        format_range_label(start_dt.date(), end_dt.date())),
        'is_all': key == 'all',
    }


def apply_range(query, column, date_range: Dict[str, Any]):
    """Restrict a query to a parsed range. A range with no bounds is a no-op."""
    if date_range.get('start_dt') is not None:
        query = query.filter(column >= date_range['start_dt'])
    if date_range.get('end_dt') is not None:
        query = query.filter(column <= date_range['end_dt'])
    return query


def in_range(value, date_range: Dict[str, Any]) -> bool:
    """Whether a datetime/date falls inside a parsed range.

    For filtering lists already in memory, where re-querying would cost more
    than the check. A record with no date is treated as outside the range -
    it cannot be shown to belong to the period.
    """
    if value is None:
        return False
    start, end = date_range.get('start_dt'), date_range.get('end_dt')
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, date):
        moment = datetime.combine(value, datetime.min.time())
    else:
        return False
    if start is not None and moment < start:
        return False
    if end is not None and moment > end:
        return False
    return True
