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
    EnvironmentalFeatureCandidate,
    EnvironmentalFetchResult,
    EnvironmentalProvider,
    EnvironmentalProviderError,
    EnvironmentalProviderLimitExceededError,
)
from app.context.environment import ENVIRONMENT_DATASET, ENVIRONMENT_PROVIDER_NAME
from app.gis.conversion import geojson_geometry_to_wkb, wkb_to_geojson_geometry
from app.models import (
    ChangeEvent,
    ChangeEventEnvironmentalExposure,
    EnvironmentalFeature,
    Monitor,
)
from app.schemas import (
    EnvironmentRefreshResponse,
    EnvironmentalExposureFeatureRead,
    EnvironmentalExposureSummaryRead,
)

logger = logging.getLogger(__name__)

MAX_ENVIRONMENT_QUERY_AREA_KM2 = 750.0
MAX_ENVIRONMENT_FEATURES = 5_000
DEFAULT_ENVIRONMENT_NEARBY_BUFFER_M = 500.0
EXISTING_KEY_QUERY_CHUNK_SIZE = 1_000


class EnvironmentPersistenceError(Exception):
    pass


class EnvironmentQueryError(Exception):
    pass


class EnvironmentProviderRequestError(Exception):
    pass


class EnvironmentQueryTooLargeError(Exception):
    pass


class EnvironmentValidationError(Exception):
    pass


class EnvironmentConflictError(Exception):
    pass


def _normalize_optional_text(value: str | None, *, lower: bool = False) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if lower:
        normalized = normalized.lower()
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
        raise EnvironmentQueryError("Failed to fetch monitor") from exc


def _get_event(db_session: Session, *, monitor_id: UUID, event_id: UUID) -> ChangeEvent | None:
    try:
        return db_session.execute(
            select(ChangeEvent).where(
                ChangeEvent.monitor_id == monitor_id,
                ChangeEvent.id == event_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise EnvironmentQueryError("Failed to fetch change event") from exc


def _monitor_area_km2(db_session: Session, monitor_id: UUID) -> float:
    try:
        area_m2 = db_session.execute(
            text("SELECT ST_Area(geometry::geography) FROM monitors WHERE id = :monitor_id"),
            {"monitor_id": monitor_id},
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise EnvironmentQueryError("Failed to compute monitor area") from exc

    if area_m2 is None:
        raise EnvironmentQueryError("Unable to resolve monitor area")

    return float(area_m2) / 1_000_000


def _normalize_candidates(
    candidates: Sequence[EnvironmentalFeatureCandidate],
    *,
    provider: str,
    dataset: str,
    dataset_version: str,
    attribution: str,
) -> tuple[list[EnvironmentalFeatureCandidate], int]:
    normalized: list[EnvironmentalFeatureCandidate] = []
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
            EnvironmentalFeatureCandidate(
                source_feature_id=str(candidate.source_feature_id),
                feature_type=_normalize_optional_text(candidate.feature_type, lower=True) or "protected_area",
                feature_subtype=_normalize_optional_text(candidate.feature_subtype, lower=True),
                name=_normalize_optional_text(candidate.name),
                designation=_normalize_optional_text(candidate.designation),
                manager=_normalize_optional_text(candidate.manager),
                geometry=mapping(areal_geometry),
                properties=properties,
                source_updated_at=candidate.source_updated_at,
            )
        )

    return normalized, skipped


def _upsert_environmental_features(
    db_session: Session,
    *,
    monitor_id: UUID,
    provider: str,
    dataset: str,
    dataset_version: str,
    candidates: list[EnvironmentalFeatureCandidate],
) -> tuple[int, int]:
    if not candidates:
        return 0, 0

    deduped_by_key: dict[str, EnvironmentalFeatureCandidate] = {}
    for candidate in candidates:
        deduped_by_key[candidate.source_feature_id] = candidate

    source_feature_ids = list(deduped_by_key.keys())
    existing_ids: set[str] = set()

    try:
        for index in range(0, len(source_feature_ids), EXISTING_KEY_QUERY_CHUNK_SIZE):
            chunk = source_feature_ids[index : index + EXISTING_KEY_QUERY_CHUNK_SIZE]
            rows = db_session.execute(
                select(EnvironmentalFeature.source_feature_id).where(
                    EnvironmentalFeature.monitor_id == monitor_id,
                    EnvironmentalFeature.provider == provider,
                    EnvironmentalFeature.dataset == dataset,
                    EnvironmentalFeature.source_feature_id.in_(chunk),
                )
            ).scalars().all()
            existing_ids.update(rows)
    except SQLAlchemyError as exc:
        raise EnvironmentQueryError("Failed to load existing environmental features") from exc

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
                "feature_type": candidate.feature_type,
                "feature_subtype": candidate.feature_subtype,
                "name": candidate.name,
                "designation": candidate.designation,
                "manager": candidate.manager,
                "geometry": geojson_geometry_to_wkb(candidate.geometry),
                "properties": candidate.properties,
                "fetched_at": datetime.now(tz=timezone.utc),
                "updated_at": datetime.now(tz=timezone.utc),
            }
        )

    try:
        statement = insert(EnvironmentalFeature.__table__).values(rows_to_upsert)
        statement = statement.on_conflict_do_update(
            index_elements=["monitor_id", "provider", "dataset", "source_feature_id"],
            set_={
                "dataset_version": statement.excluded.dataset_version,
                "feature_type": statement.excluded.feature_type,
                "feature_subtype": statement.excluded.feature_subtype,
                "name": statement.excluded.name,
                "designation": statement.excluded.designation,
                "manager": statement.excluded.manager,
                "geometry": statement.excluded.geometry,
                "properties": statement.excluded.properties,
                "fetched_at": statement.excluded.fetched_at,
                "updated_at": statement.excluded.updated_at,
            },
        )
        db_session.execute(statement)
        db_session.commit()
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise EnvironmentPersistenceError("Failed to persist environmental features") from exc

    return inserted_count, updated_count


