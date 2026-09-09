import { describe, expect, it } from "vitest";

import { motionDuration, prefersReducedMotion, REDUCED_MOTION_QUERY } from "@/lib/motion";

describe("motion utilities", () => {
  it("detects reduced motion when matcher reports matches", () => {
    const value = prefersReducedMotion((query) => {
      expect(query).toBe(REDUCED_MOTION_QUERY);
      return { matches: true };
    });

    expect(value).toBe(true);
  });

  it("returns false when matcher reports no reduced motion", () => {
    expect(prefersReducedMotion(() => ({ matches: false }))).toBe(false);
  });

  it("returns reduced duration when reduction is requested", () => {
    expect(motionDuration(500, 0, true)).toBe(0);
  });

  it("returns base duration when reduction is not requested", () => {
    expect(motionDuration(500, 0, false)).toBe(500);
  });
});

