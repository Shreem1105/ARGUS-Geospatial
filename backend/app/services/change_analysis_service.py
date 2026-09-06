from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname
from uuid import UUID, uuid4

import rasterio
from PIL import Image
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.gis.conversion import wkb_to_geojson_geometry
from app.models import ChangeAnalysis, Monitor, PreparedObservation, SatelliteObservation
from app.processing import ChangeDetectionError, run_change_detection
from app.schemas import ChangeAnalysisAutoRequest, ChangeAnalysisCreateRequest, ChangeAnalysisRead, ChangeAnalysisStatus
from app.services.prepared_observation_service import ensure_data_directories, validate_prepared_artifacts

logger = logging.getLogger(__name__)

CHANGE_ANALYSIS_ALGORITHM = "spectral-ndvi-baseline"
CHANGE_ANALYSIS_ALGORITHM_VERSION = "v1"


class ChangeAnalysisPersistenceError(Exception):
    pass


class ChangeAnalysisQueryError(Exception):
    pass


class ChangeAnalysisValidationError(Exception):
    pass


class ChangeAnalysisConflictError(Exception):
    pass


class ChangeAnalysisProcessingError(Exception):
    pass


@dataclass(slots=True)
class ChangeAnalysisUpsertResult:
    analysis: ChangeAnalysisRead
    reused: bool


@dataclass(slots=True)
class _PreparedContext:
    prepared: PreparedObservation
    observation: SatelliteObservation


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


def _change_artifact_paths(analysis: ChangeAnalysis) -> dict[str, Path] | None:
    score_path = _file_uri_to_path(analysis.change_score_uri)
    change_mask_path = _file_uri_to_path(analysis.change_mask_uri)
    valid_mask_path = _file_uri_to_path(analysis.valid_comparison_mask_uri)
    preview_path = _file_uri_to_path(analysis.preview_uri)

    if score_path is None or change_mask_path is None or valid_mask_path is None or preview_path is None:
        return None

    paths: dict[str, Path] = {
        "change_score": score_path,
        "change_mask": change_mask_path,
        "valid_comparison_mask": valid_mask_path,
        "preview": preview_path,
    }

    statistics = analysis.statistics if isinstance(analysis.statistics, dict) else {}
    supporting_rasters = statistics.get("supporting_rasters")
    if isinstance(supporting_rasters, dict):
        abs_delta_ndvi_uri = supporting_rasters.get("abs_delta_ndvi_uri")
        spectral_distance_uri = supporting_rasters.get("spectral_distance_uri")

        if isinstance(abs_delta_ndvi_uri, str):
            abs_delta_ndvi_path = _file_uri_to_path(abs_delta_ndvi_uri)
            if abs_delta_ndvi_path is not None:
                paths["abs_delta_ndvi"] = abs_delta_ndvi_path

        if isinstance(spectral_distance_uri, str):
            spectral_distance_path = _file_uri_to_path(spectral_distance_uri)
            if spectral_distance_path is not None:
                paths["spectral_distance"] = spectral_distance_path

    return paths


def _is_transform_aligned(left: rasterio.Affine, right: rasterio.Affine, tolerance: float = 1e-6) -> bool:
    return all(abs(float(a) - float(b)) <= tolerance for a, b in zip(left, right, strict=True))


