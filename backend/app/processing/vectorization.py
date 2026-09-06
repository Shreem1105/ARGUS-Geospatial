from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import rasterio
from pyproj import CRS, Transformer
from rasterio.features import geometry_mask, shapes
from shapely import make_valid
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform


class VectorizationError(Exception):
    pass


SEVERITY_LOW_MAX = 0.02
SEVERITY_MEDIUM_MAX = 0.08
SEVERITY_HIGH_MAX = 0.25

CONFIDENCE_STRENGTH_WEIGHT = 0.45
CONFIDENCE_SUPPORT_WEIGHT = 0.25
CONFIDENCE_SIZE_WEIGHT = 0.20
CONFIDENCE_CONSISTENCY_WEIGHT = 0.10
CONFIDENCE_SUPPORT_TARGET_RATIO = 0.05
CONFIDENCE_SIZE_SATURATION_PIXELS = 1500
CONFIDENCE_STDDEV_UPPER = 0.35
EVENT_GENERATION_VERSION = "vector-events-v1"


@dataclass(slots=True)
class EventCandidate:
    geometry_wgs84: dict[str, Any]
    area_m2: float
    perimeter_m: float
    pixel_count: int
    mean_change_score: float
    max_change_score: float
    mean_abs_delta_ndvi: float | None
    mean_spectral_distance: float | None
    confidence: float
    severity: str
    properties: dict[str, Any]


@dataclass(slots=True)
class VectorizationResult:
    candidates: list[EventCandidate]
    simplification_tolerance_m: float
    pixel_area_m2: float
    skipped_geometry_count: int
    mask_width: int
    mask_height: int


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _clamp(value: float, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))


def derive_simplification_tolerance(transform: rasterio.Affine) -> float:
    pixel_width = math.hypot(float(transform.a), float(transform.b))
    pixel_height = math.hypot(float(transform.d), float(transform.e))
    resolution = min(pixel_width, pixel_height)
    if resolution <= 0:
        raise VectorizationError("Unable to derive raster resolution from transform")
    return resolution * 0.75


def pixel_area_m2_from_transform(transform: rasterio.Affine) -> float:
    pixel_area = abs(float(transform.a * transform.e - transform.b * transform.d))
    if pixel_area <= 0:
        raise VectorizationError("Computed pixel area is not positive")
    return pixel_area


def _extract_polygon_components(geometry: BaseGeometry) -> list[Polygon]:
    if geometry.is_empty:
        return []

    if isinstance(geometry, Polygon):
        return [geometry]

    if isinstance(geometry, MultiPolygon):
        return [polygon for polygon in geometry.geoms if not polygon.is_empty]

    if isinstance(geometry, GeometryCollection):
        components: list[Polygon] = []
        for child in geometry.geoms:
            components.extend(_extract_polygon_components(child))
        return components

    return []


def _validate_or_repair_polygon(geometry: BaseGeometry) -> list[Polygon]:
    if geometry.is_empty:
        return []

    candidates = _extract_polygon_components(geometry)
    if not candidates:
        candidates = _extract_polygon_components(make_valid(geometry))

    repaired: list[Polygon] = []
    for candidate in candidates:
        if candidate.is_empty:
            continue
        current = candidate
        if not current.is_valid:
            valid_geom = make_valid(current)
            subcomponents = _extract_polygon_components(valid_geom)
            for subcomponent in subcomponents:
                if subcomponent.is_empty or not subcomponent.is_valid or subcomponent.area <= 0:
                    continue
                repaired.append(subcomponent)
            continue

        if current.area <= 0:
            continue

        repaired.append(current)

    return repaired


def _simplify_polygon(polygon: Polygon, tolerance_m: float) -> Polygon:
    if tolerance_m <= 0:
        return polygon

    simplified = polygon.simplify(tolerance_m, preserve_topology=True)
    if simplified.is_empty or simplified.area <= 0:
        return polygon

    simplified_components = _validate_or_repair_polygon(simplified)
    if not simplified_components:
        return polygon

    return max(simplified_components, key=lambda item: item.area)


