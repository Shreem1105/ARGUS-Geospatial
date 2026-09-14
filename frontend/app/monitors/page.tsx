"use client";

import Link from "next/link";
import { Plus, RefreshCw } from "lucide-react";
import { useState } from "react";

import { MonitorList } from "@/components/monitor/monitor-list";
import { ErrorState, LoadingState, Panel, PanelHeader } from "@/components/ui";
import { useRequireAuth } from "@/hooks/auth";
import { useMonitorsQuery } from "@/hooks/queries";

export default function MonitorsPage() {
  const auth = useRequireAuth();

  if (auth.isLoading || auth.isRedirecting) {
    return <LoadingState label="Checking session…" />;
  }

  return <MonitorsWorkspace />;
}

function MonitorsWorkspace() {
  const [statusFilter, setStatusFilter] = useState("");
  const [monitorTypeFilter, setMonitorTypeFilter] = useState("");

  const monitorsQuery = useMonitorsQuery({
    limit: 100,
    offset: 0,
    status: statusFilter || undefined,
    monitorType: monitorTypeFilter || undefined,
  });

  const monitorTypes = Array.from(new Set((monitorsQuery.data ?? []).map((monitor) => monitor.monitor_type))).sort();

  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Panel className="overflow-hidden xl:col-span-2">
        <PanelHeader
          title="Monitors"
          subtitle="Operational monitor inventory"
          actions={
            <div className="flex items-center gap-2 text-xs">
              <button
                type="button"
                onClick={() => void monitorsQuery.refetch()}
                className="inline-flex items-center gap-1 rounded border border-argus-border bg-argus-panel px-2 py-1 text-argus-muted"
              >
                <RefreshCw size={12} /> Refresh
              </button>
              <Link href="/monitors/new" className="inline-flex items-center gap-1 rounded border border-argus-border bg-argus-accent px-2 py-1 font-semibold text-black">
                <Plus size={12} /> New Monitor
              </Link>
            </div>
          }
        />

        <div className="border-b border-argus-border p-3">
          <div className="grid gap-2 sm:grid-cols-2">
            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
              className="rounded-md border border-argus-border bg-argus-panel px-2 py-1 text-xs"
            >
              <option value="">All statuses</option>
              <option value="active">active</option>
              <option value="paused">paused</option>
              <option value="archived">archived</option>
            </select>

            <select
              value={monitorTypeFilter}
              onChange={(event) => setMonitorTypeFilter(event.target.value)}
              className="rounded-md border border-argus-border bg-argus-panel px-2 py-1 text-xs"
            >
              <option value="">All types</option>
              {monitorTypes.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </div>
        </div>

        {monitorsQuery.isLoading ? <LoadingState label="Loading monitors…" /> : null}
        {monitorsQuery.error ? <ErrorState detail={(monitorsQuery.error as Error).message} /> : null}
        <MonitorList monitors={monitorsQuery.data ?? []} />
      </Panel>

      <Panel className="p-4">
        <h2 className="text-sm font-semibold">Monitor Mode</h2>
        <p className="mt-2 text-sm text-argus-muted">
          Monitor mode connects directly to live backend workflows for AOI creation, observation search, run orchestration,
          event review, and contextual intelligence.
        </p>
        <div className="mt-4 space-y-2 text-xs text-argus-muted">
          <p>• Create AOIs in `/monitors/new`</p>
          <p>• Inspect full workspace at `/monitors/[monitorId]`</p>
          <p>• Use `/events` and `/runs` for cross-monitor views</p>
        </div>
      </Panel>
    </div>
  );
}