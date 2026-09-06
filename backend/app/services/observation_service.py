from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Select, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.gis.conversion import geojson_geometry_to_wkb, wkb_to_geojson_geometry
from app.models import Monitor, SatelliteObservation
from app.satellite import SatelliteProvider, SatelliteProviderError
from app.schemas import (
    ObservationSearchRequest,
    ObservationSearchResponse,
    SatelliteObservationRead,
)

logger = logging.getLogger(__name__)


class ObservationPersistenceError(Exception):
    pass


class ObservationProviderRequestError(Exception):
    pass


class ObservationQueryError(Exception):
    pass


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("invalid acquired_at")

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)

    return parsed


def _normalize_assets(raw_assets: Any) -> dict[str, dict[str, Any]]:
    if raw_assets is None:
        return {}
    if not isinstance(raw_assets, dict):
        raise ValueError("invalid assets")

    normalized_assets: dict[str, dict[str, Any]] = {}
    for key, raw_asset in raw_assets.items():
        if not isinstance(key, str):
            continue
        if not isinstance(raw_asset, dict):
            continue

        href = raw_asset.get("href")
        if not isinstance(href, str) or not href.strip():
            continue

        normalized_asset: dict[str, Any] = {"href": href}

        media_type = raw_asset.get("media_type")
        if isinstance(media_type, str) and media_type:
            normalized_asset["media_type"] = media_type

        roles = raw_asset.get("roles")
        if isinstance(roles, list):
            normalized_asset["roles"] = [str(role) for role in roles]

        title = raw_asset.get("title")
        if isinstance(title, str) and title:
            normalized_asset["title"] = title

        raster_bands = raw_asset.get("raster_bands")
        if isinstance(raster_bands, list) and raster_bands:
            normalized_asset["raster_bands"] = raster_bands

        normalized_assets[key] = normalized_asset

    return normalized_assets


def _normalize_observation_payload(
    payload: dict[str, Any],
    *,
    default_provider: str,
    default_collection: str,
    max_cloud_cover: float | None,
) -> dict[str, Any]:
    item_id = payload.get("item_id")
    if not isinstance(item_id, str) or not item_id.strip():
        raise ValueError("missing item_id")

    geometry = payload.get("geometry")
    if not isinstance(geometry, dict) or "type" not in geometry:
        raise ValueError("missing geometry")

    acquired_at = _parse_datetime(payload.get("acquired_at"))

    raw_cloud_cover = payload.get("cloud_cover")
    cloud_cover: float | None
    if raw_cloud_cover is None:
        cloud_cover = None
    else:
        if isinstance(raw_cloud_cover, bool):
            raise ValueError("invalid cloud_cover")
        cloud_cover = float(raw_cloud_cover)
        if cloud_cover < 0 or cloud_cover > 100:
            raise ValueError("invalid cloud_cover")

    if max_cloud_cover is not None and (cloud_cover is None or cloud_cover > max_cloud_cover):
        raise ValueError("cloud_cover missing or exceeds max threshold")

    provider = payload.get("provider", default_provider)
    if not isinstance(provider, str) or not provider.strip():
        provider = default_provider

    collection = payload.get("collection", default_collection)
    if not isinstance(collection, str) or not collection.strip():
        collection = default_collection

    platform = payload.get("platform")
    if platform is not None and not isinstance(platform, str):
        platform = str(platform)
    if isinstance(platform, str):
        platform = platform.strip().lower() or None

    sensor = payload.get("sensor")
    if sensor is not None and not isinstance(sensor, str):
        sensor = str(sensor)
    if isinstance(sensor, str):
        sensor = sensor.strip() or None

    bbox = payload.get("bbox")
    if bbox is not None:
        if not isinstance(bbox, (list, tuple)):
            raise ValueError("invalid bbox")
        bbox = [float(value) for value in bbox]

    thumbnail_url = payload.get("thumbnail_url")
    if thumbnail_url is not None and not isinstance(thumbnail_url, str):
        thumbnail_url = str(thumbnail_url)

    metadata = payload.get("metadata")
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError("invalid metadata")

    assets = _normalize_assets(payload.get("assets"))

    return {
        "provider": provider,
        "collection": collection,
        "item_id": item_id.strip(),
        "platform": platform,
        "sensor": sensor,
        "acquired_at": acquired_at,
        "cloud_cover": cloud_cover,
        "geometry": geometry,
        "bbox": bbox,
        "thumbnail_url": thumbnail_url,
        "assets": assets,
        "metadata": metadata,
    }