def _project_to_wgs84(geometry: Polygon, source_crs: CRS) -> list[Polygon]:
    if source_crs.to_epsg() == 4326:
        transformed = geometry
    else:
        transformer = Transformer.from_crs(source_crs, CRS.from_epsg(4326), always_xy=True)
        transformed = shapely_transform(transformer.transform, geometry)

    return _validate_or_repair_polygon(transformed)


def calculate_event_confidence(
    *,
    mean_change_score: float,
    max_change_score: float,
    pixel_count: int,
    analysis_valid_pixel_count: int,
    score_stddev: float,
) -> float:
    strength_score = _clamp((0.6 * mean_change_score) + (0.4 * max_change_score))

    support_ratio = float(pixel_count) / max(1, analysis_valid_pixel_count)
    support_score = _clamp(support_ratio / CONFIDENCE_SUPPORT_TARGET_RATIO)

    size_score = _clamp(math.log1p(pixel_count) / math.log1p(CONFIDENCE_SIZE_SATURATION_PIXELS))

    normalized_stddev = min(max(score_stddev, 0.0), CONFIDENCE_STDDEV_UPPER) / CONFIDENCE_STDDEV_UPPER
    consistency_score = _clamp(1.0 - normalized_stddev)

    confidence = (
        (CONFIDENCE_STRENGTH_WEIGHT * strength_score)
        + (CONFIDENCE_SUPPORT_WEIGHT * support_score)
        + (CONFIDENCE_SIZE_WEIGHT * size_score)
        + (CONFIDENCE_CONSISTENCY_WEIGHT * consistency_score)
    )

    return round(_clamp(confidence), 6)


def classify_event_severity(*, area_m2: float, confidence: float) -> str:
    relative_magnitude_score = (float(area_m2) / 1_000_000.0) * (0.5 + float(confidence))

    if relative_magnitude_score < SEVERITY_LOW_MAX:
        return "low"
    if relative_magnitude_score < SEVERITY_MEDIUM_MAX:
        return "medium"
    if relative_magnitude_score < SEVERITY_HIGH_MAX:
        return "high"
    return "critical"


def polygonize_change_mask(
    *,
    change_mask_array: np.ndarray,
    transform: rasterio.Affine,
) -> tuple[list[Polygon], int]:
    if change_mask_array.ndim != 2:
        raise VectorizationError("change mask must be a 2D array")

    changed_mask = change_mask_array == 1
    if not np.any(changed_mask):
        return [], 0

    polygons: list[Polygon] = []
    skipped = 0

    for geometry_payload, value in shapes(
        change_mask_array.astype(np.uint8),
        mask=changed_mask,
        transform=transform,
    ):
        if int(value) != 1:
            continue

        raw_geometry = shape(geometry_payload)
        components = _validate_or_repair_polygon(raw_geometry)
        if not components:
            skipped += 1
            continue

        for component in components:
            if component.is_empty or component.area <= 0:
                skipped += 1
                continue
            polygons.append(component)

    return polygons, skipped


