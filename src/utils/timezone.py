# src/utils/timezone.py
"""
Timezone utilities for Pakistan Standard Time (PKT)
"""
from datetime import datetime, date, timedelta
from typing import Optional, Union
import pytz

# Pakistan Standard Time (UTC+5)
PKT = pytz.timezone('Asia/Karachi')


def get_current_time() -> datetime:
    """
    Get current time in Pakistan Standard Time
    
    Returns:
        datetime: Current time in PKT (timezone-aware)
    """
    return datetime.now(PKT)


def get_current_date() -> date:
    """
    Get current date in Pakistan Standard Time
    
    Returns:
        date: Current date in PKT
    """
    return get_current_time().date()


def format_pkt_time(dt: Optional[datetime], fmt: str = '%d/%m/%Y %H:%M:%S') -> str:
    """
    Format a datetime in Pakistan Standard Time
    
    Args:
        dt: Datetime to format (can be naive or aware)
        fmt: Format string (default: '%d/%m/%Y %H:%M:%S')
    
    Returns:
        Formatted string or '-' if None
    """
    if dt is None:
        return '-'
    
    # Make timezone-aware if naive
    if dt.tzinfo is None:
        dt = PKT.localize(dt)
    else:
        dt = dt.astimezone(PKT)
    
    return dt.strftime(fmt)


def format_pkt_date(dt: Optional[datetime], fmt: str = '%d/%m/%Y') -> str:
    """
    Format a date in Pakistan Standard Time
    
    Args:
        dt: Datetime to format (can be naive or aware)
        fmt: Format string (default: '%d/%m/%Y')
    
    Returns:
        Formatted string or '-' if None
    """
    if dt is None:
        return '-'
    
    if dt.tzinfo is None:
        dt = PKT.localize(dt)
    else:
        dt = dt.astimezone(PKT)
    
    return dt.strftime(fmt)


def convert_to_pkt(dt: Union[datetime, str]) -> datetime:
    """
    Convert datetime to Pakistan Standard Time
    
    Args:
        dt: Datetime (naive or aware) or string
    
    Returns:
        datetime: Timezone-aware datetime in PKT
    """
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    
    if dt.tzinfo is None:
        dt = PKT.localize(dt)
    else:
        dt = dt.astimezone(PKT)
    
    return dt


def is_today(dt: Optional[datetime]) -> bool:
    """
    Check if datetime is today in PKT
    
    Args:
        dt: Datetime to check
    
    Returns:
        bool: True if date is today
    """
    if dt is None:
        return False
    
    dt = convert_to_pkt(dt)
    today = get_current_date()
    return dt.date() == today


def is_past_due(due_date: Optional[date]) -> bool:
    """
    Check if a date is past due (before today)
    
    Args:
        due_date: Date to check
    
    Returns:
        bool: True if due date is before today
    """
    if due_date is None:
        return False
    
    today = get_current_date()
    return due_date < today


def get_days_until(target_date: Optional[date]) -> Optional[int]:
    """
    Get number of days until target date
    
    Args:
        target_date: Target date
    
    Returns:
        int: Number of days until target date, None if target_date is None
    """
    if target_date is None:
        return None
    
    today = get_current_date()
    delta = target_date - today
    return delta.days


def parse_date(date_str: str, fmt: str = '%Y-%m-%d') -> Optional[date]:
    """
    Parse date string to date object
    
    Args:
        date_str: Date string
        fmt: Format string (default: '%Y-%m-%d')
    
    Returns:
        date: Parsed date or None if parsing fails
    """
    try:
        return datetime.strptime(date_str, fmt).date()
    except (ValueError, TypeError):
        return None


def parse_datetime(dt_str: str, fmt: str = '%Y-%m-%d %H:%M:%S') -> Optional[datetime]:
    """
    Parse datetime string to datetime object in PKT
    
    Args:
        dt_str: Datetime string
        fmt: Format string (default: '%Y-%m-%d %H:%M:%S')
    
    Returns:
        datetime: Parsed datetime in PKT or None if parsing fails
    """
    try:
        dt = datetime.strptime(dt_str, fmt)
        return PKT.localize(dt)
    except (ValueError, TypeError):
        return None


def get_date_range(start_date: Optional[date], end_date: Optional[date]) -> list:
    """
    Get list of dates between start_date and end_date (inclusive)
    
    Args:
        start_date: Start date
        end_date: End date
    
    Returns:
        list: List of dates
    """
    if not start_date or not end_date:
        return []
    
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    
    days = (end_date - start_date).days + 1
    return [start_date + timedelta(days=i) for i in range(days)]


def get_time_difference(dt1: datetime, dt2: datetime) -> dict:
    """
    Get time difference between two datetimes
    
    Args:
        dt1: First datetime
        dt2: Second datetime
    
    Returns:
        dict: Time difference in days, hours, minutes, seconds
    """
    dt1 = convert_to_pkt(dt1)
    dt2 = convert_to_pkt(dt2)
    
    diff = dt2 - dt1 if dt2 > dt1 else dt1 - dt2
    
    return {
        'days': diff.days,
        'hours': diff.seconds // 3600,
        'minutes': (diff.seconds // 60) % 60,
        'seconds': diff.seconds % 60,
        'total_seconds': diff.total_seconds()
    }


def get_start_of_day(dt: Optional[datetime] = None) -> datetime:
    """
    Get start of day (00:00:00) for given datetime
    
    Args:
        dt: Datetime (default: current time)
    
    Returns:
        datetime: Start of day in PKT
    """
    if dt is None:
        dt = get_current_time()
    else:
        dt = convert_to_pkt(dt)
    
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def get_end_of_day(dt: Optional[datetime] = None) -> datetime:
    """
    Get end of day (23:59:59.999999) for given datetime
    
    Args:
        dt: Datetime (default: current time)
    
    Returns:
        datetime: End of day in PKT
    """
    if dt is None:
        dt = get_current_time()
    else:
        dt = convert_to_pkt(dt)
    
    return dt.replace(hour=23, minute=59, second=59, microsecond=999999) 
