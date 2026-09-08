"use client";

import { useQuery } from "@tanstack/react-query";
import { Download, Link2, Play, RefreshCw } from "lucide-react";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { Group as PanelGroup, Panel as ResizePanel, Separator as PanelResizeHandle } from "react-resizable-panels";

import { api } from "@/api/endpoints";
import { EventIntelligencePanel } from "@/components/events/event-intelligence-panel";
import { EventList } from "@/components/events/event-list";
import { ArgusMap } from "@/components/map/argus-map";
import { BeforeAfterViewer } from "@/components/monitor/before-after-viewer";
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
  useRunMutations,
  useScheduleMutation,
} from "@/hooks/queries";
import { useUrlState } from "@/hooks/url-state";
import { copyText, downloadJson } from "@/lib/export";
import { formatArea, formatMeters, formatNumber, formatPercent, fromNow } from "@/lib/format";

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
  const changeMaskUrl = selectedRun?.analysis_id
    ? api.analysisArtifactUrl(monitorId, selectedRun.analysis_id, "change-mask")
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

  const shareUrl = useMemo(() => {
    if (!selectedEvent) {
      return null;
    }
    if (typeof window === "undefined") {
      return `/monitor/${monitorId}?eventId=${selectedEvent.id}`;
    }
    return `${window.location.origin}/monitor/${monitorId}?eventId=${selectedEvent.id}`;
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
              className="inline-flex items-center gap-1 rounded-md border border-argus-border bg-argus-panel px-3 py-1.5 text-xs text-argus-muted"
            >
              <RefreshCw size={12} /> Refresh
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
              className="mt-1 w-full rounded border border-argus-border bg-argus-panel px-2 py-1 text-xs"
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
              className="mt-1 w-full rounded border border-argus-border bg-argus-panel px-2 py-1 text-xs"
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
              className="mt-1 w-full rounded border border-argus-border bg-argus-panel px-2 py-1 text-xs"
            />
          </label>
          <label className="text-[11px] text-argus-muted">
            Search start
            <input
              type="date"
              value={searchStart}
              onChange={(event) => setSearchStart(event.target.value)}
              className="mt-1 w-full rounded border border-argus-border bg-argus-panel px-2 py-1 text-xs"
            />
          </label>
          <label className="text-[11px] text-argus-muted">
            Search end
            <input
              type="date"
              value={searchEnd}
              onChange={(event) => setSearchEnd(event.target.value)}
              className="mt-1 w-full rounded border border-argus-border bg-argus-panel px-2 py-1 text-xs"
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
              className="mt-1 w-full rounded border border-argus-border bg-argus-panel px-2 py-1 text-xs"
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
              className="mt-1 w-full rounded border border-argus-border bg-argus-panel px-2 py-1 text-xs"
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
            className="rounded border border-argus-border bg-argus-panel px-3 py-1 text-xs text-argus-muted"
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
            className="rounded border border-argus-border bg-argus-panel px-3 py-1 text-xs text-argus-muted"
          >
            Refresh context
          </button>
          <button
            type="button"
            onClick={() => datasetRefreshMutations.refreshPopulation.mutate()}
            className="rounded border border-argus-border bg-argus-panel px-3 py-1 text-xs text-argus-muted"
          >
            Refresh population
          </button>
          <button
            type="button"
            onClick={() => datasetRefreshMutations.refreshLandCover.mutate()}
            className="rounded border border-argus-border bg-argus-panel px-3 py-1 text-xs text-argus-muted"
          >
            Refresh land cover
          </button>
          <button
            type="button"
            onClick={() => datasetRefreshMutations.refreshEnvironment.mutate()}
            className="rounded border border-argus-border bg-argus-panel px-3 py-1 text-xs text-argus-muted"
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

      <PanelGroup orientation="horizontal" className="min-h-[760px] overflow-hidden rounded-lg border border-argus-border">
        <ResizePanel defaultSize={62} minSize={40}>
          <ArgusMap
            monitor={monitor}
            events={eventsQuery.data ?? []}
            selectedEventId={selectedEvent?.id ?? null}
            onSelectEvent={(eventId) => setValues({ eventId })}
            className="h-full min-h-[760px]"
          />
        </ResizePanel>

        <PanelResizeHandle className="w-1 bg-argus-border" />

        <ResizePanel defaultSize={38} minSize={28}>
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
                      className="rounded border border-argus-border bg-argus-panel px-1"
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
                      className="rounded border border-argus-border bg-argus-panel px-1"
                    >
                      <option value="">status</option>
                      <option value="new">new</option>
                      <option value="reviewed">reviewed</option>
                      <option value="dismissed">dismissed</option>
                      <option value="confirmed">confirmed</option>
                    </select>
                  </div>
                }
              />
              <EventList
                events={eventsQuery.data ?? []}
                selectedEventId={selectedEventId}
                onSelectEvent={(eventId) => setValues({ eventId })}
              />
            </Panel>

            <EventIntelligencePanel
              loading={intelligenceQuery.isLoading}
              error={intelligenceQuery.error ? (intelligenceQuery.error as Error).message : null}
              intelligence={intelligenceQuery.data ?? null}
            />

            <Panel className="p-3">
              <PanelHeader
                title="Event Actions"
                subtitle="Review, compute impact/exposure, and export"
                actions={
                  <div className="flex gap-1">
                    <button
                      type="button"
                      disabled={!selectedEvent}
                      className="rounded border border-argus-border bg-argus-panel px-2 py-1 text-xs"
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
                      className="rounded border border-argus-border bg-argus-panel px-2 py-1 text-xs"
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
                      className="rounded border border-argus-border bg-argus-panel px-2 py-1"
                    >
                      Mark reviewed
                    </button>
                    <button
                      type="button"
                      onClick={() => eventMutations.computeImpact.mutate({ eventId: selectedEvent.id, nearbyBufferM: 100 })}
                      className="rounded border border-argus-border bg-argus-panel px-2 py-1"
                    >
                      Compute impact
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        eventMutations.computeExposure.mutate({ eventId: selectedEvent.id, nearbyBufferM: 500 })
                      }
                      className="rounded border border-argus-border bg-argus-panel px-2 py-1"
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

            <PipelineVisualizer run={selectedRun} />

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
              changeMaskUrl={selectedRunAnalysis.data?.status === "ready" ? changeMaskUrl : null}
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
      </PanelGroup>
    </div>
  );
}
