"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/endpoints";
import type { ChangeEvent, Monitor, MonitorRun, MonitorSchedule } from "@/types/api";

export const qk = {
  monitors: ["monitors"] as const,
  monitor: (monitorId: string) => ["monitor", monitorId] as const,
  monitorSummary: (monitorId: string) => ["monitor-summary", monitorId] as const,
  monitorEvents: (monitorId: string, filters: Record<string, unknown>) => ["monitor-events", monitorId, filters] as const,
  monitorRuns: (monitorId: string, filters: Record<string, unknown>) => ["monitor-runs", monitorId, filters] as const,
  monitorSchedule: (monitorId: string) => ["monitor-schedule", monitorId] as const,
  observations: (monitorId: string, filters: Record<string, unknown>) => ["observations", monitorId, filters] as const,
  preparedObservation: (monitorId: string, observationId: string) =>
    ["prepared-observation", monitorId, observationId] as const,
  analysis: (monitorId: string, analysisId: string) => ["analysis", monitorId, analysisId] as const,
  analyses: (monitorId: string) => ["analyses", monitorId] as const,
  eventIntelligence: (monitorId: string, eventId: string) => ["event-intelligence", monitorId, eventId] as const,
  contextSummary: (monitorId: string) => ["context-summary", monitorId] as const,
  contextFeatures: (monitorId: string, filters: Record<string, unknown>) =>
    ["context-features", monitorId, filters] as const,
  monitorImpactSummary: (monitorId: string) => ["monitor-impact-summary", monitorId] as const,
  monitorExposureSummary: (monitorId: string) => ["monitor-exposure-summary", monitorId] as const,
  monitorEventSummary: (monitorId: string) => ["monitor-event-summary", monitorId] as const,
  datasets: (monitorId: string) => ["monitor-datasets", monitorId] as const,
  job: (jobId: string) => ["job", jobId] as const,
  workerHealth: ["worker-health"] as const,
  readyHealth: ["ready-health"] as const,
  appHealth: ["app-health"] as const,
  rootStatus: ["root-status"] as const,
  globalEvents: (filters: Record<string, unknown>) => ["global-events", filters] as const,
  globalRuns: (filters: Record<string, unknown>) => ["global-runs", filters] as const,
};

export function useMonitorsQuery(params: { limit?: number; offset?: number; status?: string; monitorType?: string }) {
  return useQuery({
    queryKey: [...qk.monitors, params],
    queryFn: () => api.listMonitors(params),
    staleTime: 20_000,
  });
}

export function useMonitorQuery(monitorId: string | null) {
  return useQuery({
    queryKey: monitorId ? qk.monitor(monitorId) : ["monitor-none"],
    queryFn: () => api.getMonitor(monitorId as string),
    enabled: Boolean(monitorId),
  });
}

export function useMonitorSummaryQuery(monitorId: string | null) {
  return useQuery({
    queryKey: monitorId ? qk.monitorSummary(monitorId) : ["monitor-summary-none"],
    queryFn: () => api.getMonitorSummary(monitorId as string),
    enabled: Boolean(monitorId),
    retry: false,
  });
}

export function useMonitorEventsQuery(
  monitorId: string | null,
  filters: {
    limit?: number;
    offset?: number;
    severity?: string;
    status?: string;
    semanticLabel?: string;
    minConfidence?: number;
    minAreaM2?: number;
    analysisId?: string;
  },
) {
  return useQuery({
    queryKey: monitorId ? qk.monitorEvents(monitorId, filters) : ["monitor-events-none"],
    queryFn: () => api.listMonitorEvents(monitorId as string, filters),
    enabled: Boolean(monitorId),
  });
}

export function useMonitorRunsQuery(
  monitorId: string | null,
  filters: {
    limit?: number;
    offset?: number;
    status?: string;
  },
) {
  return useQuery({
    queryKey: monitorId ? qk.monitorRuns(monitorId, filters) : ["monitor-runs-none"],
    queryFn: () => api.listRuns(monitorId as string, filters),
    enabled: Boolean(monitorId),
    refetchInterval: (query) => {
      const rows = query.state.data as MonitorRun[] | undefined;
      return rows?.some((row) => row.status === "started") ? 4000 : false;
    },
  });
}

export function useMonitorScheduleQuery(monitorId: string | null) {
  return useQuery({
    queryKey: monitorId ? qk.monitorSchedule(monitorId) : ["monitor-schedule-none"],
    queryFn: () => api.getSchedule(monitorId as string),
    enabled: Boolean(monitorId),
  });
}

export function useObservationsQuery(
  monitorId: string | null,
  filters: {
    limit?: number;
    offset?: number;
    startDate?: string;
    endDate?: string;
    maxCloudCover?: number;
    platform?: string;
  },
) {
  return useQuery({
    queryKey: monitorId ? qk.observations(monitorId, filters) : ["observations-none"],
    queryFn: () => api.listObservations(monitorId as string, filters),
    enabled: Boolean(monitorId),
  });
}

