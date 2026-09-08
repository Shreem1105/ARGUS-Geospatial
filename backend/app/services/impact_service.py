from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import bindparam, delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.context import FEATURE_TYPE_ADMINISTRATIVE, FEATURE_TYPE_BUILDING, FEATURE_TYPE_ROAD, FEATURE_TYPE_WATERWAY
from app.context.normalization import normalize_road_class
from app.gis.conversion import geojson_geometry_to_wkb
from app.models import ChangeAnalysis, ChangeEvent, ChangeEventImpact, ContextFeature, Monitor
from app.schemas import (
    AdministrativeAreaContext,
    AnalysisImpactComputeResponse,
    BuildingImpactSummary,
    ChangeEventSeverity,
    ContextSignificance,
    EventImpactSummaryRead,
    MonitorImpactSummaryRead,
    RoadImpactSummary,
    WaterwayImpactSummary,
)

logger = logging.getLogger(__name__)

DEFAULT_NEARBY_BUFFER_M = 100.0
IMPACT_GENERATION_VERSION = "context-impact-v1"
DIRECT_INTERSECTION_IMPACT_TYPES = {"intersects", "contains"}
MAJOR_ROAD_CLASSES = {"motorway", "trunk", "primary"}


INTERSECTION_RELATIONSHIPS_QUERY = text(
    """
    SELECT
        e.id AS event_id,
        cf.id AS context_feature_id,
        CASE
            WHEN ST_Contains(e.geometry, cf.geometry) THEN 'contains'
            ELSE 'intersects'
        END AS impact_type,
        ST_AsGeoJSON(ST_Intersection(e.geometry, cf.geometry)) AS intersection_geometry_geojson,
        COALESCE(
            ST_Area(ST_CollectionExtract(ST_Intersection(e.geometry, cf.geometry), 3)::geography),
            0
        ) AS intersection_area_m2,
        COALESCE(
            ST_Length(ST_CollectionExtract(ST_Intersection(e.geometry, cf.geometry), 2)::geography),
            0
        ) AS intersection_length_m,
        ST_Distance(e.geometry::geography, cf.geometry::geography) AS distance_m,
        cf.feature_type,
        cf.feature_subtype,
        cf.provider,
        cf.name AS feature_name,
        cf.properties AS feature_properties
    FROM change_events AS e
    JOIN context_features AS cf
      ON cf.monitor_id = e.monitor_id
    WHERE e.monitor_id = :monitor_id
      AND e.id IN :event_ids
      AND ST_Intersects(e.geometry, cf.geometry)
    """
).bindparams(bindparam("event_ids", expanding=True))


WITHIN_BUFFER_RELATIONSHIPS_QUERY = text(
    """
    SELECT
        e.id AS event_id,
        cf.id AS context_feature_id,
        'within_buffer' AS impact_type,
        NULL AS intersection_geometry_geojson,
        0::double precision AS intersection_area_m2,
        0::double precision AS intersection_length_m,
        ST_Distance(e.geometry::geography, cf.geometry::geography) AS distance_m,
        cf.feature_type,
        cf.feature_subtype,
        cf.provider,
        cf.name AS feature_name,
        cf.properties AS feature_properties
    FROM change_events AS e
    JOIN context_features AS cf
      ON cf.monitor_id = e.monitor_id
    WHERE e.monitor_id = :monitor_id
      AND e.id IN :event_ids
      AND NOT ST_Intersects(e.geometry, cf.geometry)
      AND ST_DWithin(e.geometry::geography, cf.geometry::geography, :buffer_m)
    """
).bindparams(bindparam("event_ids", expanding=True))


class ImpactPersistenceError(Exception):
    pass


class ImpactQueryError(Exception):
    pass


class ImpactConflictError(Exception):
    pass


@dataclass(slots=True)
class EventImpactComputationResult:
    summary: EventImpactSummaryRead
    computed: bool


@dataclass(slots=True)
class BulkImpactComputationResult:
    response: AnalysisImpactComputeResponse


def _get_monitor(db_session: Session, monitor_id: UUID) -> Monitor | None:
    try:
        return db_session.execute(select(Monitor).where(Monitor.id == monitor_id)).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise ImpactQueryError("Failed to fetch monitor") from exc


