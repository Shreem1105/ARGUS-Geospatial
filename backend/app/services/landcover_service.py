from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.context import LandCoverProvider, LandCoverProviderError, LandCoverSourceCandidate
from app.gis.conversion import wkb_to_geojson_geometry
from app.models import ChangeEvent, ChangeEventLandCoverExposure, Monitor, MonitorLandCoverSource
from app.schemas import LandCoverClassExposureRead, LandCoverExposureSummaryRead, LandCoverRefreshResponse

logger = logging.getLogger(__name__)


class LandCoverPersistenceError(Exception):
    pass


class LandCoverQueryError(Exception):
    pass


class LandCoverProviderRequestError(Exception):
    pass


class LandCoverConflictError(Exception):
    pass


def _get_monitor(db_session: Session, monitor_id: UUID) -> Monitor | None:
    try:
        return db_session.execute(select(Monitor).where(Monitor.id == monitor_id)).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise LandCoverQueryError("Failed to fetch monitor") from exc


def _get_event(db_session: Session, *, monitor_id: UUID, event_id: UUID) -> ChangeEvent | None:
    try:
        return db_session.execute(
            select(ChangeEvent).where(
                ChangeEvent.monitor_id == monitor_id,
                ChangeEvent.id == event_id,
            )
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise LandCoverQueryError("Failed to fetch change event") from exc


def _get_latest_land_cover_source(db_session: Session, *, monitor_id: UUID) -> MonitorLandCoverSource | None:
    try:
        return db_session.execute(
            select(MonitorLandCoverSource)
            .where(MonitorLandCoverSource.monitor_id == monitor_id)
            .order_by(MonitorLandCoverSource.fetched_at.desc(), MonitorLandCoverSource.id.desc())
            .limit(1)
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise LandCoverQueryError("Failed to fetch land-cover source") from exc


def _source_candidate_to_row(monitor_id: UUID, source: LandCoverSourceCandidate) -> dict[str, object]:
    return {
        "monitor_id": monitor_id,
        "provider": source.provider,
        "dataset": source.dataset,
        "dataset_version": source.dataset_version,
        "source_item_id": source.source_item_id,
        "asset_key": source.asset_key,
        "asset_href": source.asset_href,
        "asset_media_type": source.asset_media_type,
        "properties": source.properties,
        "source_updated_at": source.source_updated_at,
        "fetched_at": datetime.now(tz=timezone.utc),
        "updated_at": datetime.now(tz=timezone.utc),
    }


def refresh_monitor_land_cover_source(
    db_session: Session,
    *,
    monitor_id: UUID,
    provider: LandCoverProvider,
) -> LandCoverRefreshResponse | None:
    monitor = _get_monitor(db_session, monitor_id)
    if monitor is None:
        return None

    started_at = time.perf_counter()
    monitor_geometry = wkb_to_geojson_geometry(monitor.geometry)

    try:
        source_candidate = provider.fetch_land_cover_source(intersects_geometry=monitor_geometry)
    except LandCoverProviderError as exc:
        raise LandCoverProviderRequestError("Land-cover provider request failed") from exc

    try:
        existing = db_session.execute(
            select(MonitorLandCoverSource.id).where(
                MonitorLandCoverSource.monitor_id == monitor_id,
                MonitorLandCoverSource.provider == source_candidate.provider,
                MonitorLandCoverSource.dataset == source_candidate.dataset,
            )
        ).scalar_one_or_none()

        row = _source_candidate_to_row(monitor_id, source_candidate)
        statement = insert(MonitorLandCoverSource.__table__).values(row)
        statement = statement.on_conflict_do_update(
            index_elements=["monitor_id", "provider", "dataset"],
            set_={
                "dataset_version": statement.excluded.dataset_version,
                "source_item_id": statement.excluded.source_item_id,
                "asset_key": statement.excluded.asset_key,
                "asset_href": statement.excluded.asset_href,
                "asset_media_type": statement.excluded.asset_media_type,
                "properties": statement.excluded.properties,
                "source_updated_at": statement.excluded.source_updated_at,
                "fetched_at": statement.excluded.fetched_at,
                "updated_at": statement.excluded.updated_at,
            },
        )
        db_session.execute(statement)
        db_session.commit()
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise LandCoverPersistenceError("Failed to persist land-cover source") from exc

    elapsed_seconds = time.perf_counter() - started_at
    inserted_count = 1 if existing is None else 0
    updated_count = 0 if existing is None else 1

    logger.info(
        "Land-cover refresh monitor_id=%s dataset=%s version=%s source_item=%s inserted=%s updated=%s",
        monitor_id,
        source_candidate.dataset,
        source_candidate.dataset_version,
        source_candidate.source_item_id,
        inserted_count,
        updated_count,
    )

    return LandCoverRefreshResponse(
        monitor_id=monitor_id,
        provider=source_candidate.provider,
        dataset=source_candidate.dataset,
        dataset_version=source_candidate.dataset_version,
        source_item_id=source_candidate.source_item_id,
        attribution=provider.attribution,
        fetched=1,
        inserted=inserted_count,
        updated=updated_count,
        skipped=0,
        fetched_at=datetime.now(tz=timezone.utc),
        elapsed_seconds=round(elapsed_seconds, 6),
    )


def compute_change_event_land_cover_exposure(
    db_session: Session,
    *,
    monitor_id: UUID,
    event_id: UUID,
    provider: LandCoverProvider,
) -> LandCoverExposureSummaryRead | None:
    event = _get_event(db_session, monitor_id=monitor_id, event_id=event_id)
    if event is None:
        return None

    source = _get_latest_land_cover_source(db_session, monitor_id=monitor_id)
    if source is None:
        raise LandCoverConflictError("Land-cover dataset is not available. Refresh land-cover source first.")

    source_candidate = LandCoverSourceCandidate(
        provider=source.provider,
        dataset=source.dataset,
        dataset_version=source.dataset_version,
        source_item_id=source.source_item_id,
        asset_key=source.asset_key,
        asset_href=source.asset_href,
        asset_media_type=source.asset_media_type,
        properties=source.properties,
        source_updated_at=source.source_updated_at,
    )

    event_geometry = wkb_to_geojson_geometry(event.geometry)
    try:
        exposure_result = provider.compute_land_cover_exposure(
            event_geometry=event_geometry,
            event_area_m2=float(event.area_m2),
            source=source_candidate,
        )
    except LandCoverProviderError as exc:
        raise LandCoverProviderRequestError("Failed to compute land-cover exposure") from exc

    class_rows: list[dict[str, object]] = []
    class_summaries: list[LandCoverClassExposureRead] = []
    for item in exposure_result.classes:
        class_summaries.append(
            LandCoverClassExposureRead(
                class_code=item.class_code,
                class_name=item.class_name,
                area_m2=item.area_m2,
                fraction_of_event=item.fraction_of_event,
            )
        )
        class_rows.append(
            {
                "event_id": event_id,
                "provider": exposure_result.provider,
                "dataset": exposure_result.dataset,
                "dataset_version": exposure_result.dataset_version,
                "class_code": item.class_code,
                "class_name": item.class_name,
                "area_m2": item.area_m2,
                "fraction_of_event": item.fraction_of_event,
                "properties": item.properties,
            }
        )

    dominant_class = class_summaries[0].class_name if class_summaries else None
    dominant_fraction = class_summaries[0].fraction_of_event if class_summaries else 0.0

    summary = LandCoverExposureSummaryRead(
        provider=exposure_result.provider,
        dataset=exposure_result.dataset,
        dataset_version=exposure_result.dataset_version,
        dominant_class=dominant_class,
        dominant_fraction=dominant_fraction,
        nodata_fraction=exposure_result.nodata_fraction,
        classes=class_summaries,
    )

    event_properties = dict(event.properties or {})
    event_properties["land_cover_exposure"] = {
        "provider": summary.provider,
        "dataset": summary.dataset,
        "dataset_version": summary.dataset_version,
        "dominant_class": summary.dominant_class,
        "dominant_fraction": summary.dominant_fraction,
        "nodata_fraction": summary.nodata_fraction,
        "computed_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    try:
        db_session.execute(
            delete(ChangeEventLandCoverExposure).where(
                ChangeEventLandCoverExposure.event_id == event_id,
            )
        )
        if class_rows:
            db_session.execute(insert(ChangeEventLandCoverExposure.__table__).values(class_rows))

        event.properties = event_properties
        event.updated_at = func.now()
        db_session.commit()
    except SQLAlchemyError as exc:
        db_session.rollback()
        raise LandCoverPersistenceError("Failed to persist land-cover exposure") from exc

    return summary


def get_change_event_land_cover_exposure(
    db_session: Session,
    *,
    monitor_id: UUID,
    event_id: UUID,
) -> LandCoverExposureSummaryRead | None:
    event = _get_event(db_session, monitor_id=monitor_id, event_id=event_id)
    if event is None:
        return None

    try:
        rows = db_session.execute(
            select(ChangeEventLandCoverExposure)
            .where(ChangeEventLandCoverExposure.event_id == event_id)
            .order_by(
                ChangeEventLandCoverExposure.fraction_of_event.desc(),
                ChangeEventLandCoverExposure.class_code.asc(),
            )
        ).scalars().all()
    except SQLAlchemyError as exc:
        raise LandCoverQueryError("Failed to fetch land-cover exposure") from exc

    if not rows:
        snapshot = (event.properties or {}).get("land_cover_exposure")
        if not isinstance(snapshot, dict):
            return None

        return LandCoverExposureSummaryRead(
            provider=str(snapshot.get("provider", "unknown")),
            dataset=str(snapshot.get("dataset", "unknown")),
            dataset_version=str(snapshot.get("dataset_version", "unknown")),
            dominant_class=snapshot.get("dominant_class"),
            dominant_fraction=float(snapshot.get("dominant_fraction", 0.0)),
            nodata_fraction=float(snapshot.get("nodata_fraction", 0.0)),
            classes=[],
        )

    first = rows[0]
    classes = [
        LandCoverClassExposureRead(
            class_code=row.class_code,
            class_name=row.class_name,
            area_m2=row.area_m2,
            fraction_of_event=row.fraction_of_event,
        )
        for row in rows
    ]
    nodata_fraction = 0.0
    if isinstance(first.properties, dict):
        nodata_fraction = float(first.properties.get("nodata_fraction", 0.0))

    return LandCoverExposureSummaryRead(
        provider=first.provider,
        dataset=first.dataset,
        dataset_version=first.dataset_version,
        dominant_class=classes[0].class_name,
        dominant_fraction=classes[0].fraction_of_event,
        nodata_fraction=nodata_fraction,
        classes=classes,
    )

