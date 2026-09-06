from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.features import geometry_mask, sieve
from rasterio.warp import reproject, transform_geom

from app.processing.sentinel2 import NODATA_VALUE, PREVIEW_MAX_DIMENSION, resize_preview_image

logger = logging.getLogger(__name__)

NDVI_EPSILON = 1e-6
DEFAULT_SCORE_THRESHOLD = 0.30


class ChangeDetectionError(Exception):
    pass


@dataclass(slots=True)
class RasterGrid:
    crs: str
    transform: rasterio.Affine
    width: int
    height: int
    resolution: tuple[float, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "crs": self.crs,
            "transform": [
                float(self.transform.a),
                float(self.transform.b),
                float(self.transform.c),
                float(self.transform.d),
                float(self.transform.e),
                float(self.transform.f),
            ],
            "width": self.width,
            "height": self.height,
            "resolution": [float(self.resolution[0]), float(self.resolution[1])],
        }


@dataclass(slots=True)
class ChangeDetectionResult:
    change_score_path: Path
    change_mask_path: Path
    valid_comparison_mask_path: Path
    abs_delta_ndvi_path: Path
    spectral_distance_path: Path
    preview_path: Path
    valid_pixel_count: int
    changed_pixel_count: int
    changed_fraction: float
    changed_area_m2: float
    mean_change_score: float
    max_change_score: float
    mean_abs_delta_ndvi: float
    median_abs_delta_ndvi: float
    mean_spectral_distance: float
    removed_small_component_count: int
    reprojection_needed: bool
    comparison_grid: RasterGrid
    statistics: dict[str, Any]


def _extract_resolution(dataset: rasterio.DatasetReader) -> tuple[float, float]:
    x_resolution, y_resolution = dataset.res
    return abs(float(x_resolution)), abs(float(y_resolution))


def _read_multispectral(path: Path) -> tuple[np.ndarray, RasterGrid, float]:
    try:
        with rasterio.open(path) as dataset:
            if dataset.count != 4:
                raise ChangeDetectionError(f"Expected 4-band multispectral raster at {path}")
            if dataset.crs is None:
                raise ChangeDetectionError(f"Missing CRS in multispectral raster {path}")

            stack = dataset.read(out_dtype=np.float32)
            nodata = float(dataset.nodata) if dataset.nodata is not None else NODATA_VALUE
            grid = RasterGrid(
                crs=dataset.crs.to_string(),
                transform=dataset.transform,
                width=int(dataset.width),
                height=int(dataset.height),
                resolution=_extract_resolution(dataset),
            )
    except rasterio.errors.RasterioError as exc:
        raise ChangeDetectionError(f"Unable to open multispectral raster {path}") from exc

    return stack, grid, nodata


def _read_mask(path: Path) -> tuple[np.ndarray, RasterGrid]:
    try:
        with rasterio.open(path) as dataset:
            if dataset.count != 1:
                raise ChangeDetectionError(f"Expected single-band valid-mask raster at {path}")
            if dataset.crs is None:
                raise ChangeDetectionError(f"Missing CRS in valid-mask raster {path}")

            mask = dataset.read(1, out_dtype=np.uint8)
            grid = RasterGrid(
                crs=dataset.crs.to_string(),
                transform=dataset.transform,
                width=int(dataset.width),
                height=int(dataset.height),
                resolution=_extract_resolution(dataset),
            )
    except rasterio.errors.RasterioError as exc:
        raise ChangeDetectionError(f"Unable to open valid-mask raster {path}") from exc

    return np.where(mask >= 1, 1, 0).astype(np.uint8), grid


def _transform_almost_equal(a: rasterio.Affine, b: rasterio.Affine, tolerance: float = 1e-6) -> bool:
    return all(abs(float(v1) - float(v2)) <= tolerance for v1, v2 in zip(a, b, strict=True))


def grids_aligned(left: RasterGrid, right: RasterGrid) -> bool:
    return (
        left.crs == right.crs
        and left.width == right.width
        and left.height == right.height
        and _transform_almost_equal(left.transform, right.transform)
    )


def _reproject_multispectral_to_grid(
    *,
    source_stack: np.ndarray,
    source_grid: RasterGrid,
    source_nodata: float,
    target_grid: RasterGrid,
) -> np.ndarray:
    destination = np.full(
        (source_stack.shape[0], target_grid.height, target_grid.width),
        source_nodata,
        dtype=np.float32,
    )

    for band_index in range(source_stack.shape[0]):
        reproject(
            source=source_stack[band_index],
            destination=destination[band_index],
            src_transform=source_grid.transform,
            src_crs=source_grid.crs,
            src_nodata=source_nodata,
            dst_transform=target_grid.transform,
            dst_crs=target_grid.crs,
            dst_nodata=source_nodata,
            resampling=Resampling.bilinear,
        )

    return destination


