from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import UUID

from geoalchemy2.shape import to_shape
from shapely import make_valid
from shapely.geometry import mapping, shape
from sqlalchemy import func, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.context import (
    FEATURE_TYPE_ADMINISTRATIVE,
    FEATURE_TYPE_BUILDING,
    FEATURE_TYPE_ROAD,
    FEATURE_TYPE_WATERWAY,
    SUPPORTED_CONTEXT_FEATURE_TYPES,
    ContextFeatureCandidate,
    ContextProvider,
    ContextProviderError,
    ContextProviderLimitExceededError,
)
from app.gis.conversion import geojson_geometry_to_wkb, wkb_to_geojson_geometry
from app.models import ContextFeature, Monitor
from app.schemas import ContextFeatureRead, ContextRefreshResponse, ContextSummaryRead

logger = logging.getLogger(__name__)

MAX_CONTEXT_QUERY_AREA_KM2 = 500.0
MAX_CONTEXT_FEATURES_PER_TYPE = 4_000
EXISTING_KEY_QUERY_CHUNK_SIZE = 1_000


class ContextPersistenceError(Exception):
    pass


class ContextQueryError(Exception):
    pass


class ContextProviderRequestError(Exception):
    pass


class ContextQueryTooLargeError(Exception):
    pass


class ContextValidationError(Exception):
    pass


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _normalize_optional_text(value: str | None, *, lower: bool = False) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if lower:
        normalized = normalized.lower()
    return normalized or None


def _normalize_feature_types(feature_types: Sequence[str] | None) -> list[str]:
    if feature_types is None:
        return list(SUPPORTED_CONTEXT_FEATURE_TYPES)

    normalized: list[str] = []
    seen: set[str] = set()

    for feature_type in feature_types:
        candidate = str(feature_type).strip().lower()
        if not candidate:
            raise ContextValidationError("feature type must not be blank")
        if candidate not in SUPPORTED_CONTEXT_FEATURE_TYPES:
            supported = ", ".join(SUPPORTED_CONTEXT_FEATURE_TYPES)
            raise ContextValidationError(f"feature type '{candidate}' is unsupported (supported: {supported})")
        if candidate in seen:
            continue
        normalized.append(candidate)
        seen.add(candidate)

    if not normalized:
        raise ContextValidationError("at least one feature type must be selected")

    return normalized


def _monitor_area_km2(db_session: Session, monitor_id: UUID) -> float:
    area_m2 = db_session.execute(
        text("SELECT ST_Area(geometry::geography) FROM monitors WHERE id = :monitor_id"),
        {"monitor_id": monitor_id},
    ).scalar_one_or_none()

    if area_m2 is None:
        raise ContextQueryError("Unable to resolve monitor area")

    return float(area_m2) / 1_000_000


def _monitor_vertex_count(monitor: Monitor) -> int:
    geometry = wkb_to_geojson_geometry(monitor.geometry)
    if geometry.get("type") != "Polygon":
        return 0

    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list):
        return 0

    return sum(len(ring) for ring in coordinates if isinstance(ring, list))


def _feature_to_read(feature: ContextFeature) -> ContextFeatureRead:
    return ContextFeatureRead(
        id=feature.id,
        monitor_id=feature.monitor_id,
        provider=feature.provider,
        provider_feature_id=feature.provider_feature_id,
        feature_type=feature.feature_type,
        feature_subtype=feature.feature_subtype,
        name=feature.name,
        geometry=wkb_to_geojson_geometry(feature.geometry),
        properties=feature.properties,
        source_updated_at=feature.source_updated_at,
        fetched_at=feature.fetched_at,
        created_at=feature.created_at,
        updated_at=feature.updated_at,
    )


def _get_monitor(db_session: Session, monitor_id: UUID) -> Monitor | None:
    try:
        return db_session.execute(select(Monitor).where(Monitor.id == monitor_id)).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise ContextQueryError("Failed to fetch monitor") from exc


