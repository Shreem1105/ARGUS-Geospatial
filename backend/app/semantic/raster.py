from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.warp import reproject, transform_geom

from app.processing.sentinel2 import NODATA_VALUE
from app.semantic.base import EventSpectralEvidence

ND_EPSILON = 1e-6
MODEL_RGB_BANDS: tuple[str, ...] = ("B04", "B03", "B02")
CORE_BANDS: tuple[str, ...] = ("B02", "B03", "B04", "B08")


class EventRasterExtractionError(Exception):
    pass


class EventBandMappingError(EventRasterExtractionError):
    pass


@dataclass(slots=True)
class _RasterGrid:
    crs: str
    transform: rasterio.Affine
    width: int
    height: int


def _transform_almost_equal(left: rasterio.Affine, right: rasterio.Affine, tolerance: float = 1e-6) -> bool:
    return all(abs(float(v1) - float(v2)) <= tolerance for v1, v2 in zip(left, right, strict=True))


def _grids_aligned(left: _RasterGrid, right: _RasterGrid) -> bool:
    return (
        left.crs == right.crs
        and left.width == right.width
        and left.height == right.height
        and _transform_almost_equal(left.transform, right.transform)
    )


def _read_multispectral(path: Path) -> tuple[np.ndarray, _RasterGrid, float, tuple[str | None, ...]]:
    try:
        with rasterio.open(path) as dataset:
            if dataset.crs is None:
                raise EventRasterExtractionError(f"Missing CRS in multispectral raster: {path}")

            stack = dataset.read(out_dtype=np.float32)
            nodata = float(dataset.nodata) if dataset.nodata is not None else NODATA_VALUE
            grid = _RasterGrid(
                crs=dataset.crs.to_string(),
                transform=dataset.transform,
                width=int(dataset.width),
                height=int(dataset.height),
            )
            descriptions = tuple(dataset.descriptions)
    except rasterio.errors.RasterioError as exc:
        raise EventRasterExtractionError(f"Unable to open multispectral raster: {path}") from exc

    return stack, grid, nodata, descriptions


def _read_mask(path: Path) -> tuple[np.ndarray, _RasterGrid]:
    try:
        with rasterio.open(path) as dataset:
            if dataset.crs is None:
                raise EventRasterExtractionError(f"Missing CRS in valid-mask raster: {path}")
            if dataset.count != 1:
                raise EventRasterExtractionError(f"Expected a single-band mask raster: {path}")

            mask = dataset.read(1, out_dtype=np.uint8)
            grid = _RasterGrid(
                crs=dataset.crs.to_string(),
                transform=dataset.transform,
                width=int(dataset.width),
                height=int(dataset.height),
            )
    except rasterio.errors.RasterioError as exc:
        raise EventRasterExtractionError(f"Unable to open mask raster: {path}") from exc

    return np.where(mask >= 1, 1, 0).astype(np.uint8), grid


def _reproject_stack(
    *,
    source: np.ndarray,
    source_grid: _RasterGrid,
    target_grid: _RasterGrid,
    source_nodata: float,
) -> np.ndarray:
    destination = np.full((source.shape[0], target_grid.height, target_grid.width), source_nodata, dtype=np.float32)

    for index in range(source.shape[0]):
        reproject(
            source=source[index],
            destination=destination[index],
            src_transform=source_grid.transform,
            src_crs=source_grid.crs,
            src_nodata=source_nodata,
            dst_transform=target_grid.transform,
            dst_crs=target_grid.crs,
            dst_nodata=source_nodata,
            resampling=Resampling.bilinear,
        )

    return destination


def _reproject_mask(*, source: np.ndarray, source_grid: _RasterGrid, target_grid: _RasterGrid) -> np.ndarray:
    destination = np.zeros((target_grid.height, target_grid.width), dtype=np.uint8)

    reproject(
        source=source,
        destination=destination,
        src_transform=source_grid.transform,
        src_crs=source_grid.crs,
        src_nodata=0,
        dst_transform=target_grid.transform,
        dst_crs=target_grid.crs,
        dst_nodata=0,
        resampling=Resampling.nearest,
    )

    return np.where(destination >= 1, 1, 0).astype(np.uint8)


def _normalize_band_names(
    *,
    stack: np.ndarray,
    provided_band_names: list[str],
    descriptions: tuple[str | None, ...],
) -> list[str]:
    if len(provided_band_names) == stack.shape[0]:
        return [name.strip().upper() for name in provided_band_names]

    if len(descriptions) == stack.shape[0] and all(isinstance(value, str) and value.strip() for value in descriptions):
        return [str(name).strip().upper() for name in descriptions]

    raise EventBandMappingError("Prepared observation band metadata does not match raster band count")


def _band_index_map(band_names: list[str]) -> dict[str, int]:
    return {name: index for index, name in enumerate(band_names)}


