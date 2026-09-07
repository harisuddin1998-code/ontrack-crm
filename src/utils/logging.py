# src/utils/logging.py
"""
Production-grade logging configuration
"""
import os
import logging
import sys
from logging.handlers import RotatingFileHandler, SMTPHandler
from pathlib import Path
from typing import Optional

from flask import Flask


def setup_logging(app: Flask) -> None:
    """
    Configure logging for the application
    
    Args:
        app: Flask application instance
    """
    log_level = app.config.get('LOG_LEVEL', 'INFO')
    log_file = app.config.get('LOG_FILE', 'logs/app.log')
    log_format = app.config.get('LOG_FORMAT', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    log_date_format = app.config.get('LOG_DATE_FORMAT', '%Y-%m-%d %H:%M:%S')
    max_bytes = app.config.get('LOG_MAX_BYTES', 10 * 1024 * 1024)  # 10MB
    backup_count = app.config.get('LOG_BACKUP_COUNT', 10)
    
    # Ensure log directory exists
    log_dir = Path(log_file).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Remove default Flask handlers
    app.logger.handlers.clear()
    
    # Set log level
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    app.logger.setLevel(numeric_level)
    
    # Reconfigure sys.stdout / sys.stderr to handle utf-8 gracefully on Windows
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
        except Exception:
            pass
    if hasattr(sys.stderr, 'reconfigure'):
        try:
            sys.stderr.reconfigure(encoding='utf-8', errors='backslashreplace')
        except Exception:
            pass

    # --- Console Handler ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_formatter = logging.Formatter(log_format, log_date_format)
    console_handler.setFormatter(console_formatter)
    app.logger.addHandler(console_handler)
    
    # --- File Handler (Rotating) ---
    try:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(numeric_level)
        file_formatter = logging.Formatter(log_format, log_date_format)
        file_handler.setFormatter(file_formatter)
        app.logger.addHandler(file_handler)
    except Exception as e:
        app.logger.warning(f"Could not create file handler: {e}")
    
    # --- Error File Handler (separate file for errors) ---
    try:
        error_file = Path(log_file).parent / f"{Path(log_file).stem}_error.log"
        error_handler = RotatingFileHandler(
            error_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_formatter = logging.Formatter(log_format, log_date_format)
        error_handler.setFormatter(error_formatter)
        app.logger.addHandler(error_handler)
    except Exception as e:
        app.logger.warning(f"Could not create error file handler: {e}")
    
    # --- Email Handler (for production errors) ---
    if app.config.get('ENV') == 'production':
        try:
            mail_handler = SMTPHandler(
                mailhost=(app.config.get('MAIL_SERVER'), app.config.get('MAIL_PORT')),
                fromaddr=app.config.get('MAIL_DEFAULT_SENDER'),
                toaddrs=app.config.get('NOTIFICATION_EMAILS', []),
                subject='[ON TRACK] Application Error',
                credentials=(app.config.get('MAIL_USERNAME'), app.config.get('MAIL_PASSWORD'))
            )
            mail_handler.setLevel(logging.ERROR)
            mail_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s\n\n%(message)s\n\n---\n'
            )
            mail_handler.setFormatter(mail_formatter)
            app.logger.addHandler(mail_handler)
        except Exception as e:
            app.logger.warning(f"Could not create email handler: {e}")
    
    # --- Access Log (separate file for access logs) ---
    if app.config.get('ENV') == 'production':
        try:
            access_file = Path(log_file).parent / f"{Path(log_file).stem}_access.log"
            access_handler = RotatingFileHandler(
                access_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
            access_handler.setLevel(logging.INFO)
            access_formatter = logging.Formatter(
                '%(asctime)s - %(message)s',
                log_date_format
            )
            access_handler.setFormatter(access_formatter)
            
            # Custom access logger
            access_logger = logging.getLogger('access')
            access_logger.setLevel(logging.INFO)
            access_logger.addHandler(access_handler)
            app.logger.info("Access logger configured")
        except Exception as e:
            app.logger.warning(f"Could not create access file handler: {e}")
    
    # --- SQLAlchemy Logging ---
    if app.config.get('SQLALCHEMY_ECHO', False):
        sql_logger = logging.getLogger('sqlalchemy.engine')
        sql_logger.setLevel(logging.INFO)
        sql_logger.addHandler(console_handler)
    
    # --- Werkzeug Logging ---
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.setLevel(numeric_level)
    werkzeug_logger.addHandler(console_handler)
    
    # --- Suppress noisy loggers ---
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('socketio').setLevel(logging.WARNING)
    logging.getLogger('engineio').setLevel(logging.WARNING)
    
    app.logger.info(f"Logging configured (level: {log_level})")
    app.logger.info(f"Log file: {log_file}")


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance
    
    Args:
        name: Logger name (usually __name__)
    
    Returns:
        logging.Logger: Configured logger
    """
    logger = logging.getLogger(name)
    
    # If no handlers configured, add console handler as fallback
    if not logger.handlers:
        if hasattr(sys.stdout, 'reconfigure'):
            try:
                sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
            except Exception:
                pass
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    
    return logger


def log_access(request, response=None):
    """
    Log access to the application
    
    Args:
        request: Flask request object
        response: Flask response object (optional)
    """
    access_logger = logging.getLogger('access')
    
    log_data = {
        'ip': request.remote_addr,
        'method': request.method,
        'path': request.path,
        'status': response.status_code if response else 'N/A',
        'user_agent': request.headers.get('User-Agent', ''),
        'referer': request.headers.get('Referer', ''),
    }
    
    access_logger.info(
        f"{log_data['ip']} - {log_data['method']} {log_data['path']} "
        f"- {log_data['status']} - {log_data['user_agent'][:100]}"
    ) 
