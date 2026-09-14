from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from shapely.geometry import Polygon
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.gis.validation import calculate_polygon_area_km2
from app.models import AnalysisJob, Monitor, UsageEvent, User, UserQuota
from app.schemas.account import (
    AccountQuotaRead,
    AccountUsageRead,
    UserQuotaLimitsRead,
    UserQuotaRemainingRead,
    UserQuotaUsageRead,
)


class QuotaError(Exception):
    pass


class QuotaExceededError(QuotaError):
    def __init__(self, *, quota: str, limit: float, used: float) -> None:
        self.quota = quota
        self.limit = limit
        self.used = used
        super().__init__(f"Quota exceeded for {quota}")


class QuotaQueryError(QuotaError):
    pass


USAGE_MONITOR_CREATE = "monitor_create"
USAGE_MANUAL_RUN = "manual_run"
USAGE_OBSERVATION_SEARCH = "observation_search"
USAGE_SEMANTIC_ANALYSIS = "semantic_analysis"


@dataclass(slots=True)
class EffectiveQuotaLimits:
    max_monitors: int | None
    max_active_monitors: int | None
    max_aoi_area_km2: float | None
    max_manual_runs_per_day: int | None
    max_observation_searches_per_day: int | None
    max_semantic_runs_per_day: int | None
    max_concurrent_jobs: int | None


@dataclass(slots=True)
class QuotaUsage:
    monitor_count: int
    active_monitor_count: int
    manual_runs_today: int
    observation_searches_today: int
    semantic_runs_today: int
    concurrent_jobs: int


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _today_bounds_utc() -> tuple[datetime, datetime]:
    now = _utc_now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start, end


def _next_reset_utc() -> datetime:
    start, end = _today_bounds_utc()
    _ = start
    return end


def _maybe_override(base: int | float | None, override: int | float | None) -> int | float | None:
    if override is None:
        return base
    return override


def get_effective_quota_limits(db_session: Session, *, user: User, settings: Settings | None = None) -> EffectiveQuotaLimits:
    if user.role == "admin":
        return EffectiveQuotaLimits(
            max_monitors=None,
            max_active_monitors=None,
            max_aoi_area_km2=None,
            max_manual_runs_per_day=None,
            max_observation_searches_per_day=None,
            max_semantic_runs_per_day=None,
            max_concurrent_jobs=None,
        )

    active_settings = settings or get_settings()
    limits = EffectiveQuotaLimits(
        max_monitors=active_settings.quota_default_max_monitors,
        max_active_monitors=active_settings.quota_default_max_active_monitors,
        max_aoi_area_km2=active_settings.quota_default_max_aoi_area_km2,
        max_manual_runs_per_day=active_settings.quota_default_max_manual_runs_per_day,
        max_observation_searches_per_day=active_settings.quota_default_max_observation_searches_per_day,
        max_semantic_runs_per_day=active_settings.quota_default_max_semantic_runs_per_day,
        max_concurrent_jobs=active_settings.quota_default_max_concurrent_jobs,
    )

    try:
        quota = db_session.execute(select(UserQuota).where(UserQuota.user_id == user.id)).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise QuotaQueryError("Failed to load user quota") from exc

    if quota is None:
        return limits

    return EffectiveQuotaLimits(
        max_monitors=_maybe_override(limits.max_monitors, quota.max_monitors),
        max_active_monitors=_maybe_override(limits.max_active_monitors, quota.max_active_monitors),
        max_aoi_area_km2=_maybe_override(limits.max_aoi_area_km2, quota.max_aoi_area_km2),
        max_manual_runs_per_day=_maybe_override(limits.max_manual_runs_per_day, quota.max_manual_runs_per_day),
        max_observation_searches_per_day=_maybe_override(
            limits.max_observation_searches_per_day,
            quota.max_observation_searches_per_day,
        ),
        max_semantic_runs_per_day=_maybe_override(limits.max_semantic_runs_per_day, quota.max_semantic_runs_per_day),
        max_concurrent_jobs=_maybe_override(limits.max_concurrent_jobs, quota.max_concurrent_jobs),
    )


