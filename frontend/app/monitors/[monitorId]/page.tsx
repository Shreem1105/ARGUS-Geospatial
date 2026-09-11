"use client";

import { useQuery } from "@tanstack/react-query";
import { Download, Link2, Play, RefreshCw } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { Group as PanelGroup, Panel as ResizePanel, Separator as PanelResizeHandle } from "react-resizable-panels";

import { api } from "@/api/endpoints";
import { EventIntelligencePanel } from "@/components/events/event-intelligence-panel";
import { EventList } from "@/components/events/event-list";
import { ArgusMap } from "@/components/map/argus-map";
import { BeforeAfterViewer, type MonitorLayerMode } from "@/components/monitor/before-after-viewer";
import { ObservationTimeline } from "@/components/monitor/observation-timeline";
import { ObservationBrowser } from "@/components/monitor/observation-browser";
import { PipelineVisualizer } from "@/components/monitor/pipeline-visualizer";
import { ScheduleEditor } from "@/components/monitor/schedule-editor";
import { RunList } from "@/components/runs/run-list";
import { ErrorState, LoadingState, Metric, Panel, PanelHeader } from "@/components/ui";
import {
  qk,
  useContextFeaturesQuery,
  useContextRefreshMutation,
  useContextSummaryQuery,
  useDatasetRefreshMutations,
  useEventMutations,
  useEventIntelligenceQuery,
  useMonitorEventsQuery,
  useMonitorQuery,
  useMonitorRunsQuery,
  useMonitorScheduleQuery,
  useMonitorSummaryQuery,
  useObservationMutations,
  useObservationsQuery,
  usePreparedObservationQuery,
  useJobQuery,
  useRunMutations,
  useScheduleMutation,
} from "@/hooks/queries";
import { useUrlState } from "@/hooks/url-state";
import { copyText, downloadJson } from "@/lib/export";
import { formatArea, formatMeters, formatNumber, formatPercent, fromNow } from "@/lib/format";
import { useUiState } from "@/state/ui-state";

