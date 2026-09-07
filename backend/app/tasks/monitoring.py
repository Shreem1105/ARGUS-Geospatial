from __future__ import annotations

from uuid import UUID

from celery import Task

from app.core.config import get_settings
from app.services.monitoring_service import (
    MonitorRunCancelledError,
    MonitorRunTransientError,
    execute_monitor_run_workflow,
    mark_job_cancelled,
    mark_job_failed,
    mark_job_retry_pending,
    scan_monitor_schedules,
)
from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.monitoring.run_monitor_workflow_task", bind=True)
def run_monitor_workflow_task(self: Task, job_id: str) -> dict[str, object]:
    settings = get_settings()

    try:
        parsed_job_id = UUID(job_id)
    except ValueError:
        return {"status": "invalid_job_id"}

    try:
        return execute_monitor_run_workflow(job_id=parsed_job_id, celery_task_id=self.request.id)
    except MonitorRunCancelledError:
        mark_job_cancelled(job_id=parsed_job_id, message="Job cancelled during execution")
        return {"status": "cancelled", "job_id": str(parsed_job_id)}
    except MonitorRunTransientError as exc:
        retry_attempt = int(self.request.retries) + 1
        max_retries = settings.job_max_retries

        if self.request.retries < max_retries:
            backoff = settings.job_retry_backoff_seconds * (2 ** int(self.request.retries))
            mark_job_retry_pending(
                job_id=parsed_job_id,
                stage=exc.stage,
                retry_attempt=retry_attempt,
                max_retries=max_retries,
                message=str(exc),
            )
            raise self.retry(exc=exc, countdown=backoff, max_retries=max_retries)

        mark_job_failed(
            job_id=parsed_job_id,
            stage=exc.stage,
            error_type="transient_error",
            message=str(exc),
        )
        raise
    except Exception as exc:
        mark_job_failed(
            job_id=parsed_job_id,
            stage="failed",
            error_type=exc.__class__.__name__,
            message="Monitoring workflow execution failed",
        )
        raise


@celery_app.task(name="app.tasks.monitoring.scan_monitor_schedules_task")
def scan_monitor_schedules_task() -> dict[str, object]:
    return scan_monitor_schedules()

