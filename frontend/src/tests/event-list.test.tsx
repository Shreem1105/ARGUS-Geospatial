import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EventList } from "@/components/events/event-list";
import type { ChangeEvent } from "@/types/api";

function sampleEvent(id: string): ChangeEvent {
  return {
    id,
    monitor_id: "monitor-1",
    analysis_id: "analysis-1",
    geometry: {
      type: "Polygon",
      coordinates: [
        [
          [-80.85, 35.22],
          [-80.84, 35.22],
          [-80.84, 35.23],
          [-80.85, 35.23],
          [-80.85, 35.22],
        ],
      ],
    },
    centroid: { type: "Point", coordinates: [-80.845, 35.225] },
    area_m2: 1450,
    perimeter_m: 200,
    confidence: 0.8,
    severity: "high",
    mean_change_score: 0.5,
    max_change_score: 0.9,
    mean_abs_delta_ndvi: 0.1,
    mean_spectral_distance: 0.2,
    pixel_count: 35,
    first_detected_at: "2026-09-01T10:00:00Z",
    last_detected_at: "2026-09-01T10:00:00Z",
    status: "new",
    properties: {},
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-01T10:00:00Z",
  };
}

describe("EventList", () => {
  it("renders empty state", () => {
    render(<EventList events={[]} />);
    expect(screen.getByText(/No change events/i)).toBeInTheDocument();
  });

  it("renders events and triggers selection", () => {
    const onSelect = vi.fn();
    render(<EventList events={[sampleEvent("event-1")]} onSelectEvent={onSelect} />);

    fireEvent.click(screen.getByRole("button", { name: /Event event-1/i }));
    expect(onSelect).toHaveBeenCalledWith("event-1");
  });
});
