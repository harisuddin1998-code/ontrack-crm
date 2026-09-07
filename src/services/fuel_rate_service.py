# src/services/fuel_rate_service.py
"""
Fuel Rate Service - Fetch and update fuel rates from PSO website
Specifically scrapes the PREMIER EURO 5 rate from the PSO fuel prices table
"""
import requests
import re
from datetime import date, datetime, timedelta
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup

from src.extensions import db
from src.models.technician import PetrolRate
from src.utils.logging import get_logger
from src.utils.timezone import get_current_date

logger = get_logger(__name__)


class FuelRateService:
    """Service for fetching and managing fuel rates from PSO"""
    
    PSO_URL = "https://psopk.com/en/fuels/fuel-prices"
    EURO_5_KEYWORDS = ['PREMIER EURO 5', 'EURO 5', 'PREMIER EURO']
    
    @classmethod
    def fetch_latest_euro5_rate(cls) -> Optional[float]:
        """
        Fetch the latest PREMIER EURO 5 rate from PSO website.
        Looks for the table with Product Name and Rs./Litre columns.
        
        Returns:
            Float: Rate per liter or None if not found
        """
        try:
            logger.info(f"Fetching fuel rates from: {cls.PSO_URL}")
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            response = requests.get(cls.PSO_URL, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Method 1: Find table with Product Name and Rs./Litre headers
            rate = cls._extract_from_fuel_table(soup)
            
            # Method 2: If not found, try generic table extraction
            if not rate:
                rate = cls._extract_from_tables(soup)
            
            # Method 3: Try text search as fallback
            if not rate:
                rate = cls._extract_from_text(soup)
            
            if rate:
                logger.info(f"Successfully fetched EURO 5 rate: {rate}")
                return rate
            else:
                logger.warning("Could not find EURO 5 rate on the page")
                return None
                
        except requests.RequestException as e:
            logger.error(f"Request error fetching fuel rate: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching fuel rate: {e}")
            return None
    
    @classmethod
    def _extract_from_fuel_table(cls, soup: BeautifulSoup) -> Optional[float]:
        """
        Extract PREMIER EURO 5 rate from the fuel price table.
        Looks for table with "Product Name" and "Rs./Litre" headers.
        """
        tables = soup.find_all('table')
        
        for table in tables:
            rows = table.find_all('tr')
            
            product_name_col = None
            rate_col = None
            
            # Look for header row with "Product Name" and "Rs./Litre"
            for row in rows:
                cells = row.find_all(['th', 'td'])
                cell_texts = [cell.get_text().strip() for cell in cells]
                
                if any('Product Name' in text or 'PRODUCT NAME' in text.upper() for text in cell_texts):
                    for idx, text in enumerate(cell_texts):
                        if 'Product Name' in text or 'PRODUCT NAME' in text.upper():
                            product_name_col = idx
                        if 'Rs./Litre' in text or 'RS./LITRE' in text.upper() or 'Rs/Ltr' in text:
                            rate_col = idx
                    break
            
            # If we found the header, look for PREMIER EURO 5 in the rows
            if product_name_col is not None and rate_col is not None:
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) > max(product_name_col, rate_col):
                        product_name = cells[product_name_col].get_text().strip()
                        for keyword in cls.EURO_5_KEYWORDS:
                            if keyword in product_name:
                                rate_text = cells[rate_col].get_text().strip()
                                rate = cls._parse_rate(rate_text)
                                if rate:
                                    logger.info(f"Found {product_name}: {rate}")
                                    return rate
        
        return None
    
    @classmethod
    def _extract_from_tables(cls, soup: BeautifulSoup) -> Optional[float]:
        """Extract rate from HTML tables (fallback method)"""
        tables = soup.find_all('table')
        
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all('td')
                if len(cells) >= 2:
                    for keyword in cls.EURO_5_KEYWORDS:
                        if keyword in cells[0].text:
                            rate_text = cells[1].text.strip()
                            rate = cls._parse_rate(rate_text)
                            if rate:
                                return rate
        return None
    
    @classmethod
    def _extract_from_text(cls, soup: BeautifulSoup) -> Optional[float]:
        """Extract rate from text content (fallback method)"""
        text = soup.get_text()
        
        patterns = [
            r'PREMIER\s+EURO\s*5.*?(\d+\.?\d*)',
            r'EURO\s*5.*?(\d+\.?\d*)\s*(?:Rs\.?|PKR)?',
            r'PREMIER\s+EURO.*?(\d+\.?\d*)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return float(match.group(1))
        
        for keyword in cls.EURO_5_KEYWORDS:
            if keyword in text:
                start_idx = text.find(keyword)
                surrounding = text[start_idx:start_idx + 200]
                pattern = r'(\d+\.?\d*)\s*(?:Rs\.?|PKR)?\s*(?:per\s*)?L(?:iter)?'
                match = re.search(pattern, surrounding)
                if match:
                    return float(match.group(1))
        
        return None
    
    @classmethod
    def _parse_rate(cls, rate_text: str) -> Optional[float]:
        """
        Parse rate from text string like "Rs.310.71/Ltr" -> 310.71
        
        Args:
            rate_text: Rate text string (e.g., "Rs.310.71/Ltr")
            
        Returns:
            Float: Parsed rate or None if parsing fails
        """
        try:
            # Remove all non-numeric characters except decimal point
            cleaned = re.sub(r'[^\d.]', '', rate_text)
            
            # Remove multiple decimal points (keep only the first one)
            if cleaned.count('.') > 1:
                parts = cleaned.split('.')
                cleaned = parts[0] + '.' + ''.join(parts[1:])
            
            # If cleaned starts with '.', add a leading zero
            if cleaned.startswith('.'):
                cleaned = '0' + cleaned
            
            # If cleaned ends with '.', remove it
            if cleaned.endswith('.'):
                cleaned = cleaned[:-1]
            
            if cleaned and cleaned != '.':
                rate = float(cleaned)
                # If rate is less than 1, it's likely been misinterpreted
                if 0 < rate < 1 and ('Rs.' in rate_text or 'Rs/' in rate_text):
                    rate = rate * 1000
                return rate
            return None
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse rate from '{rate_text}': {e}")
            return None
    
    @classmethod
    def update_petrol_rate(cls) -> Optional[PetrolRate]:
        """
        Fetch the latest rate and store it in the database.
        
        Returns:
            PetrolRate: Created rate object or None if failed
        """
        latest_rate = cls.fetch_latest_euro5_rate()
        
        if latest_rate:
            today = get_current_date()
            existing = PetrolRate.query.filter_by(effective_date=today).first()
            
            if existing:
                existing.rate_per_liter = latest_rate
                db.session.commit()
                logger.info(f"Updated today's petrol rate to {latest_rate}")
                return existing
            else:
                new_rate = PetrolRate(
                    rate_per_liter=latest_rate,
                    effective_date=today
                )
                db.session.add(new_rate)
                db.session.commit()
                logger.info(f"Created new petrol rate: {latest_rate} for {today}")
                return new_rate
        
        logger.warning("Failed to update petrol rate from PSO")
        return None
    
    @classmethod
    def get_current_rate(cls) -> float:
        """Get the current petrol rate from database"""
        rate = PetrolRate.query.order_by(PetrolRate.effective_date.desc()).first()
        return rate.rate_per_liter if rate else 280.0
    
    @classmethod
    def get_rate_on_date(cls, target_date: date) -> float:
        """Get petrol rate on a specific date"""
        rate = PetrolRate.query.filter(
            PetrolRate.effective_date <= target_date
        ).order_by(PetrolRate.effective_date.desc()).first()
        return rate.rate_per_liter if rate else 280.0
    
    @classmethod
    def get_rate_history(cls, days: int = 30) -> List[Dict[str, Any]]:
        """Get rate history for the last N days"""
        cutoff = get_current_date() - timedelta(days=days)
        rates = PetrolRate.query.filter(
            PetrolRate.effective_date >= cutoff
        ).order_by(PetrolRate.effective_date.desc()).all()
        
        return [{
            'date': r.effective_date.isoformat(),
            'rate': r.rate_per_liter
        } for r in rates]