export function usePreparedObservationQuery(monitorId: string | null, observationId: string | null) {
  return useQuery({
    queryKey:
      monitorId && observationId ? qk.preparedObservation(monitorId, observationId) : ["prepared-observation-none"],
    queryFn: () => api.getPreparedObservation(monitorId as string, observationId as string),
    enabled: Boolean(monitorId && observationId),
    retry: false,
  });
}


export function useJobQuery(jobId: string | null) {
  return useQuery({
    queryKey: jobId ? qk.job(jobId) : ["job-none"],
    queryFn: () => api.getJob(jobId as string),
    enabled: Boolean(jobId),
    retry: false,
    refetchInterval: (query) => {
      const job = query.state.data as { status?: string } | undefined;
      if (!job) {
        return 3000;
      }
      return job.status === "queued" || job.status === "running" ? 3000 : false;
    },
  });
}
export function useEventIntelligenceQuery(monitorId: string | null, eventId: string | null) {
  return useQuery({
    queryKey: monitorId && eventId ? qk.eventIntelligence(monitorId, eventId) : ["event-intelligence-none"],
    queryFn: () => api.getEventIntelligence(monitorId as string, eventId as string),
    enabled: Boolean(monitorId && eventId),
    retry: false,
  });
}

export function useContextSummaryQuery(monitorId: string | null) {
  return useQuery({
    queryKey: monitorId ? qk.contextSummary(monitorId) : ["context-summary-none"],
    queryFn: () => api.getContextSummary(monitorId as string),
    enabled: Boolean(monitorId),
    retry: false,
  });
}

export function useContextFeaturesQuery(
  monitorId: string | null,
  filters: {
    featureType?: string;
    featureSubtype?: string;
    provider?: string;
    limit?: number;
    offset?: number;
  },
) {
  return useQuery({
    queryKey: monitorId ? qk.contextFeatures(monitorId, filters) : ["context-features-none"],
    queryFn: () => api.listContext(monitorId as string, filters),
    enabled: Boolean(monitorId),
  });
}

export function useGlobalEventsQuery(filters: {
  limit?: number;
  offset?: number;
  severity?: string;
  status?: string;
  monitor_id?: string;
}) {
  return useQuery({
    queryKey: qk.globalEvents(filters),
    queryFn: () => api.listGlobalEvents(filters),
    staleTime: 15_000,
  });
}

export function useGlobalRunsQuery(filters: {
  limit?: number;
  offset?: number;
  status?: string;
  monitor_id?: string;
}) {
  return useQuery({
    queryKey: qk.globalRuns(filters),
    queryFn: () => api.listGlobalRuns(filters),
    refetchInterval: (query) => {
      const rows = query.state.data as MonitorRun[] | undefined;
      return rows?.some((row) => row.status === "started") ? 4000 : false;
    },
  });
}

export function useSystemHealthQueries() {
  const root = useQuery({ queryKey: qk.rootStatus, queryFn: api.getRoot, staleTime: 60_000 });
  const health = useQuery({ queryKey: qk.appHealth, queryFn: api.getHealth, staleTime: 20_000, refetchInterval: 20_000 });
  const ready = useQuery({ queryKey: qk.readyHealth, queryFn: api.getReady, staleTime: 20_000, refetchInterval: 20_000 });
  const worker = useQuery({
    queryKey: qk.workerHealth,
    queryFn: api.getWorkerHealth,
    staleTime: 20_000,
    refetchInterval: 20_000,
    retry: false,
  });

  return { root, health, ready, worker };
}

function updateCachedEntity<T extends { id: string }>(rows: T[] | undefined, entity: T): T[] {
  if (!rows) {
    return [entity];
  }
  const index = rows.findIndex((row) => row.id === entity.id);
  if (index === -1) {
    return [entity, ...rows];
  }
  const next = [...rows];
  next[index] = entity;
  return next;
}

export function useMonitorMutations() {
  const qc = useQueryClient();

  const createMonitor = useMutation({
    mutationFn: api.createMonitor,
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: qk.monitors });
      qc.setQueryData(qk.monitor(created.id), created);
    },
  });

  const updateMonitor = useMutation({
    mutationFn: ({ monitorId, payload }: { monitorId: string; payload: Partial<Monitor> }) =>
      api.updateMonitor(monitorId, payload),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: qk.monitors });
      qc.setQueryData(qk.monitor(updated.id), updated);
    },
  });

  const deleteMonitor = useMutation({
    mutationFn: (monitorId: string) => api.deleteMonitor(monitorId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.monitors });
    },
  });

  return { createMonitor, updateMonitor, deleteMonitor };
}

