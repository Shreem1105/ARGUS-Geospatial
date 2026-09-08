import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiRequest, extractApiErrorDetail } from "@/api/client";

describe("apiRequest", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns parsed JSON on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        text: async () => JSON.stringify({ status: "ok" }),
      }),
    );

    await expect(apiRequest<{ status: string }>("/health", { method: "GET" })).resolves.toEqual({ status: "ok" });
  });

  it("throws ApiError with detail string", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        text: async () => JSON.stringify({ detail: "not ready" }),
      }),
    );

    await expect(apiRequest("/ready", { method: "GET" })).rejects.toEqual(new ApiError(503, "not ready"));
  });

  it("extracts 422 detail arrays with field paths", () => {
    const detail = extractApiErrorDetail(422, {
      detail: [
        { loc: ["body", "start_date"], msg: "Field required" },
        { loc: ["body", "max_cloud_cover"], msg: "Input should be less than or equal to 100" },
      ],
    });

    expect(detail).toBe("start_date: Field required; max_cloud_cover: Input should be less than or equal to 100");
  });

  it("extracts object detail msg", () => {
    const detail = extractApiErrorDetail(400, { detail: { msg: "Invalid payload" } });
    expect(detail).toBe("Invalid payload");
  });

  it("falls back to status message for unknown detail shape", () => {
    const detail = extractApiErrorDetail(500, { error: "boom" });
    expect(detail).toBe("Request failed (500)");
  });

  it("throws fallback ApiError when body is not json", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        text: async () => "upstream unavailable",
      }),
    );

    await expect(apiRequest("/ready", { method: "GET" })).rejects.toEqual(new ApiError(502, "Request failed (502)"));
  });
});
