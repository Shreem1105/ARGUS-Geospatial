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
  onSelect: () => void;
};

export function CommandPalette() {
  const { commandPaletteOpen, setCommandPaletteOpen } = useUiState();
  const router = useRouter();
  const monitorsQuery = useMonitorsQuery({ limit: 20, offset: 0 });

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
        label: "Open Explore",
        group: "Navigation",
        shortcut: "G E",
        onSelect: () => router.push("/explore"),
      },
      {
        id: "go-monitors",
        label: "Open Monitors",
        group: "Navigation",
        shortcut: "G M",
        onSelect: () => router.push("/monitors"),
      },
      {
        id: "go-monitor-new",
        label: "Create Monitor",
        group: "Navigation",
        shortcut: "G N",
        onSelect: () => router.push("/monitors/new"),
      },
      {
        id: "go-events",
        label: "Open Global Events",
        group: "Navigation",
        shortcut: "G V",
        onSelect: () => router.push("/events"),
      },
      {
        id: "go-runs",
        label: "Open Global Runs",
        group: "Navigation",
        shortcut: "G R",
        onSelect: () => router.push("/runs"),
      },
    ];

    const monitorActions = (monitorsQuery.data ?? []).map((monitor) => ({
      id: `monitor-${monitor.id}`,
      label: `Open Monitor: ${monitor.name}`,
      group: "Monitors",
      onSelect: () => router.push(`/monitors/${monitor.id}`),
    }));

    return [...base, ...monitorActions];
  }, [monitorsQuery.data, router]);

  return (
    <Command.Dialog
      open={commandPaletteOpen}
      onOpenChange={setCommandPaletteOpen}
      label="ARGUS Command Palette"
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 pt-24"
    >
      <div className="w-full max-w-2xl overflow-hidden rounded-xl border border-argus-border bg-argus-panel shadow-panel">
        <div className="flex items-center gap-2 border-b border-argus-border px-3 py-2">
          <Search size={16} className="text-argus-muted" />
          <Command.Input
            className="w-full bg-transparent py-2 text-sm text-argus-text outline-none placeholder:text-argus-muted"
            placeholder="Search commands, pages, or monitors…"
          />
        </div>
        <Command.List className="max-h-[60vh] overflow-y-auto p-2">
          <Command.Empty className="px-3 py-6 text-sm text-argus-muted">No matches.</Command.Empty>
          <Command.Group heading="Navigation" className="px-1 pb-2 text-xs text-argus-muted">
            {actions
              .filter((action) => action.group === "Navigation")
              .map((action) => (
                <Command.Item
                  key={action.id}
                  value={action.label}
                  onSelect={() => {
                    action.onSelect();
                    setCommandPaletteOpen(false);
                  }}
                  className="mb-1 flex cursor-pointer items-center justify-between rounded-md px-3 py-2 text-sm aria-selected:bg-argus-panelMuted"
                >
                  <span>{action.label}</span>
                  {action.shortcut ? <span className="argus-kbd">{action.shortcut}</span> : null}
                </Command.Item>
              ))}
          </Command.Group>
          <Command.Group heading="Monitors" className="px-1 pb-2 text-xs text-argus-muted">
            {actions
              .filter((action) => action.group === "Monitors")
              .map((action) => (
                <Command.Item
                  key={action.id}
                  value={action.label}
                  onSelect={() => {
                    action.onSelect();
                    setCommandPaletteOpen(false);
                  }}
                  className="mb-1 cursor-pointer rounded-md px-3 py-2 text-sm aria-selected:bg-argus-panelMuted"
                >
                  {action.label}
                </Command.Item>
              ))}
          </Command.Group>
        </Command.List>
      </div>
    </Command.Dialog>
  );
}
