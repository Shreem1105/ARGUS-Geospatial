"use client";

import { useMemo, useState } from "react";
import { Group as PanelGroup, Panel as ResizePanel, Separator as PanelResizeHandle } from "react-resizable-panels";

import { EventList } from "@/components/events/event-list";
import { ArgusMap } from "@/components/map/argus-map";
import { ErrorState, LoadingState, Panel, PanelHeader } from "@/components/ui";
import { useRequireAuth } from "@/hooks/auth";
import { useGlobalEventsQuery, useMonitorsQuery } from "@/hooks/queries";
import { formatArea, formatPercent } from "@/lib/format";

export default function GlobalEventsPage() {
  const auth = useRequireAuth();

  if (auth.isLoading || auth.isRedirecting) {
    return <LoadingState label="Checking session…" />;
  }

  return <GlobalEventsWorkspace />;
}

function GlobalEventsWorkspace() {
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("");
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [focusNonce, setFocusNonce] = useState(0);

  const monitorsQuery = useMonitorsQuery({ limit: 100, offset: 0 });
  const eventsQuery = useGlobalEventsQuery({
    limit: 200,
    offset: 0,
    severity: severity || undefined,
    status: status || undefined,
  });

  const selectedEvent = useMemo(
    () => (eventsQuery.data ?? []).find((event) => event.id === selectedEventId) ?? null,
    [eventsQuery.data, selectedEventId],
  );

  const selectedMonitor = useMemo(() => {
    if (!selectedEvent) {
      return null;
    }
    return (monitorsQuery.data ?? []).find((monitor) => monitor.id === selectedEvent.monitor_id) ?? null;
  }, [monitorsQuery.data, selectedEvent]);

  const monitorName = selectedMonitor?.name ?? selectedEvent?.monitor_id ?? "—";

  return (
    <div className="space-y-3">
      <Panel className="p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className="text-lg font-semibold">Global Events</h1>
            <p className="text-xs text-argus-muted">Cross-monitor event feed with map-first selection context</p>
          </div>
          <div className="flex gap-2 text-xs">
            <select value={severity} onChange={(event) => setSeverity(event.target.value)} className="argus-field" aria-label="Filter severity">
              <option value="">All severities</option>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="critical">critical</option>
            </select>
            <select value={status} onChange={(event) => setStatus(event.target.value)} className="argus-field" aria-label="Filter status">
              <option value="">All statuses</option>
              <option value="new">new</option>
              <option value="reviewed">reviewed</option>
              <option value="dismissed">dismissed</option>
              <option value="confirmed">confirmed</option>
            </select>
          </div>
        </div>
      </Panel>

      {eventsQuery.error ? <ErrorState detail={(eventsQuery.error as Error).message} /> : null}

      <PanelGroup orientation="horizontal" className="min-h-[72vh] overflow-hidden rounded-xl border border-argus-border shadow-workspace">
        <ResizePanel defaultSize={24} minSize={20}>
          <Panel className="h-full rounded-none border-0 border-r border-argus-border">
            <PanelHeader title="Events" subtitle="Select to focus geometry" />
            <EventList
              events={eventsQuery.data ?? []}
              selectedEventId={selectedEventId}
              onSelectEvent={(eventId) => {
                setSelectedEventId(eventId);
                setFocusNonce((value) => value + 1);
              }}
            />
          </Panel>
        </ResizePanel>

        <PanelResizeHandle className="w-1 bg-argus-border" />

        <ResizePanel defaultSize={50} minSize={42}>
          <ArgusMap
            monitor={selectedMonitor}
            events={selectedEvent ? [selectedEvent] : eventsQuery.data ?? []}
            selectedEventId={selectedEventId}
            onSelectEvent={(eventId) => {
              setSelectedEventId(eventId);
              setFocusNonce((value) => value + 1);
            }}
            className="h-full min-h-[72vh]"
            focusNonce={focusNonce}
          />
        </ResizePanel>

        <PanelResizeHandle className="w-1 bg-argus-border" />

        <ResizePanel defaultSize={26} minSize={20}>
          <Panel className="h-full rounded-none border-0 border-l border-argus-border p-3">
            <h2 className="text-sm font-semibold">Event Inspector</h2>
            {!selectedEvent ? (
              <p className="mt-2 text-sm text-argus-muted">Select an event from the feed to inspect details.</p>
            ) : (
              <div className="mt-3 space-y-2 text-xs">
                <InspectorRow label="Event ID" value={selectedEvent.id} mono />
                <InspectorRow label="Monitor" value={monitorName} />
                <InspectorRow label="Scientific severity" value={selectedEvent.severity} />
                <InspectorRow label="Confidence" value={formatPercent(selectedEvent.confidence * 100, 1)} />
                <InspectorRow label="Area" value={formatArea(selectedEvent.area_m2)} />
                <InspectorRow label="Status" value={selectedEvent.status} />
              </div>
            )}
          </Panel>
        </ResizePanel>
      </PanelGroup>
    </div>
  );
}

function InspectorRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="argus-panel-muted px-2.5 py-2">
      <p className="text-[11px] text-argus-muted">{label}</p>
      <p className={mono ? "mt-1 break-all font-mono text-[11px] text-argus-text" : "mt-1 text-sm text-argus-text"}>{value}</p>
    </div>
  );
}