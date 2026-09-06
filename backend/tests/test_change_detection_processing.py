from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from PIL import Image
from pyproj import Transformer
from rasterio.transform import from_origin

from app.processing import NODATA_VALUE, run_change_detection
from app.processing.change_detection import _apply_minimum_area_filter

MONITOR_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [-80.85, 35.22],
            [-80.84, 35.22],
            [-80.84, 35.23],
            [-80.85, 35.23],
            [-80.85, 35.22],
        ]
    ],
}


@pytest.fixture(scope="module")
def monitor_bounds_utm() -> tuple[float, float, float, float]:
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32617", always_xy=True)
    coordinates = MONITOR_POLYGON["coordinates"][0]
    xs: list[float] = []
    ys: list[float] = []
    for longitude, latitude in coordinates:
        x, y = transformer.transform(longitude, latitude)
        xs.append(float(x))
        ys.append(float(y))
    return min(xs), min(ys), max(xs), max(ys)


def _create_stack(
    *,
    width: int,
    height: int,
    base_values: tuple[float, float, float, float],
    change_slice: tuple[slice, slice] | None = None,
    change_delta: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
) -> np.ndarray:
    stack = np.stack([np.full((height, width), value, dtype=np.float32) for value in base_values])

    if change_slice is not None:
        rows, cols = change_slice
        for band_index, delta in enumerate(change_delta):
            stack[band_index, rows, cols] += np.float32(delta)

    return stack


def _write_multispectral(path: Path, stack: np.ndarray, transform: rasterio.Affine) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=stack.shape[2],
        height=stack.shape[1],
        count=4,
        dtype="float32",
        crs="EPSG:32617",
        transform=transform,
        nodata=NODATA_VALUE,
        compress="deflate",
    ) as destination:
        for index in range(1, 5):
            destination.write(stack[index - 1], indexes=index)


def _write_valid_mask(path: Path, mask: np.ndarray, transform: rasterio.Affine) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=mask.shape[1],
        height=mask.shape[0],
        count=1,
        dtype="uint8",
        crs="EPSG:32617",
        transform=transform,
        nodata=0,
        compress="deflate",
    ) as destination:
        destination.write(mask.astype(np.uint8), indexes=1)


