from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, aliased

from app.gis.conversion import wkb_to_geojson_geometry
from app.models import (
    ChangeAnalysis,
    ChangeEvent,
    ChangeEventLandCoverExposure,
    ChangeEventSemanticAnalysis,
    Monitor,
    PreparedObservation,
    SatelliteObservation,
)
from app.schemas import AnalysisSemanticComputeResponse, ChangeEventSemanticAnalysisRead, SemanticLabel
from app.semantic import (
    SEMANTIC_INFERENCE_METHOD,
    SEMANTIC_MODEL_NAME,
    SEMANTIC_MODEL_VERSION,
    SemanticModelLoadError,
    compute_embedding_change,
    extract_event_spectral_evidence,
    get_model_provenance,
    infer_semantic_change,
)
from app.semantic.raster import EventBandMappingError, EventRasterExtractionError

logger = logging.getLogger(__name__)


class SemanticPersistenceError(Exception):
    pass


class SemanticQueryError(Exception):
    pass


class SemanticConflictError(Exception):
    pass


class SemanticProcessingError(Exception):
    pass


@dataclass(slots=True)
class EventSemanticComputationResult:
    summary: ChangeEventSemanticAnalysisRead
    computed: bool


@dataclass(slots=True)
class BulkSemanticComputationResult:
    response: AnalysisSemanticComputeResponse


@dataclass(slots=True)
class _EventBundle:
    event: ChangeEvent
    analysis: ChangeAnalysis
    before_prepared: PreparedObservation
    after_prepared: PreparedObservation
    before_observation: SatelliteObservation
    after_observation: SatelliteObservation


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


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


def _require_existing_file(uri: str | None, *, artifact_name: str) -> Path:
    path = _file_uri_to_path(uri)
    if path is None:
        raise SemanticConflictError(f"Missing {artifact_name} artifact URI")
    if not path.exists() or not path.is_file():
        raise SemanticConflictError(f"{artifact_name} artifact file is not available")
    return path


def _get_monitor(db_session: Session, monitor_id: UUID) -> Monitor | None:
    try:
        return db_session.execute(select(Monitor).where(Monitor.id == monitor_id)).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise SemanticQueryError("Failed to fetch monitor") from exc


