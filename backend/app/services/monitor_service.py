from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.gis.conversion import geojson_polygon_to_wkb, wkb_to_geojson_polygon
from app.models import Monitor
from app.schemas import (
    MonitorCreate,
    MonitorIntersectionResponse,
    MonitorRead,
    MonitorSpatialSummary,
    MonitorStatus,
    MonitorUpdate,
)


class MonitorPersistenceError(Exception):
    pass


class MonitorQueryError(Exception):
    pass


SUMMARY_QUERY = text(
    """
    SELECT
        id AS monitor_id,
        name,
        status,
        GeometryType(geometry) AS geometry_type,
        ST_SRID(geometry) AS srid,
        ST_Area(geometry::geography) AS area_m2,
        ST_X(ST_Centroid(geometry)) AS centroid_lon,
        ST_Y(ST_Centroid(geometry)) AS centroid_lat,
        ST_XMin(geometry) AS min_lon,
        ST_YMin(geometry) AS min_lat,
        ST_XMax(geometry) AS max_lon,
        ST_YMax(geometry) AS max_lat
    FROM monitors
    WHERE id = :monitor_id
    """
)


INTERSECTION_QUERY = text(
    """
    WITH candidate AS (
        SELECT ST_SetSRID(ST_GeomFromGeoJSON(:input_geometry), 4326) AS geometry
    )
    SELECT
        m.id AS monitor_id,
        ST_Intersects(m.geometry, c.geometry) AS intersects,
        ST_Area(m.geometry::geography) AS monitor_area_m2,
        CASE
            WHEN ST_Intersects(m.geometry, c.geometry)
                THEN ST_Area(ST_Intersection(m.geometry, c.geometry)::geography)
            ELSE 0
        END AS intersection_area_m2
    FROM monitors AS m
    CROSS JOIN candidate AS c
    WHERE m.id = :monitor_id
    """
)


def _normalize_geometry_type(geometry_type: str) -> str:
    without_prefix = geometry_type.removeprefix("ST_")
    if without_prefix.isupper():
        return without_prefix.title()
    return without_prefix


def monitor_to_read(monitor: Monitor) -> MonitorRead:
    return MonitorRead(
        id=monitor.id,
        name=monitor.name,
        description=monitor.description,
        geometry=wkb_to_geojson_polygon(monitor.geometry),
        monitor_type=monitor.monitor_type,
        sensitivity=monitor.sensitivity,
        minimum_change_area_m2=monitor.minimum_change_area_m2,
        status=monitor.status,
        created_at=monitor.created_at,
        updated_at=monitor.updated_at,
        last_analyzed_at=monitor.last_analyzed_at,
    )


def create_monitor(
    db_session: Session,
    monitor_in: MonitorCreate,
    *,
    owner_user_id: UUID,
) -> MonitorRead:
    monitor = Monitor(
        owner_user_id=owner_user_id,
        name=monitor_in.name,
        description=monitor_in.description,
        geometry=geojson_polygon_to_wkb(monitor_in.geometry.model_dump()),
        monitor_type=monitor_in.monitor_type,
        sensitivity=monitor_in.sensitivity,
        minimum_change_area_m2=monitor_in.minimum_change_area_m2,
    )

    try:
        db_session.add(monitor)
        db_session.flush()
        db_session.commit()
        db_session.refresh(monitor)
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise MonitorPersistenceError("Failed to persist monitor") from exc

    return monitor_to_read(monitor)


def list_monitors(
    db_session: Session,
    *,
    limit: int,
    offset: int,
    status: MonitorStatus | None = None,
    monitor_type: str | None = None,
    owner_user_id: UUID | None = None,
    public_only: bool = False,
) -> list[MonitorRead]:
    try:
        statement = select(Monitor)
        if owner_user_id is not None:
            statement = statement.where(Monitor.owner_user_id == owner_user_id)
        if public_only:
            statement = statement.where(Monitor.is_public.is_(True))
        if status is not None:
            statement = statement.where(Monitor.status == status.value)
        if monitor_type is not None:
            statement = statement.where(Monitor.monitor_type == monitor_type)

        statement = statement.order_by(Monitor.created_at.desc(), Monitor.id.desc()).limit(limit).offset(offset)
        monitors = db_session.execute(statement).scalars().all()
    except SQLAlchemyError as exc:
        raise MonitorQueryError("Failed to fetch monitors") from exc

    return [monitor_to_read(monitor) for monitor in monitors]


