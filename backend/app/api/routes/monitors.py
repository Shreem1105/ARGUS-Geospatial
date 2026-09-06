from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.context import ContextProvider, get_context_provider
from app.db.session import get_db_session
from app.satellite import SatelliteProvider, get_satellite_provider
from app.schemas import (
    AnalysisImpactComputeResponse,
    ContextFeatureRead,
    ContextFeatureType,
    ContextRefreshRequest,
    ContextRefreshResponse,
    ContextSummaryRead,
    EventImpactComputeResponse,
    EventImpactSummaryRead,
    MonitorImpactSummaryRead,
    ChangeAnalysisAutoRequest,
    ChangeAnalysisCreateRequest,
    ChangeAnalysisRead,
    ChangeEventGenerationResponse,
    ChangeEventIntersectsRequest,
    ChangeEventRead,
    ChangeEventSpatialSummary,
    ChangeEventStatus,
    ChangeEventStatusUpdate,
    MonitorCreate,
    MonitorIntersectionRequest,
    MonitorIntersectionResponse,
    MonitorEventSummary,
    MonitorRead,
    MonitorSpatialSummary,
    MonitorStatus,
    MonitorUpdate,
    ObservationSearchRequest,
    ObservationSearchResponse,
    PreparedObservationRead,
    PrepareObservationRequest,
    SatelliteObservationRead,
)
from app.services.context_service import (
    ContextPersistenceError,
    ContextProviderRequestError,
    ContextQueryError,
    ContextQueryTooLargeError,
    ContextValidationError,
    get_context_summary,
    list_context_features,
    refresh_monitor_context,
)
from app.services.change_analysis_service import (
    ChangeAnalysisConflictError,
    ChangeAnalysisPersistenceError,
    ChangeAnalysisProcessingError,
    ChangeAnalysisQueryError,
    ChangeAnalysisValidationError,
    create_change_analysis,
    create_change_analysis_auto,
    get_change_analysis,
    list_change_analyses,
)
from app.services.change_event_service import (
    ChangeEventConflictError,
    ChangeEventGenerationError,
    ChangeEventPersistenceError,
    ChangeEventQueryError,
    generate_change_events,
    get_change_event,
    get_change_event_spatial_summary,
    get_monitor_event_summary,
    intersects_change_events,
    list_change_events,
    list_change_events_for_analysis,
    update_change_event_status,
)
from app.services.impact_service import (
    DEFAULT_NEARBY_BUFFER_M,
    ImpactConflictError,
    ImpactPersistenceError,
    ImpactQueryError,
    compute_analysis_impacts,
    compute_change_event_impact,
    get_change_event_impact_summary,
    get_monitor_impact_summary,
)
from app.services.monitor_service import (
    MonitorPersistenceError,
    MonitorQueryError,
    check_monitor_intersection,
    create_monitor,
    delete_monitor,
    get_monitor,
    get_monitor_summary,
    list_monitors,
    update_monitor,
)
from app.services.observation_service import (
    ObservationPersistenceError,
    ObservationProviderRequestError,
    ObservationQueryError,
    get_observation,
    list_observations,
    search_and_store_observations,
)
from app.services.prepared_observation_service import (
    PreparedObservationPersistenceError,
    PreparedObservationProcessingError,
    PreparedObservationProviderError,
    PreparedObservationQueryError,
    get_prepared_observation,
    prepare_observation,
)

router = APIRouter(prefix="/monitors", tags=["monitors"])


def _normalize_monitor_type_filter(monitor_type: str | None) -> str | None:
    if monitor_type is None:
        return None

    normalized = monitor_type.strip().lower()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="monitor_type must not be blank",
        )

    return normalized


EVENT_SEVERITY_VALUES = {"low", "medium", "high", "critical"}
EVENT_STATUS_VALUES = {"new", "reviewed", "dismissed", "confirmed"}


def _normalize_event_severity_filter(severity: str | None) -> str | None:
    if severity is None:
        return None

    normalized = severity.strip().lower()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="severity must not be blank",
        )

    if normalized not in EVENT_SEVERITY_VALUES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="severity must be one of: low, medium, high, critical",
        )

    return normalized


