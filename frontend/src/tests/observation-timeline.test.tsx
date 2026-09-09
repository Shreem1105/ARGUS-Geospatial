import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ObservationTimeline } from "@/components/monitor/observation-timeline";
import type { SatelliteObservation } from "@/types/api";

function sampleObservation(id: string, acquiredAt: string): SatelliteObservation {
  return {
    id,
    monitor_id: "monitor-1",
    provider: "planetary_computer",
    collection: "sentinel-2-l2a",
    item_id: id,
    platform: "sentinel-2b",
    sensor: "MSI",
    acquired_at: acquiredAt,
    cloud_cover: 12.5,
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
    bbox: [-80.85, 35.22, -80.84, 35.23],
    thumbnail_url: null,
    assets: {},
    metadata: {},
    created_at: "2026-09-01T00:00:00Z",
  };
}

describe("ObservationTimeline", () => {
  it("shows empty state when no observations exist", () => {
    render(<ObservationTimeline observations={[]} />);
    expect(screen.getByText(/No observations persisted yet/i)).toBeInTheDocument();
  });

  it("renders timeline markers and supports selection", () => {
    const onSelect = vi.fn();
    const first = sampleObservation("obs-a", "2026-08-01T00:00:00Z");
    const second = sampleObservation("obs-b", "2026-09-01T00:00:00Z");

    render(
      <ObservationTimeline
        observations={[second, first]}
        selectedObservationId="obs-a"
        beforeObservationId="obs-a"
        afterObservationId="obs-b"
        onSelectObservation={onSelect}
      />,
    );

    expect(screen.getByText("Before")).toBeInTheDocument();
    expect(screen.getByText("After")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /obs-b/i }));
    expect(onSelect).toHaveBeenCalledWith("obs-b");
  });
});

