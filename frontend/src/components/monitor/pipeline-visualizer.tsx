"use client";

import { Panel, PanelHeader } from "@/components/ui";
import { buildPipelineSteps } from "@/lib/pipeline";
import { formatElapsed, formatPercent } from "@/lib/format";
import type { AnalysisJob, MonitorRun } from "@/types/api";

type PipelineVisualizerProps = {
  run: MonitorRun | null;
  job: AnalysisJob | null;
};

function classesForState(state: string): string {
  if (state === "done") {
    return "border-argus-good/45 bg-argus-good/10 text-argus-good";
  }
  if (state === "active") {
    return "border-argus-accent/60 bg-argus-accent/15 text-argus-text";
  }
  if (state === "failed") {
    return "border-argus-danger/45 bg-argus-danger/10 text-argus-danger";
  }
  if (state === "skipped") {
    return "border-argus-warn/45 bg-argus-warn/10 text-argus-warn";
  }
  return "border-argus-border bg-argus-panel text-argus-muted";
}

export function PipelineVisualizer({ run, job }: PipelineVisualizerProps) {
  const steps = buildPipelineSteps(run, job);

  return (
    <Panel>
      <PanelHeader
        title="Run Pipeline"
        subtitle="Satellite → Prepare → Detect → Vectorize → Context → Exposure"
        actions={
          run ? (
            <span className="text-[11px] text-argus-muted">Elapsed: {formatElapsed(run.started_at, run.completed_at)}</span>
          ) : null
        }
      />

      <div className="space-y-3 p-3">
        <div className="argus-scroll flex gap-2 overflow-x-auto pb-1">
          {steps.map((step, index) => (
            <div key={step.key} className={`min-w-[132px] rounded-lg border px-2.5 py-2 ${classesForState(step.state)}`}>
              <div className="mb-1 flex items-center justify-between gap-2 text-[11px] uppercase tracking-wide">
                <span>{index + 1}</span>
                <span>{step.state}</span>
              </div>
              <p className="text-xs font-semibold text-current">{step.label}</p>
              <p className="mt-1 text-[11px] opacity-90">{step.detail}</p>
            </div>
          ))}
        </div>

        {job ? (
          <div className="argus-panel-muted space-y-1 px-3 py-2 text-[11px] text-argus-muted">
            <div className="flex items-center justify-between">
              <span>Active stage</span>
              <span>{job.progress_stage.replaceAll("_", " ")}</span>
            </div>
            <div className="flex items-center justify-between">
              <span>Status</span>
              <span>{job.status}</span>
            </div>
            <div className="flex items-center justify-between">
              <span>Progress</span>
              <span>{formatPercent(job.progress_percent, 0)}</span>
            </div>
          </div>
        ) : null}
      </div>
    </Panel>
  );
}
