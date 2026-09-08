import type { AnalysisJob, MonitorRun } from "@/types/api";

export type PipelineStepKey = "satellite" | "prepare" | "detect" | "vectorize" | "context" | "exposure";
export type PipelineStepState = "pending" | "active" | "done" | "skipped" | "failed";

export type PipelineStep = {
  key: PipelineStepKey;
  label: string;
  state: PipelineStepState;
  detail: string;
};

const PIPELINE_ORDER: PipelineStepKey[] = ["satellite", "prepare", "detect", "vectorize", "context", "exposure"];

const STEP_LABEL: Record<PipelineStepKey, string> = {
  satellite: "Satellite",
  prepare: "Prepare",
  detect: "Detect",
  vectorize: "Vectorize",
  context: "Context",
  exposure: "Exposure",
};

const STAGE_TO_STEP: Record<string, PipelineStepKey> = {
  initializing: "satellite",
  searching_observations: "satellite",
  selecting_scenes: "satellite",
  no_new_imagery: "satellite",
  preparing_observations: "prepare",
  running_analysis: "detect",
  generating_events: "vectorize",
  refreshing_context: "context",
  computing_impacts: "context",
  computing_exposures: "exposure",
  completed: "exposure",
};

export function normalizeStageName(stage: string | null | undefined): string | null {
  if (!stage) {
    return null;
  }

  if (stage.startsWith("retry_")) {
    return stage.slice("retry_".length);
  }

  return stage;
}

export function mapStageToPipelineStep(stage: string | null | undefined): PipelineStepKey | null {
  const normalized = normalizeStageName(stage);
  if (!normalized) {
    return null;
  }
  return STAGE_TO_STEP[normalized] ?? null;
}

function humanizeStage(stage: string | null | undefined): string {
  const normalized = normalizeStageName(stage);
  if (!normalized) {
    return "pending";
  }
  return normalized.replaceAll("_", " ");
}

function extractRunStages(run: MonitorRun | null): string[] {
  const result: string[] = [];

  for (const entry of run?.progress_log ?? []) {
    const stageValue = entry.stage;
    if (typeof stageValue === "string") {
      result.push(stageValue);
    }
  }

  return result;
}

function computeReachedSteps(run: MonitorRun | null): Set<PipelineStepKey> {
  const reached = new Set<PipelineStepKey>();

  for (const stage of extractRunStages(run)) {
    const step = mapStageToPipelineStep(stage);
    if (step) {
      reached.add(step);
    }
  }

  return reached;
}

export function buildPipelineSteps(run: MonitorRun | null, job: AnalysisJob | null): PipelineStep[] {
  const reached = computeReachedSteps(run);
  const activeStep = mapStageToPipelineStep(job?.progress_stage);
  const activeStageLabel = humanizeStage(job?.progress_stage);

  return PIPELINE_ORDER.map((key) => {
    let state: PipelineStepState = reached.has(key) ? "done" : "pending";
    let detail = state === "done" ? "completed" : "pending";

    if (activeStep === key && job && (job.status === "queued" || job.status === "running")) {
      state = "active";
      detail = `${activeStageLabel} (${Math.round(job.progress_percent)}%)`;
    }

    if (run?.status === "no_new_imagery") {
      if (key === "satellite") {
        state = "done";
        detail = "no new imagery";
      } else {
        state = "skipped";
        detail = "skipped";
      }
    }

    if (run?.status === "cancelled" && activeStep === key) {
      state = "failed";
      detail = "cancelled";
    }

    if (run?.status === "failed" && activeStep === key) {
      state = "failed";
      detail = "failed";
    }

    if (run?.status === "succeeded") {
      state = "done";
      detail = "completed";
    }

    return {
      key,
      label: STEP_LABEL[key],
      state,
      detail,
    };
  });
}
