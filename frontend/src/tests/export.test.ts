import { describe, expect, it, vi } from "vitest";

import { copyText } from "@/lib/export";

describe("export helpers", () => {
  it("copyText returns false if clipboard unavailable", async () => {
    const originalClipboard = globalThis.navigator.clipboard;
    vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) } });

    const result = await copyText("abc");
    expect(result).toBe(false);

    vi.stubGlobal("navigator", { clipboard: originalClipboard });
  });
});
