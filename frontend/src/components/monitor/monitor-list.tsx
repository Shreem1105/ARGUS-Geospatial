"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui";
import { formatArea, formatDate } from "@/lib/format";
import type { Monitor, MonitorSpatialSummary } from "@/types/api";

type MonitorListProps = {
  monitors: Monitor[];
  summaries?: Record<string, MonitorSpatialSummary | undefined>;
  selectedMonitorId?: string | null;
};

export function MonitorList({ monitors, summaries = {}, selectedMonitorId }: MonitorListProps) {
  if (!monitors.length) {
    return <p className="px-3 py-4 text-sm text-argus-muted">No monitors found.</p>;
  }

  return (
    <ul className="argus-scroll max-h-[560px] space-y-1.5 overflow-y-auto p-3">
      {monitors.map((monitor) => {
        const summary = summaries[monitor.id];
        const active = selectedMonitorId === monitor.id;
        return (
          <li key={monitor.id}>
            <Link
              href={`/monitors/${monitor.id}`}
              className={`argus-soft-lift block rounded-md border p-3 transition ${
                active
                  ? "border-argus-accent bg-argus-accent/14"
                  : "border-argus-border bg-argus-panel hover:border-argus-muted/50"
              }`}
            >
              <div className="mb-1 flex items-center justify-between gap-2">
                <p className="truncate text-sm font-semibold">{monitor.name}</p>
                <ChevronRight size={14} className="text-argus-muted" />
              </div>
              <div className="mb-2 flex items-center gap-2 text-xs text-argus-muted">
                <Badge tone={monitor.status === "active" ? "good" : "default"}>{monitor.status}</Badge>
                <span>{monitor.monitor_type}</span>
              </div>
              <div className="space-y-1 text-xs text-argus-muted">
                <p>Updated: {formatDate(monitor.updated_at)}</p>
                <p>Area: {summary ? formatArea(summary.area_m2) : "—"}</p>
                <p>Last analyzed: {formatDate(monitor.last_analyzed_at)}</p>
              </div>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
