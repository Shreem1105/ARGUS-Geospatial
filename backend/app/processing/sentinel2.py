from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import planetary_computer
import rasterio
from PIL import Image
from rasterio._env import set_proj_data_search_path
from rasterio.enums import Resampling
from rasterio.errors import RasterioIOError, WindowError
from rasterio.features import geometry_mask, geometry_window
from rasterio.warp import reproject, transform_geom

logger = logging.getLogger(__name__)

DEFAULT_REFLECTANCE_SCALE = 1e-4
DEFAULT_REFLECTANCE_OFFSET = 0.0
REFLECTANCE_SCALE = DEFAULT_REFLECTANCE_SCALE
NODATA_VALUE = -9999.0
PREVIEW_MAX_DIMENSION = 1024
PROCESSING_VERSION = "sentinel2-preprocess-v1"

CONTINUOUS_BAND_KEYS = ["B02", "B03", "B04", "B08"]
SCL_KEY = "SCL"

CLOUD_SCL_CLASSES = {3, 8, 9, 10, 11}
INVALID_SCL_CLASSES = {0, 1, 255}

RASTERIO_PACKAGE_DIR = Path(rasterio.__file__).resolve().parent
RASTERIO_PROJ_DATA_DIR = RASTERIO_PACKAGE_DIR / "proj_data"
RASTERIO_GDAL_DATA_DIR = RASTERIO_PACKAGE_DIR / "gdal_data"

if RASTERIO_PROJ_DATA_DIR.exists():
    rasterio_proj_data_path = str(RASTERIO_PROJ_DATA_DIR)
    os.environ["PROJ_LIB"] = rasterio_proj_data_path
    os.environ["PROJ_DATA"] = rasterio_proj_data_path
    set_proj_data_search_path(rasterio_proj_data_path)

if RASTERIO_GDAL_DATA_DIR.exists():
    os.environ["GDAL_DATA"] = str(RASTERIO_GDAL_DATA_DIR)


class RasterAssetError(Exception):
    pass


class RasterPreparationError(Exception):
    pass


@dataclass(slots=True)
class ReflectanceScaling:
    scale: float
    offset: float
    source: str


@dataclass(slots=True)
class PreparedRasterResult:
    storage_path: Path
    valid_mask_path: Path
    preview_path: Path
    crs: str
    resolution_m: float
    width: int
    height: int
    band_names: list[str]
    cloud_fraction: float
    valid_fraction: float
    nodata_value: float
    processing_metadata: dict[str, Any]


@dataclass(slots=True)
class _ReprojectedBand:
    key: str
    array: np.ndarray
    source_crs: str
    source_resolution: tuple[float, float]
    source_width: int
    source_height: int
    source_scale: float | None
    source_offset: float | None


def _ensure_asset_payload(assets: dict[str, Any], key: str) -> dict[str, Any]:
    for candidate_key, payload in assets.items():
        if candidate_key.upper() == key:
            if isinstance(payload, dict):
                return payload
            raise RasterAssetError(f"Asset '{candidate_key}' payload is invalid")
    raise RasterAssetError(f"Required asset '{key}' missing")


def _resolve_required_asset_keys(assets: dict[str, Any]) -> dict[str, str]:
    resolved: dict[str, str] = {}

    for required_key in [*CONTINUOUS_BAND_KEYS, SCL_KEY]:
        for candidate_key in assets:
            if candidate_key.upper() == required_key:
                resolved[required_key] = candidate_key
                break
        else:
            raise RasterAssetError(f"Required asset '{required_key}' missing")

    return resolved


def _signed_asset_href(*, provider: str, href: str) -> str:
    if provider == "planetary_computer":
        try:
            return planetary_computer.sign_url(href)
        except Exception as exc:  # pragma: no cover - provider runtime behavior
            raise RasterAssetError("Failed to sign Planetary Computer asset URL") from exc

    return href


def _extract_resolution(dataset: rasterio.DatasetReader) -> tuple[float, float]:
    x_resolution, y_resolution = dataset.res
    return abs(float(x_resolution)), abs(float(y_resolution))


def _rasterio_env() -> rasterio.Env:
    env_kwargs: dict[str, Any] = {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    }
    if RASTERIO_PROJ_DATA_DIR.exists():
        rasterio_proj_data_path = str(RASTERIO_PROJ_DATA_DIR)
        env_kwargs["PROJ_DATA"] = rasterio_proj_data_path
        env_kwargs["PROJ_LIB"] = rasterio_proj_data_path
    if RASTERIO_GDAL_DATA_DIR.exists():
        env_kwargs["GDAL_DATA"] = str(RASTERIO_GDAL_DATA_DIR)
    return rasterio.Env(**env_kwargs)