def _normalize_event_status_filter(event_status: str | None) -> str | None:
    if event_status is None:
        return None

    normalized = event_status.strip().lower()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="status must not be blank",
        )

    if normalized not in EVENT_STATUS_VALUES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="status must be one of: new, reviewed, dismissed, confirmed",
        )

    return normalized


def _normalize_platform_filter(platform: str | None) -> str | None:
    if platform is None:
        return None

    normalized = platform.strip().lower()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="platform must not be blank",
        )

    return normalized


CONTEXT_FEATURE_TYPE_VALUES = {feature_type.value for feature_type in ContextFeatureType}


def _normalize_context_feature_type_filter(feature_type: str | None) -> str | None:
    if feature_type is None:
        return None

    normalized = feature_type.strip().lower()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="feature_type must not be blank",
        )

    if normalized not in CONTEXT_FEATURE_TYPE_VALUES:
        values = ", ".join(sorted(CONTEXT_FEATURE_TYPE_VALUES))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"feature_type must be one of: {values}",
        )

    return normalized


def _normalize_context_feature_subtype_filter(feature_subtype: str | None) -> str | None:
    if feature_subtype is None:
        return None

    normalized = feature_subtype.strip().lower()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="feature_subtype must not be blank",
        )

    return normalized


def _normalize_provider_filter(provider: str | None) -> str | None:
    if provider is None:
        return None

    normalized = provider.strip().lower()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="provider must not be blank",
        )

    return normalized


@router.post("", response_model=MonitorRead, status_code=status.HTTP_201_CREATED)
def create_monitor_route(
    monitor_in: MonitorCreate,
    db_session: Session = Depends(get_db_session),
) -> MonitorRead:
    try:
        return create_monitor(db_session, monitor_in)
    except MonitorPersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create monitor",
        ) from exc


@router.get("", response_model=list[MonitorRead], status_code=status.HTTP_200_OK)
def list_monitors_route(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    monitor_status: MonitorStatus | None = Query(default=None, alias="status"),
    monitor_type: str | None = Query(default=None),
    db_session: Session = Depends(get_db_session),
) -> list[MonitorRead]:
    normalized_monitor_type = _normalize_monitor_type_filter(monitor_type)

    try:
        return list_monitors(
            db_session,
            limit=limit,
            offset=offset,
            status=monitor_status,
            monitor_type=normalized_monitor_type,
        )
    except MonitorQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to fetch monitors",
        ) from exc


@router.get("/{monitor_id}", response_model=MonitorRead, status_code=status.HTTP_200_OK)
def get_monitor_route(
    monitor_id: UUID,
    db_session: Session = Depends(get_db_session),
) -> MonitorRead:
    try:
        monitor = get_monitor(db_session, monitor_id)
    except MonitorQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to fetch monitor",
        ) from exc

    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")

    return monitor


@router.patch("/{monitor_id}", response_model=MonitorRead, status_code=status.HTTP_200_OK)
def update_monitor_route(
    monitor_id: UUID,
    monitor_in: MonitorUpdate,
    db_session: Session = Depends(get_db_session),
) -> MonitorRead:
    try:
        monitor = update_monitor(db_session, monitor_id, monitor_in)
    except MonitorPersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to update monitor",
        ) from exc

    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")

    return monitor


@router.delete("/{monitor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_monitor_route(
    monitor_id: UUID,
    db_session: Session = Depends(get_db_session),
) -> Response:
    try:
        deleted = delete_monitor(db_session, monitor_id)
    except MonitorPersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to delete monitor",
        ) from exc

    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{monitor_id}/summary", response_model=MonitorSpatialSummary, status_code=status.HTTP_200_OK)
def get_monitor_summary_route(
    monitor_id: UUID,
    db_session: Session = Depends(get_db_session),
) -> MonitorSpatialSummary:
    try:
        summary = get_monitor_summary(db_session, monitor_id)
    except MonitorQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to fetch monitor summary",
        ) from exc

    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")

    return summary


@router.post(
    "/{monitor_id}/intersects",
    response_model=MonitorIntersectionResponse,
    status_code=status.HTTP_200_OK,
)
def check_monitor_intersection_route(
    monitor_id: UUID,
    request: MonitorIntersectionRequest,
    db_session: Session = Depends(get_db_session),
) -> MonitorIntersectionResponse:
    try:
        intersection = check_monitor_intersection(
            db_session,
            monitor_id,
            request.geometry.model_dump(),
        )
    except MonitorQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to evaluate monitor intersection",
        ) from exc

    if intersection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")

    return intersection


