"use client";

import { Panel, PanelHeader } from "@/components/ui";
import type { MonitorRun } from "@/types/api";

type PipelineVisualizerProps = {
  run: MonitorRun | null;
};

const stages = [
  "search_observations",
  "prepare_before",
  "prepare_after",
  "change_analysis",
  "generate_events",
  "compute_impact",
  "compute_exposure",
  "completed",
] as const;

export function PipelineVisualizer({ run }: PipelineVisualizerProps) {
  const progressStages = new Set(
    (run?.progress_log ?? [])
      .map((entry) => (typeof entry.stage === "string" ? entry.stage : null))
      .filter((value): value is string => Boolean(value)),
  );

  return (
    <Panel>
      <PanelHeader title="Pipeline" subtitle="Run orchestration progress" />
      <div className="space-y-2 p-3">
        {stages.map((stage) => {
          const reached = progressStages.has(stage) || run?.status === "succeeded";
          return (
            <div
              key={stage}
              className={`flex items-center justify-between rounded-md border px-3 py-2 text-xs ${
                reached ? "border-argus-good/40 bg-argus-good/10 text-argus-good" : "border-argus-border text-argus-muted"
              }`}
            >
              <span>{stage}</span>
              <span>{reached ? "done" : "pending"}</span>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}
