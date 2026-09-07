# src/utils/helpers.py
"""
Helper Functions - Common utilities used across the application
"""
import re
import uuid
from datetime import datetime, date
from typing import Optional, Dict, Any, List
from decimal import Decimal
import random
import string

from src.utils.timezone import get_current_time, get_current_date


def generate_po_number() -> str:
    """
    Generate a unique PO number in format: PO{YYMMDD}{XXXX}
    Example: PO2407150001
    
    Returns:
        str: Unique PO number
    """
    from src.models.purchase_order import PurchaseOrder
    from src.extensions import db
    
    date_str = get_current_time().strftime('%y%m%d')
    prefix = f"PO{date_str}"
    
    # Get today's POs
    today_start = get_current_time().replace(hour=0, minute=0, second=0, microsecond=0)
    today_pos = PurchaseOrder.query.filter(
        PurchaseOrder.created_at >= today_start
    ).all()
    
    max_num = 0
    for po in today_pos:
        if po.po_number and po.po_number.startswith(prefix):
            try:
                num = int(po.po_number[-4:])
                max_num = max(max_num, num)
            except (ValueError, TypeError):
                continue
    
    return f"{prefix}{max_num + 1:04d}"


# `generate_invoice_number` used to live here: it returned
# f"ONT-{FuelReimbursementInvoice.query.count() + 1:06d}" under a docstring
# promising a unique number, which a row count cannot give - deleting any
# invoice made the next one reuse a number already taken. Nothing called it,
# but its name and that promise were exactly what the next person wiring up
# numbering would have reached for.
#
# Fuel invoice numbers now come from
# FuelReimbursementInvoiceService.generate_invoice_number, which is timestamped
# and confirmed free against the table before it is used.


def generate_uuid() -> str:
    """Generate a UUID string"""
    return str(uuid.uuid4())


def generate_random_string(length: int = 8) -> str:
    """Generate a random string of specified length"""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


def generate_verification_code() -> str:
    """Generate a 6-digit verification code"""
    return ''.join(random.choices(string.digits, k=6))


def validate_vehicle(registration_no: str) -> bool:
    """
    Validate vehicle registration number format
    Simple validation - can be enhanced based on country format
    
    Args:
        registration_no: Vehicle registration number
        
    Returns:
        bool: True if valid
    """
    if not registration_no:
        return False
    
    # Remove spaces and convert to uppercase
    reg = registration_no.replace(' ', '').upper()
    
    # Basic validation - at least 3 characters, alphanumeric
    if len(reg) < 3:
        return False
    
    # Check for valid characters (letters, numbers, hyphens)
    pattern = r'^[A-Z0-9\-]+$'
    return bool(re.match(pattern, reg))


def sanitize_phone(phone: str) -> str:
    """
    Sanitize phone number - remove spaces, special characters
    
    Args:
        phone: Phone number string
        
    Returns:
        str: Sanitized phone number
    """
    if not phone:
        return ''
    # Remove spaces, hyphens, parentheses, plus sign
    return re.sub(r'[\s\-\(\)\+]', '', phone).strip()


def format_phone(phone: str) -> str:
    """
    Format phone number for display
    
    Args:
        phone: Phone number string
        
    Returns:
        str: Formatted phone number
    """
    if not phone:
        return ''
    
    sanitized = sanitize_phone(phone)
    
    # If it's a Pakistani number (starts with 92 or 03)
    if sanitized.startswith('92'):
        if len(sanitized) == 12:
            return f"+{sanitized[:2]} {sanitized[2:4]} {sanitized[4:7]} {sanitized[7:]}"
        return f"+{sanitized[:2]} {sanitized[2:]}"
    elif sanitized.startswith('03') and len(sanitized) == 11:
        return f"0{sanitized[1:4]} {sanitized[4:7]} {sanitized[7:]}"
    
    return sanitized


def format_currency(amount: float, currency: str = "PKR") -> str:
    """
    Format currency amount
    
    Args:
        amount: Amount to format
        currency: Currency code (default: PKR)
        
    Returns:
        str: Formatted currency string
    """
    if amount is None:
        return "PKR 0.00"
    
    formatted = f"{currency} {amount:,.2f}"
    return formatted


