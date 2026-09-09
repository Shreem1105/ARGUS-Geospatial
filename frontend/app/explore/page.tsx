"use client";

import Link from "next/link";
import { RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Group as PanelGroup, Panel as ResizePanel, Separator as PanelResizeHandle } from "react-resizable-panels";

import { EventIntelligencePanel } from "@/components/events/event-intelligence-panel";
import { EventList } from "@/components/events/event-list";
import { ArgusMap } from "@/components/map/argus-map";
import { CuratedExploreEmptyState } from "@/components/explore/curated-empty-state";
import { ErrorState, LoadingState, Panel, PanelHeader } from "@/components/ui";
import { useEventIntelligenceQuery, useGlobalEventsQuery, useMonitorsQuery } from "@/hooks/queries";
import { useUrlState } from "@/hooks/url-state";
import { curatedScenarios } from "@/lib/curated-scenarios";
import { formatDate, formatPercent } from "@/lib/format";
import { useUiState } from "@/state/ui-state";

export default function ExplorePage() {
  const { values, setValues } = useUrlState();
  const { panelState } = useUiState();

  const [mapFocusNonce, setMapFocusNonce] = useState(0);

  const selectedEventId = values.eventId ?? null;

  const monitorsQuery = useMonitorsQuery({ limit: 120, offset: 0 });
  const eventsQuery = useGlobalEventsQuery({
    limit: 260,
    offset: 0,
    severity: values.severity,
    status: values.status,
    monitor_id: values.monitorId ?? undefined,
  });

  const selectedEvent = useMemo(
    () => (eventsQuery.data ?? []).find((event) => event.id === selectedEventId) ?? null,
    [eventsQuery.data, selectedEventId],
  );

  const selectedMonitorId = values.monitorId ?? selectedEvent?.monitor_id ?? null;
  const selectedMonitor = (monitorsQuery.data ?? []).find((monitor) => monitor.id === selectedMonitorId) ?? null;

  const intelligenceQuery = useEventIntelligenceQuery(selectedEvent?.monitor_id ?? null, selectedEvent?.id ?? null);

  const noCurated = curatedScenarios.length === 0;

  useEffect(() => {
    const onNavigate = (event: Event) => {
      const detail = (event as CustomEvent<{ direction: "prev" | "next" }>).detail;
      const entries = eventsQuery.data ?? [];
      if (!entries.length) {
        return;
      }

      const currentIndex = Math.max(0, entries.findIndex((item) => item.id === selectedEventId));
      const step = detail?.direction === "prev" ? -1 : 1;
      const nextIndex = (currentIndex + step + entries.length) % entries.length;
      const next = entries[nextIndex];
      setValues({ eventId: next.id, monitorId: next.monitor_id });
      setMapFocusNonce((current) => current + 1);
    };

    const onFitSelection = () => setMapFocusNonce((current) => current + 1);

    window.addEventListener("argus:event-nav", onNavigate as EventListener);
    window.addEventListener("argus:fit-selection", onFitSelection);
    return () => {
      window.removeEventListener("argus:event-nav", onNavigate as EventListener);
      window.removeEventListener("argus:fit-selection", onFitSelection);
    };
  }, [eventsQuery.data, selectedEventId, setValues]);

  const timelineEvents = useMemo(
    () => [...(eventsQuery.data ?? [])].sort((left, right) => new Date(left.first_detected_at).getTime() - new Date(right.first_detected_at).getTime()),
    [eventsQuery.data],
  );

  return (
    <div className="space-y-3">
      <Panel className="p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className="text-lg font-semibold">Explore</h1>
            <p className="text-xs text-argus-muted">Public geospatial intelligence workspace using persisted ARGUS data only</p>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-xs">
            <select
              value={values.severity ?? ""}
              onChange={(event) => setValues({ severity: event.target.value || null })}
              className="argus-field"
              aria-label="Filter events by severity"
            >
              <option value="">All severities</option>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="critical">critical</option>
            </select>

            <select
              value={values.status ?? ""}
              onChange={(event) => setValues({ status: event.target.value || null })}
              className="argus-field"
              aria-label="Filter events by status"
            >
              <option value="">All statuses</option>
              <option value="new">new</option>
              <option value="reviewed">reviewed</option>
              <option value="dismissed">dismissed</option>
              <option value="confirmed">confirmed</option>
            </select>

            <button
              type="button"
              onClick={() => {
                void monitorsQuery.refetch();
                void eventsQuery.refetch();
              }}
              className="argus-control"
            >
              <RefreshCw size={12} /> Refresh
            </button>
          </div>
        </div>
      </Panel>

      {monitorsQuery.isLoading || eventsQuery.isLoading ? <LoadingState label="Loading Explore map and events…" /> : null}
      {monitorsQuery.error ? <ErrorState detail={(monitorsQuery.error as Error).message} /> : null}
      {eventsQuery.error ? <ErrorState detail={(eventsQuery.error as Error).message} /> : null}

      <PanelGroup orientation="horizontal" className="min-h-[74vh] overflow-hidden rounded-xl border border-argus-border shadow-workspace">
        {panelState.left ? (
          <>
            <ResizePanel defaultSize={22} minSize={16} maxSize={30}>
              <Panel className="argus-scroll h-full overflow-y-auto rounded-none border-0 border-r border-argus-border/80">
                <PanelHeader title="Explore Controls" subtitle="Cases, monitor scope, and quick navigation" />
                <div className="space-y-3 p-3 text-xs">
                  <label className="space-y-1 text-argus-muted">
                    Monitor scope
                    <select
                      value={values.monitorId ?? ""}
                      onChange={(event) => setValues({ monitorId: event.target.value || null })}
                      className="argus-field w-full"
                    >
                      <option value="">All monitors</option>
                      {(monitorsQuery.data ?? []).map((monitor) => (
                        <option key={monitor.id} value={monitor.id}>
                          {monitor.name}
                        </option>
                      ))}
                    </select>
                  </label>

                  {noCurated ? <CuratedExploreEmptyState /> : null}

                  {!noCurated ? (
                    <div className="space-y-2">
                      <p className="text-[11px] uppercase tracking-[0.16em] text-argus-muted">Curated cases</p>
                      {curatedScenarios.map((scenario) => (
                        <Link key={scenario.id} href={`/explore/${scenario.id}`} className="argus-panel-muted argus-soft-lift block px-2.5 py-2">
                          <p className="text-xs font-medium text-argus-text">{scenario.title}</p>
                          <p className="mt-1 text-[11px] text-argus-muted">{scenario.region_label}</p>
                        </Link>
                      ))}
                    </div>
                  ) : null}
                </div>
              </Panel>
            </ResizePanel>

            <PanelResizeHandle className="w-1 bg-argus-border/85" />
          </>
        ) : null}

        <ResizePanel defaultSize={panelState.right ? 56 : 78} minSize={46}>
          <div className="relative h-full">
            <ArgusMap
              monitor={selectedMonitor}
              events={eventsQuery.data ?? []}
              selectedEventId={selectedEventId}
              onSelectEvent={(eventId) => {
                const match = (eventsQuery.data ?? []).find((event) => event.id === eventId);
                if (!match) {
                  return;
                }
                setValues({ eventId, monitorId: match.monitor_id });
                setMapFocusNonce((current) => current + 1);
              }}
              className="h-full min-h-[74vh]"
              focusNonce={mapFocusNonce}
            />

            <div className="pointer-events-none absolute left-3 top-3 rounded-md border border-argus-border bg-black/45 px-2 py-1 text-[11px] text-argus-muted backdrop-blur">
              Map-first workspace · real persisted event polygons
            </div>
          </div>
        </ResizePanel>

        {panelState.right ? (
          <>
            <PanelResizeHandle className="w-1 bg-argus-border/85" />
            <ResizePanel defaultSize={22} minSize={20} maxSize={34}>
              <div className="argus-scroll grid h-full grid-rows-[40%,60%] gap-2 overflow-y-auto bg-argus-bg p-2">
                <Panel className="overflow-hidden">
                  <PanelHeader title="Events" subtitle="Selection updates deep-link state" />
                  <EventList
                    events={eventsQuery.data ?? []}
                    selectedEventId={selectedEventId}
                    onSelectEvent={(eventId) => {
                      const match = (eventsQuery.data ?? []).find((event) => event.id === eventId);
                      if (!match) {
                        return;
                      }
                      setValues({ eventId, monitorId: match.monitor_id });
                      setMapFocusNonce((current) => current + 1);
                    }}
                  />
                </Panel>
                <EventIntelligencePanel
                  loading={intelligenceQuery.isLoading}
                  error={intelligenceQuery.error ? (intelligenceQuery.error as Error).message : null}
                  intelligence={intelligenceQuery.data ?? null}
                  event={selectedEvent}
                />
              </div>
            </ResizePanel>
          </>
        ) : null}
      </PanelGroup>

      {panelState.timeline ? (
        <Panel>
          <PanelHeader title="Event Timeline" subtitle="Chronological event feed for current Explore filters" />
          {!timelineEvents.length ? (
            <p className="px-3 py-4 text-sm text-argus-muted">No events available for timeline.</p>
          ) : (
            <div className="argus-scroll flex gap-2 overflow-x-auto px-3 py-3">
              {timelineEvents.map((event) => {
                const active = event.id === selectedEventId;
                return (
                  <button
                    key={`timeline-${event.id}`}
                    type="button"
                    onClick={() => {
                      setValues({ eventId: event.id, monitorId: event.monitor_id });
                      setMapFocusNonce((current) => current + 1);
                    }}
                    className={`argus-soft-lift min-w-[190px] rounded-md border px-3 py-2 text-left ${
                      active ? "border-argus-accent bg-argus-accent/16" : "border-argus-border bg-argus-panel"
                    }`}
                  >
                    <p className="text-xs font-semibold">Event {event.id.slice(0, 8)}</p>
                    <p className="mt-1 text-[11px] text-argus-muted">{formatDate(event.first_detected_at)}</p>
                    <p className="mt-1 text-[11px] text-argus-muted">Confidence {formatPercent(event.confidence * 100, 1)}</p>
                  </button>
                );
              })}
            </div>
          )}
        </Panel>
      ) : null}
    </div>
  );
}
