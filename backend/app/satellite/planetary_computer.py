from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pystac import Asset, Item
from pystac_client import Client

from app.satellite.base import SatelliteProviderError, SatelliteSearchResult

logger = logging.getLogger(__name__)

PLANETARY_COMPUTER_STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
PLANETARY_COMPUTER_PROVIDER = "planetary_computer"
PREFERRED_SENTINEL2_COLLECTION = "sentinel-2-l2a"

SELECTED_METADATA_KEYS = {
    "constellation",
    "platform",
    "instruments",
    "processing:level",
    "s2:processing_baseline",
    "s2:mgrs_tile",
    "grid:code",
    "mgrs:tile",
    "proj:epsg",
    "gsd",
}


class PlanetaryComputerProvider:
    provider_name = PLANETARY_COMPUTER_PROVIDER

    def __init__(self, catalog_url: str = PLANETARY_COMPUTER_STAC_URL) -> None:
        self.catalog_url = catalog_url

    def _open_client(self) -> Client:
        try:
            return Client.open(self.catalog_url)
        except Exception as exc:  # pragma: no cover - network/provider runtime behavior
            raise SatelliteProviderError("Failed to connect to satellite provider") from exc

    def _resolve_sentinel2_collection(self, client: Client) -> str:
        try:
            client.get_collection(PREFERRED_SENTINEL2_COLLECTION)
            return PREFERRED_SENTINEL2_COLLECTION
        except Exception:
            pass

        try:
            for collection in client.get_collections():
                collection_id = collection.id.lower()
                if "sentinel-2" in collection_id and "l2a" in collection_id:
                    return collection.id
        except Exception as exc:  # pragma: no cover - network/provider runtime behavior
            raise SatelliteProviderError("Failed to resolve Sentinel-2 collection") from exc

        raise SatelliteProviderError("Sentinel-2 L2A collection not available from provider")

    def search_sentinel2_observations(
        self,
        *,
        intersects_geometry: dict[str, Any],
        start_datetime: datetime,
        end_datetime: datetime,
        max_cloud_cover: float | None,
        limit: int,
    ) -> SatelliteSearchResult:
        client = self._open_client()
        collection = self._resolve_sentinel2_collection(client)

        query: dict[str, Any] = {}
        if max_cloud_cover is not None:
            query["eo:cloud_cover"] = {"lte": max_cloud_cover}

        datetime_range = (
            f"{start_datetime.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
            f"/{end_datetime.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )

        try:
            search = client.search(
                collections=[collection],
                intersects=intersects_geometry,
                datetime=datetime_range,
                query=query or None,
                max_items=limit,
            )
            items = list(search.items())
        except Exception as exc:  # pragma: no cover - network/provider runtime behavior
            raise SatelliteProviderError("Satellite provider query failed") from exc

        normalized: list[dict[str, Any]] = []
        skipped_count = 0

        for item in items:
            try:
                normalized.append(
                    self._normalize_item(
                        item=item,
                        collection=collection,
                        max_cloud_cover=max_cloud_cover,
                    )
                )
            except ValueError as exc:
                skipped_count += 1
                logger.warning("Skipping malformed STAC item '%s': %s", getattr(item, "id", "unknown"), exc)

        return SatelliteSearchResult(
            provider=self.provider_name,
            collection=collection,
            observations=normalized,
            skipped_count=skipped_count,
        )

    def _normalize_item(
        self,
        *,
        item: Item,
        collection: str,
        max_cloud_cover: float | None,
    ) -> dict[str, Any]:
        properties = item.properties or {}

        acquired_at = item.datetime
        if acquired_at is None:
            raw_datetime = properties.get("datetime")
            if not isinstance(raw_datetime, str):
                raise ValueError("missing datetime")
            acquired_at = datetime.fromisoformat(raw_datetime.replace("Z", "+00:00"))

        if acquired_at.tzinfo is None:
            acquired_at = acquired_at.replace(tzinfo=timezone.utc)
        else:
            acquired_at = acquired_at.astimezone(timezone.utc)

        if not isinstance(item.geometry, dict) or "type" not in item.geometry:
            raise ValueError("missing geometry")

        cloud_cover = self._extract_cloud_cover(properties)
        if max_cloud_cover is not None:
            if cloud_cover is None:
                raise ValueError("missing cloud cover")
            if cloud_cover > max_cloud_cover:
                raise ValueError("cloud cover exceeds threshold")

        normalized_assets, thumbnail_url = self._normalize_assets(item.assets)

        return {
            "provider": self.provider_name,
            "collection": item.collection_id or collection,
            "item_id": item.id,
            "platform": self._normalize_str(properties.get("platform")),
            "sensor": self._extract_sensor(properties),
            "acquired_at": acquired_at,
            "cloud_cover": cloud_cover,
            "geometry": item.geometry,
            "bbox": item.bbox,
            "thumbnail_url": thumbnail_url,
            "assets": normalized_assets,
            "metadata": self._extract_metadata(properties),
        }

    @staticmethod
    def _normalize_str(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, list):
            if not value:
                return None
            value = value[0]
        if not isinstance(value, str):
            value = str(value)
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _extract_cloud_cover(properties: dict[str, Any]) -> float | None:
        raw_cloud_cover = properties.get("eo:cloud_cover")
        if raw_cloud_cover is None:
            return None

        if isinstance(raw_cloud_cover, bool):
            raise ValueError("invalid cloud cover value")

        try:
            cloud_cover = float(raw_cloud_cover)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid cloud cover value") from exc

        if cloud_cover < 0 or cloud_cover > 100:
            raise ValueError("cloud cover out of range")

        return cloud_cover

    def _extract_sensor(self, properties: dict[str, Any]) -> str | None:
        instruments = properties.get("instruments")
        if isinstance(instruments, list) and instruments:
            return self._normalize_str(instruments[0])
        return self._normalize_str(properties.get("sensor"))

    def _normalize_assets(self, assets: dict[str, Asset]) -> tuple[dict[str, dict[str, Any]], str | None]:
        normalized_assets: dict[str, dict[str, Any]] = {}
        thumbnail_url: str | None = None

        for key, asset in assets.items():
            if not asset.href:
                continue

            asset_payload: dict[str, Any] = {
                "href": asset.href,
                "media_type": asset.media_type,
                "roles": asset.roles,
                "title": asset.title,
            }

            raster_bands = asset.extra_fields.get("raster:bands") if isinstance(asset.extra_fields, dict) else None
            if isinstance(raster_bands, list) and raster_bands:
                asset_payload["raster_bands"] = raster_bands

            normalized_assets[key] = {
                field_name: field_value
                for field_name, field_value in asset_payload.items()
                if field_value is not None
            }

            if thumbnail_url is None and self._is_thumbnail_asset(key, asset):
                thumbnail_url = asset.href

        return normalized_assets, thumbnail_url

    @staticmethod
    def _is_thumbnail_asset(key: str, asset: Asset) -> bool:
        key_lower = key.lower()
        roles = asset.roles or []
        roles_lower = {role.lower() for role in roles}

        if "thumbnail" in roles_lower or "overview" in roles_lower:
            return True

        return key_lower in {"thumbnail", "preview", "rendered_preview", "overview"}

    @staticmethod
    def _extract_metadata(properties: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in properties.items()
            if key in SELECTED_METADATA_KEYS and value is not None
        }