def _usage_count_today(db_session: Session, *, user_id: UUID, usage_type: str) -> int:
    start, end = _today_bounds_utc()
    quantity_sum = db_session.execute(
        select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(
            UsageEvent.user_id == user_id,
            UsageEvent.usage_type == usage_type,
            UsageEvent.created_at >= start,
            UsageEvent.created_at < end,
        )
    ).scalar_one()
    return int(quantity_sum)


def get_quota_usage(db_session: Session, *, user: User) -> QuotaUsage:
    try:
        monitor_count = int(
            db_session.execute(
                select(func.count(Monitor.id)).where(Monitor.owner_user_id == user.id)
            ).scalar_one()
        )
        active_monitor_count = int(
            db_session.execute(
                select(func.count(Monitor.id)).where(
                    Monitor.owner_user_id == user.id,
                    Monitor.status == "active",
                )
            ).scalar_one()
        )
        concurrent_jobs = int(
            db_session.execute(
                select(func.count(AnalysisJob.id))
                .join(Monitor, Monitor.id == AnalysisJob.monitor_id)
                .where(
                    Monitor.owner_user_id == user.id,
                    AnalysisJob.job_type == "monitor_run",
                    AnalysisJob.status.in_(["queued", "running"]),
                )
            ).scalar_one()
        )

        manual_runs_today = _usage_count_today(db_session, user_id=user.id, usage_type=USAGE_MANUAL_RUN)
        observation_searches_today = _usage_count_today(
            db_session,
            user_id=user.id,
            usage_type=USAGE_OBSERVATION_SEARCH,
        )
        semantic_runs_today = _usage_count_today(db_session, user_id=user.id, usage_type=USAGE_SEMANTIC_ANALYSIS)
    except SQLAlchemyError as exc:
        raise QuotaQueryError("Failed to query quota usage") from exc

    return QuotaUsage(
        monitor_count=monitor_count,
        active_monitor_count=active_monitor_count,
        manual_runs_today=manual_runs_today,
        observation_searches_today=observation_searches_today,
        semantic_runs_today=semantic_runs_today,
        concurrent_jobs=concurrent_jobs,
    )


def _remaining(limit: int | None, used: int) -> int | None:
    if limit is None:
        return None
    return max(0, limit - used)


def build_account_quota(db_session: Session, *, user: User) -> AccountQuotaRead:
    limits = get_effective_quota_limits(db_session, user=user)
    usage = get_quota_usage(db_session, user=user)

    return AccountQuotaRead(
        user_id=user.id,
        role=user.role,
        limits=UserQuotaLimitsRead(
            max_monitors=limits.max_monitors,
            max_active_monitors=limits.max_active_monitors,
            max_aoi_area_km2=limits.max_aoi_area_km2,
            max_manual_runs_per_day=limits.max_manual_runs_per_day,
            max_observation_searches_per_day=limits.max_observation_searches_per_day,
            max_semantic_runs_per_day=limits.max_semantic_runs_per_day,
            max_concurrent_jobs=limits.max_concurrent_jobs,
        ),
        usage=UserQuotaUsageRead(
            monitor_count=usage.monitor_count,
            active_monitor_count=usage.active_monitor_count,
            manual_runs_today=usage.manual_runs_today,
            observation_searches_today=usage.observation_searches_today,
            semantic_runs_today=usage.semantic_runs_today,
            concurrent_jobs=usage.concurrent_jobs,
        ),
        remaining=UserQuotaRemainingRead(
            remaining_monitors=_remaining(limits.max_monitors, usage.monitor_count),
            remaining_active_monitors=_remaining(limits.max_active_monitors, usage.active_monitor_count),
            remaining_manual_runs_today=_remaining(limits.max_manual_runs_per_day, usage.manual_runs_today),
            remaining_observation_searches_today=_remaining(
                limits.max_observation_searches_per_day,
                usage.observation_searches_today,
            ),
            remaining_semantic_runs_today=_remaining(limits.max_semantic_runs_per_day, usage.semantic_runs_today),
            remaining_concurrent_jobs=_remaining(limits.max_concurrent_jobs, usage.concurrent_jobs),
        ),
        resets_at_utc=_next_reset_utc(),
    )


