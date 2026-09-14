import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiRequest, extractApiErrorDetail } from "@/api/client";

describe("apiRequest", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.cookie = "argus_csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
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

  it("extracts structured quota errors", () => {
    const detail = extractApiErrorDetail(429, {
      detail: {
        code: "quota_exceeded",
        quota: "max_manual_runs_per_day",
        used: 5,
        limit: 5,
      },
    });

    expect(detail).toBe("Daily manual-run limit reached (5/5).");
  });

  it("extracts structured rate-limit errors", () => {
    const detail = extractApiErrorDetail(429, {
      detail: {
        code: "rate_limited",
        scope: "auth_login",
        retry_after_seconds: 30,
      },
    });

    expect(detail).toBe("Rate limit exceeded for auth_login. Retry in 30s.");
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

  it("dispatches auth-expired event when refresh is unavailable", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      text: async () => JSON.stringify({ detail: "expired" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const expiredListener = vi.fn();
    window.addEventListener("argus:auth-expired", expiredListener);

    await expect(apiRequest("/monitors", { method: "GET" })).rejects.toEqual(new ApiError(401, "expired"));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(expiredListener).toHaveBeenCalledTimes(1);
    window.removeEventListener("argus:auth-expired", expiredListener);
  });

  it("refreshes and retries once for eligible 401 responses", async () => {
    document.cookie = "argus_csrf_token=test-token; path=/";

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        text: async () => JSON.stringify({ detail: "expired" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        text: async () => "",
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        text: async () => JSON.stringify({ status: "retried" }),
      });

    vi.stubGlobal("fetch", fetchMock);

    await expect(apiRequest<{ status: string }>("/monitors", { method: "GET" })).resolves.toEqual({ status: "retried" });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/backend/monitors");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/backend/auth/refresh");
    expect(fetchMock.mock.calls[2][0]).toBe("/api/backend/monitors");
  });
});