def _normalized_difference(numerator_band: np.ndarray, denominator_band: np.ndarray) -> np.ndarray:
    denominator = numerator_band + denominator_band
    output = np.zeros(numerator_band.shape, dtype=np.float32)
    valid = np.abs(denominator) > ND_EPSILON
    output[valid] = ((numerator_band[valid] - denominator_band[valid]) / denominator[valid]).astype(np.float32)
    return output


def _mean_or_none(array: np.ndarray, mask: np.ndarray) -> float | None:
    if array.shape != mask.shape:
        raise EventRasterExtractionError("Metric array and mask shape mismatch")
    values = array[mask]
    if values.size == 0:
        return None
    return float(np.mean(values))


def _band_valid_mask(stack: np.ndarray, *, nodata: float, band_indices: list[int]) -> np.ndarray:
    masks: list[np.ndarray] = []
    for band_index in band_indices:
        band = stack[band_index]
        masks.append(np.isfinite(band) & ~np.isclose(band, nodata, atol=1e-6))
    return np.logical_and.reduce(masks)


def _safe_delta(before_value: float | None, after_value: float | None) -> float | None:
    if before_value is None or after_value is None:
        return None
    return float(after_value - before_value)


def _extract_rgb_patches(
    *,
    before_stack: np.ndarray,
    after_stack: np.ndarray,
    before_band_map: dict[str, int],
    after_band_map: dict[str, int],
    event_pixels: np.ndarray,
    valid_pixels: np.ndarray,
) -> tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None]:
    rows, cols = np.where(event_pixels)
    if rows.size == 0 or cols.size == 0:
        return None, None, None

    row_start = max(int(rows.min()) - 1, 0)
    row_end = min(int(rows.max()) + 2, event_pixels.shape[0])
    col_start = max(int(cols.min()) - 1, 0)
    col_end = min(int(cols.max()) + 2, event_pixels.shape[1])

    crop_event = event_pixels[row_start:row_end, col_start:col_end]
    crop_valid = valid_pixels[row_start:row_end, col_start:col_end]
    patch_valid = crop_event & crop_valid

    if not np.any(patch_valid):
        return None, None, None

    before_rgb = np.stack(
        [before_stack[before_band_map[band], row_start:row_end, col_start:col_end] for band in MODEL_RGB_BANDS],
        axis=0,
    ).astype(np.float32)
    after_rgb = np.stack(
        [after_stack[after_band_map[band], row_start:row_end, col_start:col_end] for band in MODEL_RGB_BANDS],
        axis=0,
    ).astype(np.float32)

    before_rgb[:, ~patch_valid] = 0.0
    after_rgb[:, ~patch_valid] = 0.0

    return before_rgb, after_rgb, patch_valid