@router.post(
    "/{monitor_id}/context/refresh",
    response_model=ContextRefreshResponse,
    status_code=status.HTTP_200_OK,
)
def refresh_context_route(
    monitor_id: UUID,
    request: ContextRefreshRequest | None = None,
    db_session: Session = Depends(get_db_session),
    provider: ContextProvider = Depends(get_context_provider),
) -> ContextRefreshResponse:
    feature_types: list[str] | None = None
    if request is not None and request.feature_types is not None:
        feature_types = [item.value for item in request.feature_types]

    try:
        result = refresh_monitor_context(
            db_session,
            monitor_id=monitor_id,
            feature_types=feature_types,
            provider=provider,
        )
    except ContextValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ContextQueryTooLargeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ContextProviderRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Context provider unavailable",
        ) from exc
    except (ContextPersistenceError, ContextQueryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to refresh monitor context",
        ) from exc

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")

    return result


@router.get(
    "/{monitor_id}/context",
    response_model=list[ContextFeatureRead],
    status_code=status.HTTP_200_OK,
)
def list_context_route(
    monitor_id: UUID,
    feature_type: str | None = Query(default=None),
    feature_subtype: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db_session: Session = Depends(get_db_session),
) -> list[ContextFeatureRead]:
    normalized_feature_type = _normalize_context_feature_type_filter(feature_type)
    normalized_feature_subtype = _normalize_context_feature_subtype_filter(feature_subtype)
    normalized_provider = _normalize_provider_filter(provider)

    try:
        features = list_context_features(
            db_session,
            monitor_id=monitor_id,
            feature_type=normalized_feature_type,
            feature_subtype=normalized_feature_subtype,
            provider=normalized_provider,
            limit=limit,
            offset=offset,
        )
    except ContextQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to fetch context features",
        ) from exc

    if features is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")

    return features


@router.get(
    "/{monitor_id}/context/summary",
    response_model=ContextSummaryRead,
    status_code=status.HTTP_200_OK,
)
def get_context_summary_route(
    monitor_id: UUID,
    db_session: Session = Depends(get_db_session),
) -> ContextSummaryRead:
    try:
        summary = get_context_summary(db_session, monitor_id=monitor_id)
    except ContextQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to fetch context summary",
        ) from exc

    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")

    return summary


@router.post(
    "/{monitor_id}/observations/search",
    response_model=ObservationSearchResponse,
    status_code=status.HTTP_200_OK,
)
def search_observations_route(
    monitor_id: UUID,
    request: ObservationSearchRequest,
    db_session: Session = Depends(get_db_session),
    provider: SatelliteProvider = Depends(get_satellite_provider),
) -> ObservationSearchResponse:
    try:
        result = search_and_store_observations(
            db_session,
            monitor_id=monitor_id,
            request=request,
            provider=provider,
        )
    except ObservationProviderRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Satellite provider unavailable",
        ) from exc
    except (ObservationPersistenceError, ObservationQueryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to search observations",
        ) from exc

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")

    return result


@router.get(
    "/{monitor_id}/observations",
    response_model=list[SatelliteObservationRead],
    status_code=status.HTTP_200_OK,
)
def list_observations_route(
    monitor_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    max_cloud_cover: float | None = Query(default=None, ge=0, le=100),
    platform: str | None = Query(default=None),
    db_session: Session = Depends(get_db_session),
) -> list[SatelliteObservationRead]:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_date must be less than or equal to end_date",
        )

    normalized_platform = _normalize_platform_filter(platform)

    try:
        observations = list_observations(
            db_session,
            monitor_id=monitor_id,
            limit=limit,
            offset=offset,
            start_date=start_date,
            end_date=end_date,
            max_cloud_cover=max_cloud_cover,
            platform=normalized_platform,
        )
    except ObservationQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to fetch observations",
        ) from exc

    if observations is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")

    return observations


