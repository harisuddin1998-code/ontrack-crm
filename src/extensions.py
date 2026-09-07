# src/extensions.py
"""
Flask Extensions Initialization
"""
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_socketio import SocketIO
from flask_mail import Mail
from flask_caching import Cache
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager
from prometheus_flask_exporter import PrometheusMetrics
import redis

# Database
db = SQLAlchemy()

# Database Migrations
migrate = Migrate()

# Real-time WebSocket
socketio = SocketIO()

# Email
mail = Mail()

# Caching
cache = Cache()

# CORS
cors = CORS()

# Rate Limiting
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100 per hour"],
    storage_uri="memory://",
    strategy="fixed-window"
)

# CSRF Protection
csrf = CSRFProtect()

# Flask-Login - ADDED
login_manager = LoginManager()

# Prometheus Metrics
metrics = PrometheusMetrics(app=None)

# Redis client
redis_client = None


def init_redis(app):
    """Initialize Redis client"""
    global redis_client
    try:
        redis_url = app.config.get('CACHE_REDIS_URL', 'redis://localhost:6379/2')
        redis_client = redis.from_url(redis_url)
        redis_client.ping()
        app.logger.info("Redis connection established successfully")
        return redis_client
    except Exception as e:
        app.logger.warning(f"Redis connection failed: {e}")
        return None


def init_extensions(app):
    """Initialize all extensions with app context"""
    
    # Database
    db.init_app(app)
    
    # Migrations
    migrate.init_app(app, db)
    
    # SocketIO
    socketio.init_app(
        app,
        cors_allowed_origins=app.config.get('CORS_ORIGINS', '*'),
        async_mode='threading',
        ping_timeout=60,
        ping_interval=25
    )
    
    # Mail
    mail.init_app(app)
    
    # Cache
    cache.init_app(
        app,
        config={
            'CACHE_TYPE': app.config.get('CACHE_TYPE', 'RedisCache'),
            'CACHE_REDIS_URL': app.config.get('CACHE_REDIS_URL'),
            'CACHE_DEFAULT_TIMEOUT': app.config.get('CACHE_DEFAULT_TIMEOUT', 300)
        }
    )
    
    # CORS
    cors.init_app(
        app,
        origins=app.config.get('CORS_ORIGINS', ['*']),
        supports_credentials=True,
        allow_headers=['Content-Type', 'Authorization'],
        methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS']
    )
    
    # Rate Limiting
    limiter.init_app(app)
    
    # CSRF
    if app.config.get('CSRF_ENABLED', True):
        csrf.init_app(app)
    
    # Flask-Login - ADDED
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please login to access this page.'
    login_manager.login_message_category = 'info'
    
    # Prometheus Metrics
    metrics.init_app(app)
    
    # Redis
    init_redis(app)
    
    app.logger.info("All extensions initialized successfully")
    
    return app