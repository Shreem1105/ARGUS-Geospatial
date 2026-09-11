import { apiDelete, apiGet, apiPatch, apiPost } from "@/api/client";
import type {
  AnalysisSemanticComputeResponse,
  AnalysisJob,
  ChangeAnalysis,
  ChangeEvent,
  ChangeEventSemanticAnalysis,
  ContextFeature,
  ContextSummary,
  EventExposureSummary,
  EventImpactSummary,
  EventIntelligence,
  EventSemanticComputeResponse,
  Monitor,
  MonitorDatasetEntry,
  MonitorEventSummary,
  MonitorExposureSummary,
  MonitorImpactSummary,
  MonitorRun,
  MonitorSchedule,
  MonitorSpatialSummary,
  PreparedObservation,
  ReadyHealth,
  RootStatus,
  SatelliteObservation,
  WorkerHealth,
} from "@/types/api";

function toQuery(params: Record<string, string | number | boolean | undefined | null>): string {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    searchParams.set(key, String(value));
  });
  const query = searchParams.toString();
  return query ? `?${query}` : "";
}

export const api = {
  getRoot: () => apiGet<RootStatus>("/"),
  getHealth: () => apiGet<{ status: string }>("/health"),
  getReady: () => apiGet<ReadyHealth>("/ready"),
  getWorkerHealth: () => apiGet<WorkerHealth>("/worker/health"),

  listMonitors: (params?: { limit?: number; offset?: number; status?: string; monitorType?: string }) =>
    apiGet<Monitor[]>(
      `/monitors${
        toQuery({
          limit: params?.limit,
          offset: params?.offset,
          status: params?.status,
          monitor_type: params?.monitorType,
        })
      }`,
    ),
  createMonitor: (payload: {
    name: string;
    description: string | null;
    geometry: { type: "Polygon"; coordinates: number[][][] };
    monitor_type: string;
    sensitivity: number;
    minimum_change_area_m2: number;
  }) => apiPost<Monitor>("/monitors", payload),
  updateMonitor: (monitorId: string, payload: Partial<Monitor>) => apiPatch<Monitor>(`/monitors/${monitorId}`, payload),
  deleteMonitor: (monitorId: string) => apiDelete(`/monitors/${monitorId}`),
  getMonitor: (monitorId: string) => apiGet<Monitor>(`/monitors/${monitorId}`),
  getMonitorSummary: (monitorId: string) => apiGet<MonitorSpatialSummary>(`/monitors/${monitorId}/summary`),

  listMonitorEvents: (
    monitorId: string,
    params?: {
      limit?: number;
      offset?: number;
      severity?: string;
      status?: string;
      semanticLabel?: string;
      minConfidence?: number;
      minAreaM2?: number;
      analysisId?: string;
    },
  ) =>
    apiGet<ChangeEvent[]>(
      `/monitors/${monitorId}/events${
        toQuery({
          limit: params?.limit,
          offset: params?.offset,
          severity: params?.severity,
          status: params?.status,
          semantic_label: params?.semanticLabel,
          min_confidence: params?.minConfidence,
          min_area_m2: params?.minAreaM2,
          analysis_id: params?.analysisId,
        })
      }`,
    ),
  getEvent: (monitorId: string, eventId: string) => apiGet<ChangeEvent>(`/monitors/${monitorId}/events/${eventId}`),
  getEventSemantics: (monitorId: string, eventId: string) =>
    apiGet<ChangeEventSemanticAnalysis>(`/monitors/${monitorId}/events/${eventId}/semantics`),
  computeEventSemantics: (monitorId: string, eventId: string, forceRecompute = false) =>
    apiPost<EventSemanticComputeResponse>(
      `/monitors/${monitorId}/events/${eventId}/semantics${toQuery({ force_recompute: forceRecompute ? true : undefined })}`,
    ),
  patchEventStatus: (monitorId: string, eventId: string, status: string) =>
    apiPatch<ChangeEvent>(`/monitors/${monitorId}/events/${eventId}`, { status }),
  getEventImpact: (monitorId: string, eventId: string) =>
    apiGet<EventImpactSummary>(`/monitors/${monitorId}/events/${eventId}/impact`),
  computeEventImpact: (monitorId: string, eventId: string, nearbyBufferM = 100) =>
    apiPost<{ computed: boolean; summary: EventImpactSummary }>(
      `/monitors/${monitorId}/events/${eventId}/impact${toQuery({ nearby_buffer_m: nearbyBufferM })}`,
    ),
  getEventExposure: (monitorId: string, eventId: string) =>
    apiGet<EventExposureSummary>(`/monitors/${monitorId}/events/${eventId}/exposure`),
  computeEventExposure: (monitorId: string, eventId: string, nearbyBufferM = 500) =>
    apiPost<{ computed: boolean; summary: EventExposureSummary }>(
      `/monitors/${monitorId}/events/${eventId}/exposure${toQuery({ environment_nearby_buffer_m: nearbyBufferM })}`,
    ),
  getEventIntelligence: (monitorId: string, eventId: string) =>
    apiGet<EventIntelligence>(`/monitors/${monitorId}/events/${eventId}/intelligence`),
  getMonitorEventSummary: (monitorId: string) => apiGet<MonitorEventSummary>(`/monitors/${monitorId}/events/summary`),

  listObservations: (
    monitorId: string,
    params?: {
      limit?: number;
      offset?: number;
      startDate?: string;
      endDate?: string;
      maxCloudCover?: number;
      platform?: string;
    },
  ) =>
    apiGet<SatelliteObservation[]>(
      `/monitors/${monitorId}/observations${
        toQuery({
          limit: params?.limit,
          offset: params?.offset,
          start_date: params?.startDate,
          end_date: params?.endDate,
          max_cloud_cover: params?.maxCloudCover,
          platform: params?.platform,
        })
      }`,
    ),
  searchObservations: (
    monitorId: string,
    payload: { start_date: string; end_date: string; max_cloud_cover?: number | null; limit?: number },
  ) =>
    apiPost<{
      monitor_id: string;
      provider: string;
      collection: string;
      count: number;
      inserted_count: number;
      skipped_count: number;
      observations: SatelliteObservation[];
    }>(`/monitors/${monitorId}/observations/search`, payload),
  getObservation: (monitorId: string, observationId: string) =>
    apiGet<SatelliteObservation>(`/monitors/${monitorId}/observations/${observationId}`),
  prepareObservation: (monitorId: string, observationId: string, forceReprocess = false) =>
    apiPost<PreparedObservation>(`/monitors/${monitorId}/observations/${observationId}/prepare`, {
      force_reprocess: forceReprocess,
    }),
  getPreparedObservation: (monitorId: string, observationId: string) =>
    apiGet<PreparedObservation>(`/monitors/${monitorId}/observations/${observationId}/prepared`),

  listAnalyses: (monitorId: string, params?: { limit?: number; offset?: number }) =>
    apiGet<ChangeAnalysis[]>(`/monitors/${monitorId}/analyses${toQuery({ limit: params?.limit, offset: params?.offset })}`),
  createAnalysisAuto: (
    monitorId: string,
    payload: {
      before_start_date: string;
      before_end_date: string;
      after_start_date: string;
      after_end_date: string;
      max_local_cloud_fraction?: number | null;
      threshold?: number;
      minimum_change_area_m2?: number | null;
    },
  ) => apiPost<ChangeAnalysis>(`/monitors/${monitorId}/analyses/auto`, payload),
  getAnalysis: (monitorId: string, analysisId: string) => apiGet<ChangeAnalysis>(`/monitors/${monitorId}/analyses/${analysisId}`),
  listAnalysisEvents: (monitorId: string, analysisId: string, params?: { limit?: number; offset?: number }) =>
    apiGet<ChangeEvent[]>(
      `/monitors/${monitorId}/analyses/${analysisId}/events${toQuery({ limit: params?.limit, offset: params?.offset })}`,
    ),
  generateEvents: (monitorId: string, analysisId: string) =>
    apiPost<{ analysis_id: string; count: number; generated: boolean; events: ChangeEvent[] }>(
      `/monitors/${monitorId}/analyses/${analysisId}/events`,
    ),
  computeAnalysisSemantics: (monitorId: string, analysisId: string, forceRecompute = false) =>
    apiPost<AnalysisSemanticComputeResponse>(
      `/monitors/${monitorId}/analyses/${analysisId}/semantics${toQuery({ force_recompute: forceRecompute ? true : undefined })}`,
    ),

  listContext: (
    monitorId: string,
    params?: {
      featureType?: string;
      featureSubtype?: string;
      provider?: string;
      limit?: number;
      offset?: number;
    },
  ) =>
    apiGet<ContextFeature[]>(
      `/monitors/${monitorId}/context${
        toQuery({
          feature_type: params?.featureType,
          feature_subtype: params?.featureSubtype,
          provider: params?.provider,
          limit: params?.limit,
          offset: params?.offset,
        })
      }`,
    ),
  refreshContext: (monitorId: string, featureTypes?: string[]) =>
    apiPost<{
      monitor_id: string;
      provider: string;
      attribution: string;
      fetched: number;
      inserted: number;
      updated: number;
      skipped: number;
      by_type: Record<string, number>;
      elapsed_seconds: number;
    }>(`/monitors/${monitorId}/context/refresh`, featureTypes ? { feature_types: featureTypes } : undefined),
  getContextSummary: (monitorId: string) => apiGet<ContextSummary>(`/monitors/${monitorId}/context/summary`),

  refreshPopulation: (monitorId: string) => apiPost(`/monitors/${monitorId}/population/refresh`),
  refreshLandCover: (monitorId: string) => apiPost(`/monitors/${monitorId}/land-cover/refresh`),
  refreshEnvironment: (monitorId: string) => apiPost(`/monitors/${monitorId}/environment/refresh`),

  getImpactSummary: (monitorId: string) => apiGet<MonitorImpactSummary>(`/monitors/${monitorId}/impact/summary`),
  getExposureSummary: (monitorId: string) => apiGet<MonitorExposureSummary>(`/monitors/${monitorId}/exposure/summary`),
  getDatasets: (monitorId: string) => apiGet<{ monitor_id: string; datasets: MonitorDatasetEntry[] }>(`/monitors/${monitorId}/datasets`),

  listRuns: (monitorId: string, params?: { limit?: number; offset?: number; status?: string }) =>
    apiGet<MonitorRun[]>(
      `/monitors/${monitorId}/runs${toQuery({ limit: params?.limit, offset: params?.offset, status: params?.status })}`,
    ),
  enqueueRun: (
    monitorId: string,
    payload: {
      start_date?: string;
      end_date?: string;
      lookback_days?: number;
      max_cloud_cover?: number | null;
      search_limit?: number;
      threshold?: number;
      minimum_change_area_m2?: number | null;
      impact_nearby_buffer_m?: number;
      environment_nearby_buffer_m?: number;
      auto_context_refresh?: boolean;
      auto_population_refresh?: boolean;
      auto_land_cover_refresh?: boolean;
      auto_environment_refresh?: boolean;
      force_reprocess?: boolean;
    },
  ) => apiPost<{ job: AnalysisJob; run: MonitorRun }>(`/monitors/${monitorId}/runs`, payload),
  getRun: (monitorId: string, runId: string) => apiGet<MonitorRun>(`/monitors/${monitorId}/runs/${runId}`),

  getSchedule: (monitorId: string) => apiGet<MonitorSchedule>(`/monitors/${monitorId}/schedule`),
  patchSchedule: (
    monitorId: string,
    payload: {
      enabled?: boolean;
      interval_hours?: number;
      lookback_days?: number;
      max_cloud_cover?: number | null;
      search_limit?: number;
      auto_context_refresh?: boolean;
      auto_population_refresh?: boolean;
      auto_land_cover_refresh?: boolean;
      auto_environment_refresh?: boolean;
      threshold?: number;
      minimum_change_area_m2?: number | null;
      impact_nearby_buffer_m?: number;
      environment_nearby_buffer_m?: number;
    },
  ) => apiPatch<MonitorSchedule>(`/monitors/${monitorId}/schedule`, payload),

  getJob: (jobId: string) => apiGet<AnalysisJob>(`/jobs/${jobId}`),
  cancelJob: (jobId: string) => apiPost<{ cancelled: boolean; job: AnalysisJob }>(`/jobs/${jobId}/cancel`),

  listGlobalEvents: (params?: {
    limit?: number;
    offset?: number;
    severity?: string;
    status?: string;
    monitor_id?: string;
  }) =>
    (async () => {
      const limit = params?.limit ?? 100;
      const offset = params?.offset ?? 0;

      const monitorIds = params?.monitor_id
        ? [params.monitor_id]
        : (await api.listMonitors({ limit: 100, offset: 0 })).map((monitor) => monitor.id);

      const batches = await Promise.all(
        monitorIds.map((monitorId) =>
          api.listMonitorEvents(monitorId, {
            limit: Math.min(limit, 100),
            offset: 0,
            severity: params?.severity,
            status: params?.status,
          }),
        ),
      );

      return batches
        .flat()
        .sort((left, right) => new Date(right.first_detected_at).getTime() - new Date(left.first_detected_at).getTime())
        .slice(offset, offset + limit);
    })(),
  listGlobalRuns: (params?: { limit?: number; offset?: number; status?: string; monitor_id?: string }) =>
    (async () => {
      const limit = params?.limit ?? 100;
      const offset = params?.offset ?? 0;

      const monitorIds = params?.monitor_id
        ? [params.monitor_id]
        : (await api.listMonitors({ limit: 100, offset: 0 })).map((monitor) => monitor.id);

      const batches = await Promise.all(
        monitorIds.map((monitorId) =>
          api.listRuns(monitorId, {
            limit: Math.min(limit, 100),
            offset: 0,
            status: params?.status,
          }),
        ),
      );

      return batches
        .flat()
        .sort((left, right) => new Date(right.started_at).getTime() - new Date(left.started_at).getTime())
        .slice(offset, offset + limit);
    })(),

  preparedArtifactUrl: (monitorId: string, observationId: string, artifact: "preview" | "multispectral" | "valid-mask") =>
    `/api/backend/monitors/${monitorId}/observations/${observationId}/prepared/artifacts/${artifact}`,
  analysisArtifactUrl: (
    monitorId: string,
    analysisId: string,
    artifact: "preview" | "change-mask" | "change-score" | "valid-comparison-mask" | "abs-delta-ndvi" | "spectral-distance",
  ) => `/api/backend/monitors/${monitorId}/analyses/${analysisId}/artifacts/${artifact}`,
};
