from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import numpy as np
import planetary_computer
import rasterio
from rasterio.errors import RasterioError
from rasterio.mask import mask
from rasterio.warp import transform_geom
from pystac import Item
from pystac_client import Client

logger = logging.getLogger(__name__)

LAND_COVER_PROVIDER_NAME = "planetary_computer"
LAND_COVER_ATTRIBUTION = "Contains modified Copernicus Sentinel data (2021+)"
PLANETARY_COMPUTER_STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"

WORLD_COVER_CLASS_MAP: dict[int, str] = {
    10: "tree_cover",
    20: "shrubland",
    30: "grassland",
    40: "cropland",
    50: "built_up",
    60: "bare_sparse_vegetation",
    70: "snow_and_ice",
    80: "permanent_water_bodies",
    90: "herbaceous_wetland",
    95: "mangroves",
    100: "moss_and_lichen",
}


class LandCoverProviderError(Exception):
    pass


@dataclass(slots=True)
class LandCoverSourceCandidate:
    provider: str
    dataset: str
    dataset_version: str
    source_item_id: str
    asset_key: str
    asset_href: str
    asset_media_type: str | None
    properties: dict[str, Any]
    source_updated_at: datetime | None


@dataclass(slots=True)
class LandCoverClassBreakdown:
    class_code: int
    class_name: str
    area_m2: float
    fraction_of_event: float
    properties: dict[str, Any]


@dataclass(slots=True)
class LandCoverExposureResult:
    provider: str
    dataset: str
    dataset_version: str
    classes: list[LandCoverClassBreakdown]
    nodata_fraction: float
    total_pixels: int
    valid_pixels: int