export function useEventMutations(monitorId: string | null) {
  const qc = useQueryClient();

  const patchStatus = useMutation({
    mutationFn: ({ eventId, status }: { eventId: string; status: string }) =>
      api.patchEventStatus(monitorId as string, eventId, status),
    onSuccess: (updated) => {
      if (!monitorId) {
        return;
      }
      qc.setQueriesData({ queryKey: ["monitor-events", monitorId] }, (old: ChangeEvent[] | undefined) =>
        updateCachedEntity(old, updated),
      );
    },
  });

  const computeImpact = useMutation({
    mutationFn: ({ eventId, nearbyBufferM }: { eventId: string; nearbyBufferM?: number }) =>
      api.computeEventImpact(monitorId as string, eventId, nearbyBufferM),
    onSuccess: (_, { eventId }) => {
      if (!monitorId) {
        return;
      }
      qc.invalidateQueries({ queryKey: qk.eventIntelligence(monitorId, eventId) });
      qc.invalidateQueries({ queryKey: qk.monitorImpactSummary(monitorId) });
    },
  });

  const computeSemantics = useMutation({
    mutationFn: ({ eventId, forceRecompute }: { eventId: string; forceRecompute?: boolean }) =>
      api.computeEventSemantics(monitorId as string, eventId, forceRecompute),
    onSuccess: (_, { eventId }) => {
      if (!monitorId) {
        return;
      }
      qc.invalidateQueries({ queryKey: qk.eventIntelligence(monitorId, eventId) });
      qc.invalidateQueries({ queryKey: ["monitor-events", monitorId] });
    },
  });

  const computeExposure = useMutation({
    mutationFn: ({ eventId, nearbyBufferM }: { eventId: string; nearbyBufferM?: number }) =>
      api.computeEventExposure(monitorId as string, eventId, nearbyBufferM),
    onSuccess: (_, { eventId }) => {
      if (!monitorId) {
        return;
      }
      qc.invalidateQueries({ queryKey: qk.eventIntelligence(monitorId, eventId) });
      qc.invalidateQueries({ queryKey: qk.monitorExposureSummary(monitorId) });
    },
  });

  return { patchStatus, computeSemantics, computeImpact, computeExposure };
}

export function useRunMutations(monitorId: string | null) {
  const qc = useQueryClient();

  const enqueueRun = useMutation({
    mutationFn: (payload: Parameters<typeof api.enqueueRun>[1]) => api.enqueueRun(monitorId as string, payload),
    onSuccess: ({ run, job }) => {
      qc.invalidateQueries({ queryKey: monitorId ? ["monitor-runs", monitorId] : ["monitor-runs"] });
      qc.setQueryData(["job", job.id], job);
      if (monitorId) {
        qc.setQueryData(["monitor-run", monitorId, run.id], run);
      }
    },
  });

  const cancelJob = useMutation({
    mutationFn: (jobId: string) => api.cancelJob(jobId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["monitor-runs"] });
      qc.invalidateQueries({ queryKey: ["global-runs"] });
    },
  });

  return { enqueueRun, cancelJob };
}

export function useObservationMutations(monitorId: string | null) {
  const qc = useQueryClient();

  const searchObservations = useMutation({
    mutationFn: (payload: Parameters<typeof api.searchObservations>[1]) => api.searchObservations(monitorId as string, payload),
    onSuccess: () => {
      if (!monitorId) {
        return;
      }
      qc.invalidateQueries({ queryKey: ["observations", monitorId] });
    },
  });

  const prepareObservation = useMutation({
    mutationFn: ({ observationId, forceReprocess }: { observationId: string; forceReprocess?: boolean }) =>
      api.prepareObservation(monitorId as string, observationId, forceReprocess),
    onSuccess: (prepared) => {
      if (!monitorId) {
        return;
      }
      qc.setQueryData(qk.preparedObservation(monitorId, prepared.observation_id), prepared);
      qc.invalidateQueries({ queryKey: qk.analyses(monitorId) });
    },
  });

  return { searchObservations, prepareObservation };
}

export function useScheduleMutation(monitorId: string | null) {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (payload: Parameters<typeof api.patchSchedule>[1]) => api.patchSchedule(monitorId as string, payload),
    onSuccess: (schedule: MonitorSchedule) => {
      if (!monitorId) {
        return;
      }
      qc.setQueryData(qk.monitorSchedule(monitorId), schedule);
    },
  });
}

export function useContextRefreshMutation(monitorId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (featureTypes?: string[]) => api.refreshContext(monitorId as string, featureTypes),
    onSuccess: () => {
      if (!monitorId) {
        return;
      }
      qc.invalidateQueries({ queryKey: qk.contextSummary(monitorId) });
      qc.invalidateQueries({ queryKey: ["context-features", monitorId] });
    },
  });
}

export function useDatasetRefreshMutations(monitorId: string | null) {
  const qc = useQueryClient();

  const refreshPopulation = useMutation({
    mutationFn: () => api.refreshPopulation(monitorId as string),
    onSuccess: () => {
      if (!monitorId) {
        return;
      }
      qc.invalidateQueries({ queryKey: qk.datasets(monitorId) });
    },
  });

  const refreshLandCover = useMutation({
    mutationFn: () => api.refreshLandCover(monitorId as string),
    onSuccess: () => {
      if (!monitorId) {
        return;
      }
      qc.invalidateQueries({ queryKey: qk.datasets(monitorId) });
    },
  });

  const refreshEnvironment = useMutation({
    mutationFn: () => api.refreshEnvironment(monitorId as string),
    onSuccess: () => {
      if (!monitorId) {
        return;
      }
      qc.invalidateQueries({ queryKey: qk.datasets(monitorId) });
    },
  });

  return { refreshPopulation, refreshLandCover, refreshEnvironment };
}