def observation_to_read(observation: SatelliteObservation) -> SatelliteObservationRead:
    return SatelliteObservationRead(
        id=observation.id,
        monitor_id=observation.monitor_id,
        provider=observation.provider,
        collection=observation.collection,
        item_id=observation.item_id,
        platform=observation.platform,
        sensor=observation.sensor,
        acquired_at=observation.acquired_at,
        cloud_cover=observation.cloud_cover,
        geometry=wkb_to_geojson_geometry(observation.geometry),
        bbox=observation.bbox,
        thumbnail_url=observation.thumbnail_url,
        assets=observation.assets,
        metadata=observation.metadata_,
        created_at=observation.created_at,
    )


def _get_monitor(db_session: Session, monitor_id: UUID) -> Monitor | None:
    try:
        statement = select(Monitor).where(Monitor.id == monitor_id)
        return db_session.execute(statement).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise ObservationQueryError("Failed to fetch monitor") from exc


def _query_observations_by_keys(
    db_session: Session,
    *,
    monitor_id: UUID,
    keys: list[tuple[str, str, str]],
) -> list[SatelliteObservation]:
    if not keys:
        return []

    try:
        statement = (
            select(SatelliteObservation)
            .where(SatelliteObservation.monitor_id == monitor_id)
            .where(
                tuple_(
                    SatelliteObservation.provider,
                    SatelliteObservation.collection,
                    SatelliteObservation.item_id,
                ).in_(keys)
            )
            .order_by(SatelliteObservation.acquired_at.desc(), SatelliteObservation.id.desc())
        )
        return db_session.execute(statement).scalars().all()
    except SQLAlchemyError as exc:
        raise ObservationQueryError("Failed to fetch observations") from exc


def search_and_store_observations(
    db_session: Session,
    *,
    monitor_id: UUID,
    request: ObservationSearchRequest,
    provider: SatelliteProvider,
) -> ObservationSearchResponse | None:
    monitor = _get_monitor(db_session, monitor_id)
    if monitor is None:
        return None

    monitor_geometry = wkb_to_geojson_geometry(monitor.geometry)
    start_datetime, end_datetime = request.to_datetime_range()

    logger.info(
        "Searching observations for monitor_id=%s range=%s..%s max_cloud_cover=%s limit=%s",
        monitor_id,
        start_datetime.isoformat(),
        end_datetime.isoformat(),
        request.max_cloud_cover,
        request.limit,
    )

    try:
        search_result = provider.search_sentinel2_observations(
            intersects_geometry=monitor_geometry,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            max_cloud_cover=request.max_cloud_cover,
            limit=request.limit,
        )
    except SatelliteProviderError as exc:
        logger.error("Satellite provider error for monitor_id=%s: %s", monitor_id, exc)
        raise ObservationProviderRequestError("Satellite provider query failed") from exc

    normalized_observations: list[dict[str, Any]] = []
    skipped_count = search_result.skipped_count

    for item in search_result.observations:
        try:
            normalized_observations.append(
                _normalize_observation_payload(
                    item,
                    default_provider=search_result.provider,
                    default_collection=search_result.collection,
                    max_cloud_cover=request.max_cloud_cover,
                )
            )
        except (TypeError, ValueError) as exc:
            skipped_count += 1
            logger.warning("Skipping malformed normalized item for monitor_id=%s: %s", monitor_id, exc)

    keys: list[tuple[str, str, str]] = []
    rows_to_insert: list[dict[str, Any]] = []
    for item in normalized_observations:
        try:
            rows_to_insert.append(
                {
                    "id": uuid4(),
                    "monitor_id": monitor_id,
                    "provider": item["provider"],
                    "collection": item["collection"],
                    "item_id": item["item_id"],
                    "platform": item["platform"],
                    "sensor": item["sensor"],
                    "acquired_at": item["acquired_at"],
                    "cloud_cover": item["cloud_cover"],
                    "geometry": geojson_geometry_to_wkb(item["geometry"]),
                    "bbox": item["bbox"],
                    "thumbnail_url": item["thumbnail_url"],
                    "assets": item["assets"],
                    "metadata": item["metadata"],
                }
            )
            keys.append((item["provider"], item["collection"], item["item_id"]))
        except Exception as exc:
            skipped_count += 1
            logger.warning(
                "Skipping unpersistable observation item_id=%s for monitor_id=%s: %s",
                item.get("item_id"),
                monitor_id,
                exc,
            )

    keys = list(set(keys))

    inserted_count = 0
    if rows_to_insert:
        try:
            statement = insert(SatelliteObservation.__table__).values(rows_to_insert)
            statement = statement.on_conflict_do_nothing(
                index_elements=["monitor_id", "provider", "collection", "item_id"]
            ).returning(SatelliteObservation.__table__.c.id)
            inserted_ids = db_session.execute(statement).scalars().all()
            inserted_count = len(inserted_ids)
            db_session.commit()
        except SQLAlchemyError as exc:
            db_session.rollback()
            logger.error("Observation persistence failed for monitor_id=%s: %s", monitor_id, exc)
            raise ObservationPersistenceError("Failed to persist observations") from exc

    observations = _query_observations_by_keys(
        db_session,
        monitor_id=monitor_id,
        keys=keys,
    )

    duplicate_count = max(len(rows_to_insert) - inserted_count, 0)
    logger.info(
        "Observation search result monitor_id=%s stac_count=%s inserted=%s duplicates=%s skipped=%s",
        monitor_id,
        len(search_result.observations),
        inserted_count,
        duplicate_count,
        skipped_count,
    )

    return ObservationSearchResponse(
        monitor_id=monitor_id,
        provider=search_result.provider,
        collection=search_result.collection,
        count=len(observations),
        inserted_count=inserted_count,
        skipped_count=skipped_count,
        observations=[observation_to_read(observation) for observation in observations],
    )