def _first_numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _resolve_dataset_scale_offset(source: rasterio.DatasetReader) -> tuple[float | None, float | None]:
    scale: float | None = None
    offset: float | None = None

    if source.scales and len(source.scales) > 0:
        scale = _first_numeric(source.scales[0])
    if source.offsets and len(source.offsets) > 0:
        offset = _first_numeric(source.offsets[0])

    return scale, offset


def _resolve_stac_raster_scale_offset(asset_payload: dict[str, Any]) -> tuple[float | None, float | None]:
    raster_bands = asset_payload.get("raster_bands")
    if raster_bands is None:
        raster_bands = asset_payload.get("raster:bands")

    if isinstance(raster_bands, list) and raster_bands:
        first_band = raster_bands[0]
        if isinstance(first_band, dict):
            scale = _first_numeric(first_band.get("scale"))
            offset = _first_numeric(first_band.get("offset"))
            return scale, offset

    return None, None


def _normalize_scaling_value(*, scale: float, offset: float, asset_key: str) -> tuple[float, float]:
    if not np.isfinite(scale) or not np.isfinite(offset):
        raise RasterPreparationError(f"Invalid reflectance scaling for {asset_key}")

    if math.isclose(scale, 0.0, abs_tol=1e-12):
        raise RasterPreparationError(f"Resolved reflectance scale cannot be zero for {asset_key}")

    return float(scale), float(offset)


def resolve_reflectance_scaling(
    *,
    provider: str,
    collection: str | None,
    asset_key: str,
    asset_payload: dict[str, Any],
    dataset_scale: float | None,
    dataset_offset: float | None,
    observation_metadata: dict[str, Any] | None,
) -> ReflectanceScaling:
    if dataset_scale is not None or dataset_offset is not None:
        resolved_scale = 1.0 if dataset_scale is None else dataset_scale
        resolved_offset = 0.0 if dataset_offset is None else dataset_offset

        if not (
            math.isclose(resolved_scale, 1.0, rel_tol=0.0, abs_tol=1e-12)
            and math.isclose(resolved_offset, 0.0, rel_tol=0.0, abs_tol=1e-12)
        ):
            scale, offset = _normalize_scaling_value(
                scale=resolved_scale,
                offset=resolved_offset,
                asset_key=asset_key,
            )
            return ReflectanceScaling(scale=scale, offset=offset, source="rasterio_dataset_scale_offset")

    stac_scale, stac_offset = _resolve_stac_raster_scale_offset(asset_payload)
    if stac_scale is not None or stac_offset is not None:
        scale = DEFAULT_REFLECTANCE_SCALE if stac_scale is None else stac_scale
        offset = DEFAULT_REFLECTANCE_OFFSET if stac_offset is None else stac_offset
        scale, offset = _normalize_scaling_value(scale=scale, offset=offset, asset_key=asset_key)
        return ReflectanceScaling(scale=scale, offset=offset, source="stac_asset_raster_bands")

    collection_lower = (collection or "").strip().lower()
    processing_level = None
    if observation_metadata is not None:
        processing_level = observation_metadata.get("processing:level")

    if provider == "planetary_computer":
        if "sentinel-2" in collection_lower and "l2a" in collection_lower:
            return ReflectanceScaling(
                scale=DEFAULT_REFLECTANCE_SCALE,
                offset=DEFAULT_REFLECTANCE_OFFSET,
                source="provider_fallback_planetary_computer_sentinel2_l2a",
            )
        if isinstance(processing_level, str) and "l2a" in processing_level.lower():
            return ReflectanceScaling(
                scale=DEFAULT_REFLECTANCE_SCALE,
                offset=DEFAULT_REFLECTANCE_OFFSET,
                source="provider_metadata_fallback_processing_level_l2a",
            )

    logger.warning(
        "Using identity reflectance scaling fallback for asset_key=%s provider=%s collection=%s",
        asset_key,
        provider,
        collection,
    )

    return ReflectanceScaling(scale=1.0, offset=0.0, source="identity_fallback")


def apply_reflectance_scaling(
    raw_band: np.ndarray,
    *,
    scale: float,
    offset: float,
    valid_mask: np.ndarray,
) -> np.ndarray:
    scaled = np.where(np.isfinite(raw_band), raw_band * scale + offset, NODATA_VALUE).astype(np.float32)
    scaled[~valid_mask] = NODATA_VALUE
    return scaled


