from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from celery.exceptions import CeleryError
from kombu.exceptions import KombuError
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import Select, func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.context import (
    LandCoverProvider,
    get_context_provider,
    get_environmental_provider,
    get_land_cover_provider,
    get_population_provider,
)
from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models import AnalysisJob, ChangeEvent, Monitor, MonitorRun, MonitorSchedule, SatelliteObservation
from app.satellite import get_satellite_provider
from app.schemas import (
    AnalysisJobRead,
    AnalysisJobStatus,
    AnalysisJobType,
    ChangeAnalysisCreateRequest,
    JobCancelResponse,
    MonitorRunEnqueueRequest,
    MonitorRunEnqueueResponse,
    MonitorRunRead,
    MonitorRunStatus,
    MonitorRunType,
    MonitorScheduleRead,
    MonitorScheduleWrite,
    ObservationSearchRequest,
)
from app.services.change_analysis_service import (
    ChangeAnalysisConflictError,
    ChangeAnalysisPersistenceError,
    ChangeAnalysisProcessingError,
    ChangeAnalysisQueryError,
    ChangeAnalysisValidationError,
    create_change_analysis,
)
from app.services.change_event_service import (
    ChangeEventConflictError,
    ChangeEventGenerationError,
    ChangeEventPersistenceError,
    ChangeEventQueryError,
    generate_change_events,
)
from app.services.context_service import (
    ContextPersistenceError,
    ContextProviderRequestError,
    ContextQueryError,
    ContextQueryTooLargeError,
    refresh_monitor_context,
)
from app.services.environment_service import (
    EnvironmentPersistenceError,
    EnvironmentProviderRequestError,
    EnvironmentQueryError,
    EnvironmentQueryTooLargeError,
    refresh_monitor_environment,
)
from app.services.exposure_service import (
    ExposureConflictError,
    ExposurePersistenceError,
    ExposureProviderRequestError,
    ExposureQueryError,
    compute_analysis_exposures,
    get_change_event_exposure,
)
from app.services.impact_service import (
    ImpactConflictError,
    ImpactPersistenceError,
    ImpactQueryError,
    compute_analysis_impacts,
    get_change_event_impact_summary,
)
from app.services.landcover_service import (
    LandCoverPersistenceError,
    LandCoverProviderRequestError,
    LandCoverQueryError,
    refresh_monitor_land_cover_source,
)
from app.services.observation_service import (
    ObservationPersistenceError,
    ObservationProviderRequestError,
    ObservationQueryError,
    search_and_store_observations,
)
from app.services.population_service import (
    PopulationPersistenceError,
    PopulationProviderRequestError,
    PopulationQueryError,
    PopulationQueryTooLargeError,
    refresh_monitor_population,
)
from app.services.prepared_observation_service import (
    PreparedObservationPersistenceError,
    PreparedObservationProcessingError,
    PreparedObservationProviderError,
    PreparedObservationQueryError,
    prepare_observation,
)

logger = logging.getLogger(__name__)

FINAL_JOB_STATUSES = {
    AnalysisJobStatus.SUCCEEDED.value,
    AnalysisJobStatus.FAILED.value,
    AnalysisJobStatus.CANCELLED.value,
}

TRANSIENT_PROVIDER_ERRORS = (
    ObservationProviderRequestError,
    PreparedObservationProviderError,
    LandCoverProviderRequestError,
    ExposureProviderRequestError,
)

RETRYABLE_CONTEXT_ERRORS = (
    ContextProviderRequestError,
    PopulationProviderRequestError,
    EnvironmentProviderRequestError,
)

SCHEDULER_ADVISORY_LOCK_ID = 438_921_552


class JobQueryError(Exception):
    pass


class JobPersistenceError(Exception):
    pass


class JobConflictError(Exception):
    pass


class JobQueueUnavailableError(Exception):
    pass


class MonitorRunTransientError(Exception):
    def __init__(self, message: str, *, stage: str) -> None:
        super().__init__(message)
        self.stage = stage


class MonitorRunCancelledError(Exception):
    pass


@dataclass(slots=True)
class _ScenePair:
    before: Any
    after: Any
    selection_rule: str


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


def _analysis_event_ids(db_session: Session, *, monitor_id: UUID, analysis_id: UUID) -> list[UUID]:
    try:
        return db_session.execute(
            select(ChangeEvent.id).where(
                ChangeEvent.monitor_id == monitor_id,
                ChangeEvent.analysis_id == analysis_id,
            )
        ).scalars().all()
    except SQLAlchemyError as exc:
        raise JobQueryError("Failed to fetch analysis events for reuse") from exc


def _reuse_existing_analysis_impact_payload(
    db_session: Session,
    *,
    monitor_id: UUID,
    analysis_id: UUID,
) -> dict[str, Any] | None:
    event_ids = _analysis_event_ids(db_session, monitor_id=monitor_id, analysis_id=analysis_id)
    if not event_ids:
        return {
            "analysis_id": str(analysis_id),
            "event_count": 0,
            "computed": 0,
            "failed": 0,
            "impact_relationship_count": 0,
            "elapsed_seconds": 0.0,
        }

    relationship_count = 0
    for event_id in event_ids:
        summary = get_change_event_impact_summary(
            db_session,
            monitor_id=monitor_id,
            event_id=event_id,
        )
        if summary is None:
            return None
        relationship_count += int(summary.impact_relationship_count)

    return {
        "analysis_id": str(analysis_id),
        "event_count": len(event_ids),
        "computed": 0,
        "failed": 0,
        "impact_relationship_count": relationship_count,
        "elapsed_seconds": 0.0,
    }


def _reuse_existing_analysis_exposure_payload(
    db_session: Session,
    *,
    monitor_id: UUID,
    analysis_id: UUID,
) -> dict[str, Any] | None:
    event_ids = _analysis_event_ids(db_session, monitor_id=monitor_id, analysis_id=analysis_id)
    if not event_ids:
        return {
            "analysis_id": str(analysis_id),
            "event_count": 0,
            "computed": 0,
            "reused": 0,
            "failed": 0,
            "elapsed_seconds": 0.0,
        }

    for event_id in event_ids:
        summary = get_change_event_exposure(
            db_session,
            monitor_id=monitor_id,
            event_id=event_id,
        )
        if summary is None:
            return None

    return {
        "analysis_id": str(analysis_id),
        "event_count": len(event_ids),
        "computed": 0,
        "reused": len(event_ids),
        "failed": 0,
        "elapsed_seconds": 0.0,
    }