def _upsert_context_features(
    db_session: Session,
    *,
    monitor_id: UUID,
    candidates: list[ContextFeatureCandidate],
    provider_name: str,
) -> tuple[int, int]:
    if not candidates:
        return 0, 0

    deduped_by_key: dict[tuple[str, str, str], ContextFeatureCandidate] = {}
    for candidate in candidates:
        key = (
            provider_name,
            candidate.provider_feature_id,
            candidate.feature_type,
        )
        deduped_by_key[key] = candidate

    deduped_candidates = list(deduped_by_key.values())
    key_tuples = list(deduped_by_key.keys())

    try:
        existing_keys: set[tuple[str, str, str]] = set()
        for start in range(0, len(key_tuples), EXISTING_KEY_QUERY_CHUNK_SIZE):
            chunk = key_tuples[start : start + EXISTING_KEY_QUERY_CHUNK_SIZE]
            chunk_rows = db_session.execute(
                select(
                    ContextFeature.provider,
                    ContextFeature.provider_feature_id,
                    ContextFeature.feature_type,
                ).where(
                    ContextFeature.monitor_id == monitor_id,
                    tuple_(
                        ContextFeature.provider,
                        ContextFeature.provider_feature_id,
                        ContextFeature.feature_type,
                    ).in_(chunk),
                )
            ).all()
            existing_keys.update((str(row[0]), str(row[1]), str(row[2])) for row in chunk_rows)
    except SQLAlchemyError as exc:
        raise ContextQueryError("Failed to check existing context features") from exc

    inserted_count = sum(1 for key in key_tuples if key not in existing_keys)
    updated_count = len(key_tuples) - inserted_count

    fetched_at = datetime.now(tz=timezone.utc)
    rows: list[dict[str, Any]] = []
    for candidate in deduped_candidates:
        rows.append(
            {
                "monitor_id": monitor_id,
                "provider": provider_name,
                "provider_feature_id": candidate.provider_feature_id,
                "feature_type": candidate.feature_type,
                "feature_subtype": candidate.feature_subtype,
                "name": candidate.name,
                "geometry": geojson_geometry_to_wkb(candidate.geometry),
                "properties": candidate.properties,
                "source_updated_at": candidate.source_updated_at,
                "fetched_at": fetched_at,
            }
        )

    try:
        statement = insert(ContextFeature.__table__).values(rows)
        statement = statement.on_conflict_do_update(
            index_elements=["monitor_id", "provider", "provider_feature_id", "feature_type"],
            set_={
                "feature_subtype": statement.excluded.feature_subtype,
                "name": statement.excluded.name,
                "geometry": statement.excluded.geometry,
                "properties": statement.excluded.properties,
                "source_updated_at": statement.excluded.source_updated_at,
                "fetched_at": statement.excluded.fetched_at,
                "updated_at": func.now(),
            },
        )
        db_session.execute(statement)
        db_session.commit()
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise ContextPersistenceError("Failed to persist context features") from exc

    return inserted_count, updated_count


def refresh_monitor_context(
    db_session: Session,
    *,
    monitor_id: UUID,
    feature_types: Sequence[str] | None,
    provider: ContextProvider,
) -> ContextRefreshResponse | None:
    monitor = _get_monitor(db_session, monitor_id)
    if monitor is None:
        return None

    selected_types = _normalize_feature_types(feature_types)
    monitor_area_km2 = _monitor_area_km2(db_session, monitor_id)
    if monitor_area_km2 > MAX_CONTEXT_QUERY_AREA_KM2:
        raise ContextQueryTooLargeError(
            "Monitor AOI is too large for direct contextual refresh; a bulk-data workflow is required"
        )

    if _monitor_vertex_count(monitor) > 1_500:
        raise ContextQueryTooLargeError(
            "Monitor AOI geometry is too complex for direct contextual refresh; a bulk-data workflow is required"
        )

    monitor_geometry = wkb_to_geojson_geometry(monitor.geometry)
    monitor_shape = to_shape(monitor.geometry)

    provider_methods = {
        FEATURE_TYPE_ROAD: provider.fetch_roads,
        FEATURE_TYPE_BUILDING: provider.fetch_buildings,
        FEATURE_TYPE_WATERWAY: provider.fetch_waterways,
        FEATURE_TYPE_ADMINISTRATIVE: provider.fetch_administrative_boundaries,
    }

    started_at = time.perf_counter()
    fetched_count = 0
    skipped_count = 0
    by_type = {feature_type: 0 for feature_type in SUPPORTED_CONTEXT_FEATURE_TYPES}
    normalized_candidates: list[ContextFeatureCandidate] = []

    for feature_type in selected_types:
        fetch_fn = provider_methods[feature_type]
        try:
            batch = fetch_fn(
                intersects_geometry=monitor_geometry,
                max_features=MAX_CONTEXT_FEATURES_PER_TYPE,
            )
        except ContextProviderLimitExceededError as exc:
            raise ContextQueryTooLargeError(
                "Context provider returned too many features for this AOI; reduce AOI size or use a bulk-data workflow"
            ) from exc
        except ContextProviderError as exc:
            raise ContextProviderRequestError("Context provider unavailable") from exc

        fetched_count += batch.fetched_count
        skipped_count += batch.skipped_count

        for candidate in batch.features:
            try:
                candidate_shape = shape(candidate.geometry)
            except Exception:
                skipped_count += 1
                continue

            if not candidate_shape.is_valid:
                candidate_shape = make_valid(candidate_shape)

            if candidate_shape.is_empty:
                skipped_count += 1
                continue

            if not candidate_shape.intersects(monitor_shape):
                skipped_count += 1
                continue

            if feature_type in {FEATURE_TYPE_BUILDING, FEATURE_TYPE_ADMINISTRATIVE}:
                if candidate_shape.geom_type not in {"Polygon", "MultiPolygon"}:
                    skipped_count += 1
                    continue

            if feature_type == FEATURE_TYPE_ROAD:
                if candidate_shape.geom_type not in {"LineString", "MultiLineString"}:
                    skipped_count += 1
                    continue

            by_type[feature_type] += 1

            properties = dict(candidate.properties)
            properties["provider_attribution"] = provider.attribution

            normalized_candidates.append(
                ContextFeatureCandidate(
                    provider_feature_id=candidate.provider_feature_id,
                    feature_type=feature_type,
                    feature_subtype=_normalize_optional_text(candidate.feature_subtype, lower=True),
                    name=_normalize_optional_text(candidate.name),
                    geometry=_jsonable(mapping(candidate_shape)),
                    properties=properties,
                    source_updated_at=candidate.source_updated_at,
                )
            )

    inserted_count, updated_count = _upsert_context_features(
        db_session,
        monitor_id=monitor_id,
        candidates=normalized_candidates,
        provider_name=provider.provider_name,
    )

    elapsed_seconds = time.perf_counter() - started_at
    logger.info(
        "Context refresh monitor_id=%s provider=%s fetched=%s inserted=%s updated=%s skipped=%s area_km2=%.3f",
        monitor_id,
        provider.provider_name,
        fetched_count,
        inserted_count,
        updated_count,
        skipped_count,
        monitor_area_km2,
    )

    return ContextRefreshResponse(
        monitor_id=monitor_id,
        provider=provider.provider_name,
        attribution=provider.attribution,
        fetched=fetched_count,
        inserted=inserted_count,
        updated=updated_count,
        skipped=skipped_count,
        by_type=by_type,
        elapsed_seconds=round(elapsed_seconds, 6),
    )


