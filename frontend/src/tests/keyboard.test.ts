import { describe, expect, it } from "vitest";

import { isTextEntryTarget } from "@/lib/keyboard";

describe("isTextEntryTarget", () => {
  it("returns true for form fields", () => {
    const input = document.createElement("input");
    const textarea = document.createElement("textarea");
    const select = document.createElement("select");

    expect(isTextEntryTarget(input)).toBe(true);
    expect(isTextEntryTarget(textarea)).toBe(true);
    expect(isTextEntryTarget(select)).toBe(true);
  });

  it("returns true for contenteditable nodes", () => {
    const editable = document.createElement("div");
    editable.setAttribute("contenteditable", "true");
    const child = document.createElement("span");
    editable.appendChild(child);
    document.body.appendChild(editable);

    expect(isTextEntryTarget(editable)).toBe(true);
    expect(isTextEntryTarget(child)).toBe(true);

    editable.remove();
  });

  it("returns false for non-editable nodes", () => {
    const div = document.createElement("div");
    expect(isTextEntryTarget(div)).toBe(false);
    expect(isTextEntryTarget(null)).toBe(false);
  });
});
