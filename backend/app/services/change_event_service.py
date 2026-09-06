from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname
from uuid import UUID, uuid4

import numpy as np
import rasterio
from shapely.geometry import Point, shape
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.gis.conversion import geojson_geometry_to_wkb, wkb_to_geojson_geometry
from app.models import ChangeAnalysis, ChangeEvent, Monitor, PreparedObservation, SatelliteObservation
from app.processing import EVENT_GENERATION_VERSION, VectorizationError, build_event_candidates
from app.schemas import (
    ChangeEventGenerationResponse,
    ChangeEventRead,
    ChangeEventSpatialSummary,
    ChangeEventStatus,
    MonitorEventSummary,
)
from app.services.change_analysis_service import validate_change_analysis_artifacts

logger = logging.getLogger(__name__)


class ChangeEventPersistenceError(Exception):
    pass


class ChangeEventQueryError(Exception):
    pass


class ChangeEventConflictError(Exception):
    pass


class ChangeEventGenerationError(Exception):
    pass


@dataclass(slots=True)
class ChangeEventGenerationResult:
    response: ChangeEventGenerationResponse
    generated: bool


def _file_uri_to_path(uri: str | None) -> Path | None:
    if uri is None:
        return None

    parsed = urlparse(uri)
    if parsed.scheme in {"", None}:
        return Path(uri)

    if parsed.scheme != "file":
        return None

    decoded_path = unquote(parsed.path)
    local_path = url2pathname(decoded_path)

    if parsed.netloc and not local_path.startswith("\\\\"):
        local_path = f"\\\\{parsed.netloc}{local_path}"

    return Path(local_path)


def _normalize_geometry_type(geometry_type: str) -> str:
    without_prefix = geometry_type.removeprefix("ST_")
    if without_prefix.isupper():
        return without_prefix.title()
    return without_prefix


def _centroid_from_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    centroid = shape(geometry).centroid
    if not isinstance(centroid, Point):
        raise ChangeEventQueryError("Unable to compute event centroid")
    return {
        "type": "Point",
        "coordinates": (float(centroid.x), float(centroid.y)),
    }


def _event_to_read(change_event: ChangeEvent) -> ChangeEventRead:
    geometry = wkb_to_geojson_geometry(change_event.geometry)
    return ChangeEventRead(
        id=change_event.id,
        monitor_id=change_event.monitor_id,
        analysis_id=change_event.analysis_id,
        geometry=geometry,
        centroid=_centroid_from_geometry(geometry),
        area_m2=change_event.area_m2,
        perimeter_m=change_event.perimeter_m,
        confidence=change_event.confidence,
        severity=change_event.severity,
        mean_change_score=change_event.mean_change_score,
        max_change_score=change_event.max_change_score,
        mean_abs_delta_ndvi=change_event.mean_abs_delta_ndvi,
        mean_spectral_distance=change_event.mean_spectral_distance,
        pixel_count=change_event.pixel_count,
        first_detected_at=change_event.first_detected_at,
        last_detected_at=change_event.last_detected_at,
        status=ChangeEventStatus(change_event.status),
        properties=change_event.properties,
        created_at=change_event.created_at,
        updated_at=change_event.updated_at,
    )


def _get_monitor(db_session: Session, monitor_id: UUID) -> Monitor | None:
    try:
        return db_session.execute(select(Monitor).where(Monitor.id == monitor_id)).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise ChangeEventQueryError("Failed to fetch monitor") from exc