def _date_to_start_datetime(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _date_to_end_datetime(value: date) -> datetime:
    return datetime.combine(value, time.max, tzinfo=timezone.utc)


def _apply_observation_filters(
    statement: Select[tuple[SatelliteObservation]],
    *,
    start_date: date | None,
    end_date: date | None,
    max_cloud_cover: float | None,
    platform: str | None,
) -> Select[tuple[SatelliteObservation]]:
    if start_date is not None:
        statement = statement.where(SatelliteObservation.acquired_at >= _date_to_start_datetime(start_date))
    if end_date is not None:
        statement = statement.where(SatelliteObservation.acquired_at <= _date_to_end_datetime(end_date))
    if max_cloud_cover is not None:
        statement = statement.where(SatelliteObservation.cloud_cover.is_not(None))
        statement = statement.where(SatelliteObservation.cloud_cover <= max_cloud_cover)
    if platform is not None:
        statement = statement.where(SatelliteObservation.platform == platform)
    return statement


def list_observations(
    db_session: Session,
    *,
    monitor_id: UUID,
    limit: int,
    offset: int,
    start_date: date | None,
    end_date: date | None,
    max_cloud_cover: float | None,
    platform: str | None,
) -> list[SatelliteObservationRead] | None:
    monitor = _get_monitor(db_session, monitor_id)
    if monitor is None:
        return None

    try:
        statement = select(SatelliteObservation).where(SatelliteObservation.monitor_id == monitor_id)
        statement = _apply_observation_filters(
            statement,
            start_date=start_date,
            end_date=end_date,
            max_cloud_cover=max_cloud_cover,
            platform=platform,
        )
        statement = statement.order_by(SatelliteObservation.acquired_at.desc(), SatelliteObservation.id.desc())
        statement = statement.limit(limit).offset(offset)
        observations = db_session.execute(statement).scalars().all()
    except SQLAlchemyError as exc:
        raise ObservationQueryError("Failed to fetch observations") from exc

    return [observation_to_read(observation) for observation in observations]


def get_observation(
    db_session: Session,
    *,
    monitor_id: UUID,
    observation_id: UUID,
) -> SatelliteObservationRead | None:
    try:
        statement = select(SatelliteObservation).where(
            SatelliteObservation.id == observation_id,
            SatelliteObservation.monitor_id == monitor_id,
        )
        observation = db_session.execute(statement).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise ObservationQueryError("Failed to fetch observation") from exc

    if observation is None:
        return None

    return observation_to_read(observation)

