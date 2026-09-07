# src/config.py
"""
Application Configuration Management
Uses Pydantic for validation and environment variables
"""
import os
from typing import Optional, List, Dict, Any
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field, validator, PostgresDsn

# Get the absolute path to the project root and instance folder
PROJECT_ROOT = Path(__file__).parent.parent
INSTANCE_PATH = PROJECT_ROOT / 'instance'
DB_PATH = INSTANCE_PATH / 'management.db'

class Config(BaseSettings):
    """Base configuration with environment variable support"""
    
    # Flask Core
    SECRET_KEY: str = Field(
        default="dev-secret-key-change-in-production",
        validation_alias="SECRET_KEY"
    )
    DEBUG: bool = Field(default=False, validation_alias="DEBUG")
    TESTING: bool = Field(default=False, validation_alias="TESTING")
    
    # Database - FIXED: Using absolute path to instance folder
    SQLALCHEMY_DATABASE_URI: str = Field(
        default=f"sqlite:///{DB_PATH.as_posix()}",
        validation_alias="DATABASE_URL"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_ECHO: bool = Field(default=False, validation_alias="SQLALCHEMY_ECHO")
    
    SQLALCHEMY_ENGINE_OPTIONS: Dict[str, Any] = {
        "pool_recycle": 3600,
        "pool_pre_ping": True,
    }
    
    @validator("SQLALCHEMY_DATABASE_URI", pre=True)
    def validate_database_url(cls, v: str) -> str:
        """Ensure database URL is valid"""
        if not v:
            return f"sqlite:///{DB_PATH.as_posix()}"
        if v.startswith("sqlite"):
            return v
        try:
            PostgresDsn(v)
        except Exception:
            pass
        return v
    
    # Redis / Cache
    CACHE_TYPE: str = Field(default="RedisCache", validation_alias="CACHE_TYPE")
    CACHE_REDIS_URL: str = Field(
        default="redis://localhost:6379/2",
        validation_alias="CACHE_REDIS_URL"
    )
    CACHE_DEFAULT_TIMEOUT: int = Field(default=300, validation_alias="CACHE_DEFAULT_TIMEOUT")
    
    # Celery
    CELERY_BROKER_URL: str = Field(
        default="redis://localhost:6379/0",
        validation_alias="CELERY_BROKER_URL"
    )
    CELERY_RESULT_BACKEND: str = Field(
        default="redis://localhost:6379/1",
        validation_alias="CELERY_RESULT_BACKEND"
    )
    CELERY_TASK_SERIALIZER: str = "json"
    CELERY_RESULT_SERIALIZER: str = "json"
    CELERY_ACCEPT_CONTENT: List[str] = ["json"]
    CELERY_TIMEZONE: str = "Asia/Karachi"
    CELERY_ENABLE_UTC: bool = False
    CELERY_TASK_TRACK_STARTED: bool = True
    CELERY_TASK_TIME_LIMIT: int = 30 * 60
    CELERY_TASK_SOFT_TIME_LIMIT: int = 25 * 60
    CELERY_WORKER_PREFETCH_MULTIPLIER: int = 1
    CELERY_TASK_ACKS_LATE: bool = True
    CELERY_TASK_REJECT_ON_WORKER_LOST: bool = True
    
    # Email
    MAIL_SERVER: str = Field(
        default="mail.on-tracking.com",
        validation_alias="MAIL_SERVER"
    )
    MAIL_PORT: int = Field(default=26, validation_alias="MAIL_PORT")
    MAIL_USE_TLS: bool = Field(default=False, validation_alias="MAIL_USE_TLS")
    MAIL_USE_SSL: bool = Field(default=False, validation_alias="MAIL_USE_SSL")
    MAIL_USERNAME: str = Field(
        default="cs@on-tracking.com",
        validation_alias="MAIL_USERNAME"
    )
    MAIL_PASSWORD: str = Field(
        default="",
        validation_alias="MAIL_PASSWORD"
    )
    MAIL_DEFAULT_SENDER: str = Field(
        default="cs@on-tracking.com",
        validation_alias="MAIL_DEFAULT_SENDER"
    )
    MAIL_MAX_EMAILS: int = Field(default=100, validation_alias="MAIL_MAX_EMAILS")
    MAIL_ASCII_ATTACHMENTS: bool = False
    
    NOTIFICATION_EMAILS: List[str] = Field(
        default=[
            "Sharoon@on-tracking.com",
            "shaan@on-tracking.com",
            "alister@on-tracking.com",
            "cs@on-tracking.com",
            "Salman@on-tracking.com",
            "cr@on-tracking.com",
            "sunita@on-tracking.com"
        ],
        validation_alias="NOTIFICATION_EMAILS"
    )
    
    @validator("NOTIFICATION_EMAILS", pre=True)
    def parse_notification_emails(cls, v):
        if isinstance(v, str):
            return [email.strip() for email in v.split(",") if email.strip()]
        return v
    
    # GPS API
    GPS_API_URL: str = Field(
        default="",
        validation_alias="GPS_API_URL"
    )
    GPS_API_KEY: str = Field(
        default="",
        validation_alias="GPS_API_KEY"
    )
    GPS_SYNC_INTERVAL: int = Field(default=300, validation_alias="GPS_SYNC_INTERVAL")

    # Background scheduler (GPS sync, fuel rates, AMC snapshot, the month-end
    # management email). It runs in-process, so exactly one process must own
    # it: every worker starting its own would sync GPS N times over and send
    # the month-end report to senior management N times.
    #
    # Under gunicorn that is what `--preload` achieves - the application is
    # built once in the arbiter, before the workers are forked, so the
    # scheduler starts once. This switch is for the cases preload cannot
    # cover: a second web instance behind a load balancer, or a console that
    # should not be firing scheduled jobs at all.
    SCHEDULER_ENABLED: bool = Field(default=True, validation_alias="SCHEDULER_ENABLED")

    # Internal Database
    INTERNAL_DB_SERVER: str = Field(
        default="",
        validation_alias="INTERNAL_DB_SERVER"
    )
    INTERNAL_DB_USER: str = Field(
        default="",
        validation_alias="INTERNAL_DB_USER"
    )
    INTERNAL_DB_PASSWORD: str = Field(
        default="",
        validation_alias="INTERNAL_DB_PASSWORD"
    )
    INTERNAL_DB_DRIVER: str = Field(
        default="{ODBC Driver 17 for SQL Server}",
        validation_alias="INTERNAL_DB_DRIVER"
    )
    INTERNAL_DB_NAME: str = Field(
        default="SJ_MIS",
        validation_alias="INTERNAL_DB_NAME"
    )
    INTERNAL_DB_TIMEOUT: int = Field(default=10, validation_alias="INTERNAL_DB_TIMEOUT")
    
    @property
    def INTERNAL_DB_CONNECTION_STRING(self) -> str:
        return (
            f"DRIVER={self.INTERNAL_DB_DRIVER};"
            f"SERVER={self.INTERNAL_DB_SERVER};"
            f"DATABASE={self.INTERNAL_DB_NAME};"
            f"UID={self.INTERNAL_DB_USER};"
            f"PWD={self.INTERNAL_DB_PASSWORD}"
        )
    
    # Upload Settings
    UPLOAD_FOLDER: str = Field(
        default="uploads",
        validation_alias="UPLOAD_FOLDER"
    )
    MAX_CONTENT_LENGTH: int = Field(
        default=16 * 1024 * 1024,
        validation_alias="MAX_CONTENT_LENGTH"
    )
    ALLOWED_EXTENSIONS: List[str] = Field(
        default=[".xlsx", ".xls", ".csv", ".pdf", ".jpg", ".jpeg", ".png"],
        validation_alias="ALLOWED_EXTENSIONS"
    )
    # Explicit path to the wkhtmltopdf binary, which renders the invoice and
    # certificate templates. Leave empty to let PDFService find it on PATH or
    # in the standard install locations - set it only when it lives somewhere
    # unusual. Without it, documents fall back to a plain ReportLab layout.
    WKHTMLTOPDF_PATH: str = Field(
        default="",
        validation_alias="WKHTMLTOPDF_PATH"
    )
    
    @validator("ALLOWED_EXTENSIONS", pre=True)
    def parse_extensions(cls, v):
        if isinstance(v, str):
            return [ext.strip() for ext in v.split(",") if ext.strip()]
        return v
    
    # Security
    SESSION_COOKIE_SECURE: bool = Field(default=False, validation_alias="SESSION_COOKIE_SECURE")
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SAMESITE: str = "Lax"
    PERMANENT_SESSION_LIFETIME: int = Field(
        default=7 * 24 * 60 * 60,
        validation_alias="PERMANENT_SESSION_LIFETIME"
    )
    CSRF_ENABLED: bool = Field(default=True, validation_alias="CSRF_ENABLED")
    CSRF_TIME_LIMIT: int = Field(default=3600, validation_alias="CSRF_TIME_LIMIT")
    # Flask-WTF reads WTF_CSRF_TIME_LIMIT, not CSRF_TIME_LIMIT above - which
    # is why tokens were expiring after the library's own default hour no
    # matter what CSRF_TIME_LIMIT said.
    #
    # None ties a token's life to the session instead of a stopwatch. The
    # token is still session-bound and still checked; what stops happening is
    # a form that was open while someone did something else failing on
    # submit, with their typing lost. The session itself expires
    # (PERMANENT_SESSION_LIFETIME), and that is the control that matters.
    WTF_CSRF_TIME_LIMIT: Optional[int] = Field(
        default=None, validation_alias="WTF_CSRF_TIME_LIMIT"
    )
    
    CORS_ORIGINS: List[str] = Field(
        default=["http://localhost:5000", "http://127.0.0.1:5000"],
        validation_alias="CORS_ORIGINS"
    )
    
    @validator("CORS_ORIGINS", pre=True)
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            if v == "*":
                return ["*"]
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v
    
    # Rate Limiting
    RATELIMIT_ENABLED: bool = Field(default=True, validation_alias="RATELIMIT_ENABLED")
    RATELIMIT_DEFAULT: str = Field(default="100/hour", validation_alias="RATELIMIT_DEFAULT")
    RATELIMIT_STORAGE_URL: str = Field(
        default="redis://localhost:6379/3",
        validation_alias="RATELIMIT_STORAGE_URL"
    )
    RATELIMIT_STRATEGY: str = "fixed-window"
    RATELIMIT_HEADERS_ENABLED: bool = True
    
    # Logging
    LOG_LEVEL: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    LOG_FILE: str = Field(default="logs/app.log", validation_alias="LOG_FILE")
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"
    LOG_MAX_BYTES: int = 10 * 1024 * 1024
    LOG_BACKUP_COUNT: int = 10
    
    # PDF Generation
    WKHTMLTOPDF_PATH: Optional[str] = Field(
        default=None,
        validation_alias="WKHTMLTOPDF_PATH"
    )
    REPORTLAB_FONT_PATH: Optional[str] = Field(
        default=None,
        validation_alias="REPORTLAB_FONT_PATH"
    )
    
    # Timezone
    TIMEZONE: str = Field(default="Asia/Karachi", validation_alias="TIMEZONE")
    
    # API
    API_TITLE: str = "ON TRACK Vehicle Tracking API"
    API_VERSION: str = "1.0.0"
    API_DESCRIPTION: str = "Complete API for ON TRACK Vehicle Tracking Management System"
    API_PREFIX: str = "/api/v1"
    
    # Monitoring
    PROMETHEUS_ENABLED: bool = Field(default=True, validation_alias="PROMETHEUS_ENABLED")
    PROMETHEUS_NAMESPACE: str = "on_track"
    
    # System Paths
    PROJECT_ROOT: Path = Path(__file__).parent.parent
    INSTANCE_PATH: Path = Path(__file__).parent.parent / "instance"
    UPLOAD_PATH: Path = Path(__file__).parent.parent / "uploads"
    LOG_PATH: Path = Path(__file__).parent.parent / "logs"
    
    # Development Only
    DEBUG_TB_ENABLED: bool = Field(default=False, validation_alias="DEBUG_TB_ENABLED")
    DEBUG_TB_INTERCEPT_REDIRECTS: bool = False
    
    # Security Briefing Defaults
    SECURITY_BRIEFING_DEFAULT_SEGMENT: str = "COMMERCIAL"
    SECURITY_BRIEFING_DEFAULT_STATUS: str = "PENDING"
    
    # Payment Recovery Defaults
    PAYMENT_DEFAULT_DUE_DAYS: int = Field(default=30, validation_alias="PAYMENT_DEFAULT_DUE_DAYS")
    PAYMENT_LATE_FEE_PERCENTAGE: float = Field(default=0.0, validation_alias="PAYMENT_LATE_FEE_PERCENTAGE")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG: bool = True
    SQLALCHEMY_ECHO: bool = True
    CORS_ORIGINS: List[str] = ["http://localhost:5000", "http://127.0.0.1:5000"]
    GPS_SYNC_INTERVAL: int = 60
    RATELIMIT_ENABLED: bool = False
    DEBUG_TB_ENABLED: bool = True
    SESSION_COOKIE_SECURE: bool = False
    # FIXED: Using absolute path to instance folder
    SQLALCHEMY_DATABASE_URI: str = f"sqlite:///{DB_PATH.as_posix()}"


class TestingConfig(Config):
    """Testing configuration"""
    TESTING: bool = True
    DEBUG: bool = False
    SQLALCHEMY_DATABASE_URI: str = "sqlite:///:memory:"
    SQLALCHEMY_ECHO: bool = False
    CELERY_ALWAYS_EAGER: bool = True
    CELERY_EAGER_PROPAGATES_EXCEPTIONS: bool = True
    RATELIMIT_ENABLED: bool = False
    # In-memory cache: the suite must not require a running Redis.
    # Inheriting the base "redis" type made every app fixture fail to
    # build on a clean machine (ImportStringError on
    # flask_caching.backends.redis).
    CACHE_TYPE: str = "SimpleCache"
    # Initialise CSRFProtect so templates calling csrf_token() render. With this
    # off, that Jinja global is never registered and every page using it returns
    # 500 under test - which hides real page-level breakage from the suite.
    # WTF_CSRF_ENABLED stays False, so tests can still POST without a token.
    CSRF_ENABLED: bool = True
    WTF_CSRF_ENABLED: bool = False
    SESSION_COOKIE_SECURE: bool = False
    MAIL_SUPPRESS_SEND: bool = True
    UPLOAD_FOLDER: str = "/tmp/test_uploads"
    LOG_LEVEL: str = "ERROR"


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG: bool = False
    TESTING: bool = False
    SESSION_COOKIE_SECURE: bool = True
    CORS_ORIGINS: List[str] = []
    LOG_LEVEL: str = "WARNING"
    RATELIMIT_ENABLED: bool = True
    DEBUG_TB_ENABLED: bool = False
    SQLALCHEMY_ECHO: bool = False
    
    @validator('SQLALCHEMY_DATABASE_URI')
    def validate_production_database(cls, v: str) -> str:
        if v.startswith("sqlite"):
            raise ValueError("SQLite is not allowed in production. Use PostgreSQL instead.")
        return v


class DockerConfig(ProductionConfig):
    """Docker deployment configuration"""
    SESSION_COOKIE_SECURE: bool = False
    RATELIMIT_STORAGE_URL: str = "redis://redis:6379/3"
    CACHE_REDIS_URL: str = "redis://redis:6379/2"
    CELERY_BROKER_URL: str = "redis://redis:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/1"


def get_config(config_name: Optional[str] = None) -> Config:
    """Get configuration instance based on environment"""
    config_map = {
        "development": DevelopmentConfig,
        "testing": TestingConfig,
        "production": ProductionConfig,
        "docker": DockerConfig,
    }
    
    if config_name is None:
        env = os.environ.get("FLASK_ENV", "development")
        config_name = env
    
    config_class = config_map.get(config_name, DevelopmentConfig)
    config = config_class()
    
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        config.SQLALCHEMY_DATABASE_URI = database_url
    
    return config