def validate_change_analysis_artifacts(analysis: ChangeAnalysis) -> tuple[bool, str | None]:
    paths = _change_artifact_paths(analysis)
    if paths is None:
        return False, "analysis_artifact_uri_missing"

    for artifact_name, artifact_path in paths.items():
        if not artifact_path.exists() or not artifact_path.is_file():
            return False, f"{artifact_name}_missing"

    try:
        with rasterio.open(paths["change_score"]) as score_dataset:
            if score_dataset.count != 1:
                return False, "change_score_band_count_invalid"
            if score_dataset.crs is None:
                return False, "change_score_missing_crs"

            score_grid = {
                "crs": score_dataset.crs,
                "width": score_dataset.width,
                "height": score_dataset.height,
                "transform": score_dataset.transform,
            }

        with rasterio.open(paths["change_mask"]) as mask_dataset:
            if mask_dataset.count != 1:
                return False, "change_mask_band_count_invalid"
            if mask_dataset.crs is None:
                return False, "change_mask_missing_crs"
            if (
                mask_dataset.width != score_grid["width"]
                or mask_dataset.height != score_grid["height"]
                or mask_dataset.crs != score_grid["crs"]
                or not _is_transform_aligned(mask_dataset.transform, score_grid["transform"])
            ):
                return False, "change_mask_grid_mismatch"

        with rasterio.open(paths["valid_comparison_mask"]) as valid_dataset:
            if valid_dataset.count != 1:
                return False, "valid_comparison_mask_band_count_invalid"
            if valid_dataset.crs is None:
                return False, "valid_comparison_mask_missing_crs"
            if (
                valid_dataset.width != score_grid["width"]
                or valid_dataset.height != score_grid["height"]
                or valid_dataset.crs != score_grid["crs"]
                or not _is_transform_aligned(valid_dataset.transform, score_grid["transform"])
            ):
                return False, "valid_comparison_mask_grid_mismatch"

        for optional_name in ["abs_delta_ndvi", "spectral_distance"]:
            optional_path = paths.get(optional_name)
            if optional_path is None:
                continue
            if not optional_path.exists() or not optional_path.is_file():
                return False, f"{optional_name}_missing"

            with rasterio.open(optional_path) as optional_dataset:
                if optional_dataset.count != 1:
                    return False, f"{optional_name}_band_count_invalid"
                if optional_dataset.crs is None:
                    return False, f"{optional_name}_missing_crs"
                if (
                    optional_dataset.width != score_grid["width"]
                    or optional_dataset.height != score_grid["height"]
                    or optional_dataset.crs != score_grid["crs"]
                    or not _is_transform_aligned(optional_dataset.transform, score_grid["transform"])
                ):
                    return False, f"{optional_name}_grid_mismatch"

        with Image.open(paths["preview"]) as preview:
            preview.verify()
    except Exception as exc:
        logger.warning("Change-analysis artifacts failed validation analysis_id=%s reason=%s", analysis.id, exc)
        return False, "artifact_open_failed"

    return True, None


def _normalize_threshold(value: float) -> float:
    return round(float(value), 6)


def _normalize_minimum_change_area(value: float) -> float:
    return round(float(value), 6)


def _day_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _day_end(value: date) -> datetime:
    return datetime.combine(value, time.max, tzinfo=timezone.utc)


def _build_analysis_directory(*, monitor_id: UUID, analysis_id: UUID) -> Path:
    directories = ensure_data_directories()
    return directories["analyses"] / str(monitor_id) / str(analysis_id)


def _get_monitor(db_session: Session, monitor_id: UUID) -> Monitor | None:
    try:
        return db_session.execute(select(Monitor).where(Monitor.id == monitor_id)).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise ChangeAnalysisQueryError("Failed to fetch monitor") from exc


def _get_prepared_context(
    db_session: Session,
    *,
    monitor_id: UUID,
    prepared_id: UUID,
) -> _PreparedContext | None:
    try:
        row = db_session.execute(
            select(PreparedObservation, SatelliteObservation)
            .join(
                SatelliteObservation,
                PreparedObservation.observation_id == SatelliteObservation.id,
            )
            .where(
                PreparedObservation.id == prepared_id,
                PreparedObservation.monitor_id == monitor_id,
                SatelliteObservation.monitor_id == monitor_id,
            )
        ).one_or_none()
    except SQLAlchemyError as exc:
        raise ChangeAnalysisQueryError("Failed to fetch prepared observation context") from exc

    if row is None:
        return None

    prepared, observation = row
    return _PreparedContext(prepared=prepared, observation=observation)