class LandCoverProvider(Protocol):
    provider_name: str
    attribution: str

    def fetch_land_cover_source(
        self,
        *,
        intersects_geometry: dict[str, Any],
    ) -> LandCoverSourceCandidate: ...

    def compute_land_cover_exposure(
        self,
        *,
        event_geometry: dict[str, Any],
        event_area_m2: float,
        source: LandCoverSourceCandidate,
    ) -> LandCoverExposureResult: ...


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    normalized = value.strip()
    return normalized or None


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class PlanetaryComputerLandCoverProvider:
    provider_name = LAND_COVER_PROVIDER_NAME
    attribution = LAND_COVER_ATTRIBUTION
    preferred_collection_ids: tuple[str, ...] = ("esa-worldcover", "esa-worldcover-10m")

    def __init__(
        self,
        *,
        catalog_url: str = PLANETARY_COMPUTER_STAC_URL,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.catalog_url = catalog_url
        self.timeout_seconds = timeout_seconds

    def _open_client(self) -> Client:
        try:
            return Client.open(self.catalog_url)
        except Exception as exc:  # pragma: no cover - network/runtime behavior
            raise LandCoverProviderError("Failed to connect to land-cover provider") from exc

    def _resolve_collection_id(self, client: Client) -> str:
        for collection_id in self.preferred_collection_ids:
            try:
                client.get_collection(collection_id)
                return collection_id
            except Exception:
                continue

        try:
            for collection in client.get_collections():
                if "worldcover" in collection.id.lower():
                    return collection.id
        except Exception as exc:  # pragma: no cover - network/runtime behavior
            raise LandCoverProviderError("Failed to resolve land-cover collection") from exc

        raise LandCoverProviderError("No supported land-cover collection found")

    @staticmethod
    def _item_timestamp(item: Item) -> datetime | None:
        item_datetime = item.datetime
        if item_datetime is not None:
            if item_datetime.tzinfo is None:
                return item_datetime.replace(tzinfo=timezone.utc)
            return item_datetime.astimezone(timezone.utc)

        properties = item.properties or {}
        raw_datetime = properties.get("datetime") or properties.get("start_datetime")
        if not isinstance(raw_datetime, str):
            return None
        try:
            parsed = datetime.fromisoformat(raw_datetime.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _extract_dataset_version(item: Item) -> str:
        props = item.properties or {}
        for key in (
            "version",
            "esa_worldcover:product_version",
            "processing:software",
            "processing:level",
        ):
            value = _normalize_text(props.get(key))
            if value:
                return value

        timestamp = PlanetaryComputerLandCoverProvider._item_timestamp(item)
        if timestamp is not None:
            return str(timestamp.year)

        return "unknown"

    @staticmethod
    def _choose_asset(item: Item) -> tuple[str, Any]:
        preferred_keys = ("map", "classification", "landcover", "data")

        for key in preferred_keys:
            asset = item.assets.get(key)
            if asset and asset.href:
                return key, asset

        for key, asset in item.assets.items():
            media_type = (asset.media_type or "").lower()
            if asset.href and ("tiff" in media_type or key.lower().endswith(".tif")):
                return key, asset

        raise LandCoverProviderError("No usable land-cover raster asset found in source item")

    def fetch_land_cover_source(
        self,
        *,
        intersects_geometry: dict[str, Any],
    ) -> LandCoverSourceCandidate:
        client = self._open_client()
        collection_id = self._resolve_collection_id(client)

        try:
            search = client.search(
                collections=[collection_id],
                intersects=intersects_geometry,
                max_items=10,
            )
            items = list(search.items())
        except Exception as exc:  # pragma: no cover - network/runtime behavior
            raise LandCoverProviderError("Land-cover provider query failed") from exc

        if not items:
            raise LandCoverProviderError("No land-cover source item found for monitor geometry")

        selected_item = sorted(
            items,
            key=lambda item: self._item_timestamp(item) or datetime(1970, 1, 1, tzinfo=timezone.utc),
            reverse=True,
        )[0]
        asset_key, asset = self._choose_asset(selected_item)

        if not asset.href:
            raise LandCoverProviderError("Land-cover source asset is missing href")

        source_timestamp = self._item_timestamp(selected_item)
        dataset_version = self._extract_dataset_version(selected_item)

        properties = {
            "collection": collection_id,
            "bbox": selected_item.bbox,
            "title": _normalize_text(selected_item.properties.get("title") if selected_item.properties else None),
            "license": _normalize_text(selected_item.properties.get("license") if selected_item.properties else None),
            "provider_attribution": self.attribution,
        }

        logger.info(
            "Resolved land-cover source collection=%s item_id=%s asset_key=%s dataset_version=%s",
            collection_id,
            selected_item.id,
            asset_key,
            dataset_version,
        )

        return LandCoverSourceCandidate(
            provider=self.provider_name,
            dataset=collection_id,
            dataset_version=dataset_version,
            source_item_id=selected_item.id,
            asset_key=asset_key,
            asset_href=asset.href,
            asset_media_type=asset.media_type,
            properties={key: value for key, value in properties.items() if value is not None},
            source_updated_at=source_timestamp,
        )

    def compute_land_cover_exposure(
        self,
        *,
        event_geometry: dict[str, Any],
        event_area_m2: float,
        source: LandCoverSourceCandidate,
    ) -> LandCoverExposureResult:
        signed_href = planetary_computer.sign_url(source.asset_href)

        try:
            with rasterio.open(signed_href) as dataset:
                source_crs = dataset.crs
                if source_crs is None:
                    raise LandCoverProviderError("Land-cover raster source is missing CRS")

                event_geometry_projected = transform_geom("EPSG:4326", source_crs, event_geometry)
                data, _ = mask(dataset, [event_geometry_projected], crop=True, filled=False)
                band = np.ma.MaskedArray(data[0], mask=data.mask[0])

                inside_event_mask = ~band.mask
                total_pixels = int(np.count_nonzero(inside_event_mask))
                if total_pixels == 0:
                    return LandCoverExposureResult(
                        provider=source.provider,
                        dataset=source.dataset,
                        dataset_version=source.dataset_version,
                        classes=[],
                        nodata_fraction=1.0,
                        total_pixels=0,
                        valid_pixels=0,
                    )

                valid_mask = inside_event_mask.copy()
                nodata_value = dataset.nodata
                if nodata_value is not None:
                    valid_mask &= band.data != nodata_value

                values = band.data[valid_mask]
                valid_pixels = int(values.size)

                nodata_pixels = total_pixels - valid_pixels
                nodata_fraction = float(nodata_pixels / total_pixels) if total_pixels > 0 else 1.0

                classes: list[LandCoverClassBreakdown] = []
                if valid_pixels > 0:
                    unique_values, counts = np.unique(values.astype(np.int64), return_counts=True)
                    for value, count in zip(unique_values, counts, strict=True):
                        class_code = int(value)
                        class_name = WORLD_COVER_CLASS_MAP.get(class_code)
                        if class_name is None:
                            continue

                        fraction_of_event = float(count / total_pixels)
                        area_m2 = float(event_area_m2 * fraction_of_event)
                        classes.append(
                            LandCoverClassBreakdown(
                                class_code=class_code,
                                class_name=class_name,
                                area_m2=area_m2,
                                fraction_of_event=fraction_of_event,
                                properties={
                                    "pixel_count": int(count),
                                    "total_event_pixels": total_pixels,
                                    "valid_event_pixels": valid_pixels,
                                    "nodata_fraction": nodata_fraction,
                                },
                            )
                        )

                classes.sort(key=lambda item: item.fraction_of_event, reverse=True)
                return LandCoverExposureResult(
                    provider=source.provider,
                    dataset=source.dataset,
                    dataset_version=source.dataset_version,
                    classes=classes,
                    nodata_fraction=nodata_fraction,
                    total_pixels=total_pixels,
                    valid_pixels=valid_pixels,
                )
        except LandCoverProviderError:
            raise
        except RasterioError as exc:  # pragma: no cover - runtime file/provider behavior
            raise LandCoverProviderError("Failed to read land-cover raster source") from exc
        except Exception as exc:  # pragma: no cover - runtime behavior
            raise LandCoverProviderError("Failed to compute land-cover exposure") from exc

