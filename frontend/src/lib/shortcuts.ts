import type { WorkspacePanel } from "@/state/ui-state";

export type ShortcutSequence = {
  token: "g" | null;
  expiresAt: number;
};

export type ShortcutAction =
  | { type: "open_palette" }
  | { type: "open_shortcuts" }
  | { type: "close_overlays" }
  | { type: "navigate"; path: string }
  | { type: "event_nav"; direction: "prev" | "next" }
  | { type: "fit_selection" }
  | { type: "toggle_panel"; panel: WorkspacePanel }
  | { type: "copy_deep_link" }
  | { type: "open_selected_event" };

export type ShortcutResult = {
  handled: boolean;
  action?: ShortcutAction;
  sequence: ShortcutSequence;
};

const DEFAULT_SEQUENCE_TIMEOUT_MS = 900;

type ShortcutInput = {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
  now: number;
  sequence: ShortcutSequence;
  sequenceTimeoutMs?: number;
};

const GO_SEQUENCE_MAP: Record<string, string> = {
  h: "/",
  e: "/explore",
  m: "/monitors",
  n: "/monitors/new",
  v: "/events",
  r: "/runs",
};

export const shortcutReferenceRows: Array<{ keys: string; detail: string }> = [
  { keys: "Ctrl/Cmd + K", detail: "Open command palette" },
  { keys: "G then E", detail: "Go to Explore" },
  { keys: "G then M", detail: "Go to Monitors" },
  { keys: "N", detail: "Create monitor" },
  { keys: "[ / ]", detail: "Previous / next event" },
  { keys: "F", detail: "Fit selected event or AOI" },
  { keys: "L / I / T", detail: "Toggle left, intelligence, and timeline panels" },
  { keys: "Y", detail: "Copy current deep link" },
  { keys: "O", detail: "Open currently selected event" },
  { keys: "?", detail: "Open shortcuts help" },
  { keys: "Esc", detail: "Close overlays" },
];

export function emptyShortcutSequence(now = 0): ShortcutSequence {
  return { token: null, expiresAt: now };
}

function normalizeKey(key: string): string {
  return key.length === 1 ? key.toLowerCase() : key.toLowerCase();
}

function sequenceIsActive(sequence: ShortcutSequence, now: number): boolean {
  return sequence.token !== null && now <= sequence.expiresAt;
}

function withSequence(token: "g" | null, now: number, timeoutMs: number): ShortcutSequence {
  return {
    token,
    expiresAt: token ? now + timeoutMs : now,
  };
}

export function resolveShortcutAction(input: ShortcutInput): ShortcutResult {
  const {
    key,
    ctrlKey,
    metaKey,
    altKey,
    shiftKey,
    now,
    sequence,
    sequenceTimeoutMs = DEFAULT_SEQUENCE_TIMEOUT_MS,
  } = input;

  const normalizedKey = normalizeKey(key);
  const activeSequence = sequenceIsActive(sequence, now) ? sequence : emptyShortcutSequence(now);
  const clearSequence = withSequence(null, now, sequenceTimeoutMs);

  if ((ctrlKey || metaKey) && normalizedKey === "k") {
    return { handled: true, action: { type: "open_palette" }, sequence: clearSequence };
  }

  if (altKey && !ctrlKey && !metaKey) {
    if (normalizedKey === "1") {
      return { handled: true, action: { type: "navigate", path: "/explore" }, sequence: clearSequence };
    }
    if (normalizedKey === "2") {
      return { handled: true, action: { type: "navigate", path: "/monitors" }, sequence: clearSequence };
    }
    if (normalizedKey === "3") {
      return { handled: true, action: { type: "navigate", path: "/events" }, sequence: clearSequence };
    }
    if (normalizedKey === "4") {
      return { handled: true, action: { type: "navigate", path: "/runs" }, sequence: clearSequence };
    }
  }

  if (normalizedKey === "escape") {
    return { handled: true, action: { type: "close_overlays" }, sequence: clearSequence };
  }

  if (!ctrlKey && !metaKey && !altKey) {
    if (activeSequence.token === "g") {
      const path = GO_SEQUENCE_MAP[normalizedKey];
      if (path) {
        return { handled: true, action: { type: "navigate", path }, sequence: clearSequence };
      }
      return { handled: false, sequence: clearSequence };
    }

    if (normalizedKey === "g") {
      return { handled: true, sequence: withSequence("g", now, sequenceTimeoutMs) };
    }

    if (normalizedKey === "n") {
      return { handled: true, action: { type: "navigate", path: "/monitors/new" }, sequence: clearSequence };
    }

    if (normalizedKey === "f") {
      return { handled: true, action: { type: "fit_selection" }, sequence: clearSequence };
    }

    if (normalizedKey === "[") {
      return { handled: true, action: { type: "event_nav", direction: "prev" }, sequence: clearSequence };
    }

    if (normalizedKey === "]") {
      return { handled: true, action: { type: "event_nav", direction: "next" }, sequence: clearSequence };
    }

    if (normalizedKey === "l") {
      return { handled: true, action: { type: "toggle_panel", panel: "left" }, sequence: clearSequence };
    }

    if (normalizedKey === "i") {
      return { handled: true, action: { type: "toggle_panel", panel: "right" }, sequence: clearSequence };
    }

    if (normalizedKey === "t") {
      return { handled: true, action: { type: "toggle_panel", panel: "timeline" }, sequence: clearSequence };
    }

    if (normalizedKey === "y") {
      return { handled: true, action: { type: "copy_deep_link" }, sequence: clearSequence };
    }

    if (normalizedKey === "o") {
      return { handled: true, action: { type: "open_selected_event" }, sequence: clearSequence };
    }

    if (normalizedKey === "?" || (normalizedKey === "/" && shiftKey)) {
      return { handled: true, action: { type: "open_shortcuts" }, sequence: clearSequence };
    }
  }

  return { handled: false, sequence: activeSequence };
}

