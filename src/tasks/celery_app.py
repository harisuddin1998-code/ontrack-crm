# src/tasks/celery_app.py
"""
Celery application for the worker and beat containers.

`celery -A src.tasks.celery_app worker` imports this module and looks for a
Celery instance on it, so the module-level `celery` below is the name the
compose services bind to. It was previously an empty file, which is why both
containers crash-looped.

Tasks execute inside a Flask application context, so the database session,
configuration and logging behave exactly as they do while serving a request.

The Flask application built here has the background scheduler switched off.
The web process owns that schedule, and a worker starting its own would run
every job a second time - including the month-end report to senior
management, once per container. See SCHEDULER_ENABLED in src/config.py.
"""
import os

from celery import Celery

from src.config import get_config

# Must be set before the application is built: create_app() reads
# SCHEDULER_ENABLED off the config, which is populated from the environment.
os.environ["SCHEDULER_ENABLED"] = "false"

# Task modules are imported for their side effect of registering tasks. A
# module listed here that defines none is harmless, so new task files can be
# added to their matching module without touching this list again.
TASK_MODULES = [
    "src.tasks.email_tasks",
    "src.tasks.gps_tasks",
    "src.tasks.notification_tasks",
    "src.tasks.report_tasks",
    "src.tasks.sync_tasks",
]


def _celery_settings(config) -> dict:
    """Translate the CELERY_* config fields into Celery's own setting names."""
    return {
        "broker_url": config.CELERY_BROKER_URL,
        "result_backend": config.CELERY_RESULT_BACKEND,
        "task_serializer": config.CELERY_TASK_SERIALIZER,
        "result_serializer": config.CELERY_RESULT_SERIALIZER,
        "accept_content": config.CELERY_ACCEPT_CONTENT,
        "timezone": config.CELERY_TIMEZONE,
        "enable_utc": config.CELERY_ENABLE_UTC,
        "task_track_started": config.CELERY_TASK_TRACK_STARTED,
        "task_time_limit": config.CELERY_TASK_TIME_LIMIT,
        "task_soft_time_limit": config.CELERY_TASK_SOFT_TIME_LIMIT,
        "worker_prefetch_multiplier": config.CELERY_WORKER_PREFETCH_MULTIPLIER,
        # Acknowledge after the task returns, so work is redelivered rather
        # than lost if a worker dies mid-task.
        "task_acks_late": config.CELERY_TASK_ACKS_LATE,
        "task_reject_on_worker_lost": config.CELERY_TASK_REJECT_ON_WORKER_LOST,
    }


def create_celery_app(flask_app=None) -> Celery:
    """
    Build the Celery application.

    Args:
        flask_app: An existing Flask application to bind tasks to. Built from
            the factory when omitted, which is the case for the worker and
            beat processes that import this module directly.

    Returns:
        A configured Celery instance whose tasks run in an app context.
    """
    if flask_app is None:
        # Imported here rather than at module scope: src.app imports a good
        # deal of the application, and only the branch that actually needs it
        # should pay for that.
        from src.app import create_app

        flask_app = create_app()

    celery_app = Celery(flask_app.import_name, include=TASK_MODULES)
    celery_app.conf.update(_celery_settings(get_config()))

    class ContextTask(celery_app.Task):
        """Runs every task inside the Flask application context."""

        def __call__(self, *args, **kwargs):
            with flask_app.app_context():
                return self.run(*args, **kwargs)

    celery_app.Task = ContextTask
    celery_app.flask_app = flask_app
    return celery_app


celery = create_celery_app()

# `celery -A ... worker` accepts either name; both are exported so neither
# spelling of the -A argument breaks.
celery_app = celery