def _reproject_mask_to_grid(
    *,
    source_mask: np.ndarray,
    source_grid: RasterGrid,
    target_grid: RasterGrid,
) -> np.ndarray:
    destination = np.zeros((target_grid.height, target_grid.width), dtype=np.uint8)

    reproject(
        source=source_mask,
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


def _compute_band_valid_mask(stack: np.ndarray, nodata_value: float) -> np.ndarray:
    valid_masks: list[np.ndarray] = []
    for band in stack:
        valid_masks.append(np.isfinite(band) & ~np.isclose(band, nodata_value, atol=1e-6))
    return np.logical_and.reduce(valid_masks)


def _compute_ndvi(red: np.ndarray, nir: np.ndarray) -> np.ndarray:
    denominator = nir + red
    ndvi = np.zeros(red.shape, dtype=np.float32)
    valid = np.abs(denominator) > NDVI_EPSILON
    ndvi[valid] = ((nir[valid] - red[valid]) / denominator[valid]).astype(np.float32)
    return ndvi


def _robust_normalize(metric: np.ndarray, valid_mask: np.ndarray) -> tuple[np.ndarray, dict[str, float]]:
    normalized = np.zeros(metric.shape, dtype=np.float32)
    valid_values = metric[valid_mask]
    if valid_values.size == 0:
        return normalized, {"p05": 0.0, "p95": 0.0}

    low, high = np.percentile(valid_values, [5, 95])
    low_value = float(low)
    high_value = float(high)

    if high_value <= low_value + 1e-9:
        return normalized, {"p05": low_value, "p95": high_value}

    normalized = np.clip((metric - low_value) / (high_value - low_value), 0.0, 1.0).astype(np.float32)
    normalized[~valid_mask] = 0.0

    return normalized, {"p05": low_value, "p95": high_value}


def _compute_preview_rgb(stack: np.ndarray, valid_mask: np.ndarray) -> np.ndarray:
    red = stack[2]
    green = stack[1]
    blue = stack[0]

    channels: list[np.ndarray] = []
    for channel in [red, green, blue]:
        image_channel = np.zeros(channel.shape, dtype=np.float32)
        valid_values = channel[valid_mask]
        if valid_values.size > 0:
            low, high = np.percentile(valid_values, [2, 98])
            if high <= low:
                high = low + 1e-6
            image_channel = np.clip((channel - low) / (high - low), 0.0, 1.0)
            image_channel[~valid_mask] = 0.0
        channels.append((image_channel * 255).astype(np.uint8))

    return np.dstack(channels)


def _build_change_preview(after_stack: np.ndarray, valid_mask: np.ndarray, change_mask: np.ndarray) -> Image.Image:
    base_rgb = _compute_preview_rgb(after_stack, valid_mask)
    overlay = base_rgb.astype(np.float32)

    changed = change_mask.astype(bool)
    overlay[changed, 0] = 255.0
    overlay[changed, 1] = overlay[changed, 1] * 0.30
    overlay[changed, 2] = overlay[changed, 2] * 0.30

    image = Image.fromarray(overlay.astype(np.uint8), mode="RGB")
    return resize_preview_image(image, max_dimension=PREVIEW_MAX_DIMENSION)


def _count_removed_components(raw_mask: np.ndarray, filtered_mask: np.ndarray) -> int:
    raw_bool = raw_mask.astype(bool)
    filtered_bool = filtered_mask.astype(bool)

    if raw_bool.size == 0 or not np.any(raw_bool):
        return 0

    visited = np.zeros(raw_bool.shape, dtype=bool)
    height, width = raw_bool.shape
    removed_count = 0

    neighbors = [
        (-1, -1),
        (-1, 0),
        (-1, 1),
        (0, -1),
        (0, 1),
        (1, -1),
        (1, 0),
        (1, 1),
    ]

    for row in range(height):
        for col in range(width):
            if not raw_bool[row, col] or visited[row, col]:
                continue

            stack = [(row, col)]
            visited[row, col] = True
            retained = False

            while stack:
                current_row, current_col = stack.pop()
                if filtered_bool[current_row, current_col]:
                    retained = True

                for delta_row, delta_col in neighbors:
                    neighbor_row = current_row + delta_row
                    neighbor_col = current_col + delta_col
                    if (
                        0 <= neighbor_row < height
                        and 0 <= neighbor_col < width
                        and raw_bool[neighbor_row, neighbor_col]
                        and not visited[neighbor_row, neighbor_col]
                    ):
                        visited[neighbor_row, neighbor_col] = True
                        stack.append((neighbor_row, neighbor_col))

            if not retained:
                removed_count += 1

    return removed_count


def _apply_minimum_area_filter(
    *,
    raw_change_mask: np.ndarray,
    minimum_change_area_m2: float,
    pixel_area_m2: float,
) -> tuple[np.ndarray, int, int]:
    if minimum_change_area_m2 <= 0:
        return raw_change_mask.astype(np.uint8), 0, 1

    min_pixels = max(1, int(math.ceil(minimum_change_area_m2 / pixel_area_m2)))

    if min_pixels <= 1:
        return raw_change_mask.astype(np.uint8), 0, min_pixels

    filtered = sieve(raw_change_mask.astype(np.uint8), size=min_pixels, connectivity=8)
    removed_small_component_count = _count_removed_components(raw_change_mask.astype(bool), filtered.astype(bool))

    return filtered.astype(np.uint8), removed_small_component_count, min_pixels


def _pixel_area_m2(transform: rasterio.Affine) -> float:
    return abs(float(transform.a * transform.e - transform.b * transform.d))


def run_change_detection(
    *,
    monitor_geometry_wgs84: dict[str, Any],
    before_multispectral_path: Path,
    before_valid_mask_path: Path,
    after_multispectral_path: Path,
    after_valid_mask_path: Path,
    threshold: float,
    minimum_change_area_m2: float,
    target_directory: Path,
) -> ChangeDetectionResult:
    if threshold < 0 or threshold > 1:
        raise ChangeDetectionError("Threshold must be within [0, 1]")

    before_stack, before_grid, before_nodata = _read_multispectral(before_multispectral_path)
    after_stack, after_grid, after_nodata = _read_multispectral(after_multispectral_path)
    before_valid_mask, before_mask_grid = _read_mask(before_valid_mask_path)
    after_valid_mask, after_mask_grid = _read_mask(after_valid_mask_path)

    if not grids_aligned(after_grid, after_mask_grid):
        raise ChangeDetectionError("After multispectral and valid-mask grids do not align")

    if not grids_aligned(before_grid, before_mask_grid):
        raise ChangeDetectionError("Before multispectral and valid-mask grids do not align")

    comparison_grid = after_grid
    reprojection_needed = not grids_aligned(before_grid, comparison_grid)

    if reprojection_needed:
        before_stack_for_compare = _reproject_multispectral_to_grid(
            source_stack=before_stack,
            source_grid=before_grid,
            source_nodata=before_nodata,
            target_grid=comparison_grid,
        )
        before_valid_for_compare = _reproject_mask_to_grid(
            source_mask=before_valid_mask,
            source_grid=before_mask_grid,
            target_grid=comparison_grid,
        )
    else:
        before_stack_for_compare = before_stack
        before_valid_for_compare = before_valid_mask

    try:
        monitor_geometry_in_comparison_crs = transform_geom(
            "EPSG:4326",
            comparison_grid.crs,
            monitor_geometry_wgs84,
        )
    except Exception as exc:  # pragma: no cover - CRS runtime behavior
        raise ChangeDetectionError("Unable to project monitor geometry onto comparison grid") from exc

    inside_aoi_mask = geometry_mask(
        [monitor_geometry_in_comparison_crs],
        out_shape=(comparison_grid.height, comparison_grid.width),
        transform=comparison_grid.transform,
        invert=True,
    )

    aoi_pixel_count = int(np.count_nonzero(inside_aoi_mask))
    if aoi_pixel_count == 0:
        raise ChangeDetectionError("Monitor AOI does not overlap the comparison grid")

    before_band_valid = _compute_band_valid_mask(before_stack_for_compare, before_nodata)
    after_band_valid = _compute_band_valid_mask(after_stack, after_nodata)

    before_valid_bool = before_valid_for_compare == 1
    after_valid_bool = after_valid_mask == 1

    valid_comparison_mask = inside_aoi_mask & before_valid_bool & after_valid_bool & before_band_valid & after_band_valid
    valid_pixel_count = int(np.count_nonzero(valid_comparison_mask))
    if valid_pixel_count == 0:
        raise ChangeDetectionError("No mutually valid pixels available for temporal comparison")

    before_red = before_stack_for_compare[2]
    before_nir = before_stack_for_compare[3]
    after_red = after_stack[2]
    after_nir = after_stack[3]

    ndvi_before = _compute_ndvi(before_red, before_nir)
    ndvi_after = _compute_ndvi(after_red, after_nir)
    abs_delta_ndvi = np.abs(ndvi_after - ndvi_before).astype(np.float32)

    spectral_distance = np.sqrt(np.mean((after_stack - before_stack_for_compare) ** 2, axis=0, dtype=np.float64)).astype(
        np.float32
    )

    ndvi_score, ndvi_norm_stats = _robust_normalize(abs_delta_ndvi, valid_comparison_mask)
    spectral_score, spectral_norm_stats = _robust_normalize(spectral_distance, valid_comparison_mask)

    combined_score = (0.5 * ndvi_score + 0.5 * spectral_score).astype(np.float32)
    combined_score[~valid_comparison_mask] = 0.0

    change_score_raster = np.full((comparison_grid.height, comparison_grid.width), NODATA_VALUE, dtype=np.float32)
    change_score_raster[valid_comparison_mask] = combined_score[valid_comparison_mask]

    abs_delta_ndvi_raster = np.full((comparison_grid.height, comparison_grid.width), NODATA_VALUE, dtype=np.float32)
    abs_delta_ndvi_raster[valid_comparison_mask] = abs_delta_ndvi[valid_comparison_mask]

    spectral_distance_raster = np.full((comparison_grid.height, comparison_grid.width), NODATA_VALUE, dtype=np.float32)
    spectral_distance_raster[valid_comparison_mask] = spectral_distance[valid_comparison_mask]

    raw_change_mask = valid_comparison_mask & (combined_score >= threshold)

    pixel_area_m2 = _pixel_area_m2(comparison_grid.transform)
    if pixel_area_m2 <= 0:
        raise ChangeDetectionError("Computed pixel area is not positive")

    filtered_change_mask, removed_small_component_count, min_component_pixels = _apply_minimum_area_filter(
        raw_change_mask=raw_change_mask,
        minimum_change_area_m2=minimum_change_area_m2,
        pixel_area_m2=pixel_area_m2,
    )

    changed_pixel_count = int(np.count_nonzero(filtered_change_mask == 1))
    changed_fraction = changed_pixel_count / valid_pixel_count
    changed_area_m2 = changed_pixel_count * pixel_area_m2

    valid_scores = combined_score[valid_comparison_mask]
    valid_abs_delta_ndvi = abs_delta_ndvi[valid_comparison_mask]
    valid_spectral_distance = spectral_distance[valid_comparison_mask]

    mean_change_score = float(np.mean(valid_scores))
    max_change_score = float(np.max(valid_scores))
    mean_abs_delta_ndvi = float(np.mean(valid_abs_delta_ndvi))
    median_abs_delta_ndvi = float(np.median(valid_abs_delta_ndvi))
    mean_spectral_distance = float(np.mean(valid_spectral_distance))

    score_percentiles = {
        "p50": float(np.percentile(valid_scores, 50)),
        "p75": float(np.percentile(valid_scores, 75)),
        "p90": float(np.percentile(valid_scores, 90)),
        "p95": float(np.percentile(valid_scores, 95)),
        "p99": float(np.percentile(valid_scores, 99)),
    }

    logger.info(
        "Temporal change metrics valid=%s changed=%s fraction=%.6f mean=%.6f max=%.6f removed_small_components=%s",
        valid_pixel_count,
        changed_pixel_count,
        changed_fraction,
        mean_change_score,
        max_change_score,
        removed_small_component_count,
    )

    target_directory.mkdir(parents=True, exist_ok=True)

    change_score_path = target_directory / "change_score.tif"
    change_mask_path = target_directory / "change_mask.tif"
    valid_comparison_mask_path = target_directory / "valid_comparison_mask.tif"
    abs_delta_ndvi_path = target_directory / "abs_delta_ndvi.tif"
    spectral_distance_path = target_directory / "spectral_distance.tif"
    preview_path = target_directory / "preview.png"

    with rasterio.open(
        change_score_path,
        "w",
        driver="GTiff",
        width=comparison_grid.width,
        height=comparison_grid.height,
        count=1,
        dtype="float32",
        crs=comparison_grid.crs,
        transform=comparison_grid.transform,
        nodata=NODATA_VALUE,
        compress="deflate",
    ) as destination:
        destination.write(change_score_raster, indexes=1)
        destination.set_band_description(1, "change_score")

    with rasterio.open(
        change_mask_path,
        "w",
        driver="GTiff",
        width=comparison_grid.width,
        height=comparison_grid.height,
        count=1,
        dtype="uint8",
        crs=comparison_grid.crs,
        transform=comparison_grid.transform,
        nodata=0,
        compress="deflate",
    ) as destination:
        destination.write(filtered_change_mask, indexes=1)
        destination.set_band_description(1, "change_mask")

    with rasterio.open(
        valid_comparison_mask_path,
        "w",
        driver="GTiff",
        width=comparison_grid.width,
        height=comparison_grid.height,
        count=1,
        dtype="uint8",
        crs=comparison_grid.crs,
        transform=comparison_grid.transform,
        nodata=0,
        compress="deflate",
    ) as destination:
        destination.write(valid_comparison_mask.astype(np.uint8), indexes=1)
        destination.set_band_description(1, "valid_comparison_mask")

    with rasterio.open(
        abs_delta_ndvi_path,
        "w",
        driver="GTiff",
        width=comparison_grid.width,
        height=comparison_grid.height,
        count=1,
        dtype="float32",
        crs=comparison_grid.crs,
        transform=comparison_grid.transform,
        nodata=NODATA_VALUE,
        compress="deflate",
    ) as destination:
        destination.write(abs_delta_ndvi_raster, indexes=1)
        destination.set_band_description(1, "abs_delta_ndvi")

    with rasterio.open(
        spectral_distance_path,
        "w",
        driver="GTiff",
        width=comparison_grid.width,
        height=comparison_grid.height,
        count=1,
        dtype="float32",
        crs=comparison_grid.crs,
        transform=comparison_grid.transform,
        nodata=NODATA_VALUE,
        compress="deflate",
    ) as destination:
        destination.write(spectral_distance_raster, indexes=1)
        destination.set_band_description(1, "spectral_distance")

    preview_image = _build_change_preview(
        after_stack=after_stack,
        valid_mask=inside_aoi_mask & after_valid_bool & after_band_valid,
        change_mask=filtered_change_mask,
    )
    preview_image.save(preview_path)

    statistics = {
        "aoi_pixel_count": aoi_pixel_count,
        "valid_fraction_of_aoi": valid_pixel_count / aoi_pixel_count,
        "threshold": threshold,
        "minimum_change_area_m2": minimum_change_area_m2,
        "pixel_area_m2": pixel_area_m2,
        "minimum_component_pixels": min_component_pixels,
        "removed_small_component_count": removed_small_component_count,
        "mean_abs_delta_ndvi": mean_abs_delta_ndvi,
        "median_abs_delta_ndvi": median_abs_delta_ndvi,
        "mean_spectral_distance": mean_spectral_distance,
        "ndvi_score_normalization": ndvi_norm_stats,
        "spectral_score_normalization": spectral_norm_stats,
        "score_percentiles": score_percentiles,
        "supporting_raster_outputs": {
            "abs_delta_ndvi": "abs_delta_ndvi.tif",
            "spectral_distance": "spectral_distance.tif",
        },
        "before_grid": before_grid.as_dict(),
        "after_grid": after_grid.as_dict(),
        "comparison_grid": comparison_grid.as_dict(),
        "reprojection_needed": reprojection_needed,
        "grid_alignment": True,
    }

    return ChangeDetectionResult(
        change_score_path=change_score_path,
        change_mask_path=change_mask_path,
        valid_comparison_mask_path=valid_comparison_mask_path,
        abs_delta_ndvi_path=abs_delta_ndvi_path,
        spectral_distance_path=spectral_distance_path,
        preview_path=preview_path,
        valid_pixel_count=valid_pixel_count,
        changed_pixel_count=changed_pixel_count,
        changed_fraction=changed_fraction,
        changed_area_m2=changed_area_m2,
        mean_change_score=mean_change_score,
        max_change_score=max_change_score,
        mean_abs_delta_ndvi=mean_abs_delta_ndvi,
        median_abs_delta_ndvi=median_abs_delta_ndvi,
        mean_spectral_distance=mean_spectral_distance,
        removed_small_component_count=removed_small_component_count,
        reprojection_needed=reprojection_needed,
        comparison_grid=comparison_grid,
        statistics=statistics,
    )