def compute_cloud_fraction(
    *,
    inside_aoi_mask: np.ndarray,
    scl_array: np.ndarray,
) -> tuple[float, int, int]:
    if inside_aoi_mask.shape != scl_array.shape:
        raise RasterPreparationError("SCL array shape does not match AOI mask shape")

    scl_cloud_mask = np.isin(scl_array, list(CLOUD_SCL_CLASSES))
    scl_invalid_mask = np.isin(scl_array, list(INVALID_SCL_CLASSES))

    usable_scl_mask = inside_aoi_mask & ~scl_invalid_mask
    usable_scl_pixels = int(np.count_nonzero(usable_scl_mask))
    if usable_scl_pixels == 0:
        raise RasterPreparationError("Monitor AOI contains zero usable SCL pixels")

    cloud_pixels = int(np.count_nonzero(usable_scl_mask & scl_cloud_mask))
    return cloud_pixels / usable_scl_pixels, cloud_pixels, usable_scl_pixels


def _read_reprojected_band(
    *,
    signed_href: str,
    monitor_geometry_wgs84: dict[str, Any],
    target_crs: rasterio.crs.CRS,
    target_transform: rasterio.Affine,
    target_width: int,
    target_height: int,
    resampling: Resampling,
    destination_dtype: np.dtype,
    destination_nodata: float | int,
) -> _ReprojectedBand:
    try:
        with rasterio.open(signed_href) as source:
            if source.crs is None:
                raise RasterPreparationError("Source asset missing CRS")

            source_geometry = transform_geom(
                "EPSG:4326",
                source.crs,
                monitor_geometry_wgs84,
            )

            try:
                source_window = geometry_window(source, [source_geometry])
            except WindowError as exc:
                raise RasterPreparationError("Monitor AOI does not intersect source asset") from exc

            source_window = source_window.round_offsets().round_lengths()
            source_transform = source.window_transform(source_window)

            source_array = source.read(1, window=source_window)
            source_nodata = source.nodata
            source_scale, source_offset = _resolve_dataset_scale_offset(source)

            destination = np.full(
                (target_height, target_width),
                destination_nodata,
                dtype=destination_dtype,
            )

            reproject(
                source=source_array,
                destination=destination,
                src_transform=source_transform,
                src_crs=source.crs,
                src_nodata=source_nodata,
                dst_transform=target_transform,
                dst_crs=target_crs,
                dst_nodata=destination_nodata,
                resampling=resampling,
            )

            return _ReprojectedBand(
                key=Path(source.name).name,
                array=destination,
                source_crs=source.crs.to_string(),
                source_resolution=_extract_resolution(source),
                source_width=int(source.width),
                source_height=int(source.height),
                source_scale=source_scale,
                source_offset=source_offset,
            )
    except RasterioIOError as exc:  # pragma: no cover - provider/network behavior
        raise RasterAssetError("Failed to open source raster asset") from exc


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


def resize_preview_image(image: Image.Image, max_dimension: int = PREVIEW_MAX_DIMENSION) -> Image.Image:
    width, height = image.size
    longest_side = max(width, height)
    if longest_side <= max_dimension:
        return image

    scale = max_dimension / float(longest_side)
    resized_width = max(1, int(round(width * scale)))
    resized_height = max(1, int(round(height * scale)))
    return image.resize((resized_width, resized_height), resample=Image.Resampling.LANCZOS)