def _get_analysis(db_session: Session, *, monitor_id: UUID, analysis_id: UUID) -> ChangeAnalysis | None:
    try:
        return db_session.execute(
            select(ChangeAnalysis).where(
                ChangeAnalysis.monitor_id == monitor_id,
                ChangeAnalysis.id == analysis_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise SemanticQueryError("Failed to fetch change analysis") from exc


def _get_event_bundle(db_session: Session, *, monitor_id: UUID, event_id: UUID) -> _EventBundle | None:
    before_prepared_alias = aliased(PreparedObservation)
    after_prepared_alias = aliased(PreparedObservation)
    before_observation_alias = aliased(SatelliteObservation)
    after_observation_alias = aliased(SatelliteObservation)

    try:
        row = db_session.execute(
            select(
                ChangeEvent,
                ChangeAnalysis,
                before_prepared_alias,
                after_prepared_alias,
                before_observation_alias,
                after_observation_alias,
            )
            .join(ChangeAnalysis, ChangeAnalysis.id == ChangeEvent.analysis_id)
            .join(before_prepared_alias, before_prepared_alias.id == ChangeAnalysis.before_prepared_id)
            .join(after_prepared_alias, after_prepared_alias.id == ChangeAnalysis.after_prepared_id)
            .join(before_observation_alias, before_observation_alias.id == before_prepared_alias.observation_id)
            .join(after_observation_alias, after_observation_alias.id == after_prepared_alias.observation_id)
            .where(
                ChangeEvent.monitor_id == monitor_id,
                ChangeEvent.id == event_id,
                ChangeAnalysis.monitor_id == monitor_id,
                before_prepared_alias.monitor_id == monitor_id,
                after_prepared_alias.monitor_id == monitor_id,
                before_observation_alias.monitor_id == monitor_id,
                after_observation_alias.monitor_id == monitor_id,
            )
        ).one_or_none()
    except SQLAlchemyError as exc:
        raise SemanticQueryError("Failed to resolve change-event semantic provenance") from exc

    if row is None:
        return None

    return _EventBundle(
        event=row[0],
        analysis=row[1],
        before_prepared=row[2],
        after_prepared=row[3],
        before_observation=row[4],
        after_observation=row[5],
    )


def _get_existing_semantic_row(db_session: Session, *, event_id: UUID) -> ChangeEventSemanticAnalysis | None:
    try:
        return db_session.execute(
            select(ChangeEventSemanticAnalysis)
            .where(
                ChangeEventSemanticAnalysis.change_event_id == event_id,
                ChangeEventSemanticAnalysis.model_name == SEMANTIC_MODEL_NAME,
                ChangeEventSemanticAnalysis.model_version == SEMANTIC_MODEL_VERSION,
                ChangeEventSemanticAnalysis.inference_method == SEMANTIC_INFERENCE_METHOD,
            )
            .order_by(ChangeEventSemanticAnalysis.updated_at.desc(), ChangeEventSemanticAnalysis.id.desc())
            .limit(1)
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise SemanticQueryError("Failed to fetch existing semantic analysis") from exc


def _resolve_baseline_land_cover(db_session: Session, *, event: ChangeEvent) -> str | None:
    try:
        dominant = db_session.execute(
            select(ChangeEventLandCoverExposure.class_name)
            .where(ChangeEventLandCoverExposure.event_id == event.id)
            .order_by(
                ChangeEventLandCoverExposure.fraction_of_event.desc(),
                ChangeEventLandCoverExposure.class_code.asc(),
            )
            .limit(1)
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise SemanticQueryError("Failed to fetch baseline land-cover context") from exc

    if dominant is not None:
        return str(dominant)

    properties = event.properties if isinstance(event.properties, dict) else {}
    exposure_snapshot = properties.get("land_cover_exposure")
    if isinstance(exposure_snapshot, dict):
        dominant_class = exposure_snapshot.get("dominant_class")
        if isinstance(dominant_class, str) and dominant_class.strip():
            return dominant_class.strip()

    return None


def _explanation_from_evidence(evidence: dict[str, Any]) -> list[str]:
    explanation = evidence.get("explanation")
    if isinstance(explanation, list):
        return [str(item) for item in explanation]
    return []


def _semantic_row_to_read(row: ChangeEventSemanticAnalysis) -> ChangeEventSemanticAnalysisRead:
    evidence = dict(row.evidence or {}) if isinstance(row.evidence, dict) else {}

    return ChangeEventSemanticAnalysisRead(
        id=row.id,
        change_event_id=row.change_event_id,
        change_analysis_id=row.change_analysis_id,
        before_prepared_observation_id=row.before_prepared_observation_id,
        after_prepared_observation_id=row.after_prepared_observation_id,
        semantic_label=SemanticLabel(row.semantic_label),
        semantic_confidence=float(row.semantic_confidence),
        abstained=bool(row.abstained),
        model_name=row.model_name,
        model_version=row.model_version,
        inference_method=row.inference_method,
        before_land_cover=row.before_land_cover,
        after_land_cover=row.after_land_cover,
        before_ndvi_mean=row.before_ndvi_mean,
        after_ndvi_mean=row.after_ndvi_mean,
        ndvi_delta=row.ndvi_delta,
        before_ndwi_mean=row.before_ndwi_mean,
        after_ndwi_mean=row.after_ndwi_mean,
        ndwi_delta=row.ndwi_delta,
        before_nbr_mean=row.before_nbr_mean,
        after_nbr_mean=row.after_nbr_mean,
        nbr_delta=row.nbr_delta,
        before_built_up_score=row.before_built_up_score,
        after_built_up_score=row.after_built_up_score,
        built_up_delta=row.built_up_delta,
        embedding_distance=row.embedding_distance,
        valid_pixel_coverage=row.valid_pixel_coverage,
        explanation=_explanation_from_evidence(evidence),
        evidence=evidence,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _ensure_semantic_preconditions(bundle: _EventBundle) -> None:
    if bundle.analysis.status != "ready":
        raise SemanticConflictError("Change analysis must be ready before semantic inference")
    if bundle.before_prepared.status != "ready" or bundle.after_prepared.status != "ready":
        raise SemanticConflictError("Before/after prepared observations must be ready before semantic inference")


def _build_event_semantic_snapshot(
    *,
    semantic_label: str,
    semantic_confidence: float,
    abstained: bool,
    valid_pixel_coverage: float | None,
) -> dict[str, Any]:
    return {
        "semantic_label": semantic_label,
        "semantic_confidence": semantic_confidence,
        "abstained": abstained,
        "model_name": SEMANTIC_MODEL_NAME,
        "model_version": SEMANTIC_MODEL_VERSION,
        "inference_method": SEMANTIC_INFERENCE_METHOD,
        "valid_pixel_coverage": valid_pixel_coverage,
        "computed_at": datetime.now(tz=timezone.utc).isoformat(),
    }


def compute_change_event_semantics(
    db_session: Session,
    *,
    monitor_id: UUID,
    event_id: UUID,
    force_recompute: bool = False,
) -> EventSemanticComputationResult | None:
    bundle = _get_event_bundle(db_session, monitor_id=monitor_id, event_id=event_id)
    if bundle is None:
        return None

    _ensure_semantic_preconditions(bundle)

    existing = _get_existing_semantic_row(db_session, event_id=event_id)
    if existing is not None and not force_recompute:
        return EventSemanticComputationResult(summary=_semantic_row_to_read(existing), computed=False)

    event_geometry = wkb_to_geojson_geometry(bundle.event.geometry)
    before_multispectral_path = _require_existing_file(bundle.before_prepared.storage_uri, artifact_name="before_multispectral")
    before_valid_mask_path = _require_existing_file(bundle.before_prepared.valid_mask_uri, artifact_name="before_valid_mask")
    after_multispectral_path = _require_existing_file(bundle.after_prepared.storage_uri, artifact_name="after_multispectral")
    after_valid_mask_path = _require_existing_file(bundle.after_prepared.valid_mask_uri, artifact_name="after_valid_mask")
    analysis_valid_mask_path = _require_existing_file(
        bundle.analysis.valid_comparison_mask_uri,
        artifact_name="analysis_valid_comparison_mask",
    )

    started_at = time.perf_counter()
    try:
        spectral_evidence = extract_event_spectral_evidence(
            event_geometry_wgs84=event_geometry,
            before_multispectral_path=before_multispectral_path,
            before_valid_mask_path=before_valid_mask_path,
            after_multispectral_path=after_multispectral_path,
            after_valid_mask_path=after_valid_mask_path,
            analysis_valid_comparison_mask_path=analysis_valid_mask_path,
            before_band_names=list(bundle.before_prepared.band_names or []),
            after_band_names=list(bundle.after_prepared.band_names or []),
        )
    except (EventRasterExtractionError, EventBandMappingError) as exc:
        raise SemanticProcessingError("Failed to extract event raster evidence for semantic inference") from exc

    embedding_evidence = None
    if (
        spectral_evidence.before_rgb_patch is not None
        and spectral_evidence.after_rgb_patch is not None
        and spectral_evidence.patch_valid_mask is not None
    ):
        try:
            embedding_evidence = compute_embedding_change(
                before_rgb_patch=spectral_evidence.before_rgb_patch,
                after_rgb_patch=spectral_evidence.after_rgb_patch,
                valid_mask=spectral_evidence.patch_valid_mask,
            )
        except SemanticModelLoadError as exc:
            raise SemanticProcessingError("Semantic model inference failed") from exc

    baseline_land_cover = _resolve_baseline_land_cover(db_session, event=bundle.event)
    inference = infer_semantic_change(
        spectral=spectral_evidence,
        embedding_distance=(embedding_evidence.distance if embedding_evidence is not None else None),
        baseline_land_cover=baseline_land_cover,
    )

    provenance = get_model_provenance()
    elapsed_seconds = time.perf_counter() - started_at

    evidence_payload: dict[str, Any] = {
        "version": "semantic-evidence-v1",
        "explanation": inference.explanation,
        "signal_scores": inference.signal_scores,
        "abstention_reasons": inference.abstention_reasons,
        "diagnostics": inference.diagnostics,
        "valid_pixel_count": spectral_evidence.valid_pixel_count,
        "total_event_pixel_count": spectral_evidence.total_event_pixel_count,
        "valid_pixel_coverage": spectral_evidence.valid_pixel_coverage,
        "index_availability": spectral_evidence.index_availability,
        "notes": list(spectral_evidence.notes),
        "before_acquired_at": bundle.before_observation.acquired_at.astimezone(timezone.utc).isoformat(),
        "after_acquired_at": bundle.after_observation.acquired_at.astimezone(timezone.utc).isoformat(),
        "model": {
            **provenance,
            "inference_method": SEMANTIC_INFERENCE_METHOD,
        },
        "performance": {
            "semantic_processing_seconds": round(float(elapsed_seconds), 6),
        },
    }
    if embedding_evidence is not None:
        evidence_payload["embedding"] = {
            "distance": embedding_evidence.distance,
            "similarity": embedding_evidence.similarity,
            "embedding_dim": embedding_evidence.embedding_dim,
            "input_height": embedding_evidence.input_height,
            "input_width": embedding_evidence.input_width,
            "normalization_mean": list(embedding_evidence.normalization_mean),
            "normalization_std": list(embedding_evidence.normalization_std),
            "device": embedding_evidence.device,
            "inference_seconds": round(float(embedding_evidence.inference_seconds), 6),
            "model_load_seconds": round(float(embedding_evidence.model_load_seconds), 6),
        }
    else:
        evidence_payload["embedding"] = None

    row = existing
    if row is None:
        row = ChangeEventSemanticAnalysis(
            change_event_id=bundle.event.id,
            change_analysis_id=bundle.analysis.id,
            before_prepared_observation_id=bundle.before_prepared.id,
            after_prepared_observation_id=bundle.after_prepared.id,
            model_name=SEMANTIC_MODEL_NAME,
            model_version=SEMANTIC_MODEL_VERSION,
            inference_method=SEMANTIC_INFERENCE_METHOD,
        )

    row.semantic_label = inference.semantic_label
    row.semantic_confidence = float(inference.semantic_confidence)
    row.abstained = bool(inference.abstained)
    row.before_land_cover = baseline_land_cover
    row.after_land_cover = None
    row.before_ndvi_mean = spectral_evidence.before_ndvi_mean
    row.after_ndvi_mean = spectral_evidence.after_ndvi_mean
    row.ndvi_delta = spectral_evidence.ndvi_delta
    row.before_ndwi_mean = spectral_evidence.before_ndwi_mean
    row.after_ndwi_mean = spectral_evidence.after_ndwi_mean
    row.ndwi_delta = spectral_evidence.ndwi_delta
    row.before_nbr_mean = spectral_evidence.before_nbr_mean
    row.after_nbr_mean = spectral_evidence.after_nbr_mean
    row.nbr_delta = spectral_evidence.nbr_delta
    row.before_built_up_score = spectral_evidence.before_built_up_score
    row.after_built_up_score = spectral_evidence.after_built_up_score
    row.built_up_delta = spectral_evidence.built_up_delta
    row.embedding_distance = embedding_evidence.distance if embedding_evidence is not None else None
    row.valid_pixel_coverage = float(spectral_evidence.valid_pixel_coverage)
    row.evidence = _jsonable(evidence_payload)

    try:
        db_session.add(row)
        db_session.flush()

        snapshot = _build_event_semantic_snapshot(
            semantic_label=inference.semantic_label,
            semantic_confidence=float(inference.semantic_confidence),
            abstained=bool(inference.abstained),
            valid_pixel_coverage=float(spectral_evidence.valid_pixel_coverage),
        )
        event_properties = dict(bundle.event.properties or {})
        event_properties["semantic"] = snapshot
        bundle.event.properties = event_properties
        bundle.event.updated_at = func.now()

        db_session.add(bundle.event)
        db_session.commit()
        db_session.refresh(row)
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise SemanticPersistenceError("Failed to persist semantic analysis") from exc

    logger.info(
        "Semantic inference computed monitor_id=%s event_id=%s label=%s abstained=%s confidence=%.3f coverage=%.3f",
        monitor_id,
        event_id,
        row.semantic_label,
        row.abstained,
        row.semantic_confidence,
        row.valid_pixel_coverage or 0.0,
    )

    return EventSemanticComputationResult(summary=_semantic_row_to_read(row), computed=True)


def get_change_event_semantic_analysis(
    db_session: Session,
    *,
    monitor_id: UUID,
    event_id: UUID,
) -> ChangeEventSemanticAnalysisRead | None:
    bundle = _get_event_bundle(db_session, monitor_id=monitor_id, event_id=event_id)
    if bundle is None:
        return None

    row = _get_existing_semantic_row(db_session, event_id=event_id)
    if row is None:
        return None

    return _semantic_row_to_read(row)


def compute_analysis_semantics(
    db_session: Session,
    *,
    monitor_id: UUID,
    analysis_id: UUID,
    force_recompute: bool = False,
) -> BulkSemanticComputationResult | None:
    monitor = _get_monitor(db_session, monitor_id)
    if monitor is None:
        return None

    analysis = _get_analysis(db_session, monitor_id=monitor_id, analysis_id=analysis_id)
    if analysis is None:
        return None

    try:
        event_ids = db_session.execute(
            select(ChangeEvent.id)
            .where(
                ChangeEvent.monitor_id == monitor_id,
                ChangeEvent.analysis_id == analysis_id,
            )
            .order_by(ChangeEvent.first_detected_at.asc(), ChangeEvent.id.asc())
        ).scalars().all()
    except SQLAlchemyError as exc:
        raise SemanticQueryError("Failed to fetch change events for semantic analysis") from exc

    if not event_ids:
        return BulkSemanticComputationResult(
            response=AnalysisSemanticComputeResponse(
                analysis_id=analysis_id,
                event_count=0,
                computed=0,
                reused=0,
                failed=0,
                elapsed_seconds=0.0,
            )
        )

    started_at = time.perf_counter()
    computed = 0
    reused = 0
    failed = 0

    for event_id in event_ids:
        try:
            result = compute_change_event_semantics(
                db_session,
                monitor_id=monitor_id,
                event_id=event_id,
                force_recompute=force_recompute,
            )
        except (SemanticConflictError, SemanticPersistenceError, SemanticProcessingError, SemanticQueryError) as exc:
            failed += 1
            logger.warning(
                "Semantic inference failed for event monitor_id=%s analysis_id=%s event_id=%s error=%s",
                monitor_id,
                analysis_id,
                event_id,
                exc.__class__.__name__,
            )
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
        "Semantic inference bulk monitor_id=%s analysis_id=%s event_count=%s computed=%s reused=%s failed=%s elapsed_seconds=%.3f",
        monitor_id,
        analysis_id,
        len(event_ids),
        computed,
        reused,
        failed,
        elapsed_seconds,
    )

    return BulkSemanticComputationResult(
        response=AnalysisSemanticComputeResponse(
            analysis_id=analysis_id,
            event_count=len(event_ids),
            computed=computed,
            reused=reused,
            failed=failed,
            elapsed_seconds=round(float(elapsed_seconds), 6),
        )
    )
