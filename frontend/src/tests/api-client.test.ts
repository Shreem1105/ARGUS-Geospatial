import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiRequest } from "@/api/client";

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

  it("throws ApiError with detail", async () => {
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
});
