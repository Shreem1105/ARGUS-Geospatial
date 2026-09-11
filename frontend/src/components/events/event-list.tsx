"use client";

import clsx from "clsx";

import { Badge } from "@/components/ui";
import { formatArea, formatDate, formatPercent } from "@/lib/format";
import type { ChangeEvent } from "@/types/api";

const severityTone: Record<string, "default" | "good" | "warn" | "danger"> = {
  low: "good",
  medium: "warn",
  high: "danger",
  critical: "danger",
};

type EventListProps = {
  events: ChangeEvent[];
  selectedEventId?: string | null;
  onSelectEvent?: (eventId: string) => void;
};

export function EventList({ events, selectedEventId, onSelectEvent }: EventListProps) {
  if (!events.length) {
    return <p className="px-3 py-4 text-sm text-argus-muted">No change events for current filters.</p>;
  }

  return (
    <ul className="argus-scroll max-h-[420px] space-y-1.5 overflow-y-auto p-3">
      {events.map((event) => {
        const selected = selectedEventId === event.id;

        return (
          <li key={event.id}>
            <button
              type="button"
              onClick={() => onSelectEvent?.(event.id)}
              className={clsx(
                "argus-soft-lift w-full rounded-md border px-3 py-2 text-left transition",
                selected
                  ? "border-argus-accent bg-argus-accent/14"
                  : "border-argus-border bg-argus-panel hover:border-argus-muted/50",
              )}
            >
              <div className="mb-1.5 flex items-center justify-between gap-2">
                <p className="truncate text-sm font-semibold">Event {event.id.slice(0, 8)}</p>
                <Badge tone={severityTone[event.severity] ?? "default"}>{event.severity}</Badge>
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] text-argus-muted">
                <span>Confidence: {formatPercent(event.confidence * 100, 1)}</span>
                <span>Status: {event.status}</span>
                <span>Area: {formatArea(event.area_m2)}</span>
                <span>Detected: {formatDate(event.first_detected_at)}</span>
                <span>Semantic: {event.semantic_label ?? "—"}</span>
                <span>
                  Semantic confidence: {event.semantic_confidence === null ? "—" : formatPercent(event.semantic_confidence * 100, 1)}
                </span>
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
