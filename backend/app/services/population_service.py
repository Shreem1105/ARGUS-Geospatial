from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Sequence
from uuid import UUID

from shapely import make_valid
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping, shape
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.context import (
    PopulationFeatureCandidate,
    PopulationFetchResult,
    PopulationProvider,
    PopulationProviderError,
    PopulationProviderLimitExceededError,
)
from app.gis.conversion import geojson_geometry_to_wkb, wkb_to_geojson_geometry
from app.models import ChangeEvent, ChangeEventPopulationExposure, Monitor, PopulationFeature
from app.schemas import PopulationExposureSummaryRead, PopulationExposureUnitRead, PopulationRefreshResponse

logger = logging.getLogger(__name__)

MAX_POPULATION_QUERY_AREA_KM2 = 750.0
MAX_POPULATION_FEATURES = 5_000
EXISTING_KEY_QUERY_CHUNK_SIZE = 1_000


class PopulationPersistenceError(Exception):
    pass


class PopulationQueryError(Exception):
    pass


class PopulationProviderRequestError(Exception):
    pass


class PopulationQueryTooLargeError(Exception):
    pass


class PopulationValidationError(Exception):
    pass


class PopulationConflictError(Exception):
    pass


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _extract_areal_geometry(candidate_geometry: Polygon | MultiPolygon | GeometryCollection):
    if isinstance(candidate_geometry, Polygon):
        return candidate_geometry
    if isinstance(candidate_geometry, MultiPolygon):
        return candidate_geometry
    if isinstance(candidate_geometry, GeometryCollection):
        polygons: list[Polygon] = []
        for child in candidate_geometry.geoms:
            if isinstance(child, Polygon):
                polygons.append(child)
            elif isinstance(child, MultiPolygon):
                polygons.extend([polygon for polygon in child.geoms if not polygon.is_empty])
        if not polygons:
            return None
        if len(polygons) == 1:
            return polygons[0]
        return MultiPolygon(polygons)
    return None


def _get_monitor(db_session: Session, monitor_id: UUID) -> Monitor | None:
    try:
        return db_session.execute(select(Monitor).where(Monitor.id == monitor_id)).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise PopulationQueryError("Failed to fetch monitor") from exc


