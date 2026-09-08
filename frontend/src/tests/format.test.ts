import { describe, expect, it, vi } from "vitest";

import {
  formatArea,
  formatDate,
  formatDateUtc,
  formatElapsed,
  formatMeters,
  formatNumber,
  formatPercent,
  fromNow,
  titleCase,
} from "@/lib/format";

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

  it("formats local and UTC dates", () => {
    const iso = "2026-09-01T12:34:56Z";
    expect(formatDate(iso)).toContain("2026");
    expect(formatDateUtc(iso)).toBe("2026-09-01 12:34:56 UTC");
    expect(formatDateUtc("bad-date")).toBe("bad-date");
  });

  it("formats elapsed durations", () => {
    expect(formatElapsed("2026-09-01T00:00:00Z", "2026-09-01T00:00:05Z")).toBe("5s");
    expect(formatElapsed("2026-09-01T00:00:00Z", "2026-09-01T00:01:05Z")).toBe("1m 05s");
    expect(formatElapsed("2026-09-01T00:00:00Z", "2026-09-01T01:01:05Z")).toBe("1h 01m");
    expect(formatElapsed("bad", "2026-09-01T00:01:05Z")).toBe("—");
  });

  it("formats relative times", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-08T00:00:00Z"));
    expect(fromNow("2026-09-01T00:00:00Z")).toBeTypeOf("string");
    vi.useRealTimers();
  });

  it("converts snake case to title case", () => {
    expect(titleCase("no_new_imagery")).toBe("No New Imagery");
  });
});
