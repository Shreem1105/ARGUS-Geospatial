from __future__ import annotations

import math

import numpy as np
import pytest
from pyproj import CRS
from rasterio.transform import from_origin

from app.processing.vectorization import (
    EVENT_GENERATION_VERSION,
    build_event_candidates,
    calculate_event_confidence,
    classify_event_severity,
    derive_simplification_tolerance,
    pixel_area_m2_from_transform,
    polygonize_change_mask,
)


def _build_inputs(height: int = 20, width: int = 20):
    change_mask = np.zeros((height, width), dtype=np.uint8)
    change_score = np.full((height, width), -9999.0, dtype=np.float32)
    valid_mask = np.ones((height, width), dtype=np.uint8)
    abs_delta_ndvi = np.full((height, width), -9999.0, dtype=np.float32)
    spectral_distance = np.full((height, width), -9999.0, dtype=np.float32)
    return change_mask, change_score, valid_mask, abs_delta_ndvi, spectral_distance


def test_polygonize_one_component_returns_one_polygon() -> None:
    change_mask, *_ = _build_inputs()
    change_mask[2:6, 3:8] = 1

    polygons, skipped = polygonize_change_mask(
        change_mask_array=change_mask,
        transform=from_origin(500_000, 3_900_000, 10, 10),
    )

    assert len(polygons) == 1
    assert skipped == 0


def test_polygonize_two_components_returns_two_polygons() -> None:
    change_mask, *_ = _build_inputs()
    change_mask[2:6, 3:8] = 1
    change_mask[12:16, 13:18] = 1

    polygons, skipped = polygonize_change_mask(
        change_mask_array=change_mask,
        transform=from_origin(500_000, 3_900_000, 10, 10),
    )

    assert len(polygons) == 2
    assert skipped == 0


def test_polygonize_zero_change_returns_empty() -> None:
    change_mask, *_ = _build_inputs()

    polygons, skipped = polygonize_change_mask(
        change_mask_array=change_mask,
        transform=from_origin(500_000, 3_900_000, 10, 10),
    )

    assert polygons == []
    assert skipped == 0


def test_background_pixels_not_polygonized() -> None:
    change_mask, *_ = _build_inputs()
    change_mask[5, 5] = 2

    polygons, skipped = polygonize_change_mask(
        change_mask_array=change_mask,
        transform=from_origin(500_000, 3_900_000, 10, 10),
    )

    assert polygons == []
    assert skipped == 0


def test_build_event_candidates_metrics_and_geometry_conversion() -> None:
    change_mask, change_score, valid_mask, abs_delta_ndvi, spectral_distance = _build_inputs()
    change_mask[2:4, 3:5] = 1

    change_score[2:4, 3:5] = np.array([[0.2, 0.4], [0.6, 0.8]], dtype=np.float32)
    abs_delta_ndvi[2:4, 3:5] = np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32)
    spectral_distance[2:4, 3:5] = np.array([[0.05, 0.15], [0.25, 0.35]], dtype=np.float32)

    transform = from_origin(500_000, 3_900_000, 10, 10)
    result = build_event_candidates(
        change_mask_array=change_mask,
        change_score_array=change_score,
        valid_comparison_mask=valid_mask,
        abs_delta_ndvi_array=abs_delta_ndvi,
        spectral_distance_array=spectral_distance,
        score_nodata=-9999.0,
        ndvi_nodata=-9999.0,
        spectral_nodata=-9999.0,
        transform=transform,
        crs=CRS.from_epsg(32617),
        analysis_valid_pixel_count=int(np.count_nonzero(valid_mask == 1)),
        generation_version=EVENT_GENERATION_VERSION,
    )

    assert len(result.candidates) == 1
    event = result.candidates[0]

    assert event.pixel_count == 4
    assert event.mean_change_score == pytest.approx(0.5)
    assert event.max_change_score == pytest.approx(0.8)
    assert event.mean_abs_delta_ndvi == pytest.approx(0.25)
    assert event.mean_spectral_distance == pytest.approx(0.2)
    assert event.area_m2 == pytest.approx(400.0)
    assert event.perimeter_m > 0
    assert event.confidence >= 0
    assert event.confidence <= 1
    assert event.geometry_wgs84["type"] == "Polygon"