def _get_event(db_session: Session, *, monitor_id: UUID, event_id: UUID) -> ChangeEvent | None:
    try:
        return db_session.execute(
            select(ChangeEvent).where(
                ChangeEvent.monitor_id == monitor_id,
                ChangeEvent.id == event_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise PopulationQueryError("Failed to fetch change event") from exc


def _monitor_area_km2(db_session: Session, monitor_id: UUID) -> float:
    try:
        area_m2 = db_session.execute(
            text("SELECT ST_Area(geometry::geography) FROM monitors WHERE id = :monitor_id"),
            {"monitor_id": monitor_id},
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise PopulationQueryError("Failed to compute monitor area") from exc

    if area_m2 is None:
        raise PopulationQueryError("Unable to resolve monitor area")

    return float(area_m2) / 1_000_000


def _normalize_candidates(
    candidates: Sequence[PopulationFeatureCandidate],
    *,
    provider: str,
    dataset: str,
    dataset_version: str,
    attribution: str,
) -> tuple[list[PopulationFeatureCandidate], int]:
    normalized: list[PopulationFeatureCandidate] = []
    skipped = 0

    for candidate in candidates:
        try:
            candidate_shape = shape(candidate.geometry)
        except Exception:
            skipped += 1
            continue

        if candidate_shape.is_empty:
            skipped += 1
            continue

        repaired_shape = candidate_shape if candidate_shape.is_valid else make_valid(candidate_shape)
        if repaired_shape.is_empty:
            skipped += 1
            continue

        areal_geometry = _extract_areal_geometry(repaired_shape)
        if areal_geometry is None or areal_geometry.is_empty:
            skipped += 1
            continue

        if candidate.population is not None and candidate.population < 0:
            skipped += 1
            continue

        properties = dict(candidate.properties)
        properties.update(
            {
                "provider": provider,
                "dataset": dataset,
                "dataset_version": dataset_version,
                "provider_attribution": attribution,
            }
        )

        normalized.append(
            PopulationFeatureCandidate(
                source_feature_id=str(candidate.source_feature_id),
                geography_type=str(candidate.geography_type).strip().lower() or "unknown",
                name=_normalize_optional_text(candidate.name),
                population=candidate.population,
                geometry=mapping(areal_geometry),
                properties=properties,
                source_updated_at=candidate.source_updated_at,
            )
        )

    return normalized, skipped


def _upsert_population_features(
    db_session: Session,
    *,
    monitor_id: UUID,
    provider: str,
    dataset: str,
    dataset_version: str,
    candidates: list[PopulationFeatureCandidate],
) -> tuple[int, int]:
    if not candidates:
        return 0, 0

    deduped_by_key: dict[str, PopulationFeatureCandidate] = {}
    for candidate in candidates:
        deduped_by_key[candidate.source_feature_id] = candidate

    source_feature_ids = list(deduped_by_key.keys())
    existing_ids: set[str] = set()

    try:
        for index in range(0, len(source_feature_ids), EXISTING_KEY_QUERY_CHUNK_SIZE):
            chunk = source_feature_ids[index : index + EXISTING_KEY_QUERY_CHUNK_SIZE]
            rows = db_session.execute(
                select(PopulationFeature.source_feature_id).where(
                    PopulationFeature.monitor_id == monitor_id,
                    PopulationFeature.provider == provider,
                    PopulationFeature.dataset == dataset,
                    PopulationFeature.source_feature_id.in_(chunk),
                )
            ).scalars().all()
            existing_ids.update(rows)
    except SQLAlchemyError as exc:
        raise PopulationQueryError("Failed to load existing population features") from exc

    inserted_count = sum(1 for source_id in source_feature_ids if source_id not in existing_ids)
    updated_count = len(source_feature_ids) - inserted_count

    rows_to_upsert = []
    for source_feature_id in source_feature_ids:
        candidate = deduped_by_key[source_feature_id]
        rows_to_upsert.append(
            {
                "monitor_id": monitor_id,
                "provider": provider,
                "dataset": dataset,
                "dataset_version": dataset_version,
                "source_feature_id": source_feature_id,
                "geography_type": candidate.geography_type,
                "name": candidate.name,
                "population": candidate.population,
                "geometry": geojson_geometry_to_wkb(candidate.geometry),
                "properties": candidate.properties,
                "source_updated_at": candidate.source_updated_at,
                "fetched_at": datetime.now(tz=timezone.utc),
                "updated_at": datetime.now(tz=timezone.utc),
            }
        )

    try:
        statement = insert(PopulationFeature.__table__).values(rows_to_upsert)
        statement = statement.on_conflict_do_update(
            index_elements=["monitor_id", "provider", "dataset", "source_feature_id"],
            set_={
                "dataset_version": statement.excluded.dataset_version,
                "geography_type": statement.excluded.geography_type,
                "name": statement.excluded.name,
                "population": statement.excluded.population,
                "geometry": statement.excluded.geometry,
                "properties": statement.excluded.properties,
                "source_updated_at": statement.excluded.source_updated_at,
                "fetched_at": statement.excluded.fetched_at,
                "updated_at": statement.excluded.updated_at,
            },
        )
        db_session.execute(statement)
        db_session.commit()
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise PopulationPersistenceError("Failed to persist population features") from exc

    return inserted_count, updated_count


def refresh_monitor_population(
    db_session: Session,
    *,
    monitor_id: UUID,
    provider: PopulationProvider,
) -> PopulationRefreshResponse | None:
    monitor = _get_monitor(db_session, monitor_id)
    if monitor is None:
        return None

    monitor_area_km2 = _monitor_area_km2(db_session, monitor_id)
    if monitor_area_km2 > MAX_POPULATION_QUERY_AREA_KM2:
        raise PopulationQueryTooLargeError(
            "Population refresh AOI is too large for direct provider query. "
            "Use a smaller monitor or a bulk ingestion workflow."
        )

    started_at = time.perf_counter()
    monitor_geometry = wkb_to_geojson_geometry(monitor.geometry)

    try:
        fetch_result: PopulationFetchResult = provider.fetch_population_units(
            intersects_geometry=monitor_geometry,
            max_features=MAX_POPULATION_FEATURES,
        )
    except PopulationProviderLimitExceededError as exc:
        raise PopulationQueryTooLargeError("Population provider returned too many features for this AOI") from exc
    except PopulationProviderError as exc:
        raise PopulationProviderRequestError("Population provider request failed") from exc

    normalized_candidates, normalize_skipped = _normalize_candidates(
        fetch_result.features,
        provider=fetch_result.provider,
        dataset=fetch_result.dataset,
        dataset_version=fetch_result.dataset_version,
        attribution=fetch_result.attribution,
    )

    inserted_count, updated_count = _upsert_population_features(
        db_session,
        monitor_id=monitor_id,
        provider=fetch_result.provider,
        dataset=fetch_result.dataset,
        dataset_version=fetch_result.dataset_version,
        candidates=normalized_candidates,
    )

    skipped_count = fetch_result.skipped_count + normalize_skipped
    elapsed_seconds = time.perf_counter() - started_at

    logger.info(
        "Population refresh monitor_id=%s dataset=%s version=%s fetched=%s inserted=%s updated=%s skipped=%s",
        monitor_id,
        fetch_result.dataset,
        fetch_result.dataset_version,
        fetch_result.fetched_count,
        inserted_count,
        updated_count,
        skipped_count,
    )

    return PopulationRefreshResponse(
        monitor_id=monitor_id,
        provider=fetch_result.provider,
        dataset=fetch_result.dataset,
        dataset_version=fetch_result.dataset_version,
        attribution=fetch_result.attribution,
        fetched=fetch_result.fetched_count,
        inserted=inserted_count,
        updated=updated_count,
        skipped=skipped_count,
        elapsed_seconds=round(elapsed_seconds, 6),
    )


def _latest_population_dataset_info(
    db_session: Session,
    *,
    monitor_id: UUID,
) -> tuple[str, str] | None:
    try:
        row = db_session.execute(
            select(
                PopulationFeature.dataset,
                PopulationFeature.dataset_version,
            )
            .where(PopulationFeature.monitor_id == monitor_id)
            .order_by(PopulationFeature.fetched_at.desc(), PopulationFeature.id.desc())
            .limit(1)
        ).one_or_none()
    except SQLAlchemyError as exc:
        raise PopulationQueryError("Failed to load population dataset metadata") from exc

    if row is None:
        return None

    return str(row[0]), str(row[1])


def compute_change_event_population_exposure(
    db_session: Session,
    *,
    monitor_id: UUID,
    event_id: UUID,
) -> PopulationExposureSummaryRead | None:
    event = _get_event(db_session, monitor_id=monitor_id, event_id=event_id)
    if event is None:
        return None

    dataset_info = _latest_population_dataset_info(db_session, monitor_id=monitor_id)
    if dataset_info is None:
        raise PopulationConflictError("Population dataset is not available. Refresh population data first.")

    dataset, dataset_version = dataset_info

    try:
        rows = db_session.execute(
            text(
                """
                SELECT
                    pf.id AS population_feature_id,
                    pf.source_feature_id,
                    pf.name,
                    pf.population,
                    ST_Area(pf.geometry::geography) AS source_area_m2,
                    ST_Area(ST_Intersection(e.geometry, pf.geometry)::geography) AS intersection_area_m2
                FROM change_events AS e
                JOIN population_features AS pf
                  ON pf.monitor_id = e.monitor_id
                WHERE e.id = :event_id
                  AND e.monitor_id = :monitor_id
                  AND ST_Intersects(e.geometry, pf.geometry)
                """
            ),
            {"event_id": event_id, "monitor_id": monitor_id},
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise PopulationQueryError("Failed to compute event population intersections") from exc

    exposure_rows: list[dict[str, object]] = []
    exposure_units: list[PopulationExposureUnitRead] = []

    for row in rows:
        source_area_m2 = float(row["source_area_m2"] or 0.0)
        if source_area_m2 <= 0:
            continue

        intersection_area_m2 = float(row["intersection_area_m2"] or 0.0)
        raw_fraction = intersection_area_m2 / source_area_m2
        intersection_fraction = min(max(raw_fraction, 0.0), 1.0)

        source_population = row["population"]
        source_population_value = int(source_population) if source_population is not None else None
        estimated_exposed_population = (
            float(source_population_value * intersection_fraction)
            if source_population_value is not None
            else None
        )

        exposure_units.append(
            PopulationExposureUnitRead(
                source_feature_id=str(row["source_feature_id"]),
                name=row["name"],
                source_population=source_population_value,
                intersection_area_m2=intersection_area_m2,
                source_area_m2=source_area_m2,
                intersection_fraction=intersection_fraction,
                estimated_exposed_population=estimated_exposed_population,
            )
        )

        exposure_rows.append(
            {
                "event_id": event_id,
                "population_feature_id": row["population_feature_id"],
                "intersection_area_m2": intersection_area_m2,
                "source_area_m2": source_area_m2,
                "intersection_fraction": intersection_fraction,
                "source_population": source_population_value,
                "estimated_exposed_population": estimated_exposed_population,
                "properties": {
                    "method": "areal_weighting",
                    "dataset": dataset,
                    "dataset_version": dataset_version,
                },
            }
        )

    exposure_units.sort(
        key=lambda item: (item.estimated_exposed_population or 0.0, item.intersection_fraction),
        reverse=True,
    )
    largest_population_overlap = exposure_units[0] if exposure_units else None
    estimated_exposed_population = float(
        sum(item.estimated_exposed_population or 0.0 for item in exposure_units)
    )

    summary = PopulationExposureSummaryRead(
        method="areal_weighting",
        dataset=dataset,
        dataset_version=dataset_version,
        intersecting_units=len(exposure_units),
        estimated_exposed_population=estimated_exposed_population,
        largest_population_overlap=largest_population_overlap,
        units=exposure_units,
    )

    event_properties = dict(event.properties or {})
    event_properties["population_exposure"] = {
        "method": "areal_weighting",
        "dataset": dataset,
        "dataset_version": dataset_version,
        "intersecting_units": len(exposure_units),
        "estimated_exposed_population": estimated_exposed_population,
        "computed_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    try:
        db_session.execute(
            delete(ChangeEventPopulationExposure).where(
                ChangeEventPopulationExposure.event_id == event_id,
            )
        )
        if exposure_rows:
            db_session.execute(insert(ChangeEventPopulationExposure.__table__).values(exposure_rows))

        event.properties = event_properties
        event.updated_at = func.now()
        db_session.commit()
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise PopulationPersistenceError("Failed to persist event population exposure") from exc

    return summary


def get_change_event_population_exposure(
    db_session: Session,
    *,
    monitor_id: UUID,
    event_id: UUID,
) -> PopulationExposureSummaryRead | None:
    event = _get_event(db_session, monitor_id=monitor_id, event_id=event_id)
    if event is None:
        return None

    dataset_info = _latest_population_dataset_info(db_session, monitor_id=monitor_id)
    if dataset_info is None:
        return None
    dataset, dataset_version = dataset_info

    try:
        rows = db_session.execute(
            select(ChangeEventPopulationExposure, PopulationFeature)
            .join(
                PopulationFeature,
                PopulationFeature.id == ChangeEventPopulationExposure.population_feature_id,
            )
            .where(ChangeEventPopulationExposure.event_id == event_id)
            .order_by(
                ChangeEventPopulationExposure.estimated_exposed_population.desc().nullslast(),
                ChangeEventPopulationExposure.intersection_fraction.desc(),
            )
        ).all()
    except SQLAlchemyError as exc:
        raise PopulationQueryError("Failed to fetch event population exposure") from exc

    units = [
        PopulationExposureUnitRead(
            source_feature_id=feature.source_feature_id,
            name=feature.name,
            source_population=exposure.source_population,
            intersection_area_m2=exposure.intersection_area_m2,
            source_area_m2=exposure.source_area_m2,
            intersection_fraction=exposure.intersection_fraction,
            estimated_exposed_population=exposure.estimated_exposed_population,
        )
        for exposure, feature in rows
    ]

    if not rows:
        event_population = (event.properties or {}).get("population_exposure")
        if not isinstance(event_population, dict):
            return None

        return PopulationExposureSummaryRead(
            method="areal_weighting",
            dataset=str(event_population.get("dataset", dataset)),
            dataset_version=str(event_population.get("dataset_version", dataset_version)),
            intersecting_units=int(event_population.get("intersecting_units", 0)),
            estimated_exposed_population=float(event_population.get("estimated_exposed_population", 0.0)),
            largest_population_overlap=None,
            units=[],
        )

    largest = units[0] if units else None
    total_estimated = float(sum(unit.estimated_exposed_population or 0.0 for unit in units))

    return PopulationExposureSummaryRead(
        method="areal_weighting",
        dataset=dataset,
        dataset_version=dataset_version,
        intersecting_units=len(units),
        estimated_exposed_population=total_estimated,
        largest_population_overlap=largest,
        units=units,
    )

