from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import AnalysisJob, Monitor


class AccessQueryError(Exception):
    pass


def get_owned_monitor(db_session: Session, *, monitor_id: UUID, user_id: UUID) -> Monitor | None:
    try:
        return db_session.execute(
            select(Monitor).where(
                Monitor.id == monitor_id,
                Monitor.owner_user_id == user_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise AccessQueryError("Failed to fetch monitor ownership") from exc


def get_owned_job(db_session: Session, *, job_id: UUID, user_id: UUID) -> AnalysisJob | None:
    try:
        return db_session.execute(
            select(AnalysisJob)
            .join(Monitor, Monitor.id == AnalysisJob.monitor_id)
            .where(
                AnalysisJob.id == job_id,
                Monitor.owner_user_id == user_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise AccessQueryError("Failed to fetch job ownership") from exc
