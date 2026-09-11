from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.context import LandCoverProvider
from app.models import (
    ChangeAnalysis,
    ChangeEvent,
    ChangeEventEnvironmentalExposure,
    ChangeEventLandCoverExposure,
    ChangeEventPopulationExposure,
    ContextFeature,
    EnvironmentalFeature,
    Monitor,
    MonitorLandCoverSource,
    PopulationFeature,
)
from app.schemas import (
    AnalysisExposureComputeResponse,
    EventExposureSummaryRead,
    EventIntelligenceRead,
    ExposureFactorRead,
    ExposureSignificance,
    MonitorDatasetsRead,
    MonitorDatasetStatusEntryRead,
    MonitorExposureSummaryRead,
)
from app.services.environment_service import (
    DEFAULT_ENVIRONMENT_NEARBY_BUFFER_M,
    EnvironmentConflictError,
    EnvironmentPersistenceError,
    EnvironmentQueryError,
    compute_change_event_environmental_exposure,
    get_change_event_environmental_exposure,
)
from app.services.impact_service import ImpactQueryError, get_change_event_impact_summary
from app.services.landcover_service import (
    LandCoverConflictError,
    LandCoverPersistenceError,
    LandCoverProviderRequestError,
    LandCoverQueryError,
    compute_change_event_land_cover_exposure,
    get_change_event_land_cover_exposure,
)
from app.services.population_service import (
    PopulationConflictError,
    PopulationPersistenceError,
    PopulationQueryError,
    compute_change_event_population_exposure,
    get_change_event_population_exposure,
)
from app.services.semantic_service import SemanticQueryError, get_change_event_semantic_analysis

logger = logging.getLogger(__name__)

EXPOSURE_GENERATION_VERSION = "event-exposure-v1"

SIGNIFICANCE_POPULATION_MEDIUM = 50.0
SIGNIFICANCE_POPULATION_HIGH = 250.0
SIGNIFICANCE_BUILDINGS_MEDIUM = 1.0
SIGNIFICANCE_BUILDINGS_HIGH = 10.0
SIGNIFICANCE_MAJOR_ROADS_HIGH = 1.0
SIGNIFICANCE_WATERWAY_MEDIUM = 1.0
SIGNIFICANCE_ENV_FRACTION_MEDIUM = 0.05
SIGNIFICANCE_ENV_FRACTION_HIGH = 0.20


class ExposurePersistenceError(Exception):
    pass


class ExposureQueryError(Exception):
    pass


class ExposureConflictError(Exception):
    pass


class ExposureProviderRequestError(Exception):
    pass


@dataclass(slots=True)
class EventExposureComputationResult:
    summary: EventExposureSummaryRead
    computed: bool


@dataclass(slots=True)
class BulkExposureComputationResult:
    response: AnalysisExposureComputeResponse


def _get_monitor(db_session: Session, monitor_id: UUID) -> Monitor | None:
    try:
        return db_session.execute(select(Monitor).where(Monitor.id == monitor_id)).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise ExposureQueryError("Failed to fetch monitor") from exc


