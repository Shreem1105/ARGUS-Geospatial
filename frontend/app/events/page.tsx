"use client";

import { useMemo, useState } from "react";

import { EventList } from "@/components/events/event-list";
import { ErrorState, Panel, PanelHeader } from "@/components/ui";
import { useGlobalEventsQuery, useMonitorsQuery } from "@/hooks/queries";
import { formatArea, formatPercent } from "@/lib/format";

export default function GlobalEventsPage() {
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("");
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);

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

  const monitorName = useMemo(() => {
    if (!selectedEvent) {
      return "—";
    }
    return (monitorsQuery.data ?? []).find((monitor) => monitor.id === selectedEvent.monitor_id)?.name ?? selectedEvent.monitor_id;
  }, [monitorsQuery.data, selectedEvent]);

  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Panel className="xl:col-span-1">
        <PanelHeader title="Global Events" subtitle="Cross-monitor change-event feed" />
        <div className="flex gap-2 border-b border-argus-border p-3 text-xs">
          <select value={severity} onChange={(e) => setSeverity(e.target.value)} className="rounded border border-argus-border bg-argus-panel px-2 py-1">
            <option value="">All severities</option>
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
            <option value="critical">critical</option>
          </select>
          <select value={status} onChange={(e) => setStatus(e.target.value)} className="rounded border border-argus-border bg-argus-panel px-2 py-1">
            <option value="">All statuses</option>
            <option value="new">new</option>
            <option value="reviewed">reviewed</option>
            <option value="dismissed">dismissed</option>
            <option value="confirmed">confirmed</option>
          </select>
        </div>
        {eventsQuery.error ? <ErrorState detail={(eventsQuery.error as Error).message} /> : null}
        <EventList events={eventsQuery.data ?? []} selectedEventId={selectedEventId} onSelectEvent={setSelectedEventId} />
      </Panel>

      <Panel className="xl:col-span-2 p-4">
        <h2 className="text-base font-semibold">Event details</h2>
        {!selectedEvent ? (
          <p className="mt-2 text-sm text-argus-muted">Select an event from the list to inspect details.</p>
        ) : (
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <div className="rounded-md border border-argus-border bg-argus-panelMuted p-3">
              <p className="text-xs text-argus-muted">Event ID</p>
              <p className="mt-1 text-sm font-semibold">{selectedEvent.id}</p>
            </div>
            <div className="rounded-md border border-argus-border bg-argus-panelMuted p-3">
              <p className="text-xs text-argus-muted">Monitor</p>
              <p className="mt-1 text-sm font-semibold">{monitorName}</p>
            </div>
            <div className="rounded-md border border-argus-border bg-argus-panelMuted p-3">
              <p className="text-xs text-argus-muted">Scientific severity</p>
              <p className="mt-1 text-sm font-semibold">{selectedEvent.severity}</p>
            </div>
            <div className="rounded-md border border-argus-border bg-argus-panelMuted p-3">
              <p className="text-xs text-argus-muted">Confidence</p>
              <p className="mt-1 text-sm font-semibold">{formatPercent(selectedEvent.confidence * 100, 1)}</p>
            </div>
            <div className="rounded-md border border-argus-border bg-argus-panelMuted p-3">
              <p className="text-xs text-argus-muted">Area</p>
              <p className="mt-1 text-sm font-semibold">{formatArea(selectedEvent.area_m2)}</p>
            </div>
            <div className="rounded-md border border-argus-border bg-argus-panelMuted p-3">
              <p className="text-xs text-argus-muted">Status</p>
              <p className="mt-1 text-sm font-semibold">{selectedEvent.status}</p>
            </div>
          </div>
        )}
      </Panel>
    </div>
  );
}
