"use client";

import { useMemo, useState } from "react";

import { MonitorCreateForm } from "@/components/monitor/monitor-create-form";
import { MonitorList } from "@/components/monitor/monitor-list";
import { ErrorState, LoadingState, Panel, PanelHeader } from "@/components/ui";
import { useMonitorMutations, useMonitorsQuery } from "@/hooks/queries";

export default function MonitorWorkspacePage() {
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [monitorTypeFilter, setMonitorTypeFilter] = useState<string>("");
  const [createError, setCreateError] = useState<string | null>(null);

  const monitorsQuery = useMonitorsQuery({
    limit: 100,
    offset: 0,
    status: statusFilter || undefined,
    monitorType: monitorTypeFilter || undefined,
  });

  const { createMonitor } = useMonitorMutations();

  const monitorTypes = useMemo(() => {
    const values = new Set<string>();
    for (const monitor of monitorsQuery.data ?? []) {
      values.add(monitor.monitor_type);
    }
    return [...values].sort();
  }, [monitorsQuery.data]);

  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Panel className="overflow-hidden xl:col-span-1">
        <PanelHeader title="Monitors" subtitle="Operational monitor inventory" />
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

      <div className="xl:col-span-2">
        <MonitorCreateForm
          submitting={createMonitor.isPending}
          error={createError}
          onSubmit={async (payload) => {
            setCreateError(null);
            try {
              await createMonitor.mutateAsync(payload);
              await monitorsQuery.refetch();
            } catch (error) {
              setCreateError((error as Error).message);
            }
          }}
        />
      </div>
    </div>
  );
}