def _compute_context_products_for_run(
    db_session: Session,
    *,
    job: AnalysisJob,
    run: MonitorRun,
    analysis_id: UUID,
    parameters: dict[str, Any],
    event_count: int,
    warnings: list[str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    impact_payload: dict[str, Any] | None = None
    exposure_payload: dict[str, Any] | None = None

    if event_count <= 0:
        return impact_payload, exposure_payload

    _update_progress(db_session, job=job, run=run, stage="computing_impacts", progress_percent=84.0)
    _ensure_not_cancelled(db_session, job_id=job.id)
    try:
        impact_result = compute_analysis_impacts(
            db_session,
            monitor_id=job.monitor_id,
            analysis_id=analysis_id,
            nearby_buffer_m=float(parameters.get("impact_nearby_buffer_m") or 100.0),
        )
        if impact_result is not None:
            run.impacts_computed = True
            impact_payload = impact_result.response.model_dump(mode="json")
            db_session.add(run)
            db_session.commit()
    except ImpactConflictError as exc:
        try:
            reused_payload = _reuse_existing_analysis_impact_payload(
                db_session,
                monitor_id=job.monitor_id,
                analysis_id=analysis_id,
            )
        except (JobQueryError, ImpactQueryError):
            reused_payload = None

        if reused_payload is not None:
            run.impacts_computed = True
            impact_payload = reused_payload
            db_session.add(run)
            db_session.commit()
            logger.info(
                "Reused existing analysis impact payload after conflict job_id=%s run_id=%s monitor_id=%s analysis_id=%s",
                job.id,
                run.id,
                job.monitor_id,
                analysis_id,
            )
        else:
            warnings.append(f"impact_compute_failed:{exc.__class__.__name__}")
    except (ImpactPersistenceError, ImpactQueryError) as exc:
        warnings.append(f"impact_compute_failed:{exc.__class__.__name__}")

    _update_progress(db_session, job=job, run=run, stage="computing_exposures", progress_percent=92.0)
    _ensure_not_cancelled(db_session, job_id=job.id)
    try:
        exposure_result = compute_analysis_exposures(
            db_session,
            monitor_id=job.monitor_id,
            analysis_id=analysis_id,
            land_cover_provider=get_land_cover_provider(),
            environment_nearby_buffer_m=float(parameters.get("environment_nearby_buffer_m") or 500.0),
        )
        if exposure_result is not None:
            run.exposures_computed = True
            exposure_payload = exposure_result.response.model_dump(mode="json")
            db_session.add(run)
            db_session.commit()
    except TRANSIENT_PROVIDER_ERRORS as exc:
        warnings.append(f"exposure_provider_failed:{exc.__class__.__name__}")
    except ExposureConflictError as exc:
        try:
            reused_payload = _reuse_existing_analysis_exposure_payload(
                db_session,
                monitor_id=job.monitor_id,
                analysis_id=analysis_id,
            )
        except (JobQueryError, ExposureQueryError):
            reused_payload = None

        if reused_payload is not None:
            run.exposures_computed = True
            exposure_payload = reused_payload
            db_session.add(run)
            db_session.commit()
            logger.info(
                "Reused existing analysis exposure payload after conflict job_id=%s run_id=%s monitor_id=%s analysis_id=%s",
                job.id,
                run.id,
                job.monitor_id,
                analysis_id,
            )
        else:
            warnings.append(f"exposure_compute_failed:{exc.__class__.__name__}")
    except (ExposurePersistenceError, ExposureQueryError) as exc:
        warnings.append(f"exposure_compute_failed:{exc.__class__.__name__}")

    return impact_payload, exposure_payload


def _job_to_read(job: AnalysisJob) -> AnalysisJobRead:
    return AnalysisJobRead(
        id=job.id,
        monitor_id=job.monitor_id,
        job_type=AnalysisJobType(job.job_type),
        status=AnalysisJobStatus(job.status),
        celery_task_id=job.celery_task_id,
        progress_stage=job.progress_stage,
        progress_percent=float(job.progress_percent),
        requested_parameters=dict(job.requested_parameters or {}),
        result=dict(job.result) if isinstance(job.result, dict) else None,
        error=dict(job.error) if isinstance(job.error, dict) else None,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        updated_at=job.updated_at,
    )


def _run_to_read(run: MonitorRun) -> MonitorRunRead:
    return MonitorRunRead(
        id=run.id,
        monitor_id=run.monitor_id,
        analysis_job_id=run.analysis_job_id,
        run_type=MonitorRunType(run.run_type),
        status=MonitorRunStatus(run.status),
        search_window_start=run.search_window_start,
        search_window_end=run.search_window_end,
        observations_found=run.observations_found,
        observations_inserted=run.observations_inserted,
        before_observation_id=run.before_observation_id,
        after_observation_id=run.after_observation_id,
        before_prepared_id=run.before_prepared_id,
        after_prepared_id=run.after_prepared_id,
        analysis_id=run.analysis_id,
        events_generated=run.events_generated,
        impacts_computed=run.impacts_computed,
        exposures_computed=run.exposures_computed,
        progress_log=list(run.progress_log or []),
        requested_parameters=dict(run.requested_parameters or {}),
        result=dict(run.result) if isinstance(run.result, dict) else None,
        error=dict(run.error) if isinstance(run.error, dict) else None,
        started_at=run.started_at,
        completed_at=run.completed_at,
        updated_at=run.updated_at,
    )


def _schedule_to_read(schedule: MonitorSchedule) -> MonitorScheduleRead:
    interval_hours = max(1, int(round(schedule.cadence_minutes / 60.0)))

    return MonitorScheduleRead(
        monitor_id=schedule.monitor_id,
        enabled=schedule.enabled,
        interval_hours=interval_hours,
        cadence_minutes=schedule.cadence_minutes,
        lookback_days=schedule.lookback_days,
        max_cloud_cover=schedule.max_cloud_cover,
        search_limit=schedule.search_limit,
        auto_context_refresh=schedule.auto_context_refresh,
        auto_population_refresh=schedule.auto_population_refresh,
        auto_land_cover_refresh=schedule.auto_land_cover_refresh,
        auto_environment_refresh=schedule.auto_environment_refresh,
        threshold=schedule.threshold,
        minimum_change_area_m2=schedule.minimum_change_area_m2,
        impact_nearby_buffer_m=schedule.impact_nearby_buffer_m,
        environment_nearby_buffer_m=schedule.environment_nearby_buffer_m,
        next_run_at=schedule.next_run_after,
        last_scan_at=schedule.last_scan_at,
        last_run_at=schedule.last_run_at,
        last_enqueued_job_id=schedule.last_enqueued_job_id,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
    )


def _append_progress(run: MonitorRun, *, stage: str, progress_percent: float, note: str | None = None) -> None:
    entries = list(run.progress_log or [])
    payload: dict[str, Any] = {
        "stage": stage,
        "progress_percent": round(progress_percent, 3),
        "at": _utc_now().isoformat(),
    }
    if note:
        payload["note"] = note
    entries.append(payload)
    run.progress_log = entries


def _update_progress(
    db_session: Session,
    *,
    job: AnalysisJob,
    run: MonitorRun,
    stage: str,
    progress_percent: float,
    note: str | None = None,
) -> None:
    job.progress_stage = stage
    job.progress_percent = max(0.0, min(float(progress_percent), 100.0))
    _append_progress(run, stage=stage, progress_percent=job.progress_percent, note=note)

    try:
        db_session.add(job)
        db_session.add(run)
        db_session.commit()
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise JobPersistenceError("Failed to persist job progress") from exc


def _active_monitor_jobs_count(db_session: Session, monitor_id: UUID) -> int:
    try:
        return int(
            db_session.execute(
                select(func.count(AnalysisJob.id)).where(
                    AnalysisJob.monitor_id == monitor_id,
                    AnalysisJob.job_type == AnalysisJobType.MONITOR_RUN.value,
                    AnalysisJob.status.in_([AnalysisJobStatus.QUEUED.value, AnalysisJobStatus.RUNNING.value]),
                )
            ).scalar_one()
        )
    except SQLAlchemyError as exc:
        raise JobQueryError("Failed to check active monitor jobs") from exc


def _build_requested_parameters(
    *,
    settings: Settings,
    request: MonitorRunEnqueueRequest,
    run_type: MonitorRunType,
) -> dict[str, Any]:
    return {
        "run_type": run_type.value,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "lookback_days": request.lookback_days,
        "max_cloud_cover": (
            request.max_cloud_cover
            if request.max_cloud_cover is not None
            else settings.monitor_default_max_cloud_cover
        ),
        "search_limit": request.search_limit if request.search_limit is not None else settings.monitor_default_search_limit,
        "threshold": request.threshold,
        "minimum_change_area_m2": request.minimum_change_area_m2,
        "impact_nearby_buffer_m": request.impact_nearby_buffer_m,
        "environment_nearby_buffer_m": request.environment_nearby_buffer_m,
        "auto_context_refresh": request.auto_context_refresh,
        "auto_population_refresh": request.auto_population_refresh,
        "auto_land_cover_refresh": request.auto_land_cover_refresh,
        "auto_environment_refresh": request.auto_environment_refresh,
        "force_reprocess": request.force_reprocess,
    }


def enqueue_monitor_run_job(
    db_session: Session,
    *,
    monitor_id: UUID,
    request: MonitorRunEnqueueRequest,
    run_type: MonitorRunType = MonitorRunType.MANUAL,
) -> MonitorRunEnqueueResponse | None:
    settings = get_settings()

    monitor = db_session.execute(select(Monitor).where(Monitor.id == monitor_id)).scalar_one_or_none()
    if monitor is None:
        return None

    if _active_monitor_jobs_count(db_session, monitor_id) > 0:
        raise JobConflictError("Monitor already has an active run")

    parameters = _build_requested_parameters(settings=settings, request=request, run_type=run_type)

    job = AnalysisJob(
        monitor_id=monitor_id,
        job_type=AnalysisJobType.MONITOR_RUN.value,
        status=AnalysisJobStatus.QUEUED.value,
        progress_stage="queued",
        progress_percent=0.0,
        requested_parameters=_jsonable(parameters),
    )
    run = MonitorRun(
        monitor_id=monitor_id,
        analysis_job=job,
        run_type=run_type.value,
        status=MonitorRunStatus.STARTED.value,
        requested_parameters=_jsonable(parameters),
        progress_log=[
            {
                "stage": "queued",
                "progress_percent": 0.0,
                "at": _utc_now().isoformat(),
            }
        ],
    )

    try:
        db_session.add(job)
        db_session.add(run)
        db_session.commit()
        db_session.refresh(job)
        db_session.refresh(run)
    except IntegrityError as exc:
        db_session.rollback()
        raise JobConflictError("Monitor already has an active run") from exc
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise JobPersistenceError("Failed to create analysis job") from exc

    logger.info(
        "Enqueued monitor run job record job_id=%s run_id=%s monitor_id=%s run_type=%s",
        job.id,
        run.id,
        monitor_id,
        run_type.value,
    )

    try:
        from app.tasks.celery_app import celery_app

        async_result = celery_app.send_task(
            "app.tasks.monitoring.run_monitor_workflow_task",
            args=[str(job.id)],
            queue="monitoring",
            ignore_result=True,
            retry=False,
        )
        job.celery_task_id = async_result.id
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        logger.info(
            "Queued monitor run task to celery job_id=%s run_id=%s monitor_id=%s task_id=%s",
            job.id,
            run.id,
            monitor_id,
            async_result.id,
        )
    except (KombuError, RedisError, OSError, CeleryError, RuntimeError) as exc:
        db_session.rollback()
        job.status = AnalysisJobStatus.FAILED.value
        job.progress_stage = "enqueue_failed"
        job.progress_percent = 100.0
        job.completed_at = _utc_now()
        job.error = {
            "type": "queue_unavailable",
            "message": "Unable to enqueue monitor run task",
        }
        run.status = MonitorRunStatus.FAILED.value
        run.completed_at = _utc_now()
        run.error = {
            "type": "queue_unavailable",
            "message": "Unable to enqueue monitor run task",
        }
        _append_progress(run, stage="enqueue_failed", progress_percent=100.0)
        try:
            db_session.add(job)
            db_session.add(run)
            db_session.commit()
        except SQLAlchemyError:
            db_session.rollback()
        raise JobQueueUnavailableError("Unable to enqueue monitoring task") from exc

    return MonitorRunEnqueueResponse(job=_job_to_read(job), run=_run_to_read(run))


def get_analysis_job(db_session: Session, *, job_id: UUID) -> AnalysisJobRead | None:
    try:
        job = db_session.execute(select(AnalysisJob).where(AnalysisJob.id == job_id)).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise JobQueryError("Failed to fetch analysis job") from exc

    if job is None:
        return None
    return _job_to_read(job)


def cancel_analysis_job(db_session: Session, *, job_id: UUID) -> JobCancelResponse | None:
    try:
        row = db_session.execute(
            select(AnalysisJob, MonitorRun)
            .join(MonitorRun, MonitorRun.analysis_job_id == AnalysisJob.id)
            .where(AnalysisJob.id == job_id)
        ).one_or_none()
    except SQLAlchemyError as exc:
        raise JobQueryError("Failed to fetch analysis job") from exc

    if row is None:
        return None

    job, run = row
    if job.status not in FINAL_JOB_STATUSES:
        job.status = AnalysisJobStatus.CANCELLED.value
        job.progress_stage = "cancelled"
        job.progress_percent = 100.0
        job.completed_at = _utc_now()
        if run.status not in {MonitorRunStatus.SUCCEEDED.value, MonitorRunStatus.NO_NEW_IMAGERY.value, MonitorRunStatus.PARTIAL.value}:
            run.status = MonitorRunStatus.CANCELLED.value
            run.completed_at = _utc_now()
            _append_progress(run, stage="cancelled", progress_percent=100.0)

    try:
        db_session.add(job)
        db_session.add(run)
        db_session.commit()
        db_session.refresh(job)
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise JobPersistenceError("Failed to cancel job") from exc

    if job.celery_task_id:
        try:
            from app.tasks.celery_app import celery_app

            celery_app.control.revoke(job.celery_task_id, terminate=False)
        except Exception:
            logger.warning("Unable to revoke celery task job_id=%s task_id=%s", job.id, job.celery_task_id)

    return JobCancelResponse(cancelled=True, job=_job_to_read(job))


def _monitor_exists(db_session: Session, monitor_id: UUID) -> bool:
    try:
        return bool(db_session.execute(select(Monitor.id).where(Monitor.id == monitor_id)).scalar_one_or_none())
    except SQLAlchemyError as exc:
        raise JobQueryError("Failed to fetch monitor") from exc


def list_monitor_runs(
    db_session: Session,
    *,
    monitor_id: UUID,
    limit: int,
    offset: int,
    status: MonitorRunStatus | None,
) -> list[MonitorRunRead] | None:
    if not _monitor_exists(db_session, monitor_id):
        return None

    try:
        statement: Select[tuple[MonitorRun]] = select(MonitorRun).where(MonitorRun.monitor_id == monitor_id)
        if status is not None:
            statement = statement.where(MonitorRun.status == status.value)
        statement = statement.order_by(MonitorRun.started_at.desc(), MonitorRun.id.desc()).limit(limit).offset(offset)
        runs = db_session.execute(statement).scalars().all()
    except SQLAlchemyError as exc:
        raise JobQueryError("Failed to list monitor runs") from exc

    return [_run_to_read(run) for run in runs]


def get_monitor_run(db_session: Session, *, monitor_id: UUID, run_id: UUID) -> MonitorRunRead | None:
    try:
        run = db_session.execute(
            select(MonitorRun).where(
                MonitorRun.monitor_id == monitor_id,
                MonitorRun.id == run_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise JobQueryError("Failed to fetch monitor run") from exc

    if run is None:
        return None
    return _run_to_read(run)


def upsert_monitor_schedule(
    db_session: Session,
    *,
    monitor_id: UUID,
    request: MonitorScheduleWrite,
) -> MonitorScheduleRead | None:
    settings = get_settings()
    min_cadence = max(60, settings.min_monitor_schedule_cadence_minutes)

    if request.cadence_minutes < min_cadence:
        raise JobConflictError(f"interval_hours must be at least {max(1, int(min_cadence / 60))}")

    monitor = db_session.execute(select(Monitor).where(Monitor.id == monitor_id)).scalar_one_or_none()
    if monitor is None:
        return None

    try:
        schedule = db_session.execute(select(MonitorSchedule).where(MonitorSchedule.monitor_id == monitor_id)).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise JobQueryError("Failed to fetch monitor schedule") from exc

    now = _utc_now()
    if schedule is None:
        schedule = MonitorSchedule(
            monitor_id=monitor_id,
            enabled=request.enabled,
            cadence_minutes=request.cadence_minutes,
            lookback_days=request.lookback_days,
            max_cloud_cover=request.max_cloud_cover,
            search_limit=request.search_limit,
            auto_context_refresh=request.auto_context_refresh,
            auto_population_refresh=request.auto_population_refresh,
            auto_land_cover_refresh=request.auto_land_cover_refresh,
            auto_environment_refresh=request.auto_environment_refresh,
            threshold=request.threshold,
            minimum_change_area_m2=request.minimum_change_area_m2,
            impact_nearby_buffer_m=request.impact_nearby_buffer_m,
            environment_nearby_buffer_m=request.environment_nearby_buffer_m,
            next_run_after=(now if request.enabled else None),
        )
    else:
        schedule.enabled = request.enabled
        schedule.cadence_minutes = request.cadence_minutes
        schedule.lookback_days = request.lookback_days
        schedule.max_cloud_cover = request.max_cloud_cover
        schedule.search_limit = request.search_limit
        schedule.auto_context_refresh = request.auto_context_refresh
        schedule.auto_population_refresh = request.auto_population_refresh
        schedule.auto_land_cover_refresh = request.auto_land_cover_refresh
        schedule.auto_environment_refresh = request.auto_environment_refresh
        schedule.threshold = request.threshold
        schedule.minimum_change_area_m2 = request.minimum_change_area_m2
        schedule.impact_nearby_buffer_m = request.impact_nearby_buffer_m
        schedule.environment_nearby_buffer_m = request.environment_nearby_buffer_m

        if request.enabled and schedule.next_run_after is None:
            schedule.next_run_after = now
        if not request.enabled:
            schedule.next_run_after = None

    try:
        db_session.add(schedule)
        db_session.commit()
        db_session.refresh(schedule)
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise JobPersistenceError("Failed to save monitor schedule") from exc

    logger.info(
        "Saved monitor schedule monitor_id=%s enabled=%s interval_hours=%s next_run_at=%s",
        monitor_id,
        schedule.enabled,
        int(round(schedule.cadence_minutes / 60.0)),
        schedule.next_run_after.isoformat() if schedule.next_run_after else None,
    )

    return _schedule_to_read(schedule)


def get_monitor_schedule(db_session: Session, *, monitor_id: UUID) -> MonitorScheduleRead | None:
    if not _monitor_exists(db_session, monitor_id):
        return None

    try:
        schedule = db_session.execute(select(MonitorSchedule).where(MonitorSchedule.monitor_id == monitor_id)).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise JobQueryError("Failed to fetch monitor schedule") from exc

    if schedule is None:
        return None
    return _schedule_to_read(schedule)


def _resolve_previous_after_observation(
    db_session: Session,
    *,
    monitor_id: UUID,
    exclude_run_id: UUID,
) -> SatelliteObservation | None:
    try:
        previous_run = db_session.execute(
            select(MonitorRun)
            .where(
                MonitorRun.monitor_id == monitor_id,
                MonitorRun.id != exclude_run_id,
                MonitorRun.status.in_(
                    [
                        MonitorRunStatus.SUCCEEDED.value,
                        MonitorRunStatus.NO_NEW_IMAGERY.value,
                        MonitorRunStatus.PARTIAL.value,
                    ]
                ),
                MonitorRun.after_observation_id.is_not(None),
            )
            .order_by(MonitorRun.completed_at.desc().nullslast(), MonitorRun.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise JobQueryError("Failed to fetch previous monitor run") from exc

    if previous_run is None or previous_run.after_observation_id is None:
        return None

    try:
        return db_session.execute(
            select(SatelliteObservation).where(
                SatelliteObservation.id == previous_run.after_observation_id,
                SatelliteObservation.monitor_id == monitor_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise JobQueryError("Failed to fetch previous after observation") from exc


def _compute_search_window(
    *,
    run: MonitorRun,
    parameters: dict[str, Any],
    settings: Settings,
    previous_after_observation: SatelliteObservation | None,
) -> tuple[date, date, str]:
    explicit_start = parameters.get("start_date")
    explicit_end = parameters.get("end_date")
    if isinstance(explicit_start, str) and isinstance(explicit_end, str):
        return date.fromisoformat(explicit_start), date.fromisoformat(explicit_end), "explicit_request_window"

    if isinstance(explicit_start, date) and isinstance(explicit_end, date):
        return explicit_start, explicit_end, "explicit_request_window"

    today = _utc_now().date()
    lookback_days = int(parameters.get("lookback_days") or settings.monitor_first_run_lookback_days)
    floor_start = today - timedelta(days=max(lookback_days - 1, 0))

    if previous_after_observation is None:
        return floor_start, today, "first_run_lookback"

    overlap_days = settings.monitor_subsequent_overlap_days
    previous_date = previous_after_observation.acquired_at.astimezone(timezone.utc).date()
    candidate = previous_date - timedelta(days=overlap_days)
    start_date = candidate if candidate > floor_start else floor_start
    return start_date, today, "subsequent_overlap_window"


def _choose_scene_pair(
    *,
    observations: list[Any],
    previous_after_observation: SatelliteObservation | None,
) -> _ScenePair | None:
    ordered = sorted(
        observations,
        key=lambda item: item.acquired_at.astimezone(timezone.utc),
        reverse=True,
    )
    if len(ordered) < 2:
        return None

    after = ordered[0]

    if previous_after_observation is not None:
        for candidate in ordered[1:]:
            if candidate.id == previous_after_observation.id:
                if candidate.acquired_at < after.acquired_at:
                    return _ScenePair(before=candidate, after=after, selection_rule="reuse_previous_after_as_before")

    for candidate in ordered[1:]:
        if candidate.acquired_at < after.acquired_at:
            return _ScenePair(before=candidate, after=after, selection_rule="latest_pair")

    return None


def _load_job_and_run_for_update(db_session: Session, *, job_id: UUID) -> tuple[AnalysisJob | None, MonitorRun | None]:
    try:
        row = db_session.execute(
            select(AnalysisJob, MonitorRun)
            .join(MonitorRun, MonitorRun.analysis_job_id == AnalysisJob.id)
            .where(AnalysisJob.id == job_id)
            .with_for_update()
        ).one_or_none()
    except SQLAlchemyError as exc:
        raise JobQueryError("Failed to fetch job/run for execution") from exc

    if row is None:
        return None, None
    return row[0], row[1]


def _refresh_job_status(db_session: Session, *, job_id: UUID) -> AnalysisJobStatus:
    try:
        status_value = db_session.execute(
            select(AnalysisJob.status).where(AnalysisJob.id == job_id)
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise JobQueryError("Failed to check current job status") from exc

    if status_value is None:
        raise JobQueryError("Analysis job was not found")
    return AnalysisJobStatus(status_value)


def _ensure_not_cancelled(db_session: Session, *, job_id: UUID) -> None:
    status_value = _refresh_job_status(db_session, job_id=job_id)
    if status_value == AnalysisJobStatus.CANCELLED:
        raise MonitorRunCancelledError("Analysis job was cancelled")


def _update_schedule_after_run(
    db_session: Session,
    *,
    monitor_id: UUID,
    completed_at: datetime,
) -> None:
    try:
        schedule = db_session.execute(
            select(MonitorSchedule).where(MonitorSchedule.monitor_id == monitor_id).with_for_update()
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise JobPersistenceError("Failed to refresh monitor schedule state") from exc

    if schedule is None:
        return

    schedule.last_run_at = completed_at
    if schedule.enabled:
        schedule.next_run_after = completed_at + timedelta(minutes=schedule.cadence_minutes)

    db_session.add(schedule)


def _mark_job_final(
    db_session: Session,
    *,
    job: AnalysisJob,
    run: MonitorRun,
    job_status: AnalysisJobStatus,
    run_status: MonitorRunStatus,
    stage: str,
    result: dict[str, Any] | None,
    error: dict[str, Any] | None,
) -> None:
    completed_at = _utc_now()

    job.status = job_status.value
    job.progress_stage = stage
    job.progress_percent = 100.0
    job.completed_at = completed_at
    job.result = _jsonable(result) if result is not None else None
    job.error = _jsonable(error) if error is not None else None

    run.status = run_status.value
    run.completed_at = completed_at
    run.result = _jsonable(result) if result is not None else None
    run.error = _jsonable(error) if error is not None else None
    _append_progress(run, stage=stage, progress_percent=100.0)

    _update_schedule_after_run(
        db_session,
        monitor_id=run.monitor_id,
        completed_at=completed_at,
    )

    try:
        db_session.add(job)
        db_session.add(run)
        db_session.commit()
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise JobPersistenceError("Failed to persist final job state") from exc

    logger.info(
        "Finalized monitor run job_id=%s run_id=%s monitor_id=%s job_status=%s run_status=%s stage=%s",
        job.id,
        run.id,
        run.monitor_id,
        job.status,
        run.status,
        stage,
    )


def mark_job_retry_pending(
    *,
    job_id: UUID,
    stage: str,
    retry_attempt: int,
    max_retries: int,
    message: str,
) -> None:
    with SessionLocal() as db_session:
        job, run = _load_job_and_run_for_update(db_session, job_id=job_id)
        if job is None or run is None:
            return

        if job.status == AnalysisJobStatus.CANCELLED.value:
            return

        job.status = AnalysisJobStatus.QUEUED.value
        job.progress_stage = f"retry_{stage}"
        job.error = {
            "type": "transient_error",
            "stage": stage,
            "retry_attempt": retry_attempt,
            "max_retries": max_retries,
            "message": message,
        }
        _append_progress(
            run,
            stage=f"retry_{stage}",
            progress_percent=float(job.progress_percent),
            note=f"retry {retry_attempt}/{max_retries}",
        )

        try:
            db_session.add(job)
            db_session.add(run)
            db_session.commit()
        except SQLAlchemyError:
            db_session.rollback()


def mark_job_failed(
    *,
    job_id: UUID,
    stage: str,
    error_type: str,
    message: str,
) -> None:
    with SessionLocal() as db_session:
        job, run = _load_job_and_run_for_update(db_session, job_id=job_id)
        if job is None or run is None:
            return

        _mark_job_final(
            db_session,
            job=job,
            run=run,
            job_status=AnalysisJobStatus.FAILED,
            run_status=MonitorRunStatus.FAILED,
            stage=stage,
            result=None,
            error={
                "type": error_type,
                "stage": stage,
                "message": message,
            },
        )


def mark_job_cancelled(*, job_id: UUID, stage: str = "cancelled", message: str = "Job cancelled") -> None:
    with SessionLocal() as db_session:
        job, run = _load_job_and_run_for_update(db_session, job_id=job_id)
        if job is None or run is None:
            return

        _mark_job_final(
            db_session,
            job=job,
            run=run,
            job_status=AnalysisJobStatus.CANCELLED,
            run_status=MonitorRunStatus.CANCELLED,
            stage=stage,
            result=None,
            error={
                "type": "cancelled",
                "stage": stage,
                "message": message,
            },
        )


def execute_monitor_run_workflow(
    *,
    job_id: UUID,
    celery_task_id: str | None,
) -> dict[str, Any]:
    settings = get_settings()
    started_at = time.perf_counter()

    with SessionLocal() as db_session:
        job, run = _load_job_and_run_for_update(db_session, job_id=job_id)
        if job is None or run is None:
            return {"status": "missing"}

        if job.status in FINAL_JOB_STATUSES:
            return {"status": job.status, "job_id": str(job.id), "skipped": True}

        if job.status == AnalysisJobStatus.CANCELLED.value:
            _mark_job_final(
                db_session,
                job=job,
                run=run,
                job_status=AnalysisJobStatus.CANCELLED,
                run_status=MonitorRunStatus.CANCELLED,
                stage="cancelled",
                result=None,
                error={"type": "cancelled", "message": "Job cancelled before execution"},
            )
            return {"status": "cancelled", "job_id": str(job.id)}

        if celery_task_id and not job.celery_task_id:
            job.celery_task_id = celery_task_id

        job.status = AnalysisJobStatus.RUNNING.value
        if job.started_at is None:
            job.started_at = _utc_now()
        run.status = MonitorRunStatus.STARTED.value
        db_session.add(job)
        db_session.add(run)
        db_session.commit()

        logger.info(
            "Starting monitor workflow job_id=%s run_id=%s monitor_id=%s",
            job.id,
            run.id,
            job.monitor_id,
        )

        _update_progress(db_session, job=job, run=run, stage="initializing", progress_percent=5.0)
        _ensure_not_cancelled(db_session, job_id=job.id)

        parameters = dict(job.requested_parameters or {})
        warnings: list[str] = []

        if any(
            bool(parameters.get(flag))
            for flag in (
                "auto_context_refresh",
                "auto_population_refresh",
                "auto_land_cover_refresh",
                "auto_environment_refresh",
            )
        ):
            _update_progress(db_session, job=job, run=run, stage="refreshing_context", progress_percent=15.0)
            _ensure_not_cancelled(db_session, job_id=job.id)

            if parameters.get("auto_context_refresh"):
                try:
                    refresh_monitor_context(
                        db_session,
                        monitor_id=job.monitor_id,
                        provider=get_context_provider(),
                        feature_types=None,
                    )
                except (ContextPersistenceError, ContextQueryError, ContextQueryTooLargeError, ContextProviderRequestError) as exc:
                    warnings.append(f"context_refresh_failed:{exc.__class__.__name__}")
            if parameters.get("auto_population_refresh"):
                try:
                    refresh_monitor_population(
                        db_session,
                        monitor_id=job.monitor_id,
                        provider=get_population_provider(),
                    )
                except (
                    PopulationPersistenceError,
                    PopulationQueryError,
                    PopulationQueryTooLargeError,
                    PopulationProviderRequestError,
                ) as exc:
                    warnings.append(f"population_refresh_failed:{exc.__class__.__name__}")
            if parameters.get("auto_land_cover_refresh"):
                try:
                    refresh_monitor_land_cover_source(
                        db_session,
                        monitor_id=job.monitor_id,
                        provider=get_land_cover_provider(),
                    )
                except (LandCoverPersistenceError, LandCoverQueryError, LandCoverProviderRequestError) as exc:
                    warnings.append(f"land_cover_refresh_failed:{exc.__class__.__name__}")
            if parameters.get("auto_environment_refresh"):
                try:
                    refresh_monitor_environment(
                        db_session,
                        monitor_id=job.monitor_id,
                        provider=get_environmental_provider(),
                    )
                except (
                    EnvironmentPersistenceError,
                    EnvironmentQueryError,
                    EnvironmentQueryTooLargeError,
                    EnvironmentProviderRequestError,
                ) as exc:
                    warnings.append(f"environment_refresh_failed:{exc.__class__.__name__}")

        _update_progress(db_session, job=job, run=run, stage="searching_observations", progress_percent=30.0)
        _ensure_not_cancelled(db_session, job_id=job.id)

        previous_after = _resolve_previous_after_observation(
            db_session,
            monitor_id=job.monitor_id,
            exclude_run_id=run.id,
        )

        search_start, search_end, search_rule = _compute_search_window(
            run=run,
            parameters=parameters,
            settings=settings,
            previous_after_observation=previous_after,
        )
        run.search_window_start = search_start
        run.search_window_end = search_end
        db_session.add(run)
        db_session.commit()

        request = ObservationSearchRequest(
            start_date=search_start,
            end_date=search_end,
            max_cloud_cover=float(parameters.get("max_cloud_cover")) if parameters.get("max_cloud_cover") is not None else None,
            limit=int(parameters.get("search_limit") or settings.monitor_default_search_limit),
        )

        try:
            search_response = search_and_store_observations(
                db_session,
                monitor_id=job.monitor_id,
                request=request,
                provider=get_satellite_provider(),
            )
        except TRANSIENT_PROVIDER_ERRORS as exc:
            raise MonitorRunTransientError("Satellite search provider unavailable", stage="searching_observations") from exc
        except (ObservationPersistenceError, ObservationQueryError) as exc:
            raise JobPersistenceError("Failed to persist observation search results") from exc

        if search_response is None:
            raise JobConflictError("Monitor not found for observation search")

        run.observations_found = search_response.count
        run.observations_inserted = search_response.inserted_count
        db_session.add(run)
        db_session.commit()

        logger.info(
            "Observation search complete job_id=%s run_id=%s monitor_id=%s found=%s inserted=%s",
            job.id,
            run.id,
            job.monitor_id,
            search_response.count,
            search_response.inserted_count,
        )

        _update_progress(db_session, job=job, run=run, stage="selecting_scenes", progress_percent=38.0)

        pair = _choose_scene_pair(observations=search_response.observations, previous_after_observation=previous_after)
        if pair is None:
            result_payload = {
                "search_window_start": search_start,
                "search_window_end": search_end,
                "search_window_rule": search_rule,
                "observations_found": search_response.count,
                "observations_inserted": search_response.inserted_count,
                "message": "No suitable before/after pair found",
                "selection_rule": "no_pair",
                "reason": "no_new_suitable_observation",
                "latest_analyzed_observation": str(previous_after.id) if previous_after is not None else None,
                "newest_available_observation": (
                    str(search_response.observations[0].id) if search_response.observations else None
                ),
            }
            _mark_job_final(
                db_session,
                job=job,
                run=run,
                job_status=AnalysisJobStatus.SUCCEEDED,
                run_status=MonitorRunStatus.NO_NEW_IMAGERY,
                stage="no_new_imagery",
                result=result_payload,
                error=None,
            )
            logger.info(
                "No-new-imagery monitor run job_id=%s run_id=%s monitor_id=%s reason=%s",
                job.id,
                run.id,
                job.monitor_id,
                result_payload.get("reason"),
            )
            return {"status": "no_new_imagery", **_jsonable(result_payload)}

        if previous_after is not None and pair.after.id == previous_after.id:
            result_payload = {
                "search_window_start": search_start,
                "search_window_end": search_end,
                "search_window_rule": search_rule,
                "observations_found": search_response.count,
                "observations_inserted": search_response.inserted_count,
                "message": "Latest observation unchanged since last successful run",
                "selection_rule": "latest_matches_previous_after",
                "reason": "no_new_suitable_observation",
                "latest_analyzed_observation": str(previous_after.id),
                "newest_available_observation": str(pair.after.id),
                "after_observation_id": str(pair.after.id),
            }
            _mark_job_final(
                db_session,
                job=job,
                run=run,
                job_status=AnalysisJobStatus.SUCCEEDED,
                run_status=MonitorRunStatus.NO_NEW_IMAGERY,
                stage="no_new_imagery",
                result=result_payload,
                error=None,
            )
            logger.info(
                "No-new-imagery monitor run job_id=%s run_id=%s monitor_id=%s reason=%s",
                job.id,
                run.id,
                job.monitor_id,
                result_payload.get("reason"),
            )
            return {"status": "no_new_imagery", **_jsonable(result_payload)}

        run.before_observation_id = pair.before.id
        run.after_observation_id = pair.after.id
        db_session.add(run)
        db_session.commit()

        logger.info(
            "Selected observation pair job_id=%s run_id=%s monitor_id=%s before=%s after=%s rule=%s",
            job.id,
            run.id,
            job.monitor_id,
            pair.before.id,
            pair.after.id,
            pair.selection_rule,
        )

        _update_progress(db_session, job=job, run=run, stage="preparing_observations", progress_percent=50.0)
        _ensure_not_cancelled(db_session, job_id=job.id)

        force_reprocess = bool(parameters.get("force_reprocess", False))

        try:
            before_prepared = prepare_observation(
                db_session,
                monitor_id=job.monitor_id,
                observation_id=pair.before.id,
                force_reprocess=force_reprocess,
            )
            after_prepared = prepare_observation(
                db_session,
                monitor_id=job.monitor_id,
                observation_id=pair.after.id,
                force_reprocess=force_reprocess,
            )
        except TRANSIENT_PROVIDER_ERRORS as exc:
            raise MonitorRunTransientError("Raster asset provider unavailable", stage="preparing_observations") from exc
        except (
            PreparedObservationProcessingError,
            PreparedObservationPersistenceError,
            PreparedObservationQueryError,
        ) as exc:
            raise JobPersistenceError("Failed to prepare observations") from exc

        if before_prepared is None or after_prepared is None:
            raise JobConflictError("Unable to prepare selected observations")

        run.before_prepared_id = before_prepared.id
        run.after_prepared_id = after_prepared.id
        db_session.add(run)
        db_session.commit()

        _update_progress(db_session, job=job, run=run, stage="running_analysis", progress_percent=65.0)
        _ensure_not_cancelled(db_session, job_id=job.id)

        analysis_request = ChangeAnalysisCreateRequest(
            before_prepared_id=before_prepared.id,
            after_prepared_id=after_prepared.id,
            threshold=float(parameters.get("threshold") or 0.12),
            minimum_change_area_m2=(
                float(parameters["minimum_change_area_m2"])
                if parameters.get("minimum_change_area_m2") is not None
                else None
            ),
        )

        try:
            analysis_result = create_change_analysis(
                db_session,
                monitor_id=job.monitor_id,
                request=analysis_request,
            )
        except (
            ChangeAnalysisValidationError,
            ChangeAnalysisConflictError,
            ChangeAnalysisProcessingError,
            ChangeAnalysisPersistenceError,
            ChangeAnalysisQueryError,
        ) as exc:
            raise JobPersistenceError("Failed to compute change analysis") from exc

        if analysis_result is None:
            raise JobConflictError("Unable to create analysis for selected observations")

        analysis = analysis_result.analysis
        run.analysis_id = analysis.id
        db_session.add(run)
        db_session.commit()

        _update_progress(db_session, job=job, run=run, stage="generating_events", progress_percent=75.0)
        _ensure_not_cancelled(db_session, job_id=job.id)

        try:
            event_result = generate_change_events(
                db_session,
                monitor_id=job.monitor_id,
                analysis_id=analysis.id,
            )
        except (ChangeEventConflictError, ChangeEventGenerationError, ChangeEventPersistenceError, ChangeEventQueryError) as exc:
            raise JobPersistenceError("Failed to generate change events") from exc

        if event_result is None:
            raise JobConflictError("Unable to generate events for analysis")

        run.events_generated = event_result.response.count
        db_session.add(run)
        db_session.commit()

        impact_payload, exposure_payload = _compute_context_products_for_run(
            db_session,
            job=job,
            run=run,
            analysis_id=analysis.id,
            parameters=parameters,
            event_count=event_result.response.count,
            warnings=warnings,
        )

        elapsed_seconds = time.perf_counter() - started_at
        result_payload = {
            "search_window_start": search_start,
            "search_window_end": search_end,
            "search_window_rule": search_rule,
            "scene_selection_rule": pair.selection_rule,
            "observations_found": search_response.count,
            "observations_inserted": search_response.inserted_count,
            "before_observation_id": str(pair.before.id),
            "after_observation_id": str(pair.after.id),
            "before_prepared_id": str(before_prepared.id),
            "after_prepared_id": str(after_prepared.id),
            "analysis_id": str(analysis.id),
            "analysis_reused": analysis_result.reused,
            "events_generated": event_result.response.count,
            "events_reused": (not event_result.generated),
            "impact": impact_payload,
            "exposure": exposure_payload,
            "warnings": warnings,
            "elapsed_seconds": round(elapsed_seconds, 6),
        }

        run_status = MonitorRunStatus.SUCCEEDED if not warnings else MonitorRunStatus.PARTIAL
        logger.info(
            "Workflow computed outputs job_id=%s run_id=%s monitor_id=%s analysis_id=%s events=%s warnings=%s",
            job.id,
            run.id,
            job.monitor_id,
            analysis.id,
            event_result.response.count,
            len(warnings),
        )
        _mark_job_final(
            db_session,
            job=job,
            run=run,
            job_status=AnalysisJobStatus.SUCCEEDED,
            run_status=run_status,
            stage="completed",
            result=result_payload,
            error=None,
        )

        return {
            "status": run_status.value,
            "job_id": str(job.id),
            "run_id": str(run.id),
            **_jsonable(result_payload),
        }


def _build_schedule_request_from_row(schedule: MonitorSchedule) -> MonitorRunEnqueueRequest:
    return MonitorRunEnqueueRequest(
        lookback_days=schedule.lookback_days,
        max_cloud_cover=schedule.max_cloud_cover,
        search_limit=schedule.search_limit,
        threshold=schedule.threshold,
        minimum_change_area_m2=schedule.minimum_change_area_m2,
        impact_nearby_buffer_m=schedule.impact_nearby_buffer_m,
        environment_nearby_buffer_m=schedule.environment_nearby_buffer_m,
        auto_context_refresh=schedule.auto_context_refresh,
        auto_population_refresh=schedule.auto_population_refresh,
        auto_land_cover_refresh=schedule.auto_land_cover_refresh,
        auto_environment_refresh=schedule.auto_environment_refresh,
    )


def scan_monitor_schedules(*, max_due: int = 10) -> dict[str, Any]:
    settings = get_settings()
    now = _utc_now()

    with SessionLocal() as db_session:
        try:
            got_lock = bool(
                db_session.execute(
                    text("SELECT pg_try_advisory_lock(:lock_id)"),
                    {"lock_id": SCHEDULER_ADVISORY_LOCK_ID},
                ).scalar_one()
            )
        except SQLAlchemyError as exc:
            raise JobQueryError("Failed to acquire scheduler advisory lock") from exc

        if not got_lock:
            return {
                "lock_acquired": False,
                "scanned": 0,
                "enqueued": 0,
                "skipped_overlap": 0,
                "failed": 0,
            }

        scanned = 0
        enqueued = 0
        skipped_overlap = 0
        failed = 0

        try:
            due_schedules = db_session.execute(
                select(MonitorSchedule)
                .join(Monitor, Monitor.id == MonitorSchedule.monitor_id)
                .where(
                    MonitorSchedule.enabled.is_(True),
                    Monitor.status == "active",
                    (MonitorSchedule.next_run_after.is_(None) | (MonitorSchedule.next_run_after <= now)),
                )
                .order_by(MonitorSchedule.next_run_after.asc().nullsfirst(), MonitorSchedule.id.asc())
                .limit(max_due)
                .with_for_update(skip_locked=True)
            ).scalars().all()

            for schedule in due_schedules:
                scanned += 1
                schedule.last_scan_at = now

                if _active_monitor_jobs_count(db_session, schedule.monitor_id) > 0:
                    skipped_overlap += 1
                    schedule.next_run_after = now + timedelta(minutes=schedule.cadence_minutes)
                    db_session.add(schedule)
                    db_session.commit()
                    continue

                try:
                    enqueue_response = enqueue_monitor_run_job(
                        db_session,
                        monitor_id=schedule.monitor_id,
                        request=_build_schedule_request_from_row(schedule),
                        run_type=MonitorRunType.SCHEDULED,
                    )
                except JobConflictError:
                    skipped_overlap += 1
                    schedule.next_run_after = now + timedelta(minutes=schedule.cadence_minutes)
                    db_session.add(schedule)
                    db_session.commit()
                    continue
                except JobQueueUnavailableError:
                    failed += 1
                    schedule.next_run_after = now + timedelta(minutes=max(5, schedule.cadence_minutes))
                    db_session.add(schedule)
                    db_session.commit()
                    continue

                if enqueue_response is None:
                    failed += 1
                    continue

                enqueued += 1
                schedule.last_enqueued_job_id = enqueue_response.job.id
                schedule.next_run_after = now + timedelta(minutes=schedule.cadence_minutes)
                db_session.add(schedule)
                db_session.commit()

            scan_result = {
                "lock_acquired": True,
                "scan_cadence_seconds": settings.monitor_schedule_scan_seconds,
                "scanned": scanned,
                "enqueued": enqueued,
                "skipped_overlap": skipped_overlap,
                "failed": failed,
            }
            logger.info(
                "Scheduler scan complete lock=%s scanned=%s enqueued=%s skipped_overlap=%s failed=%s",
                True,
                scanned,
                enqueued,
                skipped_overlap,
                failed,
            )
            return scan_result
        finally:
            try:
                db_session.execute(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": SCHEDULER_ADVISORY_LOCK_ID},
                )
                db_session.commit()
            except SQLAlchemyError:
                db_session.rollback()


def redis_ping_status() -> tuple[bool, str | None]:
    settings = get_settings()
    try:
        client = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
        ok = bool(client.ping())
        return ok, None if ok else "Redis ping returned false"
    except RedisError as exc:
        return False, exc.__class__.__name__
    except Exception as exc:
        return False, exc.__class__.__name__


def celery_worker_ping(timeout_seconds: float = 3.0) -> tuple[bool, int]:
    try:
        from app.tasks.celery_app import celery_app

        replies = celery_app.control.inspect(timeout=timeout_seconds).ping() or {}
        if not isinstance(replies, dict):
            return False, 0
        return len(replies) > 0, len(replies)
    except Exception:
        return False, 0
