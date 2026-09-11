from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from app.semantic.raster import extract_event_spectral_evidence


def _write_multispectral(path: Path, stack: np.ndarray, *, band_names: list[str], nodata: float = -9999.0) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=stack.shape[2],
        height=stack.shape[1],
        count=stack.shape[0],
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(-80.8600, 35.2400, 0.0001, 0.0001),
        nodata=nodata,
    ) as dataset:
        dataset.write(stack.astype(np.float32))
        dataset.descriptions = tuple(band_names)


def _write_mask(path: Path, mask: np.ndarray) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=mask.shape[1],
        height=mask.shape[0],
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(-80.8600, 35.2400, 0.0001, 0.0001),
        nodata=0,
    ) as dataset:
        dataset.write(mask.astype(np.uint8), 1)


def _event_polygon_inside() -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [-80.8588, 35.2388],
                [-80.8578, 35.2388],
                [-80.8578, 35.2396],
                [-80.8588, 35.2396],
                [-80.8588, 35.2388],
            ]
        ],
    }


def _event_polygon_outside() -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [-80.9000, 35.2800],
                [-80.8990, 35.2800],
                [-80.8990, 35.2810],
                [-80.9000, 35.2810],
                [-80.9000, 35.2800],
            ]
        ],
    }


def test_extract_event_spectral_evidence_computes_expected_directional_deltas(tmp_path: Path) -> None:
    band_names = ["B02", "B03", "B04", "B08", "B11", "B12"]

    before_stack = np.zeros((6, 32, 32), dtype=np.float32)
    after_stack = np.zeros((6, 32, 32), dtype=np.float32)

    before_stack[0, :, :] = 0.10
    before_stack[1, :, :] = 0.15
    before_stack[2, :, :] = 0.20
    before_stack[3, :, :] = 0.35
    before_stack[4, :, :] = 0.20
    before_stack[5, :, :] = 0.18

    after_stack[0, :, :] = 0.10
    after_stack[1, :, :] = 0.17
    after_stack[2, :, :] = 0.26
    after_stack[3, :, :] = 0.25
    after_stack[4, :, :] = 0.28
    after_stack[5, :, :] = 0.23

    mask = np.ones((32, 32), dtype=np.uint8)

    before_path = tmp_path / "before.tif"
    after_path = tmp_path / "after.tif"
    before_mask_path = tmp_path / "before_mask.tif"
    after_mask_path = tmp_path / "after_mask.tif"
    analysis_mask_path = tmp_path / "analysis_mask.tif"

    _write_multispectral(before_path, before_stack, band_names=band_names)
    _write_multispectral(after_path, after_stack, band_names=band_names)
    _write_mask(before_mask_path, mask)
    _write_mask(after_mask_path, mask)
    _write_mask(analysis_mask_path, mask)

    evidence = extract_event_spectral_evidence(
        event_geometry_wgs84=_event_polygon_inside(),
        before_multispectral_path=before_path,
        before_valid_mask_path=before_mask_path,
        after_multispectral_path=after_path,
        after_valid_mask_path=after_mask_path,
        analysis_valid_comparison_mask_path=analysis_mask_path,
        before_band_names=band_names,
        after_band_names=band_names,
    )

    assert evidence.valid_pixel_count > 0
    assert evidence.valid_pixel_coverage > 0
    assert evidence.ndvi_delta is not None and evidence.ndvi_delta < 0
    assert evidence.ndwi_delta is not None and evidence.ndwi_delta > 0
    assert evidence.built_up_delta is not None and evidence.built_up_delta > 0
    assert evidence.index_availability["nbr"] is True
    assert evidence.index_availability["ndbi"] is True
    assert evidence.before_rgb_patch is not None
    assert evidence.after_rgb_patch is not None
    assert evidence.patch_valid_mask is not None


