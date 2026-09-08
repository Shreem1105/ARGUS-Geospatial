"use client";

import { Panel, PanelHeader } from "@/components/ui";
import { buildPipelineSteps } from "@/lib/pipeline";
import type { AnalysisJob, MonitorRun } from "@/types/api";

type PipelineVisualizerProps = {
  run: MonitorRun | null;
  job: AnalysisJob | null;
};

export function PipelineVisualizer({ run, job }: PipelineVisualizerProps) {
  const steps = buildPipelineSteps(run, job);

  return (
    <Panel>
      <PanelHeader title="Pipeline" subtitle="Satellite → Prepare → Detect → Vectorize → Context → Exposure" />
      <div className="space-y-2 p-3">
        {steps.map((step) => {
          const className =
            step.state === "done"
              ? "border-argus-good/40 bg-argus-good/10 text-argus-good"
              : step.state === "active"
                ? "border-argus-accent/50 bg-argus-accent/10 text-argus-text"
                : step.state === "failed"
                  ? "border-argus-danger/50 bg-argus-danger/10 text-argus-danger"
                  : step.state === "skipped"
                    ? "border-argus-warn/40 bg-argus-warn/10 text-argus-warn"
                    : "border-argus-border text-argus-muted";

          return (
            <div key={step.key} className={`rounded-md border px-3 py-2 ${className}`}>
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold">{step.label}</span>
                <span>{step.state}</span>
              </div>
              <p className="mt-1 text-[11px] opacity-90">{step.detail}</p>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}