@router.get(
    "/{monitor_id}/observations/{observation_id}",
    response_model=SatelliteObservationRead,
    status_code=status.HTTP_200_OK,
)
def get_observation_route(
    monitor_id: UUID,
    observation_id: UUID,
    db_session: Session = Depends(get_db_session),
) -> SatelliteObservationRead:
    try:
        observation = get_observation(
            db_session,
            monitor_id=monitor_id,
            observation_id=observation_id,
        )
    except ObservationQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to fetch observation",
        ) from exc

    if observation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Observation not found")

    return observation


@router.post(
    "/{monitor_id}/observations/{observation_id}/prepare",
    response_model=PreparedObservationRead,
    status_code=status.HTTP_200_OK,
)
def prepare_observation_route(
    monitor_id: UUID,
    observation_id: UUID,
    request: PrepareObservationRequest,
    db_session: Session = Depends(get_db_session),
) -> PreparedObservationRead:
    try:
        prepared = prepare_observation(
            db_session,
            monitor_id=monitor_id,
            observation_id=observation_id,
            force_reprocess=request.force_reprocess,
        )
    except PreparedObservationProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Satellite asset provider unavailable",
        ) from exc
    except PreparedObservationProcessingError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to prepare observation raster",
        ) from exc
    except (PreparedObservationPersistenceError, PreparedObservationQueryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to prepare observation",
        ) from exc

    if prepared is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Observation not found")

    return prepared


@router.get(
    "/{monitor_id}/observations/{observation_id}/prepared",
    response_model=PreparedObservationRead,
    status_code=status.HTTP_200_OK,
)
def get_prepared_observation_route(
    monitor_id: UUID,
    observation_id: UUID,
    db_session: Session = Depends(get_db_session),
) -> PreparedObservationRead:
    try:
        prepared = get_prepared_observation(
            db_session,
            monitor_id=monitor_id,
            observation_id=observation_id,
        )
    except PreparedObservationQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to fetch prepared observation",
        ) from exc

    if prepared is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prepared observation not found")

    return prepared


@router.post(
    "/{monitor_id}/analyses",
    response_model=ChangeAnalysisRead,
    status_code=status.HTTP_201_CREATED,
)
def create_analysis_route(
    monitor_id: UUID,
    request: ChangeAnalysisCreateRequest,
    response: Response,
    db_session: Session = Depends(get_db_session),
) -> ChangeAnalysisRead:
    try:
        result = create_change_analysis(
            db_session,
            monitor_id=monitor_id,
            request=request,
        )
    except ChangeAnalysisValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ChangeAnalysisConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ChangeAnalysisProcessingError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to compute change analysis",
        ) from exc
    except (ChangeAnalysisPersistenceError, ChangeAnalysisQueryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create change analysis",
        ) from exc

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prepared observation not found")

    if result.reused:
        response.status_code = status.HTTP_200_OK

    return result.analysis


@router.post(
    "/{monitor_id}/analyses/auto",
    response_model=ChangeAnalysisRead,
    status_code=status.HTTP_201_CREATED,
)
def create_analysis_auto_route(
    monitor_id: UUID,
    request: ChangeAnalysisAutoRequest,
    response: Response,
    db_session: Session = Depends(get_db_session),
) -> ChangeAnalysisRead:
    try:
        result = create_change_analysis_auto(
            db_session,
            monitor_id=monitor_id,
            request=request,
        )
    except ChangeAnalysisValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ChangeAnalysisConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ChangeAnalysisProcessingError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to compute change analysis",
        ) from exc
    except (ChangeAnalysisPersistenceError, ChangeAnalysisQueryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create change analysis",
        ) from exc

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")

    if result.reused:
        response.status_code = status.HTTP_200_OK

    return result.analysis


@router.get(
    "/{monitor_id}/analyses",
    response_model=list[ChangeAnalysisRead],
    status_code=status.HTTP_200_OK,
)
def list_analyses_route(
    monitor_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db_session: Session = Depends(get_db_session),
) -> list[ChangeAnalysisRead]:
    try:
        analyses = list_change_analyses(
            db_session,
            monitor_id=monitor_id,
            limit=limit,
            offset=offset,
        )
    except ChangeAnalysisQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to fetch change analyses",
        ) from exc

    if analyses is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")

    return analyses


