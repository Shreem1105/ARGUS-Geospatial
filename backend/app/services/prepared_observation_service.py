from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname
from uuid import UUID

import rasterio
from PIL import Image
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.gis.conversion import wkb_to_geojson_geometry
from app.models import Monitor, PreparedObservation, SatelliteObservation
from app.processing import RasterAssetError, RasterPreparationError, prepare_sentinel2_raster
from app.schemas import ObservationSummary, PreparedObservationRead, PreparedObservationStatus

logger = logging.getLogger(__name__)


class PreparedObservationPersistenceError(Exception):
    pass


class PreparedObservationQueryError(Exception):
    pass


class PreparedObservationProviderError(Exception):
    pass


class PreparedObservationProcessingError(Exception):
    pass


def _data_root() -> Path:
    settings = get_settings()
    data_root = Path(settings.argus_data_dir)
    if not data_root.is_absolute():
        config_file = Path(__file__).resolve()
        project_root = config_file.parents[3]
        data_root = project_root / data_root
    return data_root.resolve()


def ensure_data_directories() -> dict[str, Path]:
    root = _data_root()
    cache_dir = root / "cache"
    prepared_dir = root / "prepared"
    analyses_dir = root / "analyses"

    cache_dir.mkdir(parents=True, exist_ok=True)
    prepared_dir.mkdir(parents=True, exist_ok=True)
    analyses_dir.mkdir(parents=True, exist_ok=True)

    return {
        "root": root,
        "cache": cache_dir,
        "prepared": prepared_dir,
        "analyses": analyses_dir,
    }


def _to_observation_summary(observation: SatelliteObservation) -> ObservationSummary:
    return ObservationSummary(
        id=observation.id,
        item_id=observation.item_id,
        provider=observation.provider,
        collection=observation.collection,
        platform=observation.platform,
        acquired_at=observation.acquired_at,
        cloud_cover=observation.cloud_cover,
    )


def prepared_observation_to_read(
    prepared_observation: PreparedObservation,
    observation: SatelliteObservation,
) -> PreparedObservationRead:
    return PreparedObservationRead(
        id=prepared_observation.id,
        monitor_id=prepared_observation.monitor_id,
        observation_id=prepared_observation.observation_id,
        status=PreparedObservationStatus(prepared_observation.status),
        storage_uri=prepared_observation.storage_uri,
        valid_mask_uri=prepared_observation.valid_mask_uri,
        preview_uri=prepared_observation.preview_uri,
        crs=prepared_observation.crs,
        resolution_m=prepared_observation.resolution_m,
        width=prepared_observation.width,
        height=prepared_observation.height,
        band_names=prepared_observation.band_names,
        cloud_fraction=prepared_observation.cloud_fraction,
        valid_fraction=prepared_observation.valid_fraction,
        nodata_value=prepared_observation.nodata_value,
        processing_metadata=prepared_observation.processing_metadata,
        created_at=prepared_observation.created_at,
        updated_at=prepared_observation.updated_at,
        observation=_to_observation_summary(observation),
    )


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


def _transforms_match(left: rasterio.Affine, right: rasterio.Affine, tolerance: float = 1e-6) -> bool:
    return all(abs(float(a) - float(b)) <= tolerance for a, b in zip(left, right, strict=True))


