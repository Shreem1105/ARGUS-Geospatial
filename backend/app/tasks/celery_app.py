from __future__ import annotations

from celery import Celery
from celery.schedules import schedule

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "argus",
    broker=settings.effective_celery_broker_url,
    backend=settings.effective_celery_result_backend,
    include=["app.tasks.monitoring", "app.tasks.alerts"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_default_queue="monitoring",
    result_extended=True,
    task_time_limit=settings.celery_task_time_limit_seconds,
    task_soft_time_limit=settings.celery_task_soft_time_limit_seconds,
    broker_transport_options={
        "socket_connect_timeout": 2,
        "socket_timeout": 2,
        "retry_on_timeout": False,
    },
    result_backend_transport_options={
        "socket_connect_timeout": 2,
        "socket_timeout": 2,
    },
    beat_schedule={
        "scan-monitor-schedules": {
            "task": "app.tasks.monitoring.scan_monitor_schedules_task",
            "schedule": schedule(run_every=settings.monitor_schedule_scan_seconds),
        }
    },
)