export default function MonitorDetailPage() {
  const params = useParams<{ monitorId: string }>();
  const monitorId = params.monitorId;

  const { values, setValues } = useUrlState();
  const [actionError, setActionError] = useState<string | null>(null);
  const [searchStart, setSearchStart] = useState("2026-08-01");
  const [searchEnd, setSearchEnd] = useState("2026-09-01");
  const [searchCloud, setSearchCloud] = useState(40);
  const [searchLimit, setSearchLimit] = useState(20);
  const [lookbackDays, setLookbackDays] = useState(60);
  const [maxCloudCover, setMaxCloudCover] = useState(40);
  const [threshold, setThreshold] = useState(0.12);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [layerMode, setLayerMode] = useState<MonitorLayerMode>("event_polygons");
  const [mapFocusNonce, setMapFocusNonce] = useState(0);

  const { panelState, setPanelOpen } = useUiState();

  const selectedEventId = values.eventId ?? null;
  const selectedRunId = values.runId ?? null;
  const selectedObservationId = values.observationId ?? null;

  const monitorQuery = useMonitorQuery(monitorId);
  const monitorSummaryQuery = useMonitorSummaryQuery(monitorId);
  const scheduleQuery = useMonitorScheduleQuery(monitorId);
  const eventsQuery = useMonitorEventsQuery(monitorId, {
    limit: 100,
    offset: 0,
    severity: values.severity,
    status: values.eventStatus,
    semanticLabel: values.semanticLabel,
  });
  const runsQuery = useMonitorRunsQuery(monitorId, {
    limit: 100,
    offset: 0,
    status: values.runStatus,
  });
  const observationsQuery = useObservationsQuery(monitorId, {
    limit: 100,
    offset: 0,
    platform: values.platform,
  });
  const contextSummaryQuery = useContextSummaryQuery(monitorId);
  const contextFeaturesQuery = useContextFeaturesQuery(monitorId, {
    featureType: values.featureType,
    limit: 50,
    offset: 0,
  });

  const selectedEvent = (eventsQuery.data ?? []).find((event) => event.id === selectedEventId) ?? null;
  const selectedRun = (runsQuery.data ?? []).find((run) => run.id === selectedRunId) ?? (runsQuery.data?.[0] ?? null);
  const selectedJobId = activeJobId ?? selectedRun?.analysis_job_id ?? null;

  const jobQuery = useJobQuery(selectedJobId);
  const finalizedJobRef = useRef<string | null>(null);

  const intelligenceQuery = useEventIntelligenceQuery(monitorId, selectedEvent?.id ?? null);

  const analysesQuery = useQuery({
    queryKey: qk.analyses(monitorId),
    queryFn: () => api.listAnalyses(monitorId, { limit: 100, offset: 0 }),
  });

  const selectedRunAnalysis = useQuery({
    queryKey: selectedRun?.analysis_id ? qk.analysis(monitorId, selectedRun.analysis_id) : ["analysis-none"],
    queryFn: () => api.getAnalysis(monitorId, selectedRun?.analysis_id as string),
    enabled: Boolean(selectedRun?.analysis_id),
    retry: false,
  });

  const beforePreparedQuery = usePreparedObservationQuery(monitorId, selectedRun?.before_observation_id ?? null);
  const afterPreparedQuery = usePreparedObservationQuery(monitorId, selectedRun?.after_observation_id ?? null);

  const impactSummaryQuery = useQuery({
    queryKey: qk.monitorImpactSummary(monitorId),
    queryFn: () => api.getImpactSummary(monitorId),
    retry: false,
  });

  const exposureSummaryQuery = useQuery({
    queryKey: qk.monitorExposureSummary(monitorId),
    queryFn: () => api.getExposureSummary(monitorId),
    retry: false,
  });

  const datasetsQuery = useQuery({
    queryKey: qk.datasets(monitorId),
    queryFn: () => api.getDatasets(monitorId),
    retry: false,
  });

  const runMutations = useRunMutations(monitorId);
  const observationMutations = useObservationMutations(monitorId);
  const eventMutations = useEventMutations(monitorId);
  const scheduleMutation = useScheduleMutation(monitorId);
  const contextRefreshMutation = useContextRefreshMutation(monitorId);
  const datasetRefreshMutations = useDatasetRefreshMutations(monitorId);

  const beforePreviewUrl = selectedRun?.before_observation_id
    ? api.preparedArtifactUrl(monitorId, selectedRun.before_observation_id, "preview")
    : null;
  const afterPreviewUrl = selectedRun?.after_observation_id
    ? api.preparedArtifactUrl(monitorId, selectedRun.after_observation_id, "preview")
    : null;
  const changePreviewUrl = selectedRun?.analysis_id
    ? api.analysisArtifactUrl(monitorId, selectedRun.analysis_id, "preview")
    : null;
  const changeMaskUrl = selectedRun?.analysis_id
    ? api.analysisArtifactUrl(monitorId, selectedRun.analysis_id, "change-mask")
    : null;

  const observationById = useMemo(() => {
    return new Map((observationsQuery.data ?? []).map((observation) => [observation.id, observation]));
  }, [observationsQuery.data]);

  const beforeObservation = selectedRun?.before_observation_id
    ? observationById.get(selectedRun.before_observation_id) ?? null
    : null;
  const afterObservation = selectedRun?.after_observation_id
    ? observationById.get(selectedRun.after_observation_id) ?? null
    : null;

  const topErrors = [
    monitorQuery.error,
    eventsQuery.error,
    runsQuery.error,
    observationsQuery.error,
    contextSummaryQuery.error,
  ].filter(Boolean) as Error[];

  const monitor = monitorQuery.data;
  const isLoading = monitorQuery.isLoading || eventsQuery.isLoading || runsQuery.isLoading;

  useEffect(() => {
    const job = jobQuery.data;
    if (!selectedJobId || !job) {
      return;
    }

    if (job.status === "queued" || job.status === "running") {
      finalizedJobRef.current = null;
      return;
    }

    if (finalizedJobRef.current === selectedJobId) {
      return;
    }

    finalizedJobRef.current = selectedJobId;
    setActiveJobId(null);

    void Promise.all([
      monitorQuery.refetch(),
      monitorSummaryQuery.refetch(),
      eventsQuery.refetch(),
      runsQuery.refetch(),
      observationsQuery.refetch(),
      contextSummaryQuery.refetch(),
      contextFeaturesQuery.refetch(),
      analysesQuery.refetch(),
    ]);
  }, [
    analysesQuery,
    contextFeaturesQuery,
    contextSummaryQuery,
    eventsQuery,
    jobQuery.data,
    monitorQuery,
    monitorSummaryQuery,
    observationsQuery,
    runsQuery,
    selectedJobId,
  ]);

  useEffect(() => {
    const onNavigate = (event: Event) => {
      const detail = (event as CustomEvent<{ direction: "prev" | "next" }>).detail;
      const entries = eventsQuery.data ?? [];

      if (!entries.length) {
        return;
      }

      const currentIndex = Math.max(0, entries.findIndex((item) => item.id === selectedEventId));
      const offset = detail?.direction === "prev" ? -1 : 1;
      const nextIndex = (currentIndex + offset + entries.length) % entries.length;
      const next = entries[nextIndex];

      setValues({ eventId: next.id });
      setPanelOpen("right", true);
      setMapFocusNonce((current) => current + 1);
    };

    const onFitSelection = () => setMapFocusNonce((current) => current + 1);

    window.addEventListener("argus:event-nav", onNavigate as EventListener);
    window.addEventListener("argus:fit-selection", onFitSelection);

    return () => {
      window.removeEventListener("argus:event-nav", onNavigate as EventListener);
      window.removeEventListener("argus:fit-selection", onFitSelection);
    };
  }, [eventsQuery.data, selectedEventId, setPanelOpen, setValues]);

  const shareUrl = useMemo(() => {
    if (!selectedEvent) {
      return null;
    }
    if (typeof window === "undefined") {
      return `/monitors/${monitorId}?eventId=${selectedEvent.id}`;
    }
    return `${window.location.origin}/monitors/${monitorId}?eventId=${selectedEvent.id}`;
  }, [selectedEvent, monitorId]);

  const analysesById = useMemo(() => {
    const map = new Map<string, string>();
    for (const analysis of analysesQuery.data ?? []) {
      map.set(analysis.id, analysis.status);
    }
    return map;
  }, [analysesQuery.data]);

  return (
    <div className="space-y-3">
      <Panel className="p-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold">{monitor?.name ?? "Monitor"}</h1>
            <p className="text-xs text-argus-muted">
              Monitor ID: {monitorId} · Updated {monitor ? fromNow(monitor.updated_at) : "—"}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={layerMode}
              onChange={(event) => setLayerMode(event.target.value as MonitorLayerMode)}
              className="argus-field"
              aria-label="Select monitor layer mode"
            >
              <option value="event_polygons">Event polygons</option>
              <option value="semantic_change">Semantic change</option>
              <option value="before_imagery">Before imagery</option>
              <option value="after_imagery">After imagery</option>
              <option value="change_preview">Change preview</option>
              <option value="change_mask">Change mask</option>
            </select>
            <button
              type="button"
              onClick={async () => {
                setActionError(null);
                try {
                  const result = await runMutations.enqueueRun.mutateAsync({
                    lookback_days: lookbackDays,
                    max_cloud_cover: maxCloudCover,
                    threshold,
                    search_limit: 80,
                  });
                  setActiveJobId(result.job.id);
                  setValues({ runId: result.run.id });
                  await runsQuery.refetch();
                } catch (error) {
                  setActionError((error as Error).message);
                }
              }}
              className="inline-flex items-center gap-1 rounded-md border border-argus-border bg-argus-accent px-3 py-1.5 text-xs font-semibold text-black"
            >
              <Play size={12} /> Run analysis
            </button>
            <button
              type="button"
              onClick={() => {
                void monitorQuery.refetch();
                void monitorSummaryQuery.refetch();
                void eventsQuery.refetch();
                void runsQuery.refetch();
                void observationsQuery.refetch();
              }}
              className="argus-control"
            >
              <RefreshCw size={12} /> Refresh
            </button>
            <button
              type="button"
              onClick={() => setPanelOpen("right", !panelState.right)}
              className={`argus-control ${panelState.right ? "argus-control-active" : ""}`}
            >
              {panelState.right ? "Hide" : "Show"} intelligence
            </button>
            <button
              type="button"
              onClick={() => setPanelOpen("timeline", !panelState.timeline)}
              className={`argus-control ${panelState.timeline ? "argus-control-active" : ""}`}
            >
              {panelState.timeline ? "Hide" : "Show"} timeline
            </button>
          </div>
        </div>

        <div className="mt-3 grid gap-3 md:grid-cols-4">
          <Metric label="AOI Area" value={formatArea(monitorSummaryQuery.data?.area_m2 ?? null)} />
          <Metric label="Events" value={formatNumber(eventsQuery.data?.length ?? 0, 0)} />
          <Metric label="Runs" value={formatNumber(runsQuery.data?.length ?? 0, 0)} />
          <Metric label="Observations" value={formatNumber(observationsQuery.data?.length ?? 0, 0)} />
        </div>

        <div className="mt-3 grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <label className="text-[11px] text-argus-muted">
            Lookback days
            <input
              type="number"
              min={1}
              max={365}
              value={lookbackDays}
              onChange={(event) => setLookbackDays(Number(event.target.value))}
              className="argus-field mt-1 w-full"
            />
          </label>
          <label className="text-[11px] text-argus-muted">
            Max cloud %
            <input
              type="number"
              min={0}
              max={100}
              value={maxCloudCover}
              onChange={(event) => setMaxCloudCover(Number(event.target.value))}
              className="argus-field mt-1 w-full"
            />
          </label>
          <label className="text-[11px] text-argus-muted">
            Threshold
            <input
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={threshold}
              onChange={(event) => setThreshold(Number(event.target.value))}
              className="argus-field mt-1 w-full"
            />
          </label>
          <label className="text-[11px] text-argus-muted">
            Search start
            <input
              type="date"
              value={searchStart}
              onChange={(event) => setSearchStart(event.target.value)}
              className="argus-field mt-1 w-full"
            />
          </label>
          <label className="text-[11px] text-argus-muted">
            Search end
            <input
              type="date"
              value={searchEnd}
              onChange={(event) => setSearchEnd(event.target.value)}
              className="argus-field mt-1 w-full"
            />
          </label>
          <label className="text-[11px] text-argus-muted">
            Search cloud %
            <input
              type="number"
              min={0}
              max={100}
              value={searchCloud}
              onChange={(event) => setSearchCloud(Number(event.target.value))}
              className="argus-field mt-1 w-full"
            />
          </label>
          <label className="text-[11px] text-argus-muted">
            Search limit
            <input
              type="number"
              min={1}
              max={100}
              value={searchLimit}
              onChange={(event) => setSearchLimit(Number(event.target.value))}
              className="argus-field mt-1 w-full"
            />
          </label>
        </div>

        <div className="mt-2 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={async () => {
              setActionError(null);
              try {
                await observationMutations.searchObservations.mutateAsync({
                  start_date: searchStart,
                  end_date: searchEnd,
                  max_cloud_cover: searchCloud,
                  limit: searchLimit,
                });
                await observationsQuery.refetch();
              } catch (error) {
                setActionError((error as Error).message);
              }
            }}
            className="argus-control"
          >
            Search observations
          </button>
          <button
            type="button"
            onClick={async () => {
              setActionError(null);
              try {
                await contextRefreshMutation.mutateAsync(["road", "building", "waterway", "administrative"]);
                await contextSummaryQuery.refetch();
                await contextFeaturesQuery.refetch();
              } catch (error) {
                setActionError((error as Error).message);
              }
            }}
            className="argus-control"
          >
            Refresh context
          </button>
          <button
            type="button"
            onClick={() => datasetRefreshMutations.refreshPopulation.mutate()}
            className="argus-control"
          >
            Refresh population
          </button>
          <button
            type="button"
            onClick={() => datasetRefreshMutations.refreshLandCover.mutate()}
            className="argus-control"
          >
            Refresh land cover
          </button>
          <button
            type="button"
            onClick={() => datasetRefreshMutations.refreshEnvironment.mutate()}
            className="argus-control"
          >
            Refresh environment
          </button>
        </div>
      </Panel>

      {isLoading ? <LoadingState label="Loading monitor workspace…" /> : null}
      {topErrors.map((error, index) => (
        <ErrorState key={`err-${index}`} detail={error.message} />
      ))}
      {actionError ? <ErrorState detail={actionError} /> : null}

      {selectedJobId && jobQuery.data ? (
        <Panel className="p-3">
          <PanelHeader title="Active Job" subtitle="Real queue/worker status from /jobs" />
          <div className="grid gap-2 text-xs md:grid-cols-4">
            <Metric label="Job" value={jobQuery.data.id.slice(0, 8)} hint={jobQuery.data.job_type} />
            <Metric label="Status" value={jobQuery.data.status} hint={jobQuery.data.progress_stage.replaceAll("_", " ")} />
            <Metric label="Progress" value={formatPercent(jobQuery.data.progress_percent, 0)} />
            <Metric
              label="Updated"
              value={fromNow(jobQuery.data.updated_at)}
              hint={jobQuery.data.completed_at ? `Done ${fromNow(jobQuery.data.completed_at)}` : "Polling active"}
            />
          </div>
        </Panel>
      ) : null}

      <PanelGroup orientation="horizontal" className="min-h-[76vh] overflow-hidden rounded-xl border border-argus-border shadow-workspace">
        <ResizePanel defaultSize={panelState.right ? 68 : 100} minSize={42}>
          <ArgusMap
            monitor={monitor}
            events={eventsQuery.data ?? []}
            selectedEventId={selectedEvent?.id ?? null}
            onSelectEvent={(eventId) => {
              setValues({ eventId });
              setPanelOpen("right", true);
              setMapFocusNonce((current) => current + 1);
            }}
            className="h-full min-h-[76vh]"
            showEvents={layerMode === "event_polygons" || layerMode === "semantic_change"}
            eventColorMode={layerMode === "semantic_change" ? "semantic" : "severity"}
            focusNonce={mapFocusNonce}
          />
        </ResizePanel>

        {panelState.right ? (
          <>
            <PanelResizeHandle className="w-1 bg-argus-border" />

            <ResizePanel defaultSize={32} minSize={24}>
              <div className="argus-scroll grid h-full gap-2 overflow-y-auto bg-argus-bg p-2">
                <Panel className="overflow-hidden">
                  <PanelHeader
                    title="Events"
                    subtitle="Filterable event list"
                    actions={
                      <div className="flex gap-1 text-xs">
                        <select
                          value={values.severity ?? ""}
                          onChange={(event) => setValues({ severity: event.target.value || null })}
                          className="argus-field"
                        >
                          <option value="">severity</option>
                          <option value="low">low</option>
                          <option value="medium">medium</option>
                          <option value="high">high</option>
                          <option value="critical">critical</option>
                        </select>
                        <select
                          value={values.eventStatus ?? ""}
                          onChange={(event) => setValues({ eventStatus: event.target.value || null })}
                          className="argus-field"
                        >
                          <option value="">status</option>
                          <option value="new">new</option>
                          <option value="reviewed">reviewed</option>
                          <option value="dismissed">dismissed</option>
                          <option value="confirmed">confirmed</option>
                        </select>
                        <select
                          value={values.semanticLabel ?? ""}
                          onChange={(event) => setValues({ semanticLabel: event.target.value || null })}
                          className="argus-field"
                        >
                          <option value="">semantic</option>
                          <option value="vegetation_decrease">vegetation_decrease</option>
                          <option value="vegetation_increase">vegetation_increase</option>
                          <option value="built_area_increase">built_area_increase</option>
                          <option value="built_area_decrease">built_area_decrease</option>
                          <option value="water_expansion">water_expansion</option>
                          <option value="water_contraction">water_contraction</option>
                          <option value="bare_ground_increase">bare_ground_increase</option>
                          <option value="bare_ground_decrease">bare_ground_decrease</option>
                          <option value="mixed_change">mixed_change</option>
                          <option value="uncertain">uncertain</option>
                        </select>
                      </div>
                    }
                  />
                  <EventList
                    events={eventsQuery.data ?? []}
                    selectedEventId={selectedEventId}
                    onSelectEvent={(eventId) => {
                      setValues({ eventId });
                      setMapFocusNonce((current) => current + 1);
                    }}
                  />
                </Panel>

                {layerMode === "semantic_change" ? (
                  <Panel className="p-3">
                    <PanelHeader title="Semantic Legend" subtitle="Observable land-surface transition classes" />
                    <div className="grid gap-1.5 text-[11px] text-argus-muted sm:grid-cols-2">
                      <LegendRow color="#de5f72" label="vegetation_decrease" />
                      <LegendRow color="#4ccf7f" label="vegetation_increase" />
                      <LegendRow color="#8fa5ff" label="built_area_increase" />
                      <LegendRow color="#6b7bb7" label="built_area_decrease" />
                      <LegendRow color="#42d4ff" label="water_expansion" />
                      <LegendRow color="#207ea8" label="water_contraction" />
                      <LegendRow color="#c7925c" label="bare_ground_increase" />
                      <LegendRow color="#7f9f5b" label="bare_ground_decrease" />
                      <LegendRow color="#d996ff" label="mixed_change" />
                      <LegendRow color="#9fabc0" label="uncertain" />
                    </div>
                    <p className="mt-2 text-[11px] text-argus-muted">
                      Labels indicate observable spectral transition patterns and do not establish causal event claims.
                    </p>
                  </Panel>
                ) : null}

                <EventIntelligencePanel
                  loading={intelligenceQuery.isLoading}
                  error={intelligenceQuery.error ? (intelligenceQuery.error as Error).message : null}
                  intelligence={intelligenceQuery.data ?? null}
                  event={selectedEvent}
                />

                <Panel className="p-3">
                  <PanelHeader
                    title="Event Actions"
                    subtitle="Review, compute semantics/impact/exposure, and export"
                    actions={
                      <div className="flex gap-1">
                        <button
                          type="button"
                          disabled={!selectedEvent}
                          className="argus-control"
                          onClick={async () => {
                            if (!selectedEvent) {
                              return;
                            }
                            const payload = JSON.stringify(selectedEvent, null, 2);
                            const copied = await copyText(payload);
                            if (!copied) {
                              setActionError("Unable to copy event JSON.");
                            }
                          }}
                        >
                          <Link2 size={12} className="inline" /> Copy event
                        </button>
                        <button
                          type="button"
                          disabled={!selectedEvent}
                          className="argus-control"
                          onClick={() => {
                            if (!selectedEvent) {
                              return;
                            }
                            downloadJson(`event-${selectedEvent.id}.json`, selectedEvent);
                          }}
                        >
                          <Download size={12} className="inline" /> Export
                        </button>
                      </div>
                    }
                  />
                  {selectedEvent ? (
                    <div className="space-y-2 text-xs">
                      <p>Scientific severity: {selectedEvent.severity}</p>
                      <p>Confidence: {formatPercent(selectedEvent.confidence * 100)}</p>
                      <p>Area: {formatArea(selectedEvent.area_m2)}</p>
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => eventMutations.patchStatus.mutate({ eventId: selectedEvent.id, status: "reviewed" })}
                          className="argus-control"
                        >
                          Mark reviewed
                        </button>
                        <button
                          type="button"
                          onClick={() => eventMutations.computeSemantics.mutate({ eventId: selectedEvent.id })}
                          className="argus-control"
                        >
                          Compute semantics
                        </button>
                        <button
                          type="button"
                          onClick={() => eventMutations.computeSemantics.mutate({ eventId: selectedEvent.id, forceRecompute: true })}
                          className="argus-control"
                        >
                          Recompute semantics
                        </button>
                        <button
                          type="button"
                          onClick={() => eventMutations.computeImpact.mutate({ eventId: selectedEvent.id, nearbyBufferM: 100 })}
                          className="argus-control"
                        >
                          Compute impact
                        </button>
                        <button
                          type="button"
                          onClick={() => eventMutations.computeExposure.mutate({ eventId: selectedEvent.id, nearbyBufferM: 500 })}
                          className="argus-control"
                        >
                          Compute exposure
                        </button>
                      </div>
                      {shareUrl ? <p className="break-all text-argus-muted">Share: {shareUrl}</p> : null}
                    </div>
                  ) : (
                    <p className="text-xs text-argus-muted">Select an event to run actions.</p>
                  )}
                </Panel>

                <RunList
                  runs={runsQuery.data ?? []}
                  selectedRunId={selectedRun?.id ?? null}
                  onSelectRun={(runId) => setValues({ runId })}
                  onCancelJob={(jobId) => runMutations.cancelJob.mutate(jobId)}
                  cancellingJobId={runMutations.cancelJob.variables ?? null}
                />

                <PipelineVisualizer run={selectedRun} job={jobQuery.data ?? null} />

                <ObservationBrowser
                  observations={observationsQuery.data ?? []}
                  selectedObservationId={selectedObservationId}
                  onSelectObservation={(observationId) => setValues({ observationId })}
                  onPrepareObservation={(observationId) =>
                    observationMutations.prepareObservation.mutate({ observationId, forceReprocess: false })
                  }
                  preparingObservationId={observationMutations.prepareObservation.variables?.observationId ?? null}
                />

                <BeforeAfterViewer
                  beforePreviewUrl={beforePreparedQuery.data?.status === "ready" ? beforePreviewUrl : null}
                  afterPreviewUrl={afterPreparedQuery.data?.status === "ready" ? afterPreviewUrl : null}
                  changePreviewUrl={selectedRunAnalysis.data?.status === "ready" ? changePreviewUrl : null}
                  changeMaskUrl={selectedRunAnalysis.data?.status === "ready" ? changeMaskUrl : null}
                  beforeItemId={beforeObservation?.item_id ?? null}
                  afterItemId={afterObservation?.item_id ?? null}
                  beforeAcquiredAt={beforeObservation?.acquired_at ?? null}
                  afterAcquiredAt={afterObservation?.acquired_at ?? null}
                  activeLayer={layerMode}
                  onLayerChange={setLayerMode}
                />

                <Panel className="p-3">
                  <PanelHeader title="Context + Exposure Summary" subtitle="Monitor-level impact and dataset state" />
                  <div className="grid gap-2 text-xs md:grid-cols-2">
                    <Metric
                      label="Context features"
                      value={formatNumber(contextSummaryQuery.data?.total_features ?? 0, 0)}
                      hint={contextSummaryQuery.data?.attribution ?? ""}
                    />
                    <Metric
                      label="Events with roads"
                      value={formatNumber(impactSummaryQuery.data?.events_with_intersecting_roads ?? 0, 0)}
                      hint={`Road length ${formatMeters(impactSummaryQuery.data?.total_intersecting_road_length_m ?? 0)}`}
                    />
                    <Metric
                      label="Events with buildings"
                      value={formatNumber(impactSummaryQuery.data?.events_with_intersecting_buildings ?? 0, 0)}
                      hint={`Area ${formatArea(impactSummaryQuery.data?.total_building_intersection_area_m2 ?? 0)}`}
                    />
                    <Metric
                      label="Population exposure"
                      value={formatNumber(exposureSummaryQuery.data?.estimated_total_population_exposure_event_level_sum ?? 0, 0)}
                      hint={`Events ${formatNumber(exposureSummaryQuery.data?.events_with_population_exposure ?? 0, 0)}`}
                    />
                  </div>

                  <div className="mt-3 text-xs text-argus-muted">
                    <p>Context rows loaded: {formatNumber(contextFeaturesQuery.data?.length ?? 0, 0)}</p>
                    <p>Analyses tracked: {formatNumber(analysesById.size, 0)}</p>
                    <p>Datasets: {formatNumber(datasetsQuery.data?.datasets.length ?? 0, 0)}</p>
                  </div>
                </Panel>

                <ScheduleEditor
                  schedule={scheduleQuery.data ?? null}
                  saving={scheduleMutation.isPending}
                  onSave={async (payload) => {
                    setActionError(null);
                    try {
                      await scheduleMutation.mutateAsync(payload);
                      await scheduleQuery.refetch();
                    } catch (error) {
                      setActionError((error as Error).message);
                    }
                  }}
                />
              </div>
            </ResizePanel>
          </>
        ) : null}
      </PanelGroup>

      {panelState.timeline ? (
        <ObservationTimeline
          observations={observationsQuery.data ?? []}
          selectedObservationId={selectedObservationId}
          beforeObservationId={selectedRun?.before_observation_id ?? null}
          afterObservationId={selectedRun?.after_observation_id ?? null}
          onSelectObservation={(observationId) => setValues({ observationId })}
        />
      ) : null}
    </div>
  );
}

function LegendRow({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: color }} />
      <span>{label}</span>
    </div>
  );
}