def _get_event(db_session: Session, *, monitor_id: UUID, event_id: UUID) -> ChangeEvent | None:
    try:
        return db_session.execute(
            select(ChangeEvent).where(
                ChangeEvent.monitor_id == monitor_id,
                ChangeEvent.id == event_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise ExposureQueryError("Failed to fetch change event") from exc


def _get_analysis(db_session: Session, *, monitor_id: UUID, analysis_id: UUID) -> ChangeAnalysis | None:
    try:
        return db_session.execute(
            select(ChangeAnalysis).where(
                ChangeAnalysis.monitor_id == monitor_id,
                ChangeAnalysis.id == analysis_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise ExposureQueryError("Failed to fetch change analysis") from exc


def _dataset_readiness_checks(db_session: Session, monitor_id: UUID) -> list[str]:
    missing: list[str] = []

    try:
        context_count = db_session.execute(
            select(func.count(ContextFeature.id)).where(ContextFeature.monitor_id == monitor_id)
        ).scalar_one()
        population_count = db_session.execute(
            select(func.count(PopulationFeature.id)).where(PopulationFeature.monitor_id == monitor_id)
        ).scalar_one()
        land_cover_count = db_session.execute(
            select(func.count(MonitorLandCoverSource.id)).where(MonitorLandCoverSource.monitor_id == monitor_id)
        ).scalar_one()
    except SQLAlchemyError as exc:
        raise ExposureQueryError("Failed to verify dataset readiness") from exc

    if context_count == 0:
        missing.append("context")
    if population_count == 0:
        missing.append("population")
    if land_cover_count == 0:
        missing.append("land_cover")

    return missing


def _event_has_exposure_snapshot(event: ChangeEvent) -> bool:
    payload = event.properties if isinstance(event.properties, dict) else {}
    exposure = payload.get("exposure") if isinstance(payload, dict) else None
    if not isinstance(exposure, dict):
        return False
    return exposure.get("version") == EXPOSURE_GENERATION_VERSION


def _build_significance_factors(
    *,
    estimated_population_exposure: float,
    intersecting_buildings: int,
    major_road_intersections: int,
    waterway_intersections: int,
    protected_area_fraction: float,
) -> list[ExposureFactorRead]:
    return [
        ExposureFactorRead(
            factor="population_exposure",
            value=estimated_population_exposure,
            threshold=SIGNIFICANCE_POPULATION_MEDIUM,
            met=estimated_population_exposure >= SIGNIFICANCE_POPULATION_MEDIUM,
        ),
        ExposureFactorRead(
            factor="building_intersections",
            value=float(intersecting_buildings),
            threshold=SIGNIFICANCE_BUILDINGS_MEDIUM,
            met=float(intersecting_buildings) >= SIGNIFICANCE_BUILDINGS_MEDIUM,
        ),
        ExposureFactorRead(
            factor="major_road_intersections",
            value=float(major_road_intersections),
            threshold=SIGNIFICANCE_MAJOR_ROADS_HIGH,
            met=float(major_road_intersections) >= SIGNIFICANCE_MAJOR_ROADS_HIGH,
        ),
        ExposureFactorRead(
            factor="waterway_intersections",
            value=float(waterway_intersections),
            threshold=SIGNIFICANCE_WATERWAY_MEDIUM,
            met=float(waterway_intersections) >= SIGNIFICANCE_WATERWAY_MEDIUM,
        ),
        ExposureFactorRead(
            factor="protected_area_fraction",
            value=protected_area_fraction,
            threshold=SIGNIFICANCE_ENV_FRACTION_MEDIUM,
            met=protected_area_fraction >= SIGNIFICANCE_ENV_FRACTION_MEDIUM,
        ),
    ]


def _derive_exposure_significance(
    *,
    estimated_population_exposure: float,
    intersecting_buildings: int,
    major_road_intersections: int,
    waterway_intersections: int,
    protected_area_fraction: float,
) -> ExposureSignificance:
    high_signals = 0
    medium_signals = 0

    if estimated_population_exposure >= SIGNIFICANCE_POPULATION_HIGH:
        high_signals += 1
    elif estimated_population_exposure >= SIGNIFICANCE_POPULATION_MEDIUM:
        medium_signals += 1

    if intersecting_buildings >= SIGNIFICANCE_BUILDINGS_HIGH:
        high_signals += 1
    elif intersecting_buildings >= SIGNIFICANCE_BUILDINGS_MEDIUM:
        medium_signals += 1

    if major_road_intersections >= SIGNIFICANCE_MAJOR_ROADS_HIGH:
        high_signals += 1

    if waterway_intersections >= SIGNIFICANCE_WATERWAY_MEDIUM:
        medium_signals += 1

    if protected_area_fraction >= SIGNIFICANCE_ENV_FRACTION_HIGH:
        high_signals += 1
    elif protected_area_fraction >= SIGNIFICANCE_ENV_FRACTION_MEDIUM:
        medium_signals += 1

    if high_signals >= 2 or (high_signals >= 1 and medium_signals >= 2):
        return ExposureSignificance.HIGH
    if high_signals >= 1 or medium_signals >= 2:
        return ExposureSignificance.MEDIUM
    return ExposureSignificance.LOW


def _build_event_exposure_summary(
    *,
    event: ChangeEvent,
    population_summary,
    land_cover_summary,
    environment_summary,
    context_summary,
) -> EventExposureSummaryRead:
    major_road_intersections = 0
    intersecting_buildings = 0
    waterway_intersections = 0
    if context_summary is not None:
        major_road_intersections = int(
            context_summary.roads.classes.get("motorway", 0)
            + context_summary.roads.classes.get("trunk", 0)
            + context_summary.roads.classes.get("primary", 0)
        )
        intersecting_buildings = int(context_summary.buildings.intersecting_count)
        waterway_intersections = int(context_summary.waterways.intersecting_count)

    exposure_significance = _derive_exposure_significance(
        estimated_population_exposure=population_summary.estimated_exposed_population,
        intersecting_buildings=intersecting_buildings,
        major_road_intersections=major_road_intersections,
        waterway_intersections=waterway_intersections,
        protected_area_fraction=environment_summary.protected_area_fraction,
    )
    factors = _build_significance_factors(
        estimated_population_exposure=population_summary.estimated_exposed_population,
        intersecting_buildings=intersecting_buildings,
        major_road_intersections=major_road_intersections,
        waterway_intersections=waterway_intersections,
        protected_area_fraction=environment_summary.protected_area_fraction,
    )

    return EventExposureSummaryRead(
        event_id=event.id,
        monitor_id=event.monitor_id,
        analysis_id=event.analysis_id,
        scientific_severity=event.severity,
        population=population_summary,
        land_cover=land_cover_summary,
        environment=environment_summary,
        exposure_significance=exposure_significance,
        significance_factors=factors,
        computed_at=datetime.now(tz=timezone.utc),
    )


def _persist_exposure_snapshot(
    db_session: Session,
    *,
    event: ChangeEvent,
    summary: EventExposureSummaryRead,
) -> None:
    payload = dict(event.properties or {})
    payload["exposure"] = {
        "version": EXPOSURE_GENERATION_VERSION,
        "computed_at": summary.computed_at.isoformat(),
        "exposure_significance": summary.exposure_significance.value,
        "significance_factors": [factor.model_dump() for factor in summary.significance_factors],
        "population": {
            "dataset": summary.population.dataset,
            "dataset_version": summary.population.dataset_version,
            "estimated_exposed_population": summary.population.estimated_exposed_population,
        },
        "land_cover": {
            "dataset": summary.land_cover.dataset,
            "dataset_version": summary.land_cover.dataset_version,
            "dominant_class": summary.land_cover.dominant_class,
            "dominant_fraction": summary.land_cover.dominant_fraction,
        },
        "environment": {
            "dataset": summary.environment.dataset,
            "dataset_version": summary.environment.dataset_version,
            "intersecting_count": summary.environment.intersecting_count,
            "protected_area_fraction": summary.environment.protected_area_fraction,
        },
    }

    event.properties = payload
    event.updated_at = func.now()

    try:
        db_session.commit()
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise ExposurePersistenceError("Failed to persist event exposure snapshot") from exc


def compute_change_event_exposure(
    db_session: Session,
    *,
    monitor_id: UUID,
    event_id: UUID,
    land_cover_provider: LandCoverProvider,
    environment_nearby_buffer_m: float = DEFAULT_ENVIRONMENT_NEARBY_BUFFER_M,
) -> EventExposureComputationResult | None:
    event = _get_event(db_session, monitor_id=monitor_id, event_id=event_id)
    if event is None:
        return None

    if _event_has_exposure_snapshot(event):
        existing_summary = get_change_event_exposure(db_session, monitor_id=monitor_id, event_id=event_id)
        if existing_summary is not None:
            return EventExposureComputationResult(summary=existing_summary, computed=False)

    missing = _dataset_readiness_checks(db_session, monitor_id)
    if missing:
        missing_text = ", ".join(missing)
        raise ExposureConflictError(f"Required datasets are missing for this monitor: {missing_text}")

    try:
        population_summary = compute_change_event_population_exposure(
            db_session,
            monitor_id=monitor_id,
            event_id=event_id,
        )
        if population_summary is None:
            return None

        land_cover_summary = compute_change_event_land_cover_exposure(
            db_session,
            monitor_id=monitor_id,
            event_id=event_id,
            provider=land_cover_provider,
        )
        if land_cover_summary is None:
            return None

        environment_summary = compute_change_event_environmental_exposure(
            db_session,
            monitor_id=monitor_id,
            event_id=event_id,
            nearby_buffer_m=environment_nearby_buffer_m,
        )
        if environment_summary is None:
            return None
    except (
        PopulationConflictError,
        LandCoverConflictError,
        EnvironmentConflictError,
    ) as exc:
        raise ExposureConflictError(str(exc)) from exc
    except (
        PopulationPersistenceError,
        PopulationQueryError,
        LandCoverPersistenceError,
        LandCoverQueryError,
        EnvironmentPersistenceError,
        EnvironmentQueryError,
    ) as exc:
        raise ExposurePersistenceError("Failed to compute change-event exposure") from exc
    except LandCoverProviderRequestError as exc:
        raise ExposureProviderRequestError("Land-cover provider request failed during exposure computation") from exc

    try:
        context_summary = get_change_event_impact_summary(db_session, monitor_id=monitor_id, event_id=event_id)
    except ImpactQueryError as exc:
        raise ExposureQueryError("Failed to load context impact summary for exposure scoring") from exc

    summary = _build_event_exposure_summary(
        event=event,
        population_summary=population_summary,
        land_cover_summary=land_cover_summary,
        environment_summary=environment_summary,
        context_summary=context_summary,
    )
    _persist_exposure_snapshot(db_session, event=event, summary=summary)

    logger.info(
        "Computed event exposure monitor_id=%s event_id=%s significance=%s",
        monitor_id,
        event_id,
        summary.exposure_significance.value,
    )

    return EventExposureComputationResult(summary=summary, computed=True)


def get_change_event_exposure(
    db_session: Session,
    *,
    monitor_id: UUID,
    event_id: UUID,
) -> EventExposureSummaryRead | None:
    event = _get_event(db_session, monitor_id=monitor_id, event_id=event_id)
    if event is None:
        return None

    population_summary = get_change_event_population_exposure(db_session, monitor_id=monitor_id, event_id=event_id)
    land_cover_summary = get_change_event_land_cover_exposure(db_session, monitor_id=monitor_id, event_id=event_id)
    environment_summary = get_change_event_environmental_exposure(db_session, monitor_id=monitor_id, event_id=event_id)
    if population_summary is None or land_cover_summary is None or environment_summary is None:
        return None

    try:
        context_summary = get_change_event_impact_summary(db_session, monitor_id=monitor_id, event_id=event_id)
    except ImpactQueryError as exc:
        raise ExposureQueryError("Failed to load context impact summary") from exc

    summary = _build_event_exposure_summary(
        event=event,
        population_summary=population_summary,
        land_cover_summary=land_cover_summary,
        environment_summary=environment_summary,
        context_summary=context_summary,
    )

    snapshot = (event.properties or {}).get("exposure")
    if isinstance(snapshot, dict):
        significance_value = snapshot.get("exposure_significance")
        factors_payload = snapshot.get("significance_factors")
        if isinstance(significance_value, str) and significance_value in {item.value for item in ExposureSignificance}:
            summary.exposure_significance = ExposureSignificance(significance_value)
        if isinstance(factors_payload, list):
            parsed_factors: list[ExposureFactorRead] = []
            for item in factors_payload:
                if isinstance(item, dict):
                    try:
                        parsed_factors.append(ExposureFactorRead.model_validate(item))
                    except Exception:
                        continue
            if parsed_factors:
                summary.significance_factors = parsed_factors

        computed_at = snapshot.get("computed_at")
        if isinstance(computed_at, str):
            try:
                parsed_time = datetime.fromisoformat(computed_at.replace("Z", "+00:00"))
                if parsed_time.tzinfo is None:
                    parsed_time = parsed_time.replace(tzinfo=timezone.utc)
                summary.computed_at = parsed_time.astimezone(timezone.utc)
            except ValueError:
                pass

    return summary


def compute_analysis_exposures(
    db_session: Session,
    *,
    monitor_id: UUID,
    analysis_id: UUID,
    land_cover_provider: LandCoverProvider,
    environment_nearby_buffer_m: float = DEFAULT_ENVIRONMENT_NEARBY_BUFFER_M,
) -> BulkExposureComputationResult | None:
    analysis = _get_analysis(db_session, monitor_id=monitor_id, analysis_id=analysis_id)
    if analysis is None:
        return None

    try:
        events = db_session.execute(
            select(ChangeEvent)
            .where(
                ChangeEvent.monitor_id == monitor_id,
                ChangeEvent.analysis_id == analysis_id,
            )
            .order_by(ChangeEvent.id.asc())
        ).scalars().all()
    except SQLAlchemyError as exc:
        raise ExposureQueryError("Failed to fetch analysis events") from exc

    started_at = time.perf_counter()
    computed = 0
    reused = 0
    failed = 0

    for event in events:
        try:
            result = compute_change_event_exposure(
                db_session,
                monitor_id=monitor_id,
                event_id=event.id,
                land_cover_provider=land_cover_provider,
                environment_nearby_buffer_m=environment_nearby_buffer_m,
            )
        except ExposureConflictError:
            existing_summary = get_change_event_exposure(db_session, monitor_id=monitor_id, event_id=event.id)
            if existing_summary is not None:
                reused += 1
                continue
            raise
        except (
            ExposurePersistenceError,
            ExposureProviderRequestError,
            ExposureQueryError,
        ):
            failed += 1
            continue

        if result is None:
            failed += 1
            continue

        if result.computed:
            computed += 1
        else:
            reused += 1

    elapsed_seconds = time.perf_counter() - started_at
    logger.info(
        "Computed analysis exposures monitor_id=%s analysis_id=%s events=%s computed=%s reused=%s failed=%s elapsed_seconds=%.3f",
        monitor_id,
        analysis_id,
        len(events),
        computed,
        reused,
        failed,
        elapsed_seconds,
    )

    return BulkExposureComputationResult(
        response=AnalysisExposureComputeResponse(
            analysis_id=analysis_id,
            event_count=len(events),
            computed=computed,
            reused=reused,
            failed=failed,
            elapsed_seconds=round(elapsed_seconds, 6),
        )
    )


def get_monitor_exposure_summary(db_session: Session, *, monitor_id: UUID) -> MonitorExposureSummaryRead | None:
    monitor = _get_monitor(db_session, monitor_id)
    if monitor is None:
        return None

    try:
        population_rows = db_session.execute(
            select(ChangeEventPopulationExposure.event_id, func.coalesce(func.sum(ChangeEventPopulationExposure.estimated_exposed_population), 0.0))
            .join(ChangeEvent, ChangeEvent.id == ChangeEventPopulationExposure.event_id)
            .where(ChangeEvent.monitor_id == monitor_id)
            .group_by(ChangeEventPopulationExposure.event_id)
        ).all()

        env_rows = db_session.execute(
            select(
                ChangeEventEnvironmentalExposure.event_id,
                func.coalesce(func.sum(ChangeEventEnvironmentalExposure.intersection_area_m2), 0.0),
            )
            .join(ChangeEvent, ChangeEvent.id == ChangeEventEnvironmentalExposure.event_id)
            .where(
                ChangeEvent.monitor_id == monitor_id,
                ChangeEventEnvironmentalExposure.relationship_type == "intersects",
            )
            .group_by(ChangeEventEnvironmentalExposure.event_id)
        ).all()

        dominant_rows = db_session.execute(
            text(
                """
                SELECT DISTINCT ON (lc.event_id)
                    lc.event_id,
                    lc.class_name
                FROM change_event_land_cover_exposures AS lc
                JOIN change_events AS e ON e.id = lc.event_id
                WHERE e.monitor_id = :monitor_id
                ORDER BY lc.event_id, lc.fraction_of_event DESC, lc.class_code ASC
                """
            ),
            {"monitor_id": monitor_id},
        ).mappings().all()

        events = db_session.execute(
            select(ChangeEvent.id, ChangeEvent.properties).where(ChangeEvent.monitor_id == monitor_id)
        ).all()
    except SQLAlchemyError as exc:
        raise ExposureQueryError("Failed to summarize monitor exposure") from exc

    events_with_population_exposure = len(population_rows)
    total_population_sum = float(sum(float(row[1]) for row in population_rows))

    events_intersecting_protected = len(env_rows)
    total_protected_area = float(sum(float(row[1]) for row in env_rows))

    events_by_dominant_land_cover: dict[str, int] = {}
    for row in dominant_rows:
        class_name = str(row["class_name"])
        events_by_dominant_land_cover[class_name] = events_by_dominant_land_cover.get(class_name, 0) + 1

    events_by_exposure_significance = {
        ExposureSignificance.LOW.value: 0,
        ExposureSignificance.MEDIUM.value: 0,
        ExposureSignificance.HIGH.value: 0,
    }
    for _, properties in events:
        if not isinstance(properties, dict):
            continue
        snapshot = properties.get("exposure")
        if not isinstance(snapshot, dict):
            continue
        significance = snapshot.get("exposure_significance")
        if isinstance(significance, str) and significance in events_by_exposure_significance:
            events_by_exposure_significance[significance] += 1

    return MonitorExposureSummaryRead(
        monitor_id=monitor_id,
        events_with_population_exposure=events_with_population_exposure,
        estimated_total_population_exposure_event_level_sum=total_population_sum,
        events_intersecting_protected_areas=events_intersecting_protected,
        total_protected_area_intersection_m2=total_protected_area,
        events_by_dominant_land_cover=events_by_dominant_land_cover,
        events_by_exposure_significance=events_by_exposure_significance,
    )


def get_monitor_datasets(db_session: Session, *, monitor_id: UUID) -> MonitorDatasetsRead | None:
    monitor = _get_monitor(db_session, monitor_id)
    if monitor is None:
        return None

    try:
        context_row = db_session.execute(
            select(
                func.count(ContextFeature.id),
                func.max(ContextFeature.fetched_at),
                func.min(ContextFeature.provider),
            ).where(ContextFeature.monitor_id == monitor_id)
        ).one()

        population_row = db_session.execute(
            select(
                func.count(PopulationFeature.id),
                func.max(PopulationFeature.fetched_at),
                func.max(PopulationFeature.dataset),
                func.max(PopulationFeature.dataset_version),
                func.max(PopulationFeature.provider),
            ).where(PopulationFeature.monitor_id == monitor_id)
        ).one()

        land_cover_row = db_session.execute(
            select(MonitorLandCoverSource)
            .where(MonitorLandCoverSource.monitor_id == monitor_id)
            .order_by(MonitorLandCoverSource.fetched_at.desc(), MonitorLandCoverSource.id.desc())
            .limit(1)
        ).scalar_one_or_none()

        environment_row = db_session.execute(
            select(
                func.count(EnvironmentalFeature.id),
                func.max(EnvironmentalFeature.fetched_at),
                func.max(EnvironmentalFeature.dataset),
                func.max(EnvironmentalFeature.dataset_version),
                func.max(EnvironmentalFeature.provider),
            ).where(EnvironmentalFeature.monitor_id == monitor_id)
        ).one()
    except SQLAlchemyError as exc:
        raise ExposureQueryError("Failed to fetch dataset status") from exc

    datasets: list[MonitorDatasetStatusEntryRead] = []

    context_count = int(context_row[0])
    datasets.append(
        MonitorDatasetStatusEntryRead(
            category="context",
            provider=str(context_row[2]) if context_row[2] is not None else "openstreetmap",
            dataset="osm_context",
            dataset_version=None,
            fetched_at=context_row[1],
            feature_count=context_count,
            status="available" if context_count > 0 else "missing",
            attribution="© OpenStreetMap contributors",
        )
    )

    population_count = int(population_row[0])
    datasets.append(
        MonitorDatasetStatusEntryRead(
            category="population",
            provider=str(population_row[4]) if population_row[4] is not None else "us_census",
            dataset=str(population_row[2]) if population_row[2] is not None else "acs5_total_population_block_group",
            dataset_version=str(population_row[3]) if population_row[3] is not None else None,
            fetched_at=population_row[1],
            feature_count=population_count,
            status="available" if population_count > 0 else "missing",
            attribution="Source: U.S. Census Bureau",
        )
    )

    if land_cover_row is None:
        datasets.append(
            MonitorDatasetStatusEntryRead(
                category="land_cover",
                provider="planetary_computer",
                dataset="esa-worldcover",
                dataset_version=None,
                fetched_at=None,
                feature_count=0,
                status="missing",
                attribution="Contains modified Copernicus Sentinel data (2021+)",
            )
        )
    else:
        datasets.append(
            MonitorDatasetStatusEntryRead(
                category="land_cover",
                provider=land_cover_row.provider,
                dataset=land_cover_row.dataset,
                dataset_version=land_cover_row.dataset_version,
                fetched_at=land_cover_row.fetched_at,
                feature_count=1,
                status="available",
                attribution="Contains modified Copernicus Sentinel data (2021+)",
            )
        )

    environment_count = int(environment_row[0])
    datasets.append(
        MonitorDatasetStatusEntryRead(
            category="environment",
            provider=str(environment_row[4]) if environment_row[4] is not None else "openstreetmap",
            dataset=str(environment_row[2]) if environment_row[2] is not None else "osm_environmental_features",
            dataset_version=str(environment_row[3]) if environment_row[3] is not None else None,
            fetched_at=environment_row[1],
            feature_count=environment_count,
            status="available" if environment_count > 0 else "missing",
            attribution="© OpenStreetMap contributors",
        )
    )

    return MonitorDatasetsRead(
        monitor_id=monitor_id,
        datasets=datasets,
    )


def get_event_intelligence(
    db_session: Session,
    *,
    monitor_id: UUID,
    event_id: UUID,
) -> EventIntelligenceRead | None:
    event = _get_event(db_session, monitor_id=monitor_id, event_id=event_id)
    if event is None:
        return None

    try:
        context_summary = get_change_event_impact_summary(db_session, monitor_id=monitor_id, event_id=event_id)
    except ImpactQueryError as exc:
        raise ExposureQueryError("Failed to fetch context impact summary") from exc

    if context_summary is None:
        raise ExposureConflictError("Change-event impact is not available. Compute impact before intelligence.")

    exposure_summary = get_change_event_exposure(db_session, monitor_id=monitor_id, event_id=event_id)
    if exposure_summary is None:
        raise ExposureConflictError("Change-event exposure is not available. Compute exposure before intelligence.")

    try:
        semantic_summary = get_change_event_semantic_analysis(db_session, monitor_id=monitor_id, event_id=event_id)
    except SemanticQueryError as exc:
        raise ExposureQueryError("Failed to fetch semantic change analysis") from exc

    return EventIntelligenceRead(
        event_id=event.id,
        monitor_id=event.monitor_id,
        analysis_id=event.analysis_id,
        scientific_severity=event.severity,
        change_confidence=event.confidence,
        context_significance=context_summary.context_significance,
        exposure_significance=exposure_summary.exposure_significance,
        roads=context_summary.roads,
        buildings=context_summary.buildings,
        waterways=context_summary.waterways,
        administrative_areas=context_summary.administrative_areas,
        population=exposure_summary.population,
        land_cover=exposure_summary.land_cover,
        environment=exposure_summary.environment,
        significance_factors=exposure_summary.significance_factors,
        semantic=semantic_summary,
    )