def validate_prepared_artifacts(prepared_observation: PreparedObservation) -> tuple[bool, str | None]:
    storage_path = _file_uri_to_path(prepared_observation.storage_uri)
    mask_path = _file_uri_to_path(prepared_observation.valid_mask_uri)
    preview_path = _file_uri_to_path(prepared_observation.preview_uri)

    if storage_path is None:
        return False, "storage_uri_missing"
    if mask_path is None:
        return False, "valid_mask_uri_missing"
    if preview_path is None:
        return False, "preview_uri_missing"

    if not storage_path.exists() or not storage_path.is_file():
        return False, "multispectral_missing"
    if not mask_path.exists() or not mask_path.is_file():
        return False, "valid_mask_missing"
    if not preview_path.exists() or not preview_path.is_file():
        return False, "preview_missing"

    try:
        with rasterio.open(storage_path) as multispectral:
            expected_band_count = len(prepared_observation.band_names or []) or 4
            if multispectral.count != expected_band_count:
                return False, "multispectral_band_count_mismatch"
            if multispectral.crs is None:
                return False, "multispectral_missing_crs"

            if prepared_observation.width is not None and multispectral.width != prepared_observation.width:
                return False, "multispectral_width_mismatch"
            if prepared_observation.height is not None and multispectral.height != prepared_observation.height:
                return False, "multispectral_height_mismatch"
            if prepared_observation.crs is not None and multispectral.crs.to_string() != prepared_observation.crs:
                return False, "multispectral_crs_mismatch"

            multispectral_width = multispectral.width
            multispectral_height = multispectral.height
            multispectral_transform = multispectral.transform
            multispectral_crs = multispectral.crs

        with rasterio.open(mask_path) as mask:
            if mask.count != 1:
                return False, "valid_mask_band_count_invalid"
            if mask.crs is None:
                return False, "valid_mask_missing_crs"
            if mask.width != multispectral_width or mask.height != multispectral_height:
                return False, "mask_dimension_mismatch"
            if mask.crs != multispectral_crs:
                return False, "mask_crs_mismatch"
            if not _transforms_match(mask.transform, multispectral_transform):
                return False, "mask_transform_mismatch"

        with Image.open(preview_path) as preview:
            preview.verify()
    except Exception as exc:
        logger.warning(
            "Prepared artifacts failed validation monitor_id=%s observation_id=%s reason=%s",
            prepared_observation.monitor_id,
            prepared_observation.observation_id,
            exc,
        )
        return False, "artifact_open_failed"

    return True, None


