# deployment/gunicorn.conf.py
"""
Gunicorn configuration for production
"""
import os
import multiprocessing

# Server socket
bind = "0.0.0.0:5000"
backlog = 2048

# Worker processes
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "gthread"
threads = 2
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 100
timeout = 120
graceful_timeout = 30
keepalive = 5

# Logging
accesslog = "logs/gunicorn_access.log"
errorlog = "logs/gunicorn_error.log"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(L)s'

# Process naming
proc_name = "on_track"

# Server mechanics
daemon = False
pidfile = "logs/gunicorn.pid"

# SSL (optional)
# keyfile = "deployment/ssl/private.key"
# certfile = "deployment/ssl/certificate.crt"

# Preload application
preload_app = True

# Environment
raw_env = [
    "FLASK_APP=src/app.py",
    "FLASK_ENV=production",
]


def post_fork(server, worker):
    """Called after each worker fork"""
    server.log.info("Worker spawned (pid: %s)", worker.pid)


def pre_fork(server, worker):
    """Called before each worker fork"""
    pass


def pre_exec(server):
    """Called before forking new master"""
    pass


def when_ready(server):
    """Called after server is started"""
    server.log.info("Gunicorn server is ready!")