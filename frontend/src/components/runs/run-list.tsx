"use client";

import { Badge, Panel, PanelHeader } from "@/components/ui";
import { formatDate, formatDateUtc, formatElapsed, formatNumber, fromNow, titleCase } from "@/lib/format";
import type { MonitorRun } from "@/types/api";

type RunListProps = {
  runs: MonitorRun[];
  selectedRunId?: string | null;
  onSelectRun?: (runId: string) => void;
  onCancelJob?: (jobId: string) => void;
  cancellingJobId?: string | null;
};

function toneForStatus(status: MonitorRun["status"]): "default" | "good" | "warn" | "danger" {
  if (status === "succeeded") {
    return "good";
  }
  if (status === "failed" || status === "cancelled") {
    return "danger";
  }
  if (status === "no_new_imagery" || status === "partial") {
    return "warn";
  }
  return "default";
}

function statusLabel(status: MonitorRun["status"]): string {
  if (status === "no_new_imagery") {
    return "No New Imagery (skipped)";
  }
  return titleCase(status);
}

export function RunList({ runs, selectedRunId, onSelectRun, onCancelJob, cancellingJobId }: RunListProps) {
  return (
    <Panel>
      <PanelHeader title="Run History" subtitle="Monitor-run orchestration timeline" />
      {!runs.length ? (
        <p className="px-3 py-4 text-sm text-argus-muted">No runs yet.</p>
      ) : (
        <ul className="argus-scroll max-h-[360px] space-y-2 overflow-y-auto p-3">
          {runs.map((run) => {
            const active = selectedRunId === run.id;
            return (
              <li key={run.id}>
                <button
                  type="button"
                  onClick={() => onSelectRun?.(run.id)}
                  className={`w-full rounded-md border px-3 py-2 text-left ${
                    active ? "border-argus-accent bg-argus-accent/10" : "border-argus-border bg-argus-panel"
                  }`}
                >
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <Badge tone={toneForStatus(run.status)}>{statusLabel(run.status)}</Badge>
                    <span className="text-xs text-argus-muted">{fromNow(run.started_at)}</span>
                  </div>

                  <div className="grid grid-cols-2 gap-y-1 text-xs text-argus-muted">
                    <span>Trigger: {run.run_type}</span>
                    <span>Elapsed: {formatElapsed(run.started_at, run.completed_at)}</span>
                    <span>Obs found: {formatNumber(run.observations_found, 0)}</span>
                    <span>Obs inserted: {formatNumber(run.observations_inserted, 0)}</span>
                    <span>Events generated: {formatNumber(run.events_generated, 0)}</span>
                    <span>Analysis: {run.analysis_id ? run.analysis_id.slice(0, 8) : "—"}</span>
                    <span>Impact computed: {run.impacts_computed ? "yes" : "no"}</span>
                    <span>Exposure computed: {run.exposures_computed ? "yes" : "no"}</span>
                    <span>Started (local): {formatDate(run.started_at)}</span>
                    <span>Started (UTC): {formatDateUtc(run.started_at)}</span>
                  </div>
                </button>

                {run.status === "started" && onCancelJob ? (
                  <button
                    type="button"
                    onClick={() => onCancelJob(run.analysis_job_id)}
                    disabled={cancellingJobId === run.analysis_job_id}
                    className="mt-1 rounded-md border border-red-500/40 bg-red-500/10 px-2 py-1 text-xs text-red-200"
                  >
                    {cancellingJobId === run.analysis_job_id ? "Cancelling…" : "Cancel run"}
                  </button>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