def _get_event(db_session: Session, *, monitor_id: UUID, event_id: UUID) -> ChangeEvent | None:
    try:
        return db_session.execute(
            select(ChangeEvent).where(
                ChangeEvent.monitor_id == monitor_id,
                ChangeEvent.id == event_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise ImpactQueryError("Failed to fetch change event") from exc


def _get_analysis(db_session: Session, *, monitor_id: UUID, analysis_id: UUID) -> ChangeAnalysis | None:
    try:
        return db_session.execute(
            select(ChangeAnalysis).where(
                ChangeAnalysis.monitor_id == monitor_id,
                ChangeAnalysis.id == analysis_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise ImpactQueryError("Failed to fetch change analysis") from exc


def _context_count_for_monitor(db_session: Session, monitor_id: UUID) -> int:
    try:
        count = db_session.execute(
            text("SELECT COUNT(*) FROM context_features WHERE monitor_id = :monitor_id"),
            {"monitor_id": monitor_id},
        ).scalar_one()
    except SQLAlchemyError as exc:
        raise ImpactQueryError("Failed to count context features") from exc

    return int(count)


def _event_has_impact_marker(event: ChangeEvent) -> bool:
    if not isinstance(event.properties, dict):
        return False
    marker = event.properties.get("impact_computation")
    return isinstance(marker, dict)


def _fetch_relationship_rows(
    db_session: Session,
    *,
    monitor_id: UUID,
    event_ids: list[UUID],
    buffer_m: float,
) -> list[dict[str, Any]]:
    if not event_ids:
        return []

    params = {
        "monitor_id": monitor_id,
        "event_ids": event_ids,
        "buffer_m": float(buffer_m),
    }

    try:
        direct_rows = db_session.execute(INTERSECTION_RELATIONSHIPS_QUERY, params).mappings().all()
        nearby_rows = db_session.execute(WITHIN_BUFFER_RELATIONSHIPS_QUERY, params).mappings().all()
    except SQLAlchemyError as exc:
        raise ImpactQueryError("Failed to compute spatial relationships") from exc

    return [dict(row) for row in direct_rows] + [dict(row) for row in nearby_rows]


def _build_impact_insert_rows(rows: list[dict[str, Any]], *, buffer_m: float) -> list[dict[str, Any]]:
    insert_rows: list[dict[str, Any]] = []
    for row in rows:
        geometry_geojson = row.get("intersection_geometry_geojson")
        intersection_geometry = None
        if isinstance(geometry_geojson, str) and geometry_geojson.strip():
            try:
                intersection_geometry = geojson_geometry_to_wkb(json.loads(geometry_geojson))
            except Exception:
                intersection_geometry = None

        feature_properties = row.get("feature_properties") if isinstance(row.get("feature_properties"), dict) else {}
        impact_properties: dict[str, Any] = {
            "feature_type": row.get("feature_type"),
            "feature_subtype": row.get("feature_subtype"),
            "provider": row.get("provider"),
            "feature_name": row.get("feature_name"),
        }

        road_class = feature_properties.get("road_class") if isinstance(feature_properties, dict) else None
        if isinstance(road_class, str) and road_class:
            impact_properties["road_class"] = road_class

        if row.get("impact_type") == "within_buffer":
            impact_properties["nearby_buffer_m"] = float(buffer_m)

        insert_rows.append(
            {
                "id": uuid4(),
                "event_id": row["event_id"],
                "context_feature_id": row["context_feature_id"],
                "impact_type": str(row["impact_type"]),
                "intersection_geometry": intersection_geometry,
                "intersection_area_m2": float(row.get("intersection_area_m2") or 0.0),
                "intersection_length_m": float(row.get("intersection_length_m") or 0.0),
                "distance_m": float(row.get("distance_m") or 0.0),
                "properties": impact_properties,
            }
        )

    return insert_rows


def _mark_events_computed(
    *,
    events: list[ChangeEvent],
    relationship_counts: dict[UUID, int],
    nearby_buffer_m: float,
) -> None:
    computed_at = datetime.now(tz=timezone.utc).isoformat()
    for event in events:
        properties = dict(event.properties or {})
        properties["impact_computation"] = {
            "version": IMPACT_GENERATION_VERSION,
            "computed_at": computed_at,
            "relationship_count": relationship_counts.get(event.id, 0),
            "nearby_buffer_m": nearby_buffer_m,
        }
        event.properties = properties


def _delete_and_insert_impacts(
    db_session: Session,
    *,
    event_ids: list[UUID],
    insert_rows: list[dict[str, Any]],
) -> None:
    try:
        db_session.execute(delete(ChangeEventImpact).where(ChangeEventImpact.event_id.in_(event_ids)))
        if insert_rows:
            statement = insert(ChangeEventImpact.__table__).values(insert_rows)
            statement = statement.on_conflict_do_nothing(
                index_elements=["event_id", "context_feature_id", "impact_type"],
            )
            db_session.execute(statement)
        db_session.commit()
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise ImpactPersistenceError("Failed to persist change-event impacts") from exc


def _load_event_impact_pairs(
    db_session: Session,
    *,
    event_id: UUID,
) -> list[tuple[ChangeEventImpact, ContextFeature]]:
    try:
        rows = db_session.execute(
            select(ChangeEventImpact, ContextFeature)
            .join(ContextFeature, ContextFeature.id == ChangeEventImpact.context_feature_id)
            .where(ChangeEventImpact.event_id == event_id)
        ).all()
    except SQLAlchemyError as exc:
        raise ImpactQueryError("Failed to load persisted impact relationships") from exc

    return [(impact, context_feature) for impact, context_feature in rows]


def _derive_context_significance(
    *,
    road_intersecting_count: int,
    road_nearby_count: int,
    road_classes: dict[str, int],
    building_intersecting_count: int,
    building_nearby_count: int,
    waterway_intersecting_count: int,
    waterway_nearby_count: int,
) -> ContextSignificance:
    score = 0

    if road_intersecting_count > 0:
        score += 1
    if any(road_class in MAJOR_ROAD_CLASSES and count > 0 for road_class, count in road_classes.items()):
        score += 1

    if building_intersecting_count >= 10:
        score += 3
    elif building_intersecting_count >= 3:
        score += 2
    elif building_intersecting_count >= 1:
        score += 1

    if waterway_intersecting_count > 0:
        score += 1

    nearby_total = road_nearby_count + building_nearby_count + waterway_nearby_count
    if nearby_total >= 20:
        score += 1

    if score >= 5:
        return ContextSignificance.HIGH
    if score >= 3:
        return ContextSignificance.MEDIUM
    return ContextSignificance.LOW


def _build_event_summary(
    *,
    event: ChangeEvent,
    pairs: list[tuple[ChangeEventImpact, ContextFeature]],
) -> EventImpactSummaryRead:
    road_intersecting: set[UUID] = set()
    road_nearby: set[UUID] = set()
    building_intersecting: set[UUID] = set()
    building_nearby: set[UUID] = set()
    waterway_intersecting: set[UUID] = set()
    waterway_nearby: set[UUID] = set()

    road_intersection_length_m = 0.0
    building_intersection_area_m2 = 0.0
    waterway_intersection_length_m = 0.0

    road_distances: list[float] = []
    building_distances: list[float] = []
    waterway_distances: list[float] = []

    intersecting_road_classes_by_feature: dict[UUID, str] = {}
    waterway_subtypes: set[str] = set()
    administrative_areas_by_feature: dict[UUID, AdministrativeAreaContext] = {}

    for impact, feature in pairs:
        feature_type = feature.feature_type
        impact_type = impact.impact_type
        distance_m = float(impact.distance_m)
        properties = feature.properties if isinstance(feature.properties, dict) else {}

        if feature_type == FEATURE_TYPE_ROAD:
            road_distances.append(distance_m)
            road_class = properties.get("road_class")
            if not isinstance(road_class, str) or not road_class.strip():
                road_class = normalize_road_class(feature.feature_subtype)

            if impact_type in DIRECT_INTERSECTION_IMPACT_TYPES:
                road_intersecting.add(feature.id)
                road_intersection_length_m += float(impact.intersection_length_m or 0.0)
                intersecting_road_classes_by_feature[feature.id] = road_class
            elif impact_type == "within_buffer":
                road_nearby.add(feature.id)

        elif feature_type == FEATURE_TYPE_BUILDING:
            building_distances.append(distance_m)
            if impact_type in DIRECT_INTERSECTION_IMPACT_TYPES:
                building_intersecting.add(feature.id)
                building_intersection_area_m2 += float(impact.intersection_area_m2 or 0.0)
            elif impact_type == "within_buffer":
                building_nearby.add(feature.id)

        elif feature_type == FEATURE_TYPE_WATERWAY:
            waterway_distances.append(distance_m)
            subtype = feature.feature_subtype
            if isinstance(subtype, str) and subtype.strip():
                waterway_subtypes.add(subtype.strip().lower())

            if impact_type in DIRECT_INTERSECTION_IMPACT_TYPES:
                waterway_intersecting.add(feature.id)
                waterway_intersection_length_m += float(impact.intersection_length_m or 0.0)
            elif impact_type == "within_buffer":
                waterway_nearby.add(feature.id)

        elif feature_type == FEATURE_TYPE_ADMINISTRATIVE and impact_type in DIRECT_INTERSECTION_IMPACT_TYPES:
            admin_level = properties.get("admin_level")
            if admin_level is not None and not isinstance(admin_level, str):
                admin_level = str(admin_level)
            administrative_areas_by_feature[feature.id] = AdministrativeAreaContext(
                name=feature.name,
                admin_level=admin_level,
            )

    road_classes: dict[str, int] = {}
    for road_class in intersecting_road_classes_by_feature.values():
        road_classes[road_class] = road_classes.get(road_class, 0) + 1

    road_intersecting_count = len(road_intersecting)
    road_nearby_count = len(road_nearby)
    building_intersecting_count = len(building_intersecting)
    building_nearby_count = len(building_nearby)
    waterway_intersecting_count = len(waterway_intersecting)
    waterway_nearby_count = len(waterway_nearby)

    context_significance = _derive_context_significance(
        road_intersecting_count=road_intersecting_count,
        road_nearby_count=road_nearby_count,
        road_classes=road_classes,
        building_intersecting_count=building_intersecting_count,
        building_nearby_count=building_nearby_count,
        waterway_intersecting_count=waterway_intersecting_count,
        waterway_nearby_count=waterway_nearby_count,
    )

    administrative_areas = sorted(
        administrative_areas_by_feature.values(),
        key=lambda item: ((item.admin_level or ""), (item.name or "")),
    )

    return EventImpactSummaryRead(
        event_id=event.id,
        monitor_id=event.monitor_id,
        analysis_id=event.analysis_id,
        scientific_severity=ChangeEventSeverity(event.severity),
        context_significance=context_significance,
        impact_relationship_count=len(pairs),
        roads=RoadImpactSummary(
            intersecting_count=road_intersecting_count,
            intersecting_length_m=road_intersection_length_m,
            nearby_count=road_nearby_count,
            nearest_distance_m=(min(road_distances) if road_distances else None),
            classes=road_classes,
        ),
        buildings=BuildingImpactSummary(
            intersecting_count=building_intersecting_count,
            intersection_area_m2=building_intersection_area_m2,
            nearby_count=building_nearby_count,
            nearest_distance_m=(min(building_distances) if building_distances else None),
        ),
        waterways=WaterwayImpactSummary(
            intersecting_count=waterway_intersecting_count,
            intersection_length_m=waterway_intersection_length_m,
            nearby_count=waterway_nearby_count,
            nearest_distance_m=(min(waterway_distances) if waterway_distances else None),
            subtypes=sorted(waterway_subtypes),
        ),
        administrative_areas=administrative_areas,
    )


def compute_change_event_impact(
    db_session: Session,
    *,
    monitor_id: UUID,
    event_id: UUID,
    nearby_buffer_m: float = DEFAULT_NEARBY_BUFFER_M,
) -> EventImpactComputationResult | None:
    monitor = _get_monitor(db_session, monitor_id)
    if monitor is None:
        return None

    event = _get_event(db_session, monitor_id=monitor_id, event_id=event_id)
    if event is None:
        return None

    had_existing_impacts = bool(
        db_session.execute(
            text("SELECT 1 FROM change_event_impacts WHERE event_id = :event_id LIMIT 1"),
            {"event_id": event_id},
        ).first()
    )
    had_prior = had_existing_impacts or _event_has_impact_marker(event)

    context_count = _context_count_for_monitor(db_session, monitor_id)
    if context_count <= 0:
        if had_prior:
            existing_summary = get_change_event_impact_summary(
                db_session,
                monitor_id=monitor_id,
                event_id=event_id,
            )
            if existing_summary is not None:
                logger.info(
                    "Reusing existing event impact summary monitor_id=%s event_id=%s because context is unavailable",
                    monitor_id,
                    event_id,
                )
                return EventImpactComputationResult(summary=existing_summary, computed=False)
        raise ImpactConflictError("Context features are not loaded for this monitor")

    relationship_rows = _fetch_relationship_rows(
        db_session,
        monitor_id=monitor_id,
        event_ids=[event_id],
        buffer_m=nearby_buffer_m,
    )
    insert_rows = _build_impact_insert_rows(relationship_rows, buffer_m=nearby_buffer_m)

    relationship_counts = {event_id: len(insert_rows)}
    _mark_events_computed(events=[event], relationship_counts=relationship_counts, nearby_buffer_m=nearby_buffer_m)
    _delete_and_insert_impacts(
        db_session,
        event_ids=[event_id],
        insert_rows=insert_rows,
    )
    db_session.refresh(event)

    pairs = _load_event_impact_pairs(db_session, event_id=event_id)
    summary = _build_event_summary(event=event, pairs=pairs)
    logger.info(
        "Computed event impact monitor_id=%s event_id=%s relationships=%s nearby_buffer_m=%.2f",
        monitor_id,
        event_id,
        summary.impact_relationship_count,
        nearby_buffer_m,
    )

    return EventImpactComputationResult(summary=summary, computed=not had_prior)


def get_change_event_impact_summary(
    db_session: Session,
    *,
    monitor_id: UUID,
    event_id: UUID,
) -> EventImpactSummaryRead | None:
    monitor = _get_monitor(db_session, monitor_id)
    if monitor is None:
        return None

    event = _get_event(db_session, monitor_id=monitor_id, event_id=event_id)
    if event is None:
        return None

    pairs = _load_event_impact_pairs(db_session, event_id=event_id)
    if not pairs and not _event_has_impact_marker(event):
        return None

    return _build_event_summary(event=event, pairs=pairs)


def compute_analysis_impacts(
    db_session: Session,
    *,
    monitor_id: UUID,
    analysis_id: UUID,
    nearby_buffer_m: float = DEFAULT_NEARBY_BUFFER_M,
) -> BulkImpactComputationResult | None:
    monitor = _get_monitor(db_session, monitor_id)
    if monitor is None:
        return None

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
        raise ImpactQueryError("Failed to fetch analysis events") from exc

    event_ids = [event.id for event in events]

    if not event_ids:
        return BulkImpactComputationResult(
            response=AnalysisImpactComputeResponse(
                analysis_id=analysis_id,
                event_count=0,
                computed=0,
                failed=0,
                impact_relationship_count=0,
                elapsed_seconds=0.0,
            )
        )

    context_count = _context_count_for_monitor(db_session, monitor_id)
    if context_count <= 0:
        reused_summaries: list[EventImpactSummaryRead] = []
        for event in events:
            summary = get_change_event_impact_summary(
                db_session,
                monitor_id=monitor_id,
                event_id=event.id,
            )
            if summary is None:
                raise ImpactConflictError("Context features are not loaded for this monitor")
            reused_summaries.append(summary)

        relationship_count = sum(summary.impact_relationship_count for summary in reused_summaries)
        logger.info(
            "Reused existing analysis impacts monitor_id=%s analysis_id=%s events=%s relationships=%s because context is unavailable",
            monitor_id,
            analysis_id,
            len(event_ids),
            relationship_count,
        )
        return BulkImpactComputationResult(
            response=AnalysisImpactComputeResponse(
                analysis_id=analysis_id,
                event_count=len(event_ids),
                computed=0,
                failed=0,
                impact_relationship_count=relationship_count,
                elapsed_seconds=0.0,
            )
        )

    started_at = time.perf_counter()

    relationship_rows = _fetch_relationship_rows(
        db_session,
        monitor_id=monitor_id,
        event_ids=event_ids,
        buffer_m=nearby_buffer_m,
    )
    insert_rows = _build_impact_insert_rows(relationship_rows, buffer_m=nearby_buffer_m)

    relationship_counts: dict[UUID, int] = {event_id: 0 for event_id in event_ids}
    for row in insert_rows:
        event_id = row["event_id"]
        relationship_counts[event_id] = relationship_counts.get(event_id, 0) + 1

    if events:
        _mark_events_computed(events=events, relationship_counts=relationship_counts, nearby_buffer_m=nearby_buffer_m)
    _delete_and_insert_impacts(db_session, event_ids=event_ids, insert_rows=insert_rows)

    elapsed_seconds = time.perf_counter() - started_at
    logger.info(
        "Computed analysis impacts monitor_id=%s analysis_id=%s events=%s relationships=%s elapsed_seconds=%.3f",
        monitor_id,
        analysis_id,
        len(event_ids),
        len(insert_rows),
        elapsed_seconds,
    )

    return BulkImpactComputationResult(
        response=AnalysisImpactComputeResponse(
            analysis_id=analysis_id,
            event_count=len(event_ids),
            computed=len(event_ids),
            failed=0,
            impact_relationship_count=len(insert_rows),
            elapsed_seconds=round(elapsed_seconds, 6),
        )
    )


def get_monitor_impact_summary(db_session: Session, *, monitor_id: UUID) -> MonitorImpactSummaryRead | None:
    monitor = _get_monitor(db_session, monitor_id)
    if monitor is None:
        return None

    try:
        rows = db_session.execute(
            select(ChangeEventImpact, ContextFeature, ChangeEvent)
            .join(ContextFeature, ContextFeature.id == ChangeEventImpact.context_feature_id)
            .join(ChangeEvent, ChangeEvent.id == ChangeEventImpact.event_id)
            .where(ChangeEvent.monitor_id == monitor_id)
        ).all()
    except SQLAlchemyError as exc:
        raise ImpactQueryError("Failed to load monitor impacts") from exc

    events_with_intersecting_roads: set[UUID] = set()
    events_with_intersecting_buildings: set[UUID] = set()
    unique_intersecting_buildings: set[UUID] = set()
    events_near_waterways: set[UUID] = set()
    administrative_areas: set[tuple[str | None, str | None]] = set()
    unique_context_features: set[UUID] = set()

    total_intersecting_road_length_m = 0.0
    total_building_intersection_area_m2 = 0.0

    for impact, feature, event in rows:
        unique_context_features.add(feature.id)

        if feature.feature_type == FEATURE_TYPE_ROAD and impact.impact_type in DIRECT_INTERSECTION_IMPACT_TYPES:
            events_with_intersecting_roads.add(event.id)
            total_intersecting_road_length_m += float(impact.intersection_length_m or 0.0)

        if feature.feature_type == FEATURE_TYPE_BUILDING and impact.impact_type in DIRECT_INTERSECTION_IMPACT_TYPES:
            events_with_intersecting_buildings.add(event.id)
            unique_intersecting_buildings.add(feature.id)
            total_building_intersection_area_m2 += float(impact.intersection_area_m2 or 0.0)

        if feature.feature_type == FEATURE_TYPE_WATERWAY:
            events_near_waterways.add(event.id)

        if feature.feature_type == FEATURE_TYPE_ADMINISTRATIVE and impact.impact_type in DIRECT_INTERSECTION_IMPACT_TYPES:
            properties = feature.properties if isinstance(feature.properties, dict) else {}
            admin_level = properties.get("admin_level")
            if admin_level is not None and not isinstance(admin_level, str):
                admin_level = str(admin_level)
            administrative_areas.add((feature.name, admin_level))

    admin_items = sorted(administrative_areas, key=lambda item: ((item[1] or ""), (item[0] or "")))

    return MonitorImpactSummaryRead(
        monitor_id=monitor_id,
        events_with_intersecting_roads=len(events_with_intersecting_roads),
        total_intersecting_road_length_m=total_intersecting_road_length_m,
        events_with_intersecting_buildings=len(events_with_intersecting_buildings),
        unique_intersecting_buildings=len(unique_intersecting_buildings),
        total_building_intersection_area_m2=total_building_intersection_area_m2,
        events_near_waterways=len(events_near_waterways),
        administrative_areas_containing_events=[
            AdministrativeAreaContext(name=name, admin_level=admin_level)
            for name, admin_level in admin_items
        ],
        total_impact_relationships=len(rows),
        unique_context_features_in_impacts=len(unique_context_features),
    )