def prepare_sentinel2_raster(
    *,
    monitor_geometry_wgs84: dict[str, Any],
    provider: str,
    collection: str | None,
    item_id: str,
    assets: dict[str, Any],
    target_directory: Path,
    observation_metadata: dict[str, Any] | None = None,
) -> PreparedRasterResult:
    with _rasterio_env():
        resolved_asset_keys = _resolve_required_asset_keys(assets)

        reference_asset_payload = _ensure_asset_payload(assets, "B04")
        reference_href = reference_asset_payload.get("href")
        if not isinstance(reference_href, str) or not reference_href:
            raise RasterAssetError("Reference band asset 'B04' is missing href")

        signed_reference_href = _signed_asset_href(provider=provider, href=reference_href)

        try:
            with rasterio.open(signed_reference_href) as reference:
                if reference.crs is None:
                    raise RasterPreparationError("Reference raster missing CRS")

                reference_geometry = transform_geom("EPSG:4326", reference.crs, monitor_geometry_wgs84)

                try:
                    reference_window = geometry_window(reference, [reference_geometry])
                except WindowError as exc:
                    raise RasterPreparationError("Monitor AOI does not intersect reference raster") from exc

                reference_window = reference_window.round_offsets().round_lengths()
                width = int(reference_window.width)
                height = int(reference_window.height)
                if width <= 0 or height <= 0:
                    raise RasterPreparationError("Reference AOI window has non-positive dimensions")

                target_transform = reference.window_transform(reference_window)
                target_crs = reference.crs
                target_resolution = _extract_resolution(reference)

                inside_aoi_mask = geometry_mask(
                    [reference_geometry],
                    out_shape=(height, width),
                    transform=target_transform,
                    invert=True,
                )
        except RasterioIOError as exc:  # pragma: no cover - provider/network behavior
            raise RasterAssetError("Failed to open reference raster asset") from exc

        total_aoi_pixels = int(np.count_nonzero(inside_aoi_mask))
        if total_aoi_pixels == 0:
            raise RasterPreparationError("Monitor AOI contains zero pixels on reference grid")

        continuous_bands: list[np.ndarray] = []
        source_asset_metadata: dict[str, Any] = {}
        reflectance_scalings: dict[str, dict[str, Any]] = {}

        for required_key in CONTINUOUS_BAND_KEYS:
            asset_payload = _ensure_asset_payload(assets, required_key)
            href = asset_payload.get("href")
            if not isinstance(href, str) or not href:
                raise RasterAssetError(f"Asset '{required_key}' missing href")

            signed_href = _signed_asset_href(provider=provider, href=href)
            reprojected = _read_reprojected_band(
                signed_href=signed_href,
                monitor_geometry_wgs84=monitor_geometry_wgs84,
                target_crs=target_crs,
                target_transform=target_transform,
                target_width=width,
                target_height=height,
                resampling=Resampling.bilinear,
                destination_dtype=np.float32,
                destination_nodata=np.nan,
            )

            scaling = resolve_reflectance_scaling(
                provider=provider,
                collection=collection,
                asset_key=required_key,
                asset_payload=asset_payload,
                dataset_scale=reprojected.source_scale,
                dataset_offset=reprojected.source_offset,
                observation_metadata=observation_metadata,
            )

            continuous_bands.append(reprojected.array.astype(np.float32))
            source_asset_metadata[required_key] = {
                "asset_key": resolved_asset_keys[required_key],
                "source_crs": reprojected.source_crs,
                "source_resolution": list(reprojected.source_resolution),
                "source_width": reprojected.source_width,
                "source_height": reprojected.source_height,
                "dataset_scale": reprojected.source_scale,
                "dataset_offset": reprojected.source_offset,
            }
            reflectance_scalings[required_key] = {
                "scale": scaling.scale,
                "offset": scaling.offset,
                "source": scaling.source,
            }

        scl_payload = _ensure_asset_payload(assets, SCL_KEY)
        scl_href = scl_payload.get("href")
        if not isinstance(scl_href, str) or not scl_href:
            raise RasterAssetError("Asset 'SCL' missing href")

        signed_scl_href = _signed_asset_href(provider=provider, href=scl_href)
        reprojected_scl = _read_reprojected_band(
            signed_href=signed_scl_href,
            monitor_geometry_wgs84=monitor_geometry_wgs84,
            target_crs=target_crs,
            target_transform=target_transform,
            target_width=width,
            target_height=height,
            resampling=Resampling.nearest,
            destination_dtype=np.uint16,
            destination_nodata=255,
        )

        source_asset_metadata[SCL_KEY] = {
            "asset_key": resolved_asset_keys[SCL_KEY],
            "source_crs": reprojected_scl.source_crs,
            "source_resolution": list(reprojected_scl.source_resolution),
            "source_width": reprojected_scl.source_width,
            "source_height": reprojected_scl.source_height,
        }

        band_valid_mask = np.logical_and.reduce([np.isfinite(band) for band in continuous_bands])
        scl_cloud_mask = np.isin(reprojected_scl.array, list(CLOUD_SCL_CLASSES))
        scl_invalid_mask = np.isin(reprojected_scl.array, list(INVALID_SCL_CLASSES))

        cloud_fraction, cloud_pixels, usable_scl_pixels = compute_cloud_fraction(
            inside_aoi_mask=inside_aoi_mask,
            scl_array=reprojected_scl.array,
        )

        valid_mask = inside_aoi_mask & ~scl_cloud_mask & ~scl_invalid_mask & band_valid_mask
        valid_pixels = int(np.count_nonzero(valid_mask))
        valid_fraction = valid_pixels / total_aoi_pixels

        reflectance_bands: list[np.ndarray] = []
        for band_name, band in zip(CONTINUOUS_BAND_KEYS, continuous_bands, strict=True):
            scaling = reflectance_scalings[band_name]
            scaled = apply_reflectance_scaling(
                band,
                scale=float(scaling["scale"]),
                offset=float(scaling["offset"]),
                valid_mask=valid_mask,
            )
            reflectance_bands.append(scaled)

        stack = np.stack(reflectance_bands, axis=0).astype(np.float32)
        valid_mask_uint8 = valid_mask.astype(np.uint8)
        preview_rgb = _compute_preview_rgb(stack=stack, valid_mask=valid_mask)

        target_directory.mkdir(parents=True, exist_ok=True)

        storage_path = target_directory / "multispectral.tif"
        valid_mask_path = target_directory / "valid_mask.tif"
        preview_path = target_directory / "preview.png"

        with rasterio.open(
            storage_path,
            "w",
            driver="GTiff",
            width=width,
            height=height,
            count=4,
            dtype="float32",
            crs=target_crs,
            transform=target_transform,
            nodata=NODATA_VALUE,
            compress="deflate",
        ) as destination:
            for index, band_name in enumerate(CONTINUOUS_BAND_KEYS, start=1):
                destination.write(stack[index - 1], indexes=index)
                destination.set_band_description(index, band_name)

        with rasterio.open(
            valid_mask_path,
            "w",
            driver="GTiff",
            width=width,
            height=height,
            count=1,
            dtype="uint8",
            crs=target_crs,
            transform=target_transform,
            nodata=0,
            compress="deflate",
        ) as mask_destination:
            mask_destination.write(valid_mask_uint8, indexes=1)
            mask_destination.set_band_description(1, "valid_mask")

        preview_image = Image.fromarray(preview_rgb, mode="RGB")
        preview_image = resize_preview_image(preview_image, max_dimension=PREVIEW_MAX_DIMENSION)
        preview_image.save(preview_path)

    logger.info(
        "Prepared raster item_id=%s width=%s height=%s cloud_fraction=%.4f valid_fraction=%.4f",
        item_id,
        width,
        height,
        cloud_fraction,
        valid_fraction,
    )

    return PreparedRasterResult(
        storage_path=storage_path,
        valid_mask_path=valid_mask_path,
        preview_path=preview_path,
        crs=target_crs.to_string(),
        resolution_m=float(target_resolution[0]),
        width=width,
        height=height,
        band_names=CONTINUOUS_BAND_KEYS.copy(),
        cloud_fraction=cloud_fraction,
        valid_fraction=valid_fraction,
        nodata_value=NODATA_VALUE,
        processing_metadata={
            "processing_version": PROCESSING_VERSION,
            "source_item_id": item_id,
            "source_assets": {
                key: {"href": _ensure_asset_payload(assets, key).get("href")}
                for key in [*CONTINUOUS_BAND_KEYS, SCL_KEY]
            },
            "resolved_asset_keys": resolved_asset_keys,
            "reference_band": "B04",
            "source_asset_metadata": source_asset_metadata,
            "target_crs": target_crs.to_string(),
            "target_resolution": [float(target_resolution[0]), float(target_resolution[1])],
            "target_width": width,
            "target_height": height,
            "resampling": {
                "continuous": "bilinear",
                "scl": "nearest",
            },
            "excluded_scl_classes": sorted(list(INVALID_SCL_CLASSES | CLOUD_SCL_CLASSES)),
            "cloud_scl_classes": sorted(list(CLOUD_SCL_CLASSES)),
            "cloud_fraction_definition": "cloud_pixels / usable_scl_pixels_within_aoi",
            "valid_fraction_definition": "valid_pixels / total_aoi_pixels",
            "cloud_pixels": cloud_pixels,
            "usable_scl_pixels": usable_scl_pixels,
            "valid_pixels": valid_pixels,
            "total_aoi_pixels": total_aoi_pixels,
            "reflectance_formula": "reflectance = raw * scale + offset",
            "reflectance_scaling": reflectance_scalings,
            "nodata_value": NODATA_VALUE,
            "preview_max_dimension": PREVIEW_MAX_DIMENSION,
        },
    )

