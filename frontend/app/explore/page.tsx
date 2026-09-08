"use client";

import Link from "next/link";
import { RefreshCw } from "lucide-react";
import { Group as PanelGroup, Panel as ResizePanel, Separator as PanelResizeHandle } from "react-resizable-panels";

import { EventIntelligencePanel } from "@/components/events/event-intelligence-panel";
import { CuratedExploreEmptyState } from "@/components/explore/curated-empty-state";
import { ArgusMap } from "@/components/map/argus-map";
import { EventList } from "@/components/events/event-list";
import { ErrorState, LoadingState, Panel, PanelHeader } from "@/components/ui";
import { useEventIntelligenceQuery, useGlobalEventsQuery, useMonitorsQuery } from "@/hooks/queries";
import { useUrlState } from "@/hooks/url-state";
import { curatedScenarios } from "@/lib/curated-scenarios";

export default function ExplorePage() {
  const { values, setValues } = useUrlState();
  const monitorId = values.monitorId ?? null;
  const selectedEventId = values.eventId ?? null;

  const monitorsQuery = useMonitorsQuery({ limit: 100, offset: 0 });
  const eventsQuery = useGlobalEventsQuery({
    limit: 200,
    offset: 0,
    severity: values.severity,
    status: values.status,
    monitor_id: monitorId ?? undefined,
  });

  const selectedMonitor = (monitorsQuery.data ?? []).find((monitor) => monitor.id === monitorId) ?? null;
  const selectedEvent = (eventsQuery.data ?? []).find((event) => event.id === selectedEventId) ?? null;

  const intelligenceQuery = useEventIntelligenceQuery(selectedEvent?.monitor_id ?? null, selectedEvent?.id ?? null);

  const noCurated = curatedScenarios.length === 0;

  return (
    <div className="space-y-3">
      <Panel className="p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className="text-lg font-semibold">Explore workspace</h1>
            <p className="text-xs text-argus-muted">Public, map-first exploration of persisted ARGUS intelligence data</p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <select
              value={values.severity ?? ""}
              onChange={(event) => setValues({ severity: event.target.value || null })}
              className="rounded-md border border-argus-border bg-argus-panel px-2 py-1"
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
              className="rounded-md border border-argus-border bg-argus-panel px-2 py-1"
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
              className="inline-flex items-center gap-1 rounded-md border border-argus-border bg-argus-panel px-2 py-1 text-argus-muted"
            >
              <RefreshCw size={12} /> Refresh
            </button>
          </div>
        </div>

        {!noCurated ? (
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            {curatedScenarios.map((scenario) => (
              <Link
                key={scenario.id}
                href={`/explore/${scenario.id}`}
                className="rounded border border-argus-border bg-argus-panel px-2 py-1 text-argus-muted hover:text-argus-text"
              >
                {scenario.title}
              </Link>
            ))}
          </div>
        ) : null}
      </Panel>

      {noCurated ? <CuratedExploreEmptyState /> : null}

      {monitorsQuery.isLoading || eventsQuery.isLoading ? <LoadingState label="Loading Explore map and events…" /> : null}
      {monitorsQuery.error ? <ErrorState detail={(monitorsQuery.error as Error).message} /> : null}
      {eventsQuery.error ? <ErrorState detail={(eventsQuery.error as Error).message} /> : null}

      <PanelGroup orientation="horizontal" className="min-h-[680px] overflow-hidden rounded-lg border border-argus-border">
        <ResizePanel defaultSize={64} minSize={40}>
          <ArgusMap
            monitor={selectedMonitor}
            events={eventsQuery.data ?? []}
            selectedEventId={selectedEventId}
            onSelectEvent={(eventId) => {
              const match = (eventsQuery.data ?? []).find((event) => event.id === eventId);
              setValues({ eventId, monitorId: match?.monitor_id ?? null });
            }}
            className="h-full min-h-[680px]"
          />
        </ResizePanel>

        <PanelResizeHandle className="w-1 bg-argus-border" />

        <ResizePanel defaultSize={36} minSize={24}>
          <div className="grid h-full grid-rows-[1fr,1fr] gap-2 bg-argus-bg p-2">
            <Panel className="overflow-hidden">
              <PanelHeader title="Events" subtitle="Real persisted change-event rows" />
              <EventList
                events={eventsQuery.data ?? []}
                selectedEventId={selectedEventId}
                onSelectEvent={(eventId) => {
                  const match = (eventsQuery.data ?? []).find((event) => event.id === eventId);
                  setValues({ eventId, monitorId: match?.monitor_id ?? null });
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
      </PanelGroup>
    </div>
  );
}