def list_context_features(
    db_session: Session,
    *,
    monitor_id: UUID,
    feature_type: str | None,
    feature_subtype: str | None,
    provider: str | None,
    limit: int,
    offset: int,
) -> list[ContextFeatureRead] | None:
    monitor = _get_monitor(db_session, monitor_id)
    if monitor is None:
        return None

    try:
        statement = select(ContextFeature).where(ContextFeature.monitor_id == monitor_id)

        if feature_type is not None:
            statement = statement.where(ContextFeature.feature_type == feature_type)
        if feature_subtype is not None:
            statement = statement.where(ContextFeature.feature_subtype == feature_subtype)
        if provider is not None:
            statement = statement.where(ContextFeature.provider == provider)

        statement = statement.order_by(ContextFeature.fetched_at.desc(), ContextFeature.id.desc())
        statement = statement.limit(limit).offset(offset)

        rows = db_session.execute(statement).scalars().all()
    except SQLAlchemyError as exc:
        raise ContextQueryError("Failed to list context features") from exc

    return [_feature_to_read(row) for row in rows]


def get_context_summary(db_session: Session, *, monitor_id: UUID) -> ContextSummaryRead | None:
    monitor = _get_monitor(db_session, monitor_id)
    if monitor is None:
        return None

    try:
        aggregate = db_session.execute(
            select(
                func.count(ContextFeature.id),
                func.max(ContextFeature.fetched_at),
            ).where(ContextFeature.monitor_id == monitor_id)
        ).one()

        by_type_rows = db_session.execute(
            select(ContextFeature.feature_type, func.count(ContextFeature.id))
            .where(ContextFeature.monitor_id == monitor_id)
            .group_by(ContextFeature.feature_type)
        ).all()

        providers = db_session.execute(
            select(ContextFeature.provider)
            .where(ContextFeature.monitor_id == monitor_id)
            .distinct()
            .order_by(ContextFeature.provider.asc())
        ).scalars().all()

        road_class_expression = ContextFeature.properties["road_class"].astext
        road_class_rows = db_session.execute(
            select(road_class_expression, func.count(ContextFeature.id))
            .where(
                ContextFeature.monitor_id == monitor_id,
                ContextFeature.feature_type == FEATURE_TYPE_ROAD,
            )
            .group_by(road_class_expression)
        ).all()
    except SQLAlchemyError as exc:
        raise ContextQueryError("Failed to summarize context features") from exc

    by_type = {feature_type: 0 for feature_type in SUPPORTED_CONTEXT_FEATURE_TYPES}
    for feature_type, count in by_type_rows:
        by_type[str(feature_type)] = int(count)

    road_classes: dict[str, int] = {}
    for road_class, count in road_class_rows:
        key = str(road_class) if road_class else "other"
        road_classes[key] = int(count)

    return ContextSummaryRead(
        monitor_id=monitor_id,
        total_features=int(aggregate[0]),
        by_type=by_type,
        road_classes=road_classes,
        providers=[str(provider) for provider in providers],
        attribution="© OpenStreetMap contributors",
        last_fetched_at=aggregate[1],
    )