def test_extract_event_spectral_evidence_marks_missing_optional_indices(tmp_path: Path) -> None:
    band_names = ["B02", "B03", "B04", "B08"]

    before_stack = np.zeros((4, 24, 24), dtype=np.float32)
    after_stack = np.zeros((4, 24, 24), dtype=np.float32)

    before_stack[0, :, :] = 0.09
    before_stack[1, :, :] = 0.14
    before_stack[2, :, :] = 0.19
    before_stack[3, :, :] = 0.31

    after_stack[0, :, :] = 0.11
    after_stack[1, :, :] = 0.16
    after_stack[2, :, :] = 0.24
    after_stack[3, :, :] = 0.29

    mask = np.ones((24, 24), dtype=np.uint8)

    before_path = tmp_path / "before_basic.tif"
    after_path = tmp_path / "after_basic.tif"
    before_mask_path = tmp_path / "before_mask_basic.tif"
    after_mask_path = tmp_path / "after_mask_basic.tif"
    analysis_mask_path = tmp_path / "analysis_mask_basic.tif"

    _write_multispectral(before_path, before_stack, band_names=band_names)
    _write_multispectral(after_path, after_stack, band_names=band_names)
    _write_mask(before_mask_path, mask)
    _write_mask(after_mask_path, mask)
    _write_mask(analysis_mask_path, mask)

    evidence = extract_event_spectral_evidence(
        event_geometry_wgs84=_event_polygon_inside(),
        before_multispectral_path=before_path,
        before_valid_mask_path=before_mask_path,
        after_multispectral_path=after_path,
        after_valid_mask_path=after_mask_path,
        analysis_valid_comparison_mask_path=analysis_mask_path,
        before_band_names=band_names,
        after_band_names=band_names,
    )

    assert evidence.index_availability["nbr"] is False
    assert evidence.index_availability["ndbi"] is False
    assert evidence.before_nbr_mean is None
    assert evidence.after_nbr_mean is None
    assert evidence.before_built_up_score is None
    assert evidence.after_built_up_score is None
    assert "nbr_unavailable_missing_b12" in evidence.notes
    assert "ndbi_unavailable_missing_b11" in evidence.notes


def test_extract_event_spectral_evidence_handles_event_outside_raster(tmp_path: Path) -> None:
    band_names = ["B02", "B03", "B04", "B08"]

    before_stack = np.ones((4, 20, 20), dtype=np.float32) * 0.2
    after_stack = np.ones((4, 20, 20), dtype=np.float32) * 0.25
    mask = np.ones((20, 20), dtype=np.uint8)

    before_path = tmp_path / "before_outside.tif"
    after_path = tmp_path / "after_outside.tif"
    before_mask_path = tmp_path / "before_mask_outside.tif"
    after_mask_path = tmp_path / "after_mask_outside.tif"
    analysis_mask_path = tmp_path / "analysis_mask_outside.tif"

    _write_multispectral(before_path, before_stack, band_names=band_names)
    _write_multispectral(after_path, after_stack, band_names=band_names)
    _write_mask(before_mask_path, mask)
    _write_mask(after_mask_path, mask)
    _write_mask(analysis_mask_path, mask)

    evidence = extract_event_spectral_evidence(
        event_geometry_wgs84=_event_polygon_outside(),
        before_multispectral_path=before_path,
        before_valid_mask_path=before_mask_path,
        after_multispectral_path=after_path,
        after_valid_mask_path=after_mask_path,
        analysis_valid_comparison_mask_path=analysis_mask_path,
        before_band_names=band_names,
        after_band_names=band_names,
    )

    assert evidence.total_event_pixel_count == 0
    assert evidence.valid_pixel_count == 0
    assert evidence.valid_pixel_coverage == 0
    assert evidence.before_rgb_patch is None
    assert evidence.after_rgb_patch is None
    assert evidence.patch_valid_mask is None
    assert "event_geometry_outside_raster" in evidence.notes
    assert "no_valid_pixels" in evidence.notes
