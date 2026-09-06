from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from app.processing import (
    PREVIEW_MAX_DIMENSION,
    RasterPreparationError,
    apply_reflectance_scaling,
    compute_cloud_fraction,
    resolve_reflectance_scaling,
    resize_preview_image,
)


def test_preview_resize_enforces_max_dimension() -> None:
    image = Image.fromarray(np.zeros((922, 1732, 3), dtype=np.uint8), mode="RGB")

    resized = resize_preview_image(image)

    assert max(resized.size) <= PREVIEW_MAX_DIMENSION
    assert resized.size == (1024, 545)


def test_resolve_reflectance_scaling_prefers_dataset_scale_offset() -> None:
    scaling = resolve_reflectance_scaling(
        provider="planetary_computer",
        collection="sentinel-2-l2a",
        asset_key="B04",
        asset_payload={"href": "https://example.com/B04.tif"},
        dataset_scale=0.0002,
        dataset_offset=0.1,
        observation_metadata=None,
    )

    assert scaling.scale == pytest.approx(0.0002)
    assert scaling.offset == pytest.approx(0.1)
    assert scaling.source == "rasterio_dataset_scale_offset"


def test_resolve_reflectance_scaling_uses_stac_raster_bands() -> None:
    scaling = resolve_reflectance_scaling(
        provider="planetary_computer",
        collection="sentinel-2-l2a",
        asset_key="B08",
        asset_payload={
            "href": "https://example.com/B08.tif",
            "raster_bands": [{"scale": 0.00015, "offset": 0.02}],
        },
        dataset_scale=1.0,
        dataset_offset=0.0,
        observation_metadata=None,
    )

    assert scaling.scale == pytest.approx(0.00015)
    assert scaling.offset == pytest.approx(0.02)
    assert scaling.source == "stac_asset_raster_bands"


def test_resolve_reflectance_scaling_provider_fallback_for_pc_sentinel2_l2a() -> None:
    scaling = resolve_reflectance_scaling(
        provider="planetary_computer",
        collection="sentinel-2-l2a",
        asset_key="B02",
        asset_payload={"href": "https://example.com/B02.tif"},
        dataset_scale=1.0,
        dataset_offset=0.0,
        observation_metadata={"processing:level": "Level-2A"},
    )

    assert scaling.scale == pytest.approx(1e-4)
    assert scaling.offset == pytest.approx(0.0)
    assert scaling.source == "provider_fallback_planetary_computer_sentinel2_l2a"


def test_apply_reflectance_scaling_no_double_scaling() -> None:
    raw_band = np.array([[10000.0, 5000.0]], dtype=np.float32)
    valid_mask = np.array([[True, True]], dtype=bool)

    scaled = apply_reflectance_scaling(raw_band, scale=1e-4, offset=0.0, valid_mask=valid_mask)

    assert scaled[0, 0] == pytest.approx(1.0)
    assert scaled[0, 1] == pytest.approx(0.5)


def test_cloud_fraction_uses_usable_scl_denominator() -> None:
    inside_aoi_mask = np.array([[True, True, True, True, True, True]], dtype=bool)
    scl = np.array([[3, 8, 0, 1, 255, 4]], dtype=np.uint16)

    cloud_fraction, cloud_pixels, usable_scl_pixels = compute_cloud_fraction(
        inside_aoi_mask=inside_aoi_mask,
        scl_array=scl,
    )

    assert cloud_pixels == 2
    assert usable_scl_pixels == 3
    assert cloud_fraction == pytest.approx(2 / 3)


def test_cloud_fraction_excludes_defective_pixels_from_cloud_count() -> None:
    inside_aoi_mask = np.array([[True, True, True, True]], dtype=bool)
    scl = np.array([[1, 255, 3, 4]], dtype=np.uint16)

    cloud_fraction, cloud_pixels, usable_scl_pixels = compute_cloud_fraction(
        inside_aoi_mask=inside_aoi_mask,
        scl_array=scl,
    )

    assert usable_scl_pixels == 2
    assert cloud_pixels == 1
    assert cloud_fraction == pytest.approx(0.5)


def test_cloud_fraction_raises_when_no_usable_scl_pixels() -> None:
    inside_aoi_mask = np.array([[True, True]], dtype=bool)
    scl = np.array([[0, 255]], dtype=np.uint16)

    with pytest.raises(RasterPreparationError):
        compute_cloud_fraction(
            inside_aoi_mask=inside_aoi_mask,
            scl_array=scl,
        )
