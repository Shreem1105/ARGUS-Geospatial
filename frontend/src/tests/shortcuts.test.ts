import { describe, expect, it } from "vitest";

import { emptyShortcutSequence, resolveShortcutAction } from "@/lib/shortcuts";

function resolve(key: string, sequence = emptyShortcutSequence(0), now = 1000) {
  return resolveShortcutAction({
    key,
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    shiftKey: false,
    now,
    sequence,
  });
}

describe("resolveShortcutAction", () => {
  it("opens palette with ctrl/cmd+k", () => {
    const result = resolveShortcutAction({
      key: "k",
      ctrlKey: true,
      metaKey: false,
      altKey: false,
      shiftKey: false,
      now: 100,
      sequence: emptyShortcutSequence(0),
    });

    expect(result.handled).toBe(true);
    expect(result.action?.type).toBe("open_palette");
  });

  it("resolves g then e sequence to explore navigation", () => {
    const first = resolve("g");
    expect(first.handled).toBe(true);
    expect(first.action).toBeUndefined();

    const second = resolve("e", first.sequence, 1200);
    expect(second.action).toEqual({ type: "navigate", path: "/explore" });
  });

  it("ignores expired sequences", () => {
    const first = resolve("g");
    const second = resolve("e", first.sequence, 5000);
    expect(second.action).toBeUndefined();
  });

  it("supports event navigation shortcuts", () => {
    expect(resolve("[").action).toEqual({ type: "event_nav", direction: "prev" });
    expect(resolve("]").action).toEqual({ type: "event_nav", direction: "next" });
  });

  it("supports panel toggle shortcuts", () => {
    expect(resolve("l").action).toEqual({ type: "toggle_panel", panel: "left" });
    expect(resolve("i").action).toEqual({ type: "toggle_panel", panel: "right" });
    expect(resolve("t").action).toEqual({ type: "toggle_panel", panel: "timeline" });
  });

  it("opens shortcuts help with shifted slash", () => {
    const result = resolveShortcutAction({
      key: "/",
      ctrlKey: false,
      metaKey: false,
      altKey: false,
      shiftKey: true,
      now: 100,
      sequence: emptyShortcutSequence(0),
    });

    expect(result.action).toEqual({ type: "open_shortcuts" });
  });
});