def build_account_usage(db_session: Session, *, user: User) -> AccountUsageRead:
    usage = get_quota_usage(db_session, user=user)
    return AccountUsageRead(
        user_id=user.id,
        usage_today={
            USAGE_MONITOR_CREATE: usage.monitor_count,
            USAGE_MANUAL_RUN: usage.manual_runs_today,
            USAGE_OBSERVATION_SEARCH: usage.observation_searches_today,
            USAGE_SEMANTIC_ANALYSIS: usage.semantic_runs_today,
        },
        generated_at=_utc_now(),
    )


def record_usage_event(
    db_session: Session,
    *,
    user_id: UUID,
    usage_type: str,
    resource_id: UUID | None,
    quantity: int = 1,
    metadata: dict[str, Any] | None = None,
) -> None:
    event = UsageEvent(
        user_id=user_id,
        usage_type=usage_type,
        resource_id=resource_id,
        quantity=quantity,
        metadata_=(metadata or {}),
    )

    try:
        db_session.add(event)
        db_session.flush()
    except SQLAlchemyError as exc:
        raise QuotaQueryError("Failed to record usage") from exc


def compute_geojson_polygon_area_km2(geometry: dict[str, Any]) -> float:
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates:
        raise QuotaError("Invalid monitor geometry")

    shell = coordinates[0]
    holes = coordinates[1:] if len(coordinates) > 1 else None
    polygon = Polygon(shell=shell, holes=holes)
    return float(calculate_polygon_area_km2(polygon))


def enforce_monitor_create_quota(db_session: Session, *, user: User, geometry: dict[str, Any]) -> None:
    limits = get_effective_quota_limits(db_session, user=user)
    usage = get_quota_usage(db_session, user=user)

    if limits.max_monitors is not None and usage.monitor_count >= limits.max_monitors:
        raise QuotaExceededError(quota="max_monitors", limit=limits.max_monitors, used=usage.monitor_count)

    if limits.max_active_monitors is not None and usage.active_monitor_count >= limits.max_active_monitors:
        raise QuotaExceededError(
            quota="max_active_monitors",
            limit=limits.max_active_monitors,
            used=usage.active_monitor_count,
        )

    if limits.max_aoi_area_km2 is not None:
        area_km2 = compute_geojson_polygon_area_km2(geometry)
        if area_km2 > limits.max_aoi_area_km2:
            raise QuotaExceededError(
                quota="max_aoi_area_km2",
                limit=limits.max_aoi_area_km2,
                used=area_km2,
            )


def enforce_manual_run_quota(db_session: Session, *, user: User) -> None:
    limits = get_effective_quota_limits(db_session, user=user)
    usage = get_quota_usage(db_session, user=user)

    if limits.max_manual_runs_per_day is not None and usage.manual_runs_today >= limits.max_manual_runs_per_day:
        raise QuotaExceededError(
            quota="max_manual_runs_per_day",
            limit=limits.max_manual_runs_per_day,
            used=usage.manual_runs_today,
        )

    if limits.max_concurrent_jobs is not None and usage.concurrent_jobs >= limits.max_concurrent_jobs:
        raise QuotaExceededError(
            quota="max_concurrent_jobs",
            limit=limits.max_concurrent_jobs,
            used=usage.concurrent_jobs,
        )


def enforce_observation_search_quota(db_session: Session, *, user: User) -> None:
    limits = get_effective_quota_limits(db_session, user=user)
    usage = get_quota_usage(db_session, user=user)

    if (
        limits.max_observation_searches_per_day is not None
        and usage.observation_searches_today >= limits.max_observation_searches_per_day
    ):
        raise QuotaExceededError(
            quota="max_observation_searches_per_day",
            limit=limits.max_observation_searches_per_day,
            used=usage.observation_searches_today,
        )


def enforce_semantic_run_quota(db_session: Session, *, user: User) -> None:
    limits = get_effective_quota_limits(db_session, user=user)
    usage = get_quota_usage(db_session, user=user)

    if limits.max_semantic_runs_per_day is not None and usage.semantic_runs_today >= limits.max_semantic_runs_per_day:
        raise QuotaExceededError(
            quota="max_semantic_runs_per_day",
            limit=limits.max_semantic_runs_per_day,
            used=usage.semantic_runs_today,
        )