def parse_date(date_str: str, fmt: str = '%Y-%m-%d') -> Optional[date]:
    """
    Parse date string to date object
    
    Args:
        date_str: Date string
        fmt: Format string (default: '%Y-%m-%d')
        
    Returns:
        date: Parsed date or None if parsing fails
    """
    if not date_str:
        return None
    
    try:
        return datetime.strptime(date_str, fmt).date()
    except (ValueError, TypeError):
        return None


def parse_datetime(dt_str: str, fmt: str = '%Y-%m-%d %H:%M:%S') -> Optional[datetime]:
    """
    Parse datetime string to datetime object
    
    Args:
        dt_str: Datetime string
        fmt: Format string (default: '%Y-%m-%d %H:%M:%S')
        
    Returns:
        datetime: Parsed datetime or None if parsing fails
    """
    if not dt_str:
        return None
    
    try:
        return datetime.strptime(dt_str, fmt)
    except (ValueError, TypeError):
        return None


def truncate_string(text: str, max_length: int = 100, suffix: str = '...') -> str:
    """
    Truncate a string to a maximum length
    
    Args:
        text: String to truncate
        max_length: Maximum length
        suffix: Suffix to append when truncated
        
    Returns:
        str: Truncated string
    """
    if not text:
        return ''
    
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def slugify(text: str) -> str:
    """
    Convert text to URL-friendly slug
    
    Args:
        text: Text to slugify
        
    Returns:
        str: Slugified text
    """
    if not text:
        return ''
    
    # Convert to lowercase
    text = text.lower()
    
    # Replace spaces with hyphens
    text = re.sub(r'\s+', '-', text)
    
    # Remove special characters
    text = re.sub(r'[^a-z0-9\-]', '', text)
    
    # Remove multiple hyphens
    text = re.sub(r'-+', '-', text)
    
    return text.strip('-')


def dict_to_query_string(data: Dict[str, Any]) -> str:
    """
    Convert dictionary to URL query string
    
    Args:
        data: Dictionary of parameters
        
    Returns:
        str: Query string
    """
    if not data:
        return ''
    
    parts = []
    for key, value in data.items():
        if value is not None:
            parts.append(f"{key}={value}")
    
    return '&'.join(parts)


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """
    Safely divide two numbers, returning default if denominator is zero
    
    Args:
        numerator: Numerator
        denominator: Denominator
        default: Default value if denominator is zero
        
    Returns:
        float: Result of division or default
    """
    if denominator == 0:
        return default
    return numerator / denominator


def calculate_percentage(part: float, whole: float) -> float:
    """
    Calculate percentage
    
    Args:
        part: Part value
        whole: Whole value
        
    Returns:
        float: Percentage (0-100)
    """
    return safe_divide(part, whole, 0) * 100


def get_year_choices() -> List[tuple]:
    """
    Get year choices for forms
    
    Returns:
        List of (year, year) tuples
    """
    current_year = get_current_date().year
    return [(str(y), str(y)) for y in range(1900, current_year + 2)][::-1]


def validate_email(email: str) -> bool:
    """
    Validate email format
    
    Args:
        email: Email address
        
    Returns:
        bool: True if valid
    """
    if not email:
        return False
    
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def validate_cnic(cnic: str) -> bool:
    """
    Validate Pakistani CNIC number format (xxxxx-xxxxxxx-x)
    
    Args:
        cnic: CNIC number
        
    Returns:
        bool: True if valid
    """
    if not cnic:
        return False
    
    # Remove spaces and dashes
    cnic = re.sub(r'[\s\-]', '', cnic)
    
    # Check if it's 13 digits
    if not cnic.isdigit() or len(cnic) != 13:
        return False
    
    return True


def format_cnic(cnic: str) -> str:
    """
    Format CNIC number as xxxxx-xxxxxxx-x
    
    Args:
        cnic: CNIC number
        
    Returns:
        str: Formatted CNIC
    """
    if not cnic:
        return ''
    
    # Remove spaces and dashes
    cnic = re.sub(r'[\s\-]', '', cnic)
    
    if len(cnic) == 13 and cnic.isdigit():
        return f"{cnic[:5]}-{cnic[5:12]}-{cnic[12]}"
    
    return cnic


def get_client_ip(request) -> str:
    """
    Get client IP address from request
    
    Args:
        request: Flask request object
        
    Returns:
        str: Client IP address
    """
    # Check for proxy headers first
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        return forwarded.split(',')[0].strip()
    
    real_ip = request.headers.get('X-Real-IP')
    if real_ip:
        return real_ip
    
    return request.remote_addr or '0.0.0.0' 
