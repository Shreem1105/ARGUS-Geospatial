import { describe, expect, it } from "vitest";

import { buildPipelineSteps, mapStageToPipelineStep, normalizeStageName } from "@/lib/pipeline";
import type { AnalysisJob, MonitorRun } from "@/types/api";

function sampleRun(overrides: Partial<MonitorRun> = {}): MonitorRun {
  return {
    id: "run-1",
    monitor_id: "monitor-1",
    analysis_job_id: "job-1",
    run_type: "manual",
    status: "started",
    search_window_start: "2026-09-01T00:00:00Z",
    search_window_end: "2026-09-02T00:00:00Z",
    observations_found: 2,
    observations_inserted: 2,
    before_observation_id: "obs-1",
    after_observation_id: "obs-2",
    before_prepared_id: null,
    after_prepared_id: null,
    analysis_id: null,
    events_generated: 0,
    semantics_computed: false,
    impacts_computed: false,
    exposures_computed: false,
    progress_log: [{ stage: "searching_observations" }, { stage: "preparing_observations" }],
    requested_parameters: {},
    result: null,
    error: null,
    started_at: "2026-09-01T00:00:00Z",
    completed_at: null,
    updated_at: "2026-09-01T00:00:30Z",
    ...overrides,
  };
}

function sampleJob(overrides: Partial<AnalysisJob> = {}): AnalysisJob {
  return {
    id: "job-1",
    monitor_id: "monitor-1",
    job_type: "monitor_run",
    status: "running",
    celery_task_id: "task-1",
    progress_stage: "running_analysis",
    progress_percent: 45,
    requested_parameters: {},
    result: null,
    error: null,
    created_at: "2026-09-01T00:00:00Z",
    started_at: "2026-09-01T00:00:05Z",
    completed_at: null,
    updated_at: "2026-09-01T00:00:30Z",
    ...overrides,
  };
}

describe("pipeline mapping", () => {
  it("maps known backend stage names", () => {
    expect(mapStageToPipelineStep("searching_observations")).toBe("satellite");
    expect(mapStageToPipelineStep("preparing_observations")).toBe("prepare");
    expect(mapStageToPipelineStep("computing_semantics")).toBe("semantic");
    expect(mapStageToPipelineStep("computing_exposures")).toBe("exposure");
  });

  it("normalizes retry stage prefix", () => {
    expect(normalizeStageName("retry_preparing_observations")).toBe("preparing_observations");
    expect(mapStageToPipelineStep("retry_running_analysis")).toBe("detect");
  });

  it("marks active stage when job is running", () => {
    const steps = buildPipelineSteps(sampleRun(), sampleJob());
    expect(steps.find((step) => step.key === "detect")?.state).toBe("active");
    expect(steps.find((step) => step.key === "detect")?.detail).toContain("45");
  });

  it("marks non-imagery runs as skipped downstream", () => {
    const steps = buildPipelineSteps(sampleRun({ status: "no_new_imagery" }), sampleJob({ status: "succeeded", progress_stage: "no_new_imagery" }));
    expect(steps.find((step) => step.key === "satellite")?.detail).toBe("no new imagery");
    expect(steps.find((step) => step.key === "prepare")?.state).toBe("skipped");
  });

  it("marks all steps done when run succeeded", () => {
    const steps = buildPipelineSteps(sampleRun({ status: "succeeded" }), sampleJob({ status: "succeeded", progress_stage: "completed" }));
    expect(steps.every((step) => step.state === "done")).toBe(true);
  });

  it("marks active step failed when run is cancelled", () => {
    const steps = buildPipelineSteps(sampleRun({ status: "cancelled" }), sampleJob({ status: "cancelled", progress_stage: "running_analysis" }));
    expect(steps.find((step) => step.key === "detect")?.state).toBe("failed");
    expect(steps.find((step) => step.key === "detect")?.detail).toBe("cancelled");
  });
});
