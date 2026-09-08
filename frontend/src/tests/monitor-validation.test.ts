import { describe, expect, it } from "vitest";

import { validateMonitorPolygon } from "@/lib/monitor-validation";

const validPolygon = {
  type: "Polygon" as const,
  coordinates: [
    [
      [-80.85, 35.22],
      [-80.84, 35.22],
      [-80.84, 35.23],
      [-80.85, 35.23],
      [-80.85, 35.22],
    ],
  ],
};

describe("validateMonitorPolygon", () => {
  it("accepts a valid polygon", () => {
    expect(validateMonitorPolygon(validPolygon)).toBeNull();
  });

  it("requires a polygon", () => {
    expect(validateMonitorPolygon(null)).toBe("AOI polygon is required.");
  });

  it("rejects non-polygon objects", () => {
    expect(
      validateMonitorPolygon({
        type: "Point",
        coordinates: [-80.85, 35.22],
      } as never),
    ).toBe("AOI must be a valid GeoJSON Polygon.");
  });

  it("rejects too-short rings", () => {
    expect(
      validateMonitorPolygon({
        type: "Polygon",
        coordinates: [
          [
            [-80.85, 35.22],
            [-80.84, 35.22],
            [-80.84, 35.23],
          ],
        ],
      }),
    ).toBe("AOI polygon ring must include at least 4 positions.");
  });

  it("requires closed outer ring", () => {
    expect(
      validateMonitorPolygon({
        type: "Polygon",
        coordinates: [
          [
            [-80.85, 35.22],
            [-80.84, 35.22],
            [-80.84, 35.23],
            [-80.85, 35.23],
            [-80.84, 35.22],
          ],
        ],
      }),
    ).toBe("AOI polygon must be closed (first and last coordinate must match).");
  });
});