def _get_analysis(db_session: Session, *, monitor_id: UUID, analysis_id: UUID) -> ChangeAnalysis | None:
    try:
        return db_session.execute(
            select(ChangeAnalysis).where(
                ChangeAnalysis.id == analysis_id,
                ChangeAnalysis.monitor_id == monitor_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise ChangeEventQueryError("Failed to fetch change analysis") from exc


def _load_after_observation_time(db_session: Session, *, monitor_id: UUID, analysis: ChangeAnalysis):
    try:
        return db_session.execute(
            select(SatelliteObservation.acquired_at)
            .join(PreparedObservation, PreparedObservation.observation_id == SatelliteObservation.id)
            .where(
                PreparedObservation.id == analysis.after_prepared_id,
                PreparedObservation.monitor_id == monitor_id,
                SatelliteObservation.monitor_id == monitor_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise ChangeEventQueryError("Failed to fetch after observation time") from exc


def _load_supporting_rasters(analysis: ChangeAnalysis) -> tuple[Path, Path]:
    statistics = analysis.statistics if isinstance(analysis.statistics, dict) else {}
    supporting = statistics.get("supporting_rasters")
    if not isinstance(supporting, dict):
        raise ChangeEventConflictError("Analysis missing supporting rasters for event-level metrics")

    abs_delta_uri = supporting.get("abs_delta_ndvi_uri")
    spectral_uri = supporting.get("spectral_distance_uri")
    if not isinstance(abs_delta_uri, str) or not isinstance(spectral_uri, str):
        raise ChangeEventConflictError("Analysis missing supporting rasters for event-level metrics")

    abs_delta_path = _file_uri_to_path(abs_delta_uri)
    spectral_path = _file_uri_to_path(spectral_uri)
    if abs_delta_path is None or spectral_path is None:
        raise ChangeEventConflictError("Analysis supporting raster path is invalid")

    return abs_delta_path, spectral_path


def _transforms_match(left: rasterio.Affine, right: rasterio.Affine, tolerance: float = 1e-6) -> bool:
    return all(abs(float(a) - float(b)) <= tolerance for a, b in zip(left, right, strict=True))


def _validate_grids(*, reference: rasterio.DatasetReader, other: rasterio.DatasetReader, label: str) -> None:
    if other.crs is None or reference.crs is None:
        raise ChangeEventConflictError(f"{label} raster is missing CRS")
    if other.width != reference.width or other.height != reference.height:
        raise ChangeEventConflictError(f"{label} raster dimensions do not match change mask")
    if other.crs != reference.crs:
        raise ChangeEventConflictError(f"{label} raster CRS does not match change mask")
    if not _transforms_match(other.transform, reference.transform):
        raise ChangeEventConflictError(f"{label} raster transform does not match change mask")


def _read_analysis_rasters(analysis: ChangeAnalysis) -> dict[str, Any]:
    change_mask_path = _file_uri_to_path(analysis.change_mask_uri)
    change_score_path = _file_uri_to_path(analysis.change_score_uri)
    valid_mask_path = _file_uri_to_path(analysis.valid_comparison_mask_uri)

    if change_mask_path is None or change_score_path is None or valid_mask_path is None:
        raise ChangeEventConflictError("Change analysis missing required raster artifacts")

    abs_delta_path, spectral_path = _load_supporting_rasters(analysis)

    for required_path in [change_mask_path, change_score_path, valid_mask_path, abs_delta_path, spectral_path]:
        if not required_path.exists() or not required_path.is_file():
            raise ChangeEventConflictError(f"Required analysis artifact is missing: {required_path.name}")

    try:
        with rasterio.open(change_mask_path) as change_mask_ds:
            if change_mask_ds.count != 1:
                raise ChangeEventConflictError("Change mask must be single-band")
            if change_mask_ds.crs is None:
                raise ChangeEventConflictError("Change mask is missing CRS")
            change_mask_array = change_mask_ds.read(1)

            with rasterio.open(change_score_path) as score_ds:
                if score_ds.count != 1:
                    raise ChangeEventConflictError("Change score raster must be single-band")
                _validate_grids(reference=change_mask_ds, other=score_ds, label="Change score")
                change_score_array = score_ds.read(1).astype(np.float32)
                score_nodata = float(score_ds.nodata) if score_ds.nodata is not None else -9999.0

            with rasterio.open(valid_mask_path) as valid_ds:
                if valid_ds.count != 1:
                    raise ChangeEventConflictError("Valid comparison mask must be single-band")
                _validate_grids(reference=change_mask_ds, other=valid_ds, label="Valid comparison")
                valid_mask_array = valid_ds.read(1).astype(np.uint8)

            with rasterio.open(abs_delta_path) as ndvi_ds:
                if ndvi_ds.count != 1:
                    raise ChangeEventConflictError("abs_delta_ndvi raster must be single-band")
                _validate_grids(reference=change_mask_ds, other=ndvi_ds, label="abs_delta_ndvi")
                abs_delta_array = ndvi_ds.read(1).astype(np.float32)
                ndvi_nodata = float(ndvi_ds.nodata) if ndvi_ds.nodata is not None else None

            with rasterio.open(spectral_path) as spectral_ds:
                if spectral_ds.count != 1:
                    raise ChangeEventConflictError("spectral_distance raster must be single-band")
                _validate_grids(reference=change_mask_ds, other=spectral_ds, label="spectral_distance")
                spectral_array = spectral_ds.read(1).astype(np.float32)
                spectral_nodata = float(spectral_ds.nodata) if spectral_ds.nodata is not None else None

            return {
                "change_mask": change_mask_array,
                "change_score": change_score_array,
                "valid_mask": valid_mask_array,
                "abs_delta_ndvi": abs_delta_array,
                "spectral_distance": spectral_array,
                "score_nodata": score_nodata,
                "ndvi_nodata": ndvi_nodata,
                "spectral_nodata": spectral_nodata,
                "crs": change_mask_ds.crs,
                "transform": change_mask_ds.transform,
                "width": int(change_mask_ds.width),
                "height": int(change_mask_ds.height),
            }
    except ChangeEventConflictError:
        raise
    except rasterio.errors.RasterioError as exc:
        raise ChangeEventConflictError("Unable to read analysis artifacts") from exc


def _severity_counts(events: list[ChangeEvent]) -> dict[str, int]:
    counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    for event in events:
        counts[event.severity] = counts.get(event.severity, 0) + 1
    return counts


def _summarize_generation(
    *,
    events: list[ChangeEvent],
    elapsed_seconds: float,
    skipped_geometry_count: int,
    simplification_tolerance_m: float,
    pixel_area_m2: float,
    mask_width: int,
    mask_height: int,
) -> dict[str, Any]:
    severity_counts = _severity_counts(events)
    total_area = float(sum(event.area_m2 for event in events))

    return {
        "version": EVENT_GENERATION_VERSION,
        "status": "completed",
        "event_count": len(events),
        "total_event_area_m2": total_area,
        "low": severity_counts["low"],
        "medium": severity_counts["medium"],
        "high": severity_counts["high"],
        "critical": severity_counts["critical"],
        "elapsed_seconds": round(elapsed_seconds, 6),
        "skipped_geometry_count": skipped_geometry_count,
        "simplification_tolerance_m": simplification_tolerance_m,
        "pixel_area_m2": pixel_area_m2,
        "change_mask_width": mask_width,
        "change_mask_height": mask_height,
    }


def _generation_reusable(analysis: ChangeAnalysis, existing_events: list[ChangeEvent]) -> bool:
    statistics = analysis.statistics if isinstance(analysis.statistics, dict) else {}
    generation = statistics.get("event_generation")
    if not isinstance(generation, dict):
        return False
    if generation.get("version") != EVENT_GENERATION_VERSION:
        return False
    if generation.get("status") != "completed":
        return False

    expected_count = generation.get("event_count")
    if isinstance(expected_count, int) and expected_count != len(existing_events):
        return False

    return True


def _persist_generation_summary(
    db_session: Session,
    *,
    analysis: ChangeAnalysis,
    generation_summary: dict[str, Any],
) -> None:
    statistics = dict(analysis.statistics or {})
    statistics["event_generation"] = generation_summary
    analysis.statistics = statistics

    try:
        db_session.add(analysis)
        db_session.commit()
        db_session.refresh(analysis)
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise ChangeEventPersistenceError("Failed to persist event generation summary") from exc


def generate_change_events(
    db_session: Session,
    *,
    monitor_id: UUID,
    analysis_id: UUID,
) -> ChangeEventGenerationResult | None:
    monitor = _get_monitor(db_session, monitor_id)
    if monitor is None:
        return None

    analysis = _get_analysis(db_session, monitor_id=monitor_id, analysis_id=analysis_id)
    if analysis is None:
        return None

    if analysis.status != "ready":
        raise ChangeEventConflictError("Change analysis is not ready")

    artifacts_healthy, artifact_reason = validate_change_analysis_artifacts(analysis)
    if not artifacts_healthy:
        raise ChangeEventConflictError(
            f"Change analysis artifacts unavailable ({artifact_reason or 'unavailable'})"
        )

    existing_events = db_session.execute(
        select(ChangeEvent)
        .where(ChangeEvent.analysis_id == analysis_id, ChangeEvent.monitor_id == monitor_id)
        .order_by(ChangeEvent.first_detected_at.desc(), ChangeEvent.id.desc())
    ).scalars().all()

    if _generation_reusable(analysis, existing_events):
        return ChangeEventGenerationResult(
            response=ChangeEventGenerationResponse(
                analysis_id=analysis_id,
                count=len(existing_events),
                generated=False,
                events=[_event_to_read(event) for event in existing_events],
            ),
            generated=False,
        )

    after_acquired_at = _load_after_observation_time(db_session, monitor_id=monitor_id, analysis=analysis)
    if after_acquired_at is None:
        raise ChangeEventConflictError("Unable to resolve after-observation acquisition time")

    raster_payload = _read_analysis_rasters(analysis)

    valid_pixel_count = analysis.valid_pixel_count
    if valid_pixel_count is None or valid_pixel_count <= 0:
        valid_pixel_count = int(np.count_nonzero(raster_payload["valid_mask"] == 1))

    start_time = time.perf_counter()
    try:
        vector_result = build_event_candidates(
            change_mask_array=raster_payload["change_mask"],
            change_score_array=raster_payload["change_score"],
            valid_comparison_mask=raster_payload["valid_mask"],
            abs_delta_ndvi_array=raster_payload["abs_delta_ndvi"],
            spectral_distance_array=raster_payload["spectral_distance"],
            score_nodata=float(raster_payload["score_nodata"]),
            ndvi_nodata=raster_payload["ndvi_nodata"],
            spectral_nodata=raster_payload["spectral_nodata"],
            transform=raster_payload["transform"],
            crs=raster_payload["crs"],
            analysis_valid_pixel_count=valid_pixel_count,
            generation_version=EVENT_GENERATION_VERSION,
        )
    except VectorizationError as exc:
        raise ChangeEventGenerationError("Failed to vectorize change mask") from exc
    elapsed_seconds = time.perf_counter() - start_time

    try:
        if existing_events:
            db_session.execute(
                delete(ChangeEvent).where(
                    ChangeEvent.analysis_id == analysis_id,
                    ChangeEvent.monitor_id == monitor_id,
                )
            )

        generated_events: list[ChangeEvent] = []
        for candidate in vector_result.candidates:
            generated_events.append(
                ChangeEvent(
                    id=uuid4(),
                    monitor_id=monitor_id,
                    analysis_id=analysis_id,
                    geometry=geojson_geometry_to_wkb(candidate.geometry_wgs84),
                    area_m2=candidate.area_m2,
                    perimeter_m=candidate.perimeter_m,
                    confidence=candidate.confidence,
                    severity=candidate.severity,
                    mean_change_score=candidate.mean_change_score,
                    max_change_score=candidate.max_change_score,
                    mean_abs_delta_ndvi=candidate.mean_abs_delta_ndvi,
                    mean_spectral_distance=candidate.mean_spectral_distance,
                    pixel_count=candidate.pixel_count,
                    first_detected_at=after_acquired_at,
                    last_detected_at=after_acquired_at,
                    status=ChangeEventStatus.NEW.value,
                    properties=candidate.properties,
                )
            )

        db_session.add_all(generated_events)
        db_session.commit()

        for event in generated_events:
            db_session.refresh(event)
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise ChangeEventPersistenceError("Failed to persist change events") from exc

    generation_summary = _summarize_generation(
        events=generated_events,
        elapsed_seconds=elapsed_seconds,
        skipped_geometry_count=vector_result.skipped_geometry_count,
        simplification_tolerance_m=vector_result.simplification_tolerance_m,
        pixel_area_m2=vector_result.pixel_area_m2,
        mask_width=vector_result.mask_width,
        mask_height=vector_result.mask_height,
    )

    _persist_generation_summary(
        db_session,
        analysis=analysis,
        generation_summary=generation_summary,
    )

    logger.info(
        "Generated change events monitor_id=%s analysis_id=%s count=%s skipped=%s elapsed_seconds=%.3f",
        monitor_id,
        analysis_id,
        len(generated_events),
        vector_result.skipped_geometry_count,
        elapsed_seconds,
    )

    return ChangeEventGenerationResult(
        response=ChangeEventGenerationResponse(
            analysis_id=analysis_id,
            count=len(generated_events),
            generated=True,
            events=[_event_to_read(event) for event in generated_events],
        ),
        generated=True,
    )


def list_change_events(
    db_session: Session,
    *,
    monitor_id: UUID,
    limit: int,
    offset: int,
    severity: str | None,
    status: str | None,
    min_confidence: float | None,
    min_area_m2: float | None,
    analysis_id: UUID | None,
) -> list[ChangeEventRead] | None:
    monitor = _get_monitor(db_session, monitor_id)
    if monitor is None:
        return None

    try:
        statement = select(ChangeEvent).where(ChangeEvent.monitor_id == monitor_id)
        if severity is not None:
            statement = statement.where(ChangeEvent.severity == severity)
        if status is not None:
            statement = statement.where(ChangeEvent.status == status)
        if min_confidence is not None:
            statement = statement.where(ChangeEvent.confidence >= min_confidence)
        if min_area_m2 is not None:
            statement = statement.where(ChangeEvent.area_m2 >= min_area_m2)
        if analysis_id is not None:
            statement = statement.where(ChangeEvent.analysis_id == analysis_id)

        statement = statement.order_by(ChangeEvent.first_detected_at.desc(), ChangeEvent.id.desc())
        statement = statement.limit(limit).offset(offset)
        rows = db_session.execute(statement).scalars().all()
    except SQLAlchemyError as exc:
        raise ChangeEventQueryError("Failed to list change events") from exc

    return [_event_to_read(event) for event in rows]


def list_change_events_for_analysis(
    db_session: Session,
    *,
    monitor_id: UUID,
    analysis_id: UUID,
    limit: int,
    offset: int,
) -> list[ChangeEventRead] | None:
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
            .order_by(ChangeEvent.first_detected_at.desc(), ChangeEvent.id.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
    except SQLAlchemyError as exc:
        raise ChangeEventQueryError("Failed to list analysis change events") from exc

    return [_event_to_read(event) for event in events]


def get_change_event(
    db_session: Session,
    *,
    monitor_id: UUID,
    event_id: UUID,
) -> ChangeEventRead | None:
    try:
        event = db_session.execute(
            select(ChangeEvent).where(
                ChangeEvent.id == event_id,
                ChangeEvent.monitor_id == monitor_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise ChangeEventQueryError("Failed to fetch change event") from exc

    if event is None:
        return None

    return _event_to_read(event)


def update_change_event_status(
    db_session: Session,
    *,
    monitor_id: UUID,
    event_id: UUID,
    status: ChangeEventStatus,
) -> ChangeEventRead | None:
    try:
        event = db_session.execute(
            select(ChangeEvent).where(
                ChangeEvent.id == event_id,
                ChangeEvent.monitor_id == monitor_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise ChangeEventQueryError("Failed to fetch change event") from exc

    if event is None:
        return None

    event.status = status.value

    try:
        db_session.add(event)
        db_session.commit()
        db_session.refresh(event)
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise ChangeEventPersistenceError("Failed to update change event") from exc

    return _event_to_read(event)


EVENT_SUMMARY_QUERY = text(
    """
    SELECT
        e.id AS event_id,
        e.monitor_id,
        GeometryType(e.geometry) AS geometry_type,
        ST_SRID(e.geometry) AS srid,
        ST_Area(e.geometry::geography) AS area_m2,
        ST_Perimeter(e.geometry::geography) AS perimeter_m,
        e.area_m2 AS stored_area_m2,
        e.perimeter_m AS stored_perimeter_m,
        ST_X(ST_Centroid(e.geometry)) AS centroid_lon,
        ST_Y(ST_Centroid(e.geometry)) AS centroid_lat,
        ST_XMin(e.geometry) AS min_lon,
        ST_YMin(e.geometry) AS min_lat,
        ST_XMax(e.geometry) AS max_lon,
        ST_YMax(e.geometry) AS max_lat
    FROM change_events AS e
    WHERE e.monitor_id = :monitor_id
      AND e.id = :event_id
    """
)


def get_change_event_spatial_summary(
    db_session: Session,
    *,
    monitor_id: UUID,
    event_id: UUID,
) -> ChangeEventSpatialSummary | None:
    try:
        row = db_session.execute(
            EVENT_SUMMARY_QUERY,
            {
                "monitor_id": monitor_id,
                "event_id": event_id,
            },
        ).mappings().one_or_none()
    except SQLAlchemyError as exc:
        raise ChangeEventQueryError("Failed to fetch change event spatial summary") from exc

    if row is None:
        return None

    return ChangeEventSpatialSummary(
        monitor_id=row["monitor_id"],
        event_id=row["event_id"],
        geometry_type=_normalize_geometry_type(str(row["geometry_type"])),
        srid=int(row["srid"]),
        area_m2=float(row["area_m2"]),
        perimeter_m=float(row["perimeter_m"]),
        stored_area_m2=float(row["stored_area_m2"]),
        stored_perimeter_m=float(row["stored_perimeter_m"]),
        centroid={
            "type": "Point",
            "coordinates": (float(row["centroid_lon"]), float(row["centroid_lat"])),
        },
        bounding_box={
            "min_lon": float(row["min_lon"]),
            "min_lat": float(row["min_lat"]),
            "max_lon": float(row["max_lon"]),
            "max_lat": float(row["max_lat"]),
        },
    )


def intersects_change_events(
    db_session: Session,
    *,
    monitor_id: UUID,
    geometry: dict[str, Any],
    limit: int,
    offset: int,
) -> list[ChangeEventRead] | None:
    monitor = _get_monitor(db_session, monitor_id)
    if monitor is None:
        return None

    candidate = geojson_geometry_to_wkb(geometry)

    try:
        events = db_session.execute(
            select(ChangeEvent)
            .where(
                ChangeEvent.monitor_id == monitor_id,
                func.ST_Intersects(ChangeEvent.geometry, candidate),
            )
            .order_by(ChangeEvent.first_detected_at.desc(), ChangeEvent.id.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
    except SQLAlchemyError as exc:
        raise ChangeEventQueryError("Failed to evaluate change-event intersection") from exc

    return [_event_to_read(event) for event in events]


def get_monitor_event_summary(db_session: Session, *, monitor_id: UUID) -> MonitorEventSummary | None:
    monitor = _get_monitor(db_session, monitor_id)
    if monitor is None:
        return None

    try:
        aggregate_row = db_session.execute(
            select(
                func.count(ChangeEvent.id),
                func.coalesce(func.sum(ChangeEvent.area_m2), 0.0),
                func.avg(ChangeEvent.confidence),
                func.max(ChangeEvent.first_detected_at),
            ).where(ChangeEvent.monitor_id == monitor_id)
        ).one()

        severity_rows = db_session.execute(
            select(ChangeEvent.severity, func.count(ChangeEvent.id))
            .where(ChangeEvent.monitor_id == monitor_id)
            .group_by(ChangeEvent.severity)
        ).all()

        status_rows = db_session.execute(
            select(ChangeEvent.status, func.count(ChangeEvent.id))
            .where(ChangeEvent.monitor_id == monitor_id)
            .group_by(ChangeEvent.status)
        ).all()
    except SQLAlchemyError as exc:
        raise ChangeEventQueryError("Failed to fetch monitor event summary") from exc

    by_severity = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    for severity, count in severity_rows:
        by_severity[str(severity)] = int(count)

    by_status = {
        ChangeEventStatus.NEW.value: 0,
        ChangeEventStatus.REVIEWED.value: 0,
        ChangeEventStatus.DISMISSED.value: 0,
        ChangeEventStatus.CONFIRMED.value: 0,
    }
    for status, count in status_rows:
        by_status[str(status)] = int(count)

    mean_confidence = aggregate_row[2]

    return MonitorEventSummary(
        monitor_id=monitor_id,
        total_events=int(aggregate_row[0]),
        total_changed_area_m2=float(aggregate_row[1]),
        mean_confidence=(float(mean_confidence) if mean_confidence is not None else None),
        by_severity=by_severity,
        by_status=by_status,
        latest_detected_at=aggregate_row[3],
    )