def test_event_candidates_split_disconnected_components() -> None:
    change_mask, change_score, valid_mask, abs_delta_ndvi, spectral_distance = _build_inputs()
    change_mask[2:4, 3:5] = 1
    change_mask[12:14, 13:15] = 1

    change_score[change_mask == 1] = 0.6
    abs_delta_ndvi[change_mask == 1] = 0.2
    spectral_distance[change_mask == 1] = 0.2

    result = build_event_candidates(
        change_mask_array=change_mask,
        change_score_array=change_score,
        valid_comparison_mask=valid_mask,
        abs_delta_ndvi_array=abs_delta_ndvi,
        spectral_distance_array=spectral_distance,
        score_nodata=-9999.0,
        ndvi_nodata=-9999.0,
        spectral_nodata=-9999.0,
        transform=from_origin(500_000, 3_900_000, 10, 10),
        crs=CRS.from_epsg(32617),
        analysis_valid_pixel_count=int(np.count_nonzero(valid_mask == 1)),
        generation_version=EVENT_GENERATION_VERSION,
    )

    assert len(result.candidates) == 2


def test_simplification_tolerance_derived_from_resolution() -> None:
    transform = from_origin(500_000, 3_900_000, 10, 10)
    tolerance = derive_simplification_tolerance(transform)

    assert tolerance == pytest.approx(7.5)


def test_pixel_area_from_transform() -> None:
    transform = from_origin(500_000, 3_900_000, 20, 20)
    assert pixel_area_m2_from_transform(transform) == pytest.approx(400.0)


def test_confidence_is_bounded() -> None:
    value = calculate_event_confidence(
        mean_change_score=1.2,
        max_change_score=3.0,
        pixel_count=100,
        analysis_valid_pixel_count=10,
        score_stddev=-1.0,
    )
    assert 0.0 <= value <= 1.0


def test_confidence_increases_for_stronger_signal() -> None:
    weak = calculate_event_confidence(
        mean_change_score=0.2,
        max_change_score=0.4,
        pixel_count=20,
        analysis_valid_pixel_count=2000,
        score_stddev=0.3,
    )
    strong = calculate_event_confidence(
        mean_change_score=0.7,
        max_change_score=0.9,
        pixel_count=200,
        analysis_valid_pixel_count=2000,
        score_stddev=0.05,
    )

    assert strong >= weak


@pytest.mark.parametrize(
    ("area_m2", "confidence", "expected"),
    [
        (5_000.0, 0.2, "low"),
        (30_000.0, 0.4, "medium"),
        (120_000.0, 0.7, "high"),
        (400_000.0, 0.9, "critical"),
    ],
)
def test_severity_thresholds(area_m2: float, confidence: float, expected: str) -> None:
    assert classify_event_severity(area_m2=area_m2, confidence=confidence) == expected


def test_severity_is_deterministic() -> None:
    first = classify_event_severity(area_m2=90_000.0, confidence=0.65)
    second = classify_event_severity(area_m2=90_000.0, confidence=0.65)
    assert first == second


def test_small_component_survives_if_already_in_cleaned_mask() -> None:
    change_mask, change_score, valid_mask, abs_delta_ndvi, spectral_distance = _build_inputs(height=6, width=6)
    change_mask[2, 2] = 1
    change_score[2, 2] = 0.7
    abs_delta_ndvi[2, 2] = 0.3
    spectral_distance[2, 2] = 0.25

    result = build_event_candidates(
        change_mask_array=change_mask,
        change_score_array=change_score,
        valid_comparison_mask=valid_mask,
        abs_delta_ndvi_array=abs_delta_ndvi,
        spectral_distance_array=spectral_distance,
        score_nodata=-9999.0,
        ndvi_nodata=-9999.0,
        spectral_nodata=-9999.0,
        transform=from_origin(500_000, 3_900_000, 10, 10),
        crs=CRS.from_epsg(32617),
        analysis_valid_pixel_count=int(np.count_nonzero(valid_mask == 1)),
        generation_version=EVENT_GENERATION_VERSION,
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].pixel_count == 1
    assert math.isfinite(result.candidates[0].area_m2)