def refresh_monitor_environment(
    db_session: Session,
    *,
    monitor_id: UUID,
    provider: EnvironmentalProvider,
) -> EnvironmentRefreshResponse | None:
    monitor = _get_monitor(db_session, monitor_id)
    if monitor is None:
        return None

    monitor_area_km2 = _monitor_area_km2(db_session, monitor_id)
    if monitor_area_km2 > MAX_ENVIRONMENT_QUERY_AREA_KM2:
        raise EnvironmentQueryTooLargeError(
            "Environmental refresh AOI is too large for direct provider query. "
            "Use a smaller monitor or a bulk ingestion workflow."
        )

    started_at = time.perf_counter()
    monitor_geometry = wkb_to_geojson_geometry(monitor.geometry)

    try:
        fetch_result: EnvironmentalFetchResult = provider.fetch_protected_areas(
            intersects_geometry=monitor_geometry,
            max_features=MAX_ENVIRONMENT_FEATURES,
        )
    except EnvironmentalProviderLimitExceededError as exc:
        raise EnvironmentQueryTooLargeError("Environmental provider returned too many features for this AOI") from exc
    except EnvironmentalProviderError as exc:
        raise EnvironmentProviderRequestError("Environmental provider request failed") from exc

    normalized_candidates, normalize_skipped = _normalize_candidates(
        fetch_result.features,
        provider=fetch_result.provider,
        dataset=fetch_result.dataset,
        dataset_version=fetch_result.dataset_version,
        attribution=fetch_result.attribution,
    )

    inserted_count, updated_count = _upsert_environmental_features(
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
        "Environment refresh monitor_id=%s dataset=%s version=%s fetched=%s inserted=%s updated=%s skipped=%s",
        monitor_id,
        fetch_result.dataset,
        fetch_result.dataset_version,
        fetch_result.fetched_count,
        inserted_count,
        updated_count,
        skipped_count,
    )

    return EnvironmentRefreshResponse(
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


def _latest_environment_dataset_info(
    db_session: Session,
    *,
    monitor_id: UUID,
) -> tuple[str, str, str] | None:
    try:
        row = db_session.execute(
            select(
                EnvironmentalFeature.provider,
                EnvironmentalFeature.dataset,
                EnvironmentalFeature.dataset_version,
            )
            .where(EnvironmentalFeature.monitor_id == monitor_id)
            .order_by(EnvironmentalFeature.fetched_at.desc(), EnvironmentalFeature.id.desc())
            .limit(1)
        ).one_or_none()
    except SQLAlchemyError as exc:
        raise EnvironmentQueryError("Failed to load environmental dataset metadata") from exc

    if row is None:
        return None

    return str(row[0]), str(row[1]), str(row[2])


def compute_change_event_environmental_exposure(
    db_session: Session,
    *,
    monitor_id: UUID,
    event_id: UUID,
    nearby_buffer_m: float = DEFAULT_ENVIRONMENT_NEARBY_BUFFER_M,
) -> EnvironmentalExposureSummaryRead | None:
    event = _get_event(db_session, monitor_id=monitor_id, event_id=event_id)
    if event is None:
        return None

    dataset_info = _latest_environment_dataset_info(db_session, monitor_id=monitor_id)
    if dataset_info is None:
        provider_name = ENVIRONMENT_PROVIDER_NAME
        dataset_name = ENVIRONMENT_DATASET
        dataset_version = "unknown"
    else:
        provider_name, dataset_name, dataset_version = dataset_info

    try:
        intersects_rows = db_session.execute(
            text(
                """
                SELECT
                    ef.id AS environmental_feature_id,
                    ef.source_feature_id,
                    ef.feature_type,
                    ef.feature_subtype,
                    ef.name,
                    ef.designation,
                    ef.manager,
                    COALESCE(ST_Area(ST_Intersection(e.geometry, ef.geometry)::geography), 0) AS intersection_area_m2,
                    ST_Distance(e.geometry::geography, ef.geometry::geography) AS distance_m
                FROM change_events AS e
                JOIN environmental_features AS ef
                  ON ef.monitor_id = e.monitor_id
                WHERE e.id = :event_id
                  AND e.monitor_id = :monitor_id
                  AND ST_Intersects(e.geometry, ef.geometry)
                """
            ),
            {"event_id": event_id, "monitor_id": monitor_id},
        ).mappings().all()

        nearby_rows = db_session.execute(
            text(
                """
                SELECT
                    ef.id AS environmental_feature_id,
                    ef.source_feature_id,
                    ef.feature_type,
                    ef.feature_subtype,
                    ef.name,
                    ef.designation,
                    ef.manager,
                    ST_Distance(e.geometry::geography, ef.geometry::geography) AS distance_m
                FROM change_events AS e
                JOIN environmental_features AS ef
                  ON ef.monitor_id = e.monitor_id
                WHERE e.id = :event_id
                  AND e.monitor_id = :monitor_id
                  AND NOT ST_Intersects(e.geometry, ef.geometry)
                  AND ST_DWithin(e.geometry::geography, ef.geometry::geography, :buffer_m)
                """
            ),
            {"event_id": event_id, "monitor_id": monitor_id, "buffer_m": float(nearby_buffer_m)},
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise EnvironmentQueryError("Failed to compute environmental intersections") from exc

    event_area_m2 = float(event.area_m2)
    persisted_rows: list[dict[str, object]] = []
    features: list[EnvironmentalExposureFeatureRead] = []

    for row in intersects_rows:
        intersection_area = float(row["intersection_area_m2"] or 0.0)
        fraction = 0.0
        if event_area_m2 > 0:
            fraction = min(max(intersection_area / event_area_m2, 0.0), 1.0)

        features.append(
            EnvironmentalExposureFeatureRead(
                source_feature_id=str(row["source_feature_id"]),
                feature_type=str(row["feature_type"]),
                feature_subtype=row["feature_subtype"],
                name=row["name"],
                designation=row["designation"],
                manager=row["manager"],
                relationship_type="intersects",
                intersection_area_m2=intersection_area,
                intersection_fraction_of_event=fraction,
                distance_m=float(row["distance_m"] or 0.0),
            )
        )
        persisted_rows.append(
            {
                "event_id": event_id,
                "environmental_feature_id": row["environmental_feature_id"],
                "relationship_type": "intersects",
                "intersection_area_m2": intersection_area,
                "intersection_fraction_of_event": fraction,
                "distance_m": float(row["distance_m"] or 0.0),
                "properties": {
                    "provider": provider_name,
                    "dataset": dataset_name,
                    "dataset_version": dataset_version,
                },
            }
        )

    for row in nearby_rows:
        features.append(
            EnvironmentalExposureFeatureRead(
                source_feature_id=str(row["source_feature_id"]),
                feature_type=str(row["feature_type"]),
                feature_subtype=row["feature_subtype"],
                name=row["name"],
                designation=row["designation"],
                manager=row["manager"],
                relationship_type="within_buffer",
                intersection_area_m2=None,
                intersection_fraction_of_event=None,
                distance_m=float(row["distance_m"] or 0.0),
            )
        )
        persisted_rows.append(
            {
                "event_id": event_id,
                "environmental_feature_id": row["environmental_feature_id"],
                "relationship_type": "within_buffer",
                "intersection_area_m2": None,
                "intersection_fraction_of_event": None,
                "distance_m": float(row["distance_m"] or 0.0),
                "properties": {
                    "provider": provider_name,
                    "dataset": dataset_name,
                    "dataset_version": dataset_version,
                    "nearby_buffer_m": nearby_buffer_m,
                },
            }
        )

    features.sort(
        key=lambda item: (item.relationship_type != "intersects", item.distance_m, item.source_feature_id)
    )

    intersecting_count = sum(1 for feature in features if feature.relationship_type == "intersects")
    nearby_count = sum(1 for feature in features if feature.relationship_type == "within_buffer")
    intersection_area_m2 = float(
        sum((feature.intersection_area_m2 or 0.0) for feature in features if feature.relationship_type == "intersects")
    )
    protected_area_fraction = min(max(intersection_area_m2 / event_area_m2, 0.0), 1.0) if event_area_m2 > 0 else 0.0
    nearest_distance_m = min((feature.distance_m for feature in features), default=None)
    designations = sorted({feature.designation for feature in features if feature.designation})

    summary = EnvironmentalExposureSummaryRead(
        provider=provider_name,
        dataset=dataset_name,
        dataset_version=dataset_version,
        nearby_buffer_m=float(nearby_buffer_m),
        intersecting_count=intersecting_count,
        intersection_area_m2=intersection_area_m2,
        protected_area_fraction=protected_area_fraction,
        nearby_count=nearby_count,
        nearest_distance_m=nearest_distance_m,
        designations=designations,
        features=features,
    )

    event_properties = dict(event.properties or {})
    event_properties["environment_exposure"] = {
        "provider": provider_name,
        "dataset": dataset_name,
        "dataset_version": dataset_version,
        "intersecting_count": intersecting_count,
        "intersection_area_m2": intersection_area_m2,
        "protected_area_fraction": protected_area_fraction,
        "nearby_count": nearby_count,
        "nearest_distance_m": nearest_distance_m,
        "computed_at": datetime.now(tz=timezone.utc).isoformat(),
        "nearby_buffer_m": nearby_buffer_m,
    }

    try:
        db_session.execute(
            delete(ChangeEventEnvironmentalExposure).where(
                ChangeEventEnvironmentalExposure.event_id == event_id,
            )
        )
        if persisted_rows:
            db_session.execute(insert(ChangeEventEnvironmentalExposure.__table__).values(persisted_rows))

        event.properties = event_properties
        event.updated_at = func.now()
        db_session.commit()
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise EnvironmentPersistenceError("Failed to persist environmental exposure") from exc

    return summary


def get_change_event_environmental_exposure(
    db_session: Session,
    *,
    monitor_id: UUID,
    event_id: UUID,
) -> EnvironmentalExposureSummaryRead | None:
    event = _get_event(db_session, monitor_id=monitor_id, event_id=event_id)
    if event is None:
        return None

    try:
        rows = db_session.execute(
            select(ChangeEventEnvironmentalExposure, EnvironmentalFeature)
            .join(
                EnvironmentalFeature,
                EnvironmentalFeature.id == ChangeEventEnvironmentalExposure.environmental_feature_id,
            )
            .where(ChangeEventEnvironmentalExposure.event_id == event_id)
            .order_by(
                ChangeEventEnvironmentalExposure.relationship_type.asc(),
                ChangeEventEnvironmentalExposure.distance_m.asc(),
            )
        ).all()
    except SQLAlchemyError as exc:
        raise EnvironmentQueryError("Failed to fetch environmental exposure") from exc

    if not rows:
        snapshot = (event.properties or {}).get("environment_exposure")
        if not isinstance(snapshot, dict):
            return None

        return EnvironmentalExposureSummaryRead(
            provider=str(snapshot.get("provider", "unknown")),
            dataset=str(snapshot.get("dataset", "unknown")),
            dataset_version=str(snapshot.get("dataset_version", "unknown")),
            nearby_buffer_m=float(snapshot.get("nearby_buffer_m", DEFAULT_ENVIRONMENT_NEARBY_BUFFER_M)),
            intersecting_count=int(snapshot.get("intersecting_count", 0)),
            intersection_area_m2=float(snapshot.get("intersection_area_m2", 0.0)),
            protected_area_fraction=float(snapshot.get("protected_area_fraction", 0.0)),
            nearby_count=int(snapshot.get("nearby_count", 0)),
            nearest_distance_m=(
                float(snapshot.get("nearest_distance_m"))
                if snapshot.get("nearest_distance_m") is not None
                else None
            ),
            designations=[],
            features=[],
        )

    first_impact, first_feature = rows[0]
    features = [
        EnvironmentalExposureFeatureRead(
            source_feature_id=feature.source_feature_id,
            feature_type=feature.feature_type,
            feature_subtype=feature.feature_subtype,
            name=feature.name,
            designation=feature.designation,
            manager=feature.manager,
            relationship_type=impact.relationship_type,
            intersection_area_m2=impact.intersection_area_m2,
            intersection_fraction_of_event=impact.intersection_fraction_of_event,
            distance_m=impact.distance_m,
        )
        for impact, feature in rows
    ]

    intersection_area_m2 = float(
        sum((item.intersection_area_m2 or 0.0) for item in features if item.relationship_type == "intersects")
    )
    event_area_m2 = float(event.area_m2)
    protected_area_fraction = min(max(intersection_area_m2 / event_area_m2, 0.0), 1.0) if event_area_m2 > 0 else 0.0
    intersecting_count = sum(1 for item in features if item.relationship_type == "intersects")
    nearby_count = sum(1 for item in features if item.relationship_type == "within_buffer")
    nearest_distance_m = min((item.distance_m for item in features), default=None)
    designations = sorted({item.designation for item in features if item.designation})

    nearby_buffer_m = DEFAULT_ENVIRONMENT_NEARBY_BUFFER_M
    if isinstance(first_impact.properties, dict) and first_impact.properties.get("nearby_buffer_m") is not None:
        nearby_buffer_m = float(first_impact.properties["nearby_buffer_m"])

    return EnvironmentalExposureSummaryRead(
        provider=first_impact.properties.get("provider", first_feature.provider) if isinstance(first_impact.properties, dict) else first_feature.provider,
        dataset=first_impact.properties.get("dataset", first_feature.dataset) if isinstance(first_impact.properties, dict) else first_feature.dataset,
        dataset_version=(
            first_impact.properties.get("dataset_version", first_feature.dataset_version)
            if isinstance(first_impact.properties, dict)
            else first_feature.dataset_version
        ),
        nearby_buffer_m=nearby_buffer_m,
        intersecting_count=intersecting_count,
        intersection_area_m2=intersection_area_m2,
        protected_area_fraction=protected_area_fraction,
        nearby_count=nearby_count,
        nearest_distance_m=nearest_distance_m,
        designations=designations,
        features=features,
    )
