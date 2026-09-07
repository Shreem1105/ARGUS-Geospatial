from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.schemas import AnalysisJobRead, JobCancelResponse, WorkerHealthRead
from app.services.monitoring_service import (
    JobPersistenceError,
    JobQueryError,
    cancel_analysis_job,
    celery_worker_ping,
    get_analysis_job,
    redis_ping_status,
)

router = APIRouter(tags=["jobs"])


@router.get(
    "/jobs/{job_id}",
    response_model=AnalysisJobRead,
    status_code=status.HTTP_200_OK,
)
def get_job_status_route(
    job_id: UUID,
    db_session: Session = Depends(get_db_session),
) -> AnalysisJobRead:
    try:
        job = get_analysis_job(db_session, job_id=job_id)
    except JobQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to fetch analysis job",
        ) from exc

    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis job not found")

    return job


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=JobCancelResponse,
    status_code=status.HTTP_200_OK,
)
def cancel_job_route(
    job_id: UUID,
    db_session: Session = Depends(get_db_session),
) -> JobCancelResponse:
    try:
        result = cancel_analysis_job(db_session, job_id=job_id)
    except (JobPersistenceError, JobQueryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to cancel analysis job",
        ) from exc

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis job not found")

    return result


@router.get(
    "/worker/health",
    response_model=WorkerHealthRead,
    status_code=status.HTTP_200_OK,
)
def worker_health_route() -> JSONResponse:
    redis_ok, redis_detail = redis_ping_status()
    worker_ok, worker_count = celery_worker_ping()

    if redis_ok and worker_ok:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=WorkerHealthRead(
                status="healthy",
                redis="up",
                celery_worker=f"up:{worker_count}",
                detail=None,
            ).model_dump(mode="json"),
        )

    if not redis_ok:
        detail = "Redis unavailable" if redis_detail is None else f"Redis unavailable ({redis_detail})"
    else:
        detail = "No Celery workers responded to ping"

    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=WorkerHealthRead(
            status="degraded",
            redis="up" if redis_ok else "down",
            celery_worker=f"up:{worker_count}" if worker_ok else "down",
            detail=detail,
        ).model_dump(mode="json"),
    )

