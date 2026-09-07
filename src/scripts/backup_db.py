# src/scripts/backup_db.py
"""
Database Backup Script
"""
import os
import shutil
from datetime import datetime
from pathlib import Path
from src.app import create_app
from src.utils.logging import get_logger

logger = get_logger(__name__)


def backup_database():
    """Backup the database"""
    app = create_app()
    
    with app.app_context():
        db_path = app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
        
        if not db_path or not os.path.exists(db_path):
            logger.error(f"Database not found at: {db_path}")
            return
        
        # Create backup directory
        backup_dir = Path(app.instance_path) / 'backups'
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Create backup filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = backup_dir / f'management_backup_{timestamp}.db'
        
        # Copy database
        shutil.copy2(db_path, backup_path)
        
        logger.info(f"Database backed up to: {backup_path}")
        print(f"✅ Database backed up to: {backup_path}")
        
        # Clean old backups (keep last 10)
        backups = sorted(backup_dir.glob('management_backup_*.db'))
        if len(backups) > 10:
            for old_backup in backups[:-10]:
                old_backup.unlink()
                logger.info(f"Removed old backup: {old_backup}")
        
        return backup_path


if __name__ == "__main__":
    backup_database()