def build_event_candidates(
    *,
    change_mask_array: np.ndarray,
    change_score_array: np.ndarray,
    valid_comparison_mask: np.ndarray,
    abs_delta_ndvi_array: np.ndarray | None,
    spectral_distance_array: np.ndarray | None,
    score_nodata: float,
    ndvi_nodata: float | None,
    spectral_nodata: float | None,
    transform: rasterio.Affine,
    crs: CRS,
    analysis_valid_pixel_count: int,
    generation_version: str,
) -> VectorizationResult:
    if change_mask_array.shape != change_score_array.shape:
        raise VectorizationError("change mask and score arrays must share shape")
    if valid_comparison_mask.shape != change_mask_array.shape:
        raise VectorizationError("valid comparison mask must share shape with change mask")
    if abs_delta_ndvi_array is not None and abs_delta_ndvi_array.shape != change_mask_array.shape:
        raise VectorizationError("abs delta NDVI array shape mismatch")
    if spectral_distance_array is not None and spectral_distance_array.shape != change_mask_array.shape:
        raise VectorizationError("spectral distance array shape mismatch")

    polygon_geometries, skipped_count = polygonize_change_mask(
        change_mask_array=change_mask_array,
        transform=transform,
    )

    simplification_tolerance_m = derive_simplification_tolerance(transform)
    pixel_area_m2 = pixel_area_m2_from_transform(transform)

    changed_mask = change_mask_array == 1
    valid_mask = valid_comparison_mask == 1
    finite_score_mask = np.isfinite(change_score_array) & ~np.isclose(change_score_array, score_nodata, atol=1e-6)

    candidates: list[EventCandidate] = []

    for component_index, polygon in enumerate(polygon_geometries, start=1):
        preserve_small_component = float(polygon.area) <= (pixel_area_m2 * 2.0)
        if preserve_small_component:
            simplified_projected = polygon
        else:
            simplified_projected = _simplify_polygon(polygon, simplification_tolerance_m)
        if simplified_projected.is_empty or simplified_projected.area <= 0:
            skipped_count += 1
            continue

        component_mask = geometry_mask(
            [mapping(simplified_projected)],
            out_shape=change_mask_array.shape,
            transform=transform,
            invert=True,
        )

        event_pixel_mask = component_mask & changed_mask & valid_mask & finite_score_mask
        pixel_count = int(np.count_nonzero(event_pixel_mask))
        if pixel_count <= 0:
            skipped_count += 1
            continue

        score_values = change_score_array[event_pixel_mask]
        if score_values.size == 0:
            skipped_count += 1
            continue

        mean_change_score = float(np.mean(score_values))
        max_change_score = float(np.max(score_values))
        score_stddev = float(np.std(score_values))

        mean_abs_delta_ndvi: float | None = None
        if abs_delta_ndvi_array is not None:
            ndvi_mask = event_pixel_mask & np.isfinite(abs_delta_ndvi_array)
            if ndvi_nodata is not None:
                ndvi_mask = ndvi_mask & ~np.isclose(abs_delta_ndvi_array, ndvi_nodata, atol=1e-6)
            ndvi_values = abs_delta_ndvi_array[ndvi_mask]
            if ndvi_values.size > 0:
                mean_abs_delta_ndvi = float(np.mean(ndvi_values))

        mean_spectral_distance: float | None = None
        if spectral_distance_array is not None:
            spectral_mask = event_pixel_mask & np.isfinite(spectral_distance_array)
            if spectral_nodata is not None:
                spectral_mask = spectral_mask & ~np.isclose(spectral_distance_array, spectral_nodata, atol=1e-6)
            spectral_values = spectral_distance_array[spectral_mask]
            if spectral_values.size > 0:
                mean_spectral_distance = float(np.mean(spectral_values))

        transformed_components = _project_to_wgs84(simplified_projected, crs)
        if not transformed_components:
            skipped_count += 1
            continue

        for transformed_component in transformed_components:
            if transformed_component.is_empty or not transformed_component.is_valid or transformed_component.area <= 0:
                skipped_count += 1
                continue

            confidence = calculate_event_confidence(
                mean_change_score=mean_change_score,
                max_change_score=max_change_score,
                pixel_count=pixel_count,
                analysis_valid_pixel_count=analysis_valid_pixel_count,
                score_stddev=score_stddev,
            )
            severity = classify_event_severity(area_m2=float(simplified_projected.area), confidence=confidence)

            properties = {
                "generation_version": generation_version,
                "component_index": component_index,
                "simplification_tolerance_m": simplification_tolerance_m,
                "pixel_area_m2": pixel_area_m2,
                "score_stddev": score_stddev,
            }

            candidates.append(
                EventCandidate(
                    geometry_wgs84=_jsonable(mapping(transformed_component)),
                    area_m2=float(simplified_projected.area),
                    perimeter_m=float(simplified_projected.length),
                    pixel_count=pixel_count,
                    mean_change_score=mean_change_score,
                    max_change_score=max_change_score,
                    mean_abs_delta_ndvi=mean_abs_delta_ndvi,
                    mean_spectral_distance=mean_spectral_distance,
                    confidence=confidence,
                    severity=severity,
                    properties=properties,
                )
            )

    return VectorizationResult(
        candidates=candidates,
        simplification_tolerance_m=simplification_tolerance_m,
        pixel_area_m2=pixel_area_m2,
        skipped_geometry_count=skipped_count,
        mask_width=int(change_mask_array.shape[1]),
        mask_height=int(change_mask_array.shape[0]),
    )