def _get_monitor_and_observation(
    db_session: Session,
    *,
    monitor_id: UUID,
    observation_id: UUID,
) -> tuple[Monitor, SatelliteObservation] | None:
    try:
        monitor = db_session.execute(select(Monitor).where(Monitor.id == monitor_id)).scalar_one_or_none()
        if monitor is None:
            return None

        observation = db_session.execute(
            select(SatelliteObservation).where(
                SatelliteObservation.id == observation_id,
                SatelliteObservation.monitor_id == monitor_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise PreparedObservationQueryError("Failed to fetch monitor observation") from exc

    if observation is None:
        return None

    return monitor, observation


def _get_prepared_record(
    db_session: Session,
    *,
    monitor_id: UUID,
    observation_id: UUID,
) -> PreparedObservation | None:
    try:
        return db_session.execute(
            select(PreparedObservation).where(
                PreparedObservation.monitor_id == monitor_id,
                PreparedObservation.observation_id == observation_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise PreparedObservationQueryError("Failed to fetch prepared observation") from exc


def _build_target_directory(*, monitor_id: UUID, observation_id: UUID) -> Path:
    directories = ensure_data_directories()
    return directories["prepared"] / str(monitor_id) / str(observation_id)


def _set_failed_state(
    db_session: Session,
    *,
    prepared_observation: PreparedObservation,
    error_type: str,
    error_message: str,
) -> None:
    metadata: dict[str, Any] = dict(prepared_observation.processing_metadata or {})
    metadata["last_error"] = {
        "type": error_type,
        "message": error_message,
    }

    prepared_observation.status = PreparedObservationStatus.FAILED.value
    prepared_observation.processing_metadata = metadata

    try:
        db_session.add(prepared_observation)
        db_session.commit()
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise PreparedObservationPersistenceError("Failed to persist prepared observation failure state") from exc


def prepare_observation(
    db_session: Session,
    *,
    monitor_id: UUID,
    observation_id: UUID,
    force_reprocess: bool,
) -> PreparedObservationRead | None:
    monitor_and_observation = _get_monitor_and_observation(
        db_session,
        monitor_id=monitor_id,
        observation_id=observation_id,
    )
    if monitor_and_observation is None:
        return None

    monitor, observation = monitor_and_observation

    prepared_observation = _get_prepared_record(
        db_session,
        monitor_id=monitor_id,
        observation_id=observation_id,
    )

    repair_reason: str | None = None

    if prepared_observation is not None and not force_reprocess:
        if prepared_observation.status == PreparedObservationStatus.READY.value:
            healthy, reason = validate_prepared_artifacts(prepared_observation)
            if healthy:
                return prepared_observation_to_read(prepared_observation, observation)

            repair_reason = reason or "ready_artifact_validation_failed"
            logger.warning(
                "Prepared observation marked ready but artifacts unhealthy monitor_id=%s observation_id=%s reason=%s; reprocessing",
                monitor_id,
                observation_id,
                repair_reason,
            )
        else:
            return prepared_observation_to_read(prepared_observation, observation)

    if prepared_observation is None:
        prepared_observation = PreparedObservation(
            monitor_id=monitor_id,
            observation_id=observation_id,
            status=PreparedObservationStatus.PROCESSING.value,
            processing_metadata={"lifecycle": "created"},
        )
    else:
        prepared_observation.status = PreparedObservationStatus.PROCESSING.value
        reprocess_metadata: dict[str, Any] = {
            "lifecycle": "reprocessing",
            "force_reprocess": force_reprocess,
        }
        if repair_reason is not None:
            reprocess_metadata["repair_reason"] = repair_reason
        prepared_observation.processing_metadata = reprocess_metadata

    try:
        db_session.add(prepared_observation)
        db_session.commit()
        db_session.refresh(prepared_observation)
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise PreparedObservationPersistenceError("Failed to initialize prepared observation") from exc

    monitor_geometry = wkb_to_geojson_geometry(monitor.geometry)
    target_directory = _build_target_directory(monitor_id=monitor_id, observation_id=observation_id)

    logger.info(
        "Preparing raster monitor_id=%s observation_id=%s item_id=%s force_reprocess=%s repair_reason=%s",
        monitor_id,
        observation_id,
        observation.item_id,
        force_reprocess,
        repair_reason,
    )

    try:
        prepared_result = prepare_sentinel2_raster(
            monitor_geometry_wgs84=monitor_geometry,
            provider=observation.provider,
            collection=observation.collection,
            item_id=observation.item_id,
            assets=observation.assets,
            target_directory=target_directory,
            observation_metadata=observation.metadata_,
        )
    except RasterAssetError as exc:
        logger.error(
            "Provider/asset error during raster preparation monitor_id=%s observation_id=%s: %s",
            monitor_id,
            observation_id,
            exc,
        )
        _set_failed_state(
            db_session,
            prepared_observation=prepared_observation,
            error_type="provider_error",
            error_message=str(exc),
        )
        raise PreparedObservationProviderError("Satellite asset retrieval failed") from exc
    except RasterPreparationError as exc:
        logger.error(
            "Raster preparation failed monitor_id=%s observation_id=%s: %s",
            monitor_id,
            observation_id,
            exc,
        )
        _set_failed_state(
            db_session,
            prepared_observation=prepared_observation,
            error_type="processing_error",
            error_message=str(exc),
        )
        raise PreparedObservationProcessingError("Unable to prepare observation raster") from exc

    prepared_observation.status = PreparedObservationStatus.READY.value
    prepared_observation.storage_uri = prepared_result.storage_path.resolve().as_uri()
    prepared_observation.valid_mask_uri = prepared_result.valid_mask_path.resolve().as_uri()
    prepared_observation.preview_uri = prepared_result.preview_path.resolve().as_uri()
    prepared_observation.crs = prepared_result.crs
    prepared_observation.resolution_m = prepared_result.resolution_m
    prepared_observation.width = prepared_result.width
    prepared_observation.height = prepared_result.height
    prepared_observation.band_names = prepared_result.band_names
    prepared_observation.cloud_fraction = prepared_result.cloud_fraction
    prepared_observation.valid_fraction = prepared_result.valid_fraction
    prepared_observation.nodata_value = prepared_result.nodata_value
    prepared_observation.processing_metadata = prepared_result.processing_metadata

    try:
        db_session.add(prepared_observation)
        db_session.commit()
        db_session.refresh(prepared_observation)
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise PreparedObservationPersistenceError("Failed to persist prepared observation") from exc

    logger.info(
        "Prepared raster ready monitor_id=%s observation_id=%s width=%s height=%s valid_fraction=%.4f cloud_fraction=%.4f",
        monitor_id,
        observation_id,
        prepared_observation.width,
        prepared_observation.height,
        prepared_observation.valid_fraction,
        prepared_observation.cloud_fraction,
    )

    return prepared_observation_to_read(prepared_observation, observation)


def get_prepared_observation(
    db_session: Session,
    *,
    monitor_id: UUID,
    observation_id: UUID,
) -> PreparedObservationRead | None:
    monitor_and_observation = _get_monitor_and_observation(
        db_session,
        monitor_id=monitor_id,
        observation_id=observation_id,
    )
    if monitor_and_observation is None:
        return None

    _, observation = monitor_and_observation
    prepared_observation = _get_prepared_record(
        db_session,
        monitor_id=monitor_id,
        observation_id=observation_id,
    )
    if prepared_observation is None:
        return None

    return prepared_observation_to_read(prepared_observation, observation)