def extract_event_spectral_evidence(
    *,
    event_geometry_wgs84: dict[str, Any],
    before_multispectral_path: Path,
    before_valid_mask_path: Path,
    after_multispectral_path: Path,
    after_valid_mask_path: Path,
    analysis_valid_comparison_mask_path: Path,
    before_band_names: list[str],
    after_band_names: list[str],
) -> EventSpectralEvidence:
    before_stack, before_grid, before_nodata, before_descriptions = _read_multispectral(before_multispectral_path)
    after_stack, after_grid, after_nodata, after_descriptions = _read_multispectral(after_multispectral_path)

    before_names = _normalize_band_names(
        stack=before_stack,
        provided_band_names=before_band_names,
        descriptions=before_descriptions,
    )
    after_names = _normalize_band_names(
        stack=after_stack,
        provided_band_names=after_band_names,
        descriptions=after_descriptions,
    )

    before_map = _band_index_map(before_names)
    after_map = _band_index_map(after_names)

    missing_core_bands = [band for band in CORE_BANDS if band not in before_map or band not in after_map]
    if missing_core_bands:
        raise EventBandMappingError(f"Missing required Sentinel-2 bands for semantic inference: {', '.join(missing_core_bands)}")

    before_valid, before_valid_grid = _read_mask(before_valid_mask_path)
    after_valid, after_valid_grid = _read_mask(after_valid_mask_path)
    analysis_valid, analysis_grid = _read_mask(analysis_valid_comparison_mask_path)

    if not _grids_aligned(before_grid, after_grid):
        before_stack = _reproject_stack(
            source=before_stack,
            source_grid=before_grid,
            target_grid=after_grid,
            source_nodata=before_nodata,
        )
        before_valid = _reproject_mask(source=before_valid, source_grid=before_valid_grid, target_grid=after_grid)
        before_grid = after_grid
        before_valid_grid = after_grid

    if not _grids_aligned(before_valid_grid, after_grid):
        before_valid = _reproject_mask(source=before_valid, source_grid=before_valid_grid, target_grid=after_grid)

    if not _grids_aligned(after_valid_grid, after_grid):
        after_valid = _reproject_mask(source=after_valid, source_grid=after_valid_grid, target_grid=after_grid)

    if not _grids_aligned(analysis_grid, after_grid):
        analysis_valid = _reproject_mask(source=analysis_valid, source_grid=analysis_grid, target_grid=after_grid)

    try:
        event_geometry_target = transform_geom("EPSG:4326", after_grid.crs, event_geometry_wgs84)
    except Exception as exc:  # pragma: no cover - runtime CRS edge cases
        raise EventRasterExtractionError("Failed to transform event geometry into raster CRS") from exc

    event_pixels = geometry_mask(
        [event_geometry_target],
        out_shape=(after_grid.height, after_grid.width),
        transform=after_grid.transform,
        invert=True,
    )

    total_event_pixels = int(np.count_nonzero(event_pixels))

    index_bands = [before_map[band] for band in CORE_BANDS]
    before_band_valid = _band_valid_mask(before_stack, nodata=before_nodata, band_indices=index_bands)
    after_band_valid = _band_valid_mask(after_stack, nodata=after_nodata, band_indices=index_bands)

    valid_pixels = (
        event_pixels
        & (analysis_valid == 1)
        & (before_valid == 1)
        & (after_valid == 1)
        & before_band_valid
        & after_band_valid
    )
    valid_pixel_count = int(np.count_nonzero(valid_pixels))
    valid_pixel_coverage = float(valid_pixel_count / total_event_pixels) if total_event_pixels > 0 else 0.0

    before_ndvi = _normalized_difference(before_stack[before_map["B08"]], before_stack[before_map["B04"]])
    after_ndvi = _normalized_difference(after_stack[after_map["B08"]], after_stack[after_map["B04"]])

    before_ndwi = _normalized_difference(before_stack[before_map["B03"]], before_stack[before_map["B08"]])
    after_ndwi = _normalized_difference(after_stack[after_map["B03"]], after_stack[after_map["B08"]])

    index_availability = {
        "ndvi": True,
        "ndwi": True,
        "nbr": ("B12" in before_map and "B12" in after_map),
        "ndbi": ("B11" in before_map and "B11" in after_map),
    }

    before_nbr_mean: float | None = None
    after_nbr_mean: float | None = None
    if index_availability["nbr"]:
        before_nbr = _normalized_difference(before_stack[before_map["B08"]], before_stack[before_map["B12"]])
        after_nbr = _normalized_difference(after_stack[after_map["B08"]], after_stack[after_map["B12"]])
        before_nbr_mean = _mean_or_none(before_nbr, valid_pixels)
        after_nbr_mean = _mean_or_none(after_nbr, valid_pixels)

    before_built_up_mean: float | None = None
    after_built_up_mean: float | None = None
    if index_availability["ndbi"]:
        before_built_up = _normalized_difference(before_stack[before_map["B11"]], before_stack[before_map["B08"]])
        after_built_up = _normalized_difference(after_stack[after_map["B11"]], after_stack[after_map["B08"]])
        before_built_up_mean = _mean_or_none(before_built_up, valid_pixels)
        after_built_up_mean = _mean_or_none(after_built_up, valid_pixels)

    before_rgb_patch, after_rgb_patch, patch_valid_mask = _extract_rgb_patches(
        before_stack=before_stack,
        after_stack=after_stack,
        before_band_map=before_map,
        after_band_map=after_map,
        event_pixels=event_pixels,
        valid_pixels=valid_pixels,
    )

    notes: list[str] = []
    if total_event_pixels <= 0:
        notes.append("event_geometry_outside_raster")
    if valid_pixel_count <= 0:
        notes.append("no_valid_pixels")
    if not index_availability["ndbi"]:
        notes.append("ndbi_unavailable_missing_b11")
    if not index_availability["nbr"]:
        notes.append("nbr_unavailable_missing_b12")

    before_ndvi_mean = _mean_or_none(before_ndvi, valid_pixels)
    after_ndvi_mean = _mean_or_none(after_ndvi, valid_pixels)
    before_ndwi_mean = _mean_or_none(before_ndwi, valid_pixels)
    after_ndwi_mean = _mean_or_none(after_ndwi, valid_pixels)

    return EventSpectralEvidence(
        before_ndvi_mean=before_ndvi_mean,
        after_ndvi_mean=after_ndvi_mean,
        ndvi_delta=_safe_delta(before_ndvi_mean, after_ndvi_mean),
        before_ndwi_mean=before_ndwi_mean,
        after_ndwi_mean=after_ndwi_mean,
        ndwi_delta=_safe_delta(before_ndwi_mean, after_ndwi_mean),
        before_nbr_mean=before_nbr_mean,
        after_nbr_mean=after_nbr_mean,
        nbr_delta=_safe_delta(before_nbr_mean, after_nbr_mean),
        before_built_up_score=before_built_up_mean,
        after_built_up_score=after_built_up_mean,
        built_up_delta=_safe_delta(before_built_up_mean, after_built_up_mean),
        valid_pixel_count=valid_pixel_count,
        total_event_pixel_count=total_event_pixels,
        valid_pixel_coverage=valid_pixel_coverage,
        before_rgb_patch=before_rgb_patch,
        after_rgb_patch=after_rgb_patch,
        patch_valid_mask=patch_valid_mask,
        index_availability=index_availability,
        notes=notes,
    )