def get_monitor(db_session: Session, monitor_id: UUID) -> MonitorRead | None:
    try:
        statement = select(Monitor).where(Monitor.id == monitor_id)
        monitor = db_session.execute(statement).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise MonitorQueryError("Failed to fetch monitor") from exc

    if monitor is None:
        return None

    return monitor_to_read(monitor)


def update_monitor(
    db_session: Session,
    monitor_id: UUID,
    monitor_in: MonitorUpdate,
) -> MonitorRead | None:
    try:
        statement = select(Monitor).where(Monitor.id == monitor_id)
        monitor = db_session.execute(statement).scalar_one_or_none()
        if monitor is None:
            return None

        update_data = monitor_in.model_dump(exclude_unset=True)

        if "geometry" in update_data:
            geometry = cast(dict[str, Any], update_data.pop("geometry"))
            monitor.geometry = geojson_polygon_to_wkb(geometry)

        for field_name, value in update_data.items():
            if field_name == "status" and isinstance(value, MonitorStatus):
                value = value.value
            setattr(monitor, field_name, value)

        monitor.updated_at = func.now()

        db_session.flush()
        db_session.commit()
        db_session.refresh(monitor)
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise MonitorPersistenceError("Failed to update monitor") from exc

    return monitor_to_read(monitor)


def delete_monitor(db_session: Session, monitor_id: UUID) -> bool:
    try:
        statement = select(Monitor).where(Monitor.id == monitor_id)
        monitor = db_session.execute(statement).scalar_one_or_none()
        if monitor is None:
            return False

        db_session.delete(monitor)
        db_session.flush()
        db_session.commit()
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise MonitorPersistenceError("Failed to delete monitor") from exc

    return True


def get_monitor_summary(db_session: Session, monitor_id: UUID) -> MonitorSpatialSummary | None:
    try:
        row = db_session.execute(
            SUMMARY_QUERY,
            {"monitor_id": monitor_id},
        ).mappings().one_or_none()
    except SQLAlchemyError as exc:
        raise MonitorQueryError("Failed to fetch monitor summary") from exc

    if row is None:
        return None

    area_m2 = float(row["area_m2"])
    return MonitorSpatialSummary(
        monitor_id=row["monitor_id"],
        name=row["name"],
        status=row["status"],
        geometry_type=_normalize_geometry_type(str(row["geometry_type"])),
        srid=int(row["srid"]),
        area_m2=area_m2,
        area_km2=area_m2 / 1_000_000,
        centroid={
            "type": "Point",
            "coordinates": (float(row["centroid_lon"]), float(row["centroid_lat"])),
        },
        bounding_box={
            "min_lon": float(row["min_lon"]),
            "min_lat": float(row["min_lat"]),
            "max_lon": float(row["max_lon"]),
            "max_lat": float(row["max_lat"]),
        },
    )


def check_monitor_intersection(
    db_session: Session,
    monitor_id: UUID,
    geometry: dict[str, Any],
) -> MonitorIntersectionResponse | None:
    input_geometry = json.dumps(geometry)

    try:
        row = db_session.execute(
            INTERSECTION_QUERY,
            {
                "monitor_id": monitor_id,
                "input_geometry": input_geometry,
            },
        ).mappings().one_or_none()
    except SQLAlchemyError as exc:
        raise MonitorQueryError("Failed to evaluate monitor intersection") from exc

    if row is None:
        return None

    intersects = bool(row["intersects"])
    monitor_area_m2 = float(row["monitor_area_m2"])
    intersection_area_m2 = float(row["intersection_area_m2"])

    if not intersects or monitor_area_m2 <= 0:
        intersection_area_m2 = 0.0
        intersection_percentage_of_monitor = 0.0
    else:
        intersection_percentage_of_monitor = (intersection_area_m2 / monitor_area_m2) * 100

    return MonitorIntersectionResponse(
        monitor_id=row["monitor_id"],
        intersects=intersects,
        intersection_area_m2=intersection_area_m2,
        intersection_percentage_of_monitor=intersection_percentage_of_monitor,
    )
