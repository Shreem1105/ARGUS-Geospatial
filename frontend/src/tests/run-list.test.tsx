import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RunList } from "@/components/runs/run-list";
import type { MonitorRun } from "@/types/api";

function sampleRun(overrides: Partial<MonitorRun> = {}): MonitorRun {
  return {
    id: "run-1",
    monitor_id: "monitor-1",
    analysis_job_id: "job-1",
    run_type: "manual",
    status: "started",
    search_window_start: "2026-09-01T00:00:00Z",
    search_window_end: "2026-09-02T00:00:00Z",
    observations_found: 3,
    observations_inserted: 2,
    before_observation_id: null,
    after_observation_id: null,
    before_prepared_id: null,
    after_prepared_id: null,
    analysis_id: "analysis-1",
    events_generated: 4,
    impacts_computed: true,
    exposures_computed: false,
    progress_log: [],
    requested_parameters: {},
    result: null,
    error: null,
    started_at: "2026-09-01T00:00:00Z",
    completed_at: "2026-09-01T00:10:00Z",
    updated_at: "2026-09-01T00:10:00Z",
    ...overrides,
  };
}

describe("RunList", () => {
  it("renders empty state", () => {
    render(<RunList runs={[]} />);
    expect(screen.getByText(/No runs yet/i)).toBeInTheDocument();
  });

  it("shows informational label for no_new_imagery", () => {
    render(<RunList runs={[sampleRun({ status: "no_new_imagery" })]} />);
    expect(screen.getByText(/No New Imagery \(skipped\)/i)).toBeInTheDocument();
  });

  it("calls cancel callback for active started run", () => {
    const onCancel = vi.fn();
    render(<RunList runs={[sampleRun({ status: "started", completed_at: null })]} onCancelJob={onCancel} />);

    fireEvent.click(screen.getByRole("button", { name: /Cancel run/i }));
    expect(onCancel).toHaveBeenCalledWith("job-1");
  });

  it("calls selection callback", () => {
    const onSelect = vi.fn();
    render(<RunList runs={[sampleRun()]} onSelectRun={onSelect} />);

    fireEvent.click(screen.getByRole("button", { name: /Started/i }));
    expect(onSelect).toHaveBeenCalledWith("run-1");
  });
});
