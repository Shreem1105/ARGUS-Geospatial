import { describe, expect, it } from "vitest";

import { formatArea, formatDate, formatMeters, formatNumber, formatPercent, fromNow, titleCase } from "@/lib/format";

describe("format utils", () => {
  it("formats numeric values", () => {
    expect(formatNumber(1234.567, 1)).toBe("1,234.6");
    expect(formatNumber(null)).toBe("—");
  });

  it("formats meters and areas", () => {
    expect(formatMeters(75)).toContain("75");
    expect(formatMeters(1_500)).toContain("km");
    expect(formatArea(800)).toContain("m²");
    expect(formatArea(2_000_000)).toContain("km²");
  });

  it("formats percentages", () => {
    expect(formatPercent(12.345, 1)).toBe("12.3%");
    expect(formatPercent(undefined)).toBe("—");
  });

  it("formats dates and relative times", () => {
    expect(formatDate("2026-09-01T00:00:00Z")).toContain("2026");
    expect(fromNow("2026-09-01T00:00:00Z")).toBeTypeOf("string");
  });

  it("converts snake case to title case", () => {
    expect(titleCase("no_new_imagery")).toBe("No New Imagery");
  });
});