def _run(
    tmp_path: Path,
    *,
    before_stack: np.ndarray,
    before_mask: np.ndarray,
    before_transform: rasterio.Affine,
    after_stack: np.ndarray,
    after_mask: np.ndarray,
    after_transform: rasterio.Affine,
    threshold: float = 0.30,
    minimum_change_area_m2: float = 0.0,
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    before_multispectral = tmp_path / "before_multispectral.tif"
    before_valid_mask = tmp_path / "before_valid_mask.tif"
    after_multispectral = tmp_path / "after_multispectral.tif"
    after_valid_mask = tmp_path / "after_valid_mask.tif"

    _write_multispectral(before_multispectral, before_stack, before_transform)
    _write_valid_mask(before_valid_mask, before_mask, before_transform)
    _write_multispectral(after_multispectral, after_stack, after_transform)
    _write_valid_mask(after_valid_mask, after_mask, after_transform)

    return run_change_detection(
        monitor_geometry_wgs84=MONITOR_POLYGON,
        before_multispectral_path=before_multispectral,
        before_valid_mask_path=before_valid_mask,
        after_multispectral_path=after_multispectral,
        after_valid_mask_path=after_valid_mask,
        threshold=threshold,
        minimum_change_area_m2=minimum_change_area_m2,
        target_directory=tmp_path / "outputs",
    )


def test_identical_grids_remain_aligned(tmp_path: Path, monitor_bounds_utm: tuple[float, float, float, float]) -> None:
    min_x, _, _, max_y = monitor_bounds_utm
    transform = from_origin(min_x - 300.0, max_y + 300.0, 10.0, 10.0)
    stack = _create_stack(width=220, height=220, base_values=(0.10, 0.12, 0.14, 0.20))
    mask = np.ones((220, 220), dtype=np.uint8)

    result = _run(
        tmp_path,
        before_stack=stack,
        before_mask=mask,
        before_transform=transform,
        after_stack=stack.copy(),
        after_mask=mask.copy(),
        after_transform=transform,
    )

    assert result.reprojection_needed is False
    assert result.statistics["grid_alignment"] is True


def test_different_transforms_are_aligned_with_reprojection(
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    min_x, _, _, max_y = monitor_bounds_utm
    after_transform = from_origin(min_x - 300.0, max_y + 300.0, 10.0, 10.0)
    before_transform = from_origin(min_x - 295.0, max_y + 305.0, 10.0, 10.0)

    before_stack = _create_stack(width=220, height=220, base_values=(0.10, 0.12, 0.14, 0.20))
    after_stack = _create_stack(
        width=220,
        height=220,
        base_values=(0.10, 0.12, 0.14, 0.20),
        change_slice=(slice(90, 110), slice(90, 110)),
        change_delta=(0.05, 0.05, 0.05, 0.05),
    )
    mask = np.ones((220, 220), dtype=np.uint8)

    result = _run(
        tmp_path,
        before_stack=before_stack,
        before_mask=mask,
        before_transform=before_transform,
        after_stack=after_stack,
        after_mask=mask,
        after_transform=after_transform,
    )

    assert result.reprojection_needed is True
    assert result.comparison_grid.width == 220
    assert result.comparison_grid.height == 220


def test_valid_comparison_uses_only_mutually_valid_pixels(
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    min_x, _, _, max_y = monitor_bounds_utm
    transform = from_origin(min_x - 300.0, max_y + 300.0, 10.0, 10.0)

    stack = _create_stack(width=220, height=220, base_values=(0.10, 0.12, 0.14, 0.20))
    before_mask = np.ones((220, 220), dtype=np.uint8)
    after_mask = np.ones((220, 220), dtype=np.uint8)

    before_mask[100:110, 100:110] = 0
    after_mask[105:115, 105:115] = 0

    result = _run(
        tmp_path,
        before_stack=stack,
        before_mask=before_mask,
        before_transform=transform,
        after_stack=stack,
        after_mask=after_mask,
        after_transform=transform,
    )

    assert result.valid_pixel_count > 0
    assert result.changed_pixel_count == 0


def test_ndvi_known_values_are_correct(tmp_path: Path, monitor_bounds_utm: tuple[float, float, float, float]) -> None:
    min_x, _, _, max_y = monitor_bounds_utm
    transform = from_origin(min_x - 300.0, max_y + 300.0, 10.0, 10.0)

    before_stack = _create_stack(width=220, height=220, base_values=(0.10, 0.10, 0.20, 0.40))
    after_stack = _create_stack(width=220, height=220, base_values=(0.10, 0.10, 0.10, 0.50))
    mask = np.ones((220, 220), dtype=np.uint8)

    result = _run(
        tmp_path,
        before_stack=before_stack,
        before_mask=mask,
        before_transform=transform,
        after_stack=after_stack,
        after_mask=mask,
        after_transform=transform,
        threshold=0.1,
    )

    expected_delta_ndvi = abs((0.50 - 0.10) / (0.50 + 0.10) - (0.40 - 0.20) / (0.40 + 0.20))
    assert result.mean_abs_delta_ndvi == pytest.approx(expected_delta_ndvi, rel=1e-3)


def test_ndvi_zero_denominator_is_handled(tmp_path: Path, monitor_bounds_utm: tuple[float, float, float, float]) -> None:
    min_x, _, _, max_y = monitor_bounds_utm
    transform = from_origin(min_x - 300.0, max_y + 300.0, 10.0, 10.0)

    before_stack = _create_stack(width=220, height=220, base_values=(0.0, 0.0, 0.0, 0.0))
    after_stack = _create_stack(width=220, height=220, base_values=(0.0, 0.0, 0.0, 0.0))
    mask = np.ones((220, 220), dtype=np.uint8)

    result = _run(
        tmp_path,
        before_stack=before_stack,
        before_mask=mask,
        before_transform=transform,
        after_stack=after_stack,
        after_mask=mask,
        after_transform=transform,
    )

    assert np.isfinite(result.mean_abs_delta_ndvi)
    assert result.mean_abs_delta_ndvi == pytest.approx(0.0)


def test_identical_images_yield_near_zero_score(
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    min_x, _, _, max_y = monitor_bounds_utm
    transform = from_origin(min_x - 300.0, max_y + 300.0, 10.0, 10.0)

    stack = _create_stack(width=220, height=220, base_values=(0.15, 0.16, 0.17, 0.19))
    mask = np.ones((220, 220), dtype=np.uint8)

    result = _run(
        tmp_path,
        before_stack=stack,
        before_mask=mask,
        before_transform=transform,
        after_stack=stack.copy(),
        after_mask=mask.copy(),
        after_transform=transform,
    )

    assert result.mean_change_score == pytest.approx(0.0)
    assert result.max_change_score == pytest.approx(0.0)


def test_changed_pixels_yield_larger_score(tmp_path: Path, monitor_bounds_utm: tuple[float, float, float, float]) -> None:
    min_x, _, _, max_y = monitor_bounds_utm
    transform = from_origin(min_x - 300.0, max_y + 300.0, 10.0, 10.0)

    before_stack = _create_stack(width=220, height=220, base_values=(0.10, 0.11, 0.12, 0.20))
    after_stack = _create_stack(
        width=220,
        height=220,
        base_values=(0.10, 0.11, 0.12, 0.20),
        change_slice=(slice(90, 130), slice(90, 130)),
        change_delta=(0.10, 0.12, 0.08, 0.20),
    )
    mask = np.ones((220, 220), dtype=np.uint8)

    result = _run(
        tmp_path,
        before_stack=before_stack,
        before_mask=mask,
        before_transform=transform,
        after_stack=after_stack,
        after_mask=mask,
        after_transform=transform,
        threshold=0.15,
    )

    assert result.max_change_score > 0.5
    assert result.changed_pixel_count > 0


def test_threshold_controls_change_mask(tmp_path: Path, monitor_bounds_utm: tuple[float, float, float, float]) -> None:
    min_x, _, _, max_y = monitor_bounds_utm
    transform = from_origin(min_x - 300.0, max_y + 300.0, 10.0, 10.0)

    before_stack = _create_stack(width=220, height=220, base_values=(0.10, 0.11, 0.12, 0.20))
    after_stack = _create_stack(
        width=220,
        height=220,
        base_values=(0.10, 0.11, 0.12, 0.20),
        change_slice=(slice(95, 100), slice(95, 100)),
        change_delta=(0.08, 0.08, 0.08, 0.08),
    )
    mask = np.ones((220, 220), dtype=np.uint8)

    strict_result = _run(
        tmp_path / "strict",
        before_stack=before_stack,
        before_mask=mask,
        before_transform=transform,
        after_stack=after_stack,
        after_mask=mask,
        after_transform=transform,
        threshold=0.95,
    )

    loose_result = _run(
        tmp_path / "loose",
        before_stack=before_stack,
        before_mask=mask,
        before_transform=transform,
        after_stack=after_stack,
        after_mask=mask,
        after_transform=transform,
        threshold=0.05,
    )

    assert strict_result.changed_pixel_count <= loose_result.changed_pixel_count


def test_small_component_removed_and_large_component_retained() -> None:
    raw_change_mask = np.zeros((20, 20), dtype=bool)
    raw_change_mask[2, 2] = True
    raw_change_mask[10:14, 10:14] = True

    filtered_mask, removed_component_count, minimum_component_pixels = _apply_minimum_area_filter(
        raw_change_mask=raw_change_mask,
        minimum_change_area_m2=200.0,
        pixel_area_m2=100.0,
    )

    assert minimum_component_pixels == 2
    assert removed_component_count == 1
    assert int(np.count_nonzero(filtered_mask)) == 16
    assert filtered_mask[2, 2] == 0


def test_minimum_area_uses_transform_pixel_dimensions(
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    min_x, _, _, max_y = monitor_bounds_utm
    transform = from_origin(min_x - 600.0, max_y + 600.0, 20.0, 20.0)

    before_stack = _create_stack(width=120, height=120, base_values=(0.10, 0.11, 0.12, 0.20))
    after_stack = _create_stack(width=120, height=120, base_values=(0.10, 0.11, 0.12, 0.20))
    after_stack[:, 50:51, 50:51] += np.array([0.1, 0.1, 0.1, 0.1], dtype=np.float32).reshape(4, 1, 1)

    mask = np.ones((120, 120), dtype=np.uint8)

    result = _run(
        tmp_path,
        before_stack=before_stack,
        before_mask=mask,
        before_transform=transform,
        after_stack=after_stack,
        after_mask=mask,
        after_transform=transform,
        threshold=0.1,
        minimum_change_area_m2=401.0,
    )

    assert result.statistics["pixel_area_m2"] == pytest.approx(400.0)
    assert result.statistics["minimum_component_pixels"] == 2
    assert result.changed_pixel_count == 0


def test_output_rasters_and_preview_are_valid(
    tmp_path: Path,
    monitor_bounds_utm: tuple[float, float, float, float],
) -> None:
    min_x, _, _, max_y = monitor_bounds_utm
    transform = from_origin(min_x - 300.0, max_y + 300.0, 10.0, 10.0)

    before_stack = _create_stack(width=220, height=220, base_values=(0.10, 0.11, 0.12, 0.20))
    after_stack = _create_stack(
        width=220,
        height=220,
        base_values=(0.10, 0.11, 0.12, 0.20),
        change_slice=(slice(90, 130), slice(90, 130)),
        change_delta=(0.1, 0.1, 0.1, 0.1),
    )
    mask = np.ones((220, 220), dtype=np.uint8)

    result = _run(
        tmp_path,
        before_stack=before_stack,
        before_mask=mask,
        before_transform=transform,
        after_stack=after_stack,
        after_mask=mask,
        after_transform=transform,
        threshold=0.15,
    )

    with rasterio.open(result.change_score_path) as score:
        assert score.count == 1
        assert score.dtypes[0] == "float32"
        score_grid = (score.crs, score.transform, score.width, score.height)

    with rasterio.open(result.change_mask_path) as change_mask:
        assert change_mask.count == 1
        assert change_mask.dtypes[0] == "uint8"
        assert (change_mask.crs, change_mask.transform, change_mask.width, change_mask.height) == score_grid

    with rasterio.open(result.valid_comparison_mask_path) as valid_mask:
        assert valid_mask.count == 1
        assert valid_mask.dtypes[0] == "uint8"
        assert (valid_mask.crs, valid_mask.transform, valid_mask.width, valid_mask.height) == score_grid

    with Image.open(result.preview_path) as preview:
        assert max(preview.size) <= 1024