@router.get(
    "/{monitor_id}/analyses/{analysis_id}",
    response_model=ChangeAnalysisRead,
    status_code=status.HTTP_200_OK,
)
def get_analysis_route(
    monitor_id: UUID,
    analysis_id: UUID,
    db_session: Session = Depends(get_db_session),
) -> ChangeAnalysisRead:
    try:
        analysis = get_change_analysis(
            db_session,
            monitor_id=monitor_id,
            analysis_id=analysis_id,
        )
    except ChangeAnalysisQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to fetch change analysis",
        ) from exc

    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change analysis not found")

    return analysis


@router.post(
    "/{monitor_id}/analyses/{analysis_id}/events",
    response_model=ChangeEventGenerationResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_events_route(
    monitor_id: UUID,
    analysis_id: UUID,
    response: Response,
    db_session: Session = Depends(get_db_session),
) -> ChangeEventGenerationResponse:
    try:
        result = generate_change_events(
            db_session,
            monitor_id=monitor_id,
            analysis_id=analysis_id,
        )
    except ChangeEventConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ChangeEventGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to generate change events",
        ) from exc
    except (ChangeEventPersistenceError, ChangeEventQueryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to generate change events",
        ) from exc

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change analysis not found")

    if not result.generated:
        response.status_code = status.HTTP_200_OK

    return result.response


@router.get(
    "/{monitor_id}/analyses/{analysis_id}/events",
    response_model=list[ChangeEventRead],
    status_code=status.HTTP_200_OK,
)
def list_analysis_events_route(
    monitor_id: UUID,
    analysis_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db_session: Session = Depends(get_db_session),
) -> list[ChangeEventRead]:
    try:
        events = list_change_events_for_analysis(
            db_session,
            monitor_id=monitor_id,
            analysis_id=analysis_id,
            limit=limit,
            offset=offset,
        )
    except ChangeEventQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to fetch analysis change events",
        ) from exc

    if events is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change analysis not found")

    return events


@router.post(
    "/{monitor_id}/analyses/{analysis_id}/impact",
    response_model=AnalysisImpactComputeResponse,
    status_code=status.HTTP_200_OK,
)
def compute_analysis_impact_route(
    monitor_id: UUID,
    analysis_id: UUID,
    nearby_buffer_m: float = Query(default=DEFAULT_NEARBY_BUFFER_M, gt=0, le=5_000),
    db_session: Session = Depends(get_db_session),
) -> AnalysisImpactComputeResponse:
    try:
        result = compute_analysis_impacts(
            db_session,
            monitor_id=monitor_id,
            analysis_id=analysis_id,
            nearby_buffer_m=nearby_buffer_m,
        )
    except ImpactConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (ImpactPersistenceError, ImpactQueryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to compute analysis impacts",
        ) from exc

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change analysis not found")

    return result.response


@router.get(
    "/{monitor_id}/events/summary",
    response_model=MonitorEventSummary,
    status_code=status.HTTP_200_OK,
)
def get_monitor_event_summary_route(
    monitor_id: UUID,
    db_session: Session = Depends(get_db_session),
) -> MonitorEventSummary:
    try:
        summary = get_monitor_event_summary(db_session, monitor_id=monitor_id)
    except ChangeEventQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to fetch monitor event summary",
        ) from exc

    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")

    return summary


@router.get(
    "/{monitor_id}/impact/summary",
    response_model=MonitorImpactSummaryRead,
    status_code=status.HTTP_200_OK,
)
def get_monitor_impact_summary_route(
    monitor_id: UUID,
    db_session: Session = Depends(get_db_session),
) -> MonitorImpactSummaryRead:
    try:
        summary = get_monitor_impact_summary(db_session, monitor_id=monitor_id)
    except ImpactQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to fetch monitor impact summary",
        ) from exc

    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")

    return summary


@router.post(
    "/{monitor_id}/events/intersects",
    response_model=list[ChangeEventRead],
    status_code=status.HTTP_200_OK,
)
def intersects_events_route(
    monitor_id: UUID,
    request: ChangeEventIntersectsRequest,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db_session: Session = Depends(get_db_session),
) -> list[ChangeEventRead]:
    try:
        events = intersects_change_events(
            db_session,
            monitor_id=monitor_id,
            geometry=request.geometry.model_dump(),
            limit=limit,
            offset=offset,
        )
    except ChangeEventQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to evaluate event intersections",
        ) from exc

    if events is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")

    return events


