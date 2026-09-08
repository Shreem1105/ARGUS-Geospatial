from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ChangeAnalysis, PreparedObservation


class ArtifactQueryError(Exception):
    pass


class ArtifactValidationError(Exception):
    pass


def _data_root() -> Path:
    settings = get_settings()
    data_root = Path(settings.argus_data_dir)
    if not data_root.is_absolute():
        current_file = Path(__file__).resolve()
        project_root = current_file.parents[3]
        data_root = project_root / data_root
    return data_root.resolve()


def _uri_to_path(uri: str | None) -> Path | None:
    if not uri:
        return None

    parsed = urlparse(uri)
    if parsed.scheme in {"", None}:
        return Path(uri)
    if parsed.scheme != "file":
        return None

    decoded = unquote(parsed.path)
    local_path = url2pathname(decoded)
    if parsed.netloc and not local_path.startswith("\\\\"):
        local_path = f"\\\\{parsed.netloc}{local_path}"
    return Path(local_path)


def _resolve_safe_existing_path(path: Path | None) -> Path | None:
    if path is None:
        return None

    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        return None

    if not resolved.is_file():
        return None

    data_root = _data_root()
    try:
        resolved.relative_to(data_root)
    except ValueError as exc:
        raise ArtifactValidationError("Artifact path outside configured data directory") from exc

    return resolved


PREPARED_ARTIFACT_FIELD = {
    "preview": "preview_uri",
    "multispectral": "storage_uri",
    "valid-mask": "valid_mask_uri",
}


ANALYSIS_ARTIFACT_FIELD = {
    "preview": "preview_uri",
    "change-mask": "change_mask_uri",
    "change-score": "change_score_uri",
    "valid-comparison-mask": "valid_comparison_mask_uri",
    "abs-delta-ndvi": "statistics.abs_delta_ndvi_uri",
    "spectral-distance": "statistics.spectral_distance_uri",
}


def get_prepared_artifact_path(
    db_session: Session,
    *,
    monitor_id: UUID,
    observation_id: UUID,
    artifact_kind: str,
) -> Path | None:
    field_name = PREPARED_ARTIFACT_FIELD.get(artifact_kind)
    if field_name is None:
        raise ArtifactValidationError("Unsupported prepared artifact kind")

    try:
        prepared = db_session.execute(
            select(PreparedObservation).where(
                PreparedObservation.monitor_id == monitor_id,
                PreparedObservation.observation_id == observation_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise ArtifactQueryError("Unable to fetch prepared observation artifacts") from exc

    if prepared is None:
        return None

    uri = getattr(prepared, field_name)
    candidate = _uri_to_path(uri)
    return _resolve_safe_existing_path(candidate)


def _analysis_uri_from_kind(analysis: ChangeAnalysis, artifact_kind: str) -> str | None:
    field_name = ANALYSIS_ARTIFACT_FIELD.get(artifact_kind)
    if field_name is None:
        raise ArtifactValidationError("Unsupported analysis artifact kind")

    if field_name.startswith("statistics."):
        key = field_name.split(".", 1)[1]
        if isinstance(analysis.statistics, dict):
            value = analysis.statistics.get(key)
            return value if isinstance(value, str) else None
        return None

    return getattr(analysis, field_name)


def get_analysis_artifact_path(
    db_session: Session,
    *,
    monitor_id: UUID,
    analysis_id: UUID,
    artifact_kind: str,
) -> Path | None:
    try:
        analysis = db_session.execute(
            select(ChangeAnalysis).where(
                ChangeAnalysis.monitor_id == monitor_id,
                ChangeAnalysis.id == analysis_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise ArtifactQueryError("Unable to fetch change-analysis artifacts") from exc

    if analysis is None:
        return None

    uri = _analysis_uri_from_kind(analysis, artifact_kind)
    candidate = _uri_to_path(uri)
    return _resolve_safe_existing_path(candidate)


def infer_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }[suffix]
    if suffix in {".tif", ".tiff"}:
        return "image/tiff"
    if suffix == ".json":
        return "application/json"
    return "application/octet-stream"