def _analysis_to_read(analysis: ChangeAnalysis) -> ChangeAnalysisRead:
    return ChangeAnalysisRead(
        id=analysis.id,
        monitor_id=analysis.monitor_id,
        before_prepared_id=analysis.before_prepared_id,
        after_prepared_id=analysis.after_prepared_id,
        status=ChangeAnalysisStatus(analysis.status),
        algorithm=analysis.algorithm,
        algorithm_version=analysis.algorithm_version,
        change_score_uri=analysis.change_score_uri,
        change_mask_uri=analysis.change_mask_uri,
        valid_comparison_mask_uri=analysis.valid_comparison_mask_uri,
        preview_uri=analysis.preview_uri,
        threshold=analysis.threshold,
        minimum_change_area_m2=analysis.minimum_change_area_m2,
        changed_pixel_count=analysis.changed_pixel_count,
        valid_pixel_count=analysis.valid_pixel_count,
        changed_fraction=analysis.changed_fraction,
        changed_area_m2=analysis.changed_area_m2,
        mean_change_score=analysis.mean_change_score,
        max_change_score=analysis.max_change_score,
        statistics=analysis.statistics,
        created_at=analysis.created_at,
        updated_at=analysis.updated_at,
    )


def _set_failed_state(
    db_session: Session,
    *,
    analysis: ChangeAnalysis,
    error_type: str,
    error_message: str,
) -> None:
    statistics: dict[str, Any] = dict(analysis.statistics or {})
    statistics["last_error"] = {
        "type": error_type,
        "message": error_message,
    }

    analysis.status = ChangeAnalysisStatus.FAILED.value
    analysis.statistics = statistics

    try:
        db_session.add(analysis)
        db_session.commit()
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise ChangeAnalysisPersistenceError("Failed to persist analysis failure state") from exc


