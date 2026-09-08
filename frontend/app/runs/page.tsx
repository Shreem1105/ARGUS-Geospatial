"use client";

import { useState } from "react";

import { RunList } from "@/components/runs/run-list";
import { ErrorState, Panel, PanelHeader } from "@/components/ui";
import { useGlobalRunsQuery } from "@/hooks/queries";

export default function GlobalRunsPage() {
  const [status, setStatus] = useState("");
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  const runsQuery = useGlobalRunsQuery({ limit: 200, offset: 0, status: status || undefined });

  return (
    <div className="space-y-4">
      <Panel>
        <PanelHeader title="Global Runs" subtitle="Cross-monitor async run history" />
        <div className="border-b border-argus-border p-3 text-xs">
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            className="rounded border border-argus-border bg-argus-panel px-2 py-1"
          >
            <option value="">All statuses</option>
            <option value="started">started</option>
            <option value="succeeded">succeeded</option>
            <option value="no_new_imagery">no_new_imagery</option>
            <option value="partial">partial</option>
            <option value="failed">failed</option>
            <option value="cancelled">cancelled</option>
          </select>
        </div>
        {runsQuery.error ? <ErrorState detail={(runsQuery.error as Error).message} /> : null}
        <RunList runs={runsQuery.data ?? []} selectedRunId={selectedRunId} onSelectRun={setSelectedRunId} />
      </Panel>
    </div>
  );
}
