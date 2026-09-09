"use client";

import { Command } from "cmdk";
import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo } from "react";

import { useMonitorsQuery } from "@/hooks/queries";
import { useUiState } from "@/state/ui-state";

type PaletteAction = {
  id: string;
  label: string;
  group: string;
  shortcut?: string;
  onSelect: () => void | Promise<void>;
};

function emitWorkspaceEvent(name: string, detail?: unknown) {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new CustomEvent(name, { detail }));
}

function currentSelectedEventUrl(): string | null {
  if (typeof window === "undefined") {
    return null;
  }

  const params = new URLSearchParams(window.location.search);
  const eventId = params.get("eventId");
  const monitorFromQuery = params.get("monitorId");
  const monitorFromPath = /^\/monitors\/([^/]+)/.exec(window.location.pathname)?.[1] ?? null;
  const monitorId = monitorFromQuery ?? monitorFromPath;

  if (!eventId || !monitorId) {
    return null;
  }

  return `/monitors/${monitorId}?eventId=${encodeURIComponent(eventId)}`;
}

export function CommandPalette() {
  const { commandPaletteOpen, setCommandPaletteOpen, togglePanel } = useUiState();
  const router = useRouter();
  const monitorsQuery = useMonitorsQuery({ limit: 40, offset: 0 });

  const actions = useMemo<PaletteAction[]>(() => {
    const base: PaletteAction[] = [
      {
        id: "go-home",
        label: "Go to Product Home",
        group: "Navigation",
        shortcut: "G H",
        onSelect: () => router.push("/"),
      },
      {
        id: "go-explore",
        label: "Go to Explore",
        group: "Navigation",
        shortcut: "G E",
        onSelect: () => router.push("/explore"),
      },
      {
        id: "go-monitors",
        label: "Go to Monitors",
        group: "Navigation",
        shortcut: "G M",
        onSelect: () => router.push("/monitors"),
      },
      {
        id: "go-monitor-new",
        label: "Create Monitor",
        group: "Navigation",
        shortcut: "N",
        onSelect: () => router.push("/monitors/new"),
      },
      {
        id: "go-events",
        label: "Go to Events",
        group: "Navigation",
        shortcut: "G V",
        onSelect: () => router.push("/events"),
      },
      {
        id: "go-runs",
        label: "Go to Runs",
        group: "Navigation",
        shortcut: "G R",
        onSelect: () => router.push("/runs"),
      },
      {
        id: "toggle-left",
        label: "Toggle Left Panel",
        group: "Workspace",
        shortcut: "L",
        onSelect: () => togglePanel("left"),
      },
      {
        id: "toggle-right",
        label: "Toggle Intelligence Panel",
        group: "Workspace",
        shortcut: "I",
        onSelect: () => togglePanel("right"),
      },
      {
        id: "toggle-timeline",
        label: "Toggle Timeline",
        group: "Workspace",
        shortcut: "T",
        onSelect: () => togglePanel("timeline"),
      },
      {
        id: "fit-selection",
        label: "Fit Selected Event / AOI",
        group: "Workspace",
        shortcut: "F",
        onSelect: () => emitWorkspaceEvent("argus:fit-selection"),
      },
      {
        id: "event-prev",
        label: "Select Previous Event",
        group: "Event",
        shortcut: "[",
        onSelect: () => emitWorkspaceEvent("argus:event-nav", { type: "event_nav", direction: "prev" }),
      },
      {
        id: "event-next",
        label: "Select Next Event",
        group: "Event",
        shortcut: "]",
        onSelect: () => emitWorkspaceEvent("argus:event-nav", { type: "event_nav", direction: "next" }),
      },
      {
        id: "open-selected-event",
        label: "Open Current Selected Event",
        group: "Event",
        shortcut: "O",
        onSelect: () => {
          const href = currentSelectedEventUrl();
          if (href) {
            router.push(href);
            return;
          }
          router.push("/events");
        },
      },
      {
        id: "copy-link",
        label: "Copy Current Deep Link",
        group: "Workspace",
        shortcut: "Y",
        onSelect: () => {
          if (typeof window !== "undefined") {
            void navigator.clipboard?.writeText(window.location.href).catch(() => undefined);
          }
        },
      },
    ];

    const monitorActions: PaletteAction[] = (monitorsQuery.data ?? []).map((monitor) => ({
      id: `monitor-${monitor.id}`,
      label: `Open Monitor: ${monitor.name}`,
      group: "Monitors",
      onSelect: () => router.push(`/monitors/${monitor.id}`),
    }));

    return [...base, ...monitorActions];
  }, [monitorsQuery.data, router, togglePanel]);

  const grouped = useMemo(() => {
    const map = new Map<string, PaletteAction[]>();
    for (const action of actions) {
      const group = map.get(action.group) ?? [];
      group.push(action);
      map.set(action.group, group);
    }
    return map;
  }, [actions]);

  const runAction = async (action: PaletteAction) => {
    await action.onSelect();
    setCommandPaletteOpen(false);
  };

  return (
    <Command.Dialog
      open={commandPaletteOpen}
      onOpenChange={setCommandPaletteOpen}
      label="ARGUS Command Palette"
      className="fixed inset-0 z-[60] flex items-start justify-center bg-black/70 pt-16 md:pt-24"
    >
      <div className="w-[min(56rem,96vw)] overflow-hidden rounded-xl border border-argus-border bg-argus-panel shadow-workspace">
        <div className="flex items-center gap-2 border-b border-argus-border px-3 py-2.5">
          <Search size={16} className="text-argus-muted" />
          <Command.Input
            className="w-full bg-transparent py-1.5 text-sm text-argus-text outline-none placeholder:text-argus-muted"
            placeholder="Search routes, monitors, and workspace actions"
          />
        </div>

        <Command.List className="argus-scroll max-h-[68vh] overflow-y-auto p-2">
          <Command.Empty className="px-3 py-6 text-sm text-argus-muted">No command matches.</Command.Empty>

          {Array.from(grouped.entries()).map(([group, groupActions]) => (
            <Command.Group key={group} heading={group} className="px-1 pb-2 text-xs text-argus-muted">
              {groupActions.map((action) => (
                <Command.Item
                  key={action.id}
                  value={action.label}
                  onSelect={() => {
                    void runAction(action);
                  }}
                  className="mb-1 flex cursor-pointer items-center justify-between rounded-md border border-transparent px-3 py-2 text-sm aria-selected:border-argus-accent/45 aria-selected:bg-argus-panelMuted"
                >
                  <span>{action.label}</span>
                  {action.shortcut ? <span className="argus-kbd">{action.shortcut}</span> : null}
                </Command.Item>
              ))}
            </Command.Group>
          ))}
        </Command.List>
      </div>
    </Command.Dialog>
  );
}