def _load_existing_analysis(
    db_session: Session,
    *,
    monitor_id: UUID,
    before_prepared_id: UUID,
    after_prepared_id: UUID,
    threshold: float,
    minimum_change_area_m2: float,
) -> ChangeAnalysis | None:
    try:
        return db_session.execute(
            select(ChangeAnalysis).where(
                ChangeAnalysis.monitor_id == monitor_id,
                ChangeAnalysis.before_prepared_id == before_prepared_id,
                ChangeAnalysis.after_prepared_id == after_prepared_id,
                ChangeAnalysis.algorithm == CHANGE_ANALYSIS_ALGORITHM,
                ChangeAnalysis.algorithm_version == CHANGE_ANALYSIS_ALGORITHM_VERSION,
                ChangeAnalysis.threshold == threshold,
                ChangeAnalysis.minimum_change_area_m2 == minimum_change_area_m2,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise ChangeAnalysisQueryError("Failed to query existing analysis") from exc


def _prepare_paths_for_processing(context: _PreparedContext) -> dict[str, Path]:
    storage_path = _file_uri_to_path(context.prepared.storage_uri)
    valid_mask_path = _file_uri_to_path(context.prepared.valid_mask_uri)

    if storage_path is None or valid_mask_path is None:
        raise ChangeAnalysisConflictError("Prepared observation artifacts are not available")

    return {
        "multispectral": storage_path,
        "valid_mask": valid_mask_path,
    }


def _build_statistics(
    *,
    before_context: _PreparedContext,
    after_context: _PreparedContext,
    threshold: float,
    minimum_change_area_m2: float,
    detection_statistics: dict[str, Any],
) -> dict[str, Any]:
    before_time = before_context.observation.acquired_at.astimezone(timezone.utc)
    after_time = after_context.observation.acquired_at.astimezone(timezone.utc)

    statistics = dict(detection_statistics)
    statistics.update(
        {
            "before_observation_id": str(before_context.observation.id),
            "before_item_id": before_context.observation.item_id,
            "before_acquired_at": before_time.isoformat(),
            "before_stac_cloud_cover": before_context.observation.cloud_cover,
            "before_local_cloud_fraction": before_context.prepared.cloud_fraction,
            "before_valid_fraction": before_context.prepared.valid_fraction,
            "after_observation_id": str(after_context.observation.id),
            "after_item_id": after_context.observation.item_id,
            "after_acquired_at": after_time.isoformat(),
            "after_stac_cloud_cover": after_context.observation.cloud_cover,
            "after_local_cloud_fraction": after_context.prepared.cloud_fraction,
            "after_valid_fraction": after_context.prepared.valid_fraction,
            "days_between": (after_time - before_time).total_seconds() / 86400,
            "threshold": threshold,
            "minimum_change_area_m2": minimum_change_area_m2,
        }
    )
    return statistics


def _upsert_change_analysis(
    db_session: Session,
    *,
    monitor: Monitor,
    before_context: _PreparedContext,
    after_context: _PreparedContext,
    threshold: float,
    minimum_change_area_m2: float,
) -> ChangeAnalysisUpsertResult:
    if before_context.prepared.id == after_context.prepared.id:
        raise ChangeAnalysisValidationError("before_prepared_id and after_prepared_id must differ")

    before_time = before_context.observation.acquired_at.astimezone(timezone.utc)
    after_time = after_context.observation.acquired_at.astimezone(timezone.utc)

    if before_time >= after_time:
        raise ChangeAnalysisValidationError("before observation must be earlier than after observation")

    before_ready, before_reason = validate_prepared_artifacts(before_context.prepared)
    after_ready, after_reason = validate_prepared_artifacts(after_context.prepared)

    if before_context.prepared.status != ChangeAnalysisStatus.READY.value or not before_ready:
        raise ChangeAnalysisConflictError(
            f"before prepared observation not ready or artifacts unavailable ({before_reason or 'not_ready'})"
        )

    if after_context.prepared.status != ChangeAnalysisStatus.READY.value or not after_ready:
        raise ChangeAnalysisConflictError(
            f"after prepared observation not ready or artifacts unavailable ({after_reason or 'not_ready'})"
        )

    existing = _load_existing_analysis(
        db_session,
        monitor_id=monitor.id,
        before_prepared_id=before_context.prepared.id,
        after_prepared_id=after_context.prepared.id,
        threshold=threshold,
        minimum_change_area_m2=minimum_change_area_m2,
    )

    reused = False
    repair_reason: str | None = None

    if existing is not None and existing.status == ChangeAnalysisStatus.READY.value:
        healthy, reason = validate_change_analysis_artifacts(existing)
        if healthy:
            reused = True
            return ChangeAnalysisUpsertResult(analysis=_analysis_to_read(existing), reused=reused)

        repair_reason = reason or "analysis_artifacts_unhealthy"
        logger.warning(
            "Existing analysis requires repair analysis_id=%s monitor_id=%s reason=%s",
            existing.id,
            monitor.id,
            repair_reason,
        )

    analysis = existing
    if analysis is None:
        analysis = ChangeAnalysis(
            id=uuid4(),
            monitor_id=monitor.id,
            before_prepared_id=before_context.prepared.id,
            after_prepared_id=after_context.prepared.id,
            status=ChangeAnalysisStatus.PROCESSING.value,
            algorithm=CHANGE_ANALYSIS_ALGORITHM,
            algorithm_version=CHANGE_ANALYSIS_ALGORITHM_VERSION,
            threshold=threshold,
            minimum_change_area_m2=minimum_change_area_m2,
            statistics={"lifecycle": "created"},
        )
    else:
        lifecycle_metadata: dict[str, Any] = {
            "lifecycle": "reprocessing",
            "repair_reason": repair_reason,
        }
        analysis.status = ChangeAnalysisStatus.PROCESSING.value
        analysis.statistics = lifecycle_metadata

    try:
        db_session.add(analysis)
        db_session.commit()
        db_session.refresh(analysis)
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise ChangeAnalysisPersistenceError("Failed to initialize change analysis") from exc

    before_paths = _prepare_paths_for_processing(before_context)
    after_paths = _prepare_paths_for_processing(after_context)

    monitor_geometry = wkb_to_geojson_geometry(monitor.geometry)
    target_directory = _build_analysis_directory(monitor_id=monitor.id, analysis_id=analysis.id)

    logger.info(
        "Running change analysis monitor_id=%s analysis_id=%s before=%s after=%s threshold=%.3f minimum_change_area_m2=%.3f",
        monitor.id,
        analysis.id,
        before_context.observation.item_id,
        after_context.observation.item_id,
        threshold,
        minimum_change_area_m2,
    )

    try:
        detection_result = run_change_detection(
            monitor_geometry_wgs84=monitor_geometry,
            before_multispectral_path=before_paths["multispectral"],
            before_valid_mask_path=before_paths["valid_mask"],
            after_multispectral_path=after_paths["multispectral"],
            after_valid_mask_path=after_paths["valid_mask"],
            threshold=threshold,
            minimum_change_area_m2=minimum_change_area_m2,
            target_directory=target_directory,
        )
    except ChangeDetectionError as exc:
        _set_failed_state(
            db_session,
            analysis=analysis,
            error_type="processing_error",
            error_message=str(exc),
        )
        raise ChangeAnalysisProcessingError("Unable to compute change analysis") from exc

    analysis.status = ChangeAnalysisStatus.READY.value
    analysis.change_score_uri = detection_result.change_score_path.resolve().as_uri()
    analysis.change_mask_uri = detection_result.change_mask_path.resolve().as_uri()
    analysis.valid_comparison_mask_uri = detection_result.valid_comparison_mask_path.resolve().as_uri()
    analysis.preview_uri = detection_result.preview_path.resolve().as_uri()
    analysis.changed_pixel_count = detection_result.changed_pixel_count
    analysis.valid_pixel_count = detection_result.valid_pixel_count
    analysis.changed_fraction = detection_result.changed_fraction
    analysis.changed_area_m2 = detection_result.changed_area_m2
    analysis.mean_change_score = detection_result.mean_change_score
    analysis.max_change_score = detection_result.max_change_score
    analysis_statistics = _build_statistics(
        before_context=before_context,
        after_context=after_context,
        threshold=threshold,
        minimum_change_area_m2=minimum_change_area_m2,
        detection_statistics=detection_result.statistics,
    )
    analysis_statistics["supporting_rasters"] = {
        "abs_delta_ndvi_uri": detection_result.abs_delta_ndvi_path.resolve().as_uri(),
        "spectral_distance_uri": detection_result.spectral_distance_path.resolve().as_uri(),
    }
    analysis.statistics = analysis_statistics

    monitor.last_analyzed_at = datetime.now(tz=timezone.utc)

    try:
        db_session.add(analysis)
        db_session.add(monitor)
        db_session.commit()
        db_session.refresh(analysis)
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise ChangeAnalysisPersistenceError("Failed to persist change analysis") from exc

    return ChangeAnalysisUpsertResult(analysis=_analysis_to_read(analysis), reused=False)


def create_change_analysis(
    db_session: Session,
    *,
    monitor_id: UUID,
    request: ChangeAnalysisCreateRequest,
) -> ChangeAnalysisUpsertResult | None:
    monitor = _get_monitor(db_session, monitor_id)
    if monitor is None:
        return None

    before_context = _get_prepared_context(
        db_session,
        monitor_id=monitor_id,
        prepared_id=request.before_prepared_id,
    )
    after_context = _get_prepared_context(
        db_session,
        monitor_id=monitor_id,
        prepared_id=request.after_prepared_id,
    )

    if before_context is None or after_context is None:
        return None

    threshold = _normalize_threshold(request.threshold)
    minimum_change_area_m2 = request.minimum_change_area_m2
    if minimum_change_area_m2 is None:
        minimum_change_area_m2 = monitor.minimum_change_area_m2

    minimum_change_area_m2 = _normalize_minimum_change_area(minimum_change_area_m2)

    return _upsert_change_analysis(
        db_session,
        monitor=monitor,
        before_context=before_context,
        after_context=after_context,
        threshold=threshold,
        minimum_change_area_m2=minimum_change_area_m2,
    )


def _candidate_sort_key(candidate: _PreparedContext) -> tuple[float, float, float, str]:
    valid_fraction = candidate.prepared.valid_fraction if candidate.prepared.valid_fraction is not None else -1.0
    cloud_fraction = candidate.prepared.cloud_fraction if candidate.prepared.cloud_fraction is not None else 2.0
    acquired_at = candidate.observation.acquired_at.astimezone(timezone.utc).timestamp()
    return (-valid_fraction, cloud_fraction, -acquired_at, str(candidate.prepared.id))


def _choose_candidate_pair(
    *,
    candidates: list[_PreparedContext],
    request: ChangeAnalysisAutoRequest,
) -> tuple[_PreparedContext, _PreparedContext] | None:
    before_start = _day_start(request.before_start_date)
    before_end = _day_end(request.before_end_date)
    after_start = _day_start(request.after_start_date)
    after_end = _day_end(request.after_end_date)

    def include_candidate(candidate: _PreparedContext, start_time: datetime, end_time: datetime) -> bool:
        acquired_at = candidate.observation.acquired_at.astimezone(timezone.utc)
        if acquired_at < start_time or acquired_at > end_time:
            return False

        if request.max_local_cloud_fraction is not None:
            if candidate.prepared.cloud_fraction is None:
                return False
            if candidate.prepared.cloud_fraction > request.max_local_cloud_fraction:
                return False

        return True

    before_candidates = sorted(
        [candidate for candidate in candidates if include_candidate(candidate, before_start, before_end)],
        key=_candidate_sort_key,
    )
    after_candidates = sorted(
        [candidate for candidate in candidates if include_candidate(candidate, after_start, after_end)],
        key=_candidate_sort_key,
    )

    for before_candidate in before_candidates:
        for after_candidate in after_candidates:
            if before_candidate.prepared.id == after_candidate.prepared.id:
                continue
            if before_candidate.observation.acquired_at < after_candidate.observation.acquired_at:
                return before_candidate, after_candidate

    return None


def create_change_analysis_auto(
    db_session: Session,
    *,
    monitor_id: UUID,
    request: ChangeAnalysisAutoRequest,
) -> ChangeAnalysisUpsertResult | None:
    monitor = _get_monitor(db_session, monitor_id)
    if monitor is None:
        return None

    try:
        rows = db_session.execute(
            select(PreparedObservation, SatelliteObservation)
            .join(SatelliteObservation, PreparedObservation.observation_id == SatelliteObservation.id)
            .where(
                PreparedObservation.monitor_id == monitor_id,
                PreparedObservation.status == ChangeAnalysisStatus.READY.value,
                SatelliteObservation.monitor_id == monitor_id,
            )
        ).all()
    except SQLAlchemyError as exc:
        raise ChangeAnalysisQueryError("Failed to fetch prepared observations for auto pairing") from exc

    candidates = [_PreparedContext(prepared=prepared, observation=observation) for prepared, observation in rows]

    selected_pair = _choose_candidate_pair(candidates=candidates, request=request)
    if selected_pair is None:
        raise ChangeAnalysisConflictError("No suitable before/after prepared pair found")

    before_context, after_context = selected_pair

    minimum_change_area_m2 = request.minimum_change_area_m2
    if minimum_change_area_m2 is None:
        minimum_change_area_m2 = monitor.minimum_change_area_m2

    return _upsert_change_analysis(
        db_session,
        monitor=monitor,
        before_context=before_context,
        after_context=after_context,
        threshold=_normalize_threshold(request.threshold),
        minimum_change_area_m2=_normalize_minimum_change_area(minimum_change_area_m2),
    )


def list_change_analyses(
    db_session: Session,
    *,
    monitor_id: UUID,
    limit: int,
    offset: int,
) -> list[ChangeAnalysisRead] | None:
    monitor = _get_monitor(db_session, monitor_id)
    if monitor is None:
        return None

    try:
        analyses = db_session.execute(
            select(ChangeAnalysis)
            .where(ChangeAnalysis.monitor_id == monitor_id)
            .order_by(ChangeAnalysis.created_at.desc(), ChangeAnalysis.id.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
    except SQLAlchemyError as exc:
        raise ChangeAnalysisQueryError("Failed to list change analyses") from exc

    return [_analysis_to_read(analysis) for analysis in analyses]


def get_change_analysis(
    db_session: Session,
    *,
    monitor_id: UUID,
    analysis_id: UUID,
) -> ChangeAnalysisRead | None:
    try:
        analysis = db_session.execute(
            select(ChangeAnalysis).where(
                ChangeAnalysis.id == analysis_id,
                ChangeAnalysis.monitor_id == monitor_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise ChangeAnalysisQueryError("Failed to fetch change analysis") from exc

    if analysis is None:
        return None

    return _analysis_to_read(analysis)