@router.post(
    "/{monitor_id}/events/{event_id}/impact",
    response_model=EventImpactComputeResponse,
    status_code=status.HTTP_201_CREATED,
)
def compute_event_impact_route(
    monitor_id: UUID,
    event_id: UUID,
    response: Response,
    nearby_buffer_m: float = Query(default=DEFAULT_NEARBY_BUFFER_M, gt=0, le=5_000),
    db_session: Session = Depends(get_db_session),
) -> EventImpactComputeResponse:
    try:
        result = compute_change_event_impact(
            db_session,
            monitor_id=monitor_id,
            event_id=event_id,
            nearby_buffer_m=nearby_buffer_m,
        )
    except ImpactConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (ImpactPersistenceError, ImpactQueryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to compute change-event impact",
        ) from exc

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change event not found")

    if not result.computed:
        response.status_code = status.HTTP_200_OK

    return EventImpactComputeResponse(computed=result.computed, summary=result.summary)


@router.get(
    "/{monitor_id}/events/{event_id}/impact",
    response_model=EventImpactSummaryRead,
    status_code=status.HTTP_200_OK,
)
def get_event_impact_route(
    monitor_id: UUID,
    event_id: UUID,
    db_session: Session = Depends(get_db_session),
) -> EventImpactSummaryRead:
    try:
        summary = get_change_event_impact_summary(
            db_session,
            monitor_id=monitor_id,
            event_id=event_id,
        )
    except ImpactQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to fetch change-event impact",
        ) from exc

    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change-event impact not found")

    return summary


@router.get(
    "/{monitor_id}/events",
    response_model=list[ChangeEventRead],
    status_code=status.HTTP_200_OK,
)
def list_events_route(
    monitor_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    severity: str | None = Query(default=None),
    event_status: str | None = Query(default=None, alias="status"),
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    min_area_m2: float | None = Query(default=None, ge=0),
    analysis_id: UUID | None = Query(default=None),
    db_session: Session = Depends(get_db_session),
) -> list[ChangeEventRead]:
    normalized_severity = _normalize_event_severity_filter(severity)
    normalized_status = _normalize_event_status_filter(event_status)

    try:
        events = list_change_events(
            db_session,
            monitor_id=monitor_id,
            limit=limit,
            offset=offset,
            severity=normalized_severity,
            status=normalized_status,
            min_confidence=min_confidence,
            min_area_m2=min_area_m2,
            analysis_id=analysis_id,
        )
    except ChangeEventQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to fetch change events",
        ) from exc

    if events is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")

    return events


@router.get(
    "/{monitor_id}/events/{event_id}/summary",
    response_model=ChangeEventSpatialSummary,
    status_code=status.HTTP_200_OK,
)
def get_event_spatial_summary_route(
    monitor_id: UUID,
    event_id: UUID,
    db_session: Session = Depends(get_db_session),
) -> ChangeEventSpatialSummary:
    try:
        summary = get_change_event_spatial_summary(
            db_session,
            monitor_id=monitor_id,
            event_id=event_id,
        )
    except ChangeEventQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to fetch event spatial summary",
        ) from exc

    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change event not found")

    return summary


@router.get(
    "/{monitor_id}/events/{event_id}",
    response_model=ChangeEventRead,
    status_code=status.HTTP_200_OK,
)
def get_event_route(
    monitor_id: UUID,
    event_id: UUID,
    db_session: Session = Depends(get_db_session),
) -> ChangeEventRead:
    try:
        event = get_change_event(
            db_session,
            monitor_id=monitor_id,
            event_id=event_id,
        )
    except ChangeEventQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to fetch change event",
        ) from exc

    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change event not found")

    return event


@router.patch(
    "/{monitor_id}/events/{event_id}",
    response_model=ChangeEventRead,
    status_code=status.HTTP_200_OK,
)
def patch_event_status_route(
    monitor_id: UUID,
    event_id: UUID,
    request: ChangeEventStatusUpdate,
    db_session: Session = Depends(get_db_session),
) -> ChangeEventRead:
    try:
        event = update_change_event_status(
            db_session,
            monitor_id=monitor_id,
            event_id=event_id,
            status=request.status,
        )
    except ChangeEventPersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to update change event",
        ) from exc
    except ChangeEventQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to fetch change event",
        ) from exc

    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change event not found")

    return event
