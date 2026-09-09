"use client";

import { createContext, PropsWithChildren, useContext, useEffect, useMemo, useState } from "react";

export type AppMode = "explore" | "monitor";
export type WorkspacePanel = "left" | "right" | "timeline";

type PanelState = Record<WorkspacePanel, boolean>;

type UiStateContextValue = {
  commandPaletteOpen: boolean;
  setCommandPaletteOpen: (next: boolean) => void;
  shortcutsOpen: boolean;
  setShortcutsOpen: (next: boolean) => void;
  mode: AppMode;
  setMode: (mode: AppMode) => void;
  panelState: PanelState;
  setPanelOpen: (panel: WorkspacePanel, open: boolean) => void;
  togglePanel: (panel: WorkspacePanel) => void;
};

const UiStateContext = createContext<UiStateContextValue | null>(null);

const PANEL_STATE_STORAGE_KEY = "argus.panel-state";

const DEFAULT_PANEL_STATE: PanelState = {
  left: true,
  right: true,
  timeline: true,
};

function readPanelState(): PanelState {
  if (typeof window === "undefined") {
    return DEFAULT_PANEL_STATE;
  }

  const raw = window.sessionStorage.getItem(PANEL_STATE_STORAGE_KEY);
  if (!raw) {
    return DEFAULT_PANEL_STATE;
  }

  try {
    const parsed = JSON.parse(raw) as Partial<PanelState>;
    return {
      left: parsed.left ?? DEFAULT_PANEL_STATE.left,
      right: parsed.right ?? DEFAULT_PANEL_STATE.right,
      timeline: parsed.timeline ?? DEFAULT_PANEL_STATE.timeline,
    };
  } catch {
    return DEFAULT_PANEL_STATE;
  }
}

export function UiStateProvider({ children }: PropsWithChildren) {
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [mode, setMode] = useState<AppMode>("explore");
  const [panelState, setPanelState] = useState<PanelState>(() => readPanelState());

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    window.sessionStorage.setItem(PANEL_STATE_STORAGE_KEY, JSON.stringify(panelState));
  }, [panelState]);

  const setPanelOpen = (panel: WorkspacePanel, open: boolean) => {
    setPanelState((previous) => ({ ...previous, [panel]: open }));
  };

  const togglePanel = (panel: WorkspacePanel) => {
    setPanelState((previous) => ({ ...previous, [panel]: !previous[panel] }));
  };

  const value = useMemo(
    () => ({
      commandPaletteOpen,
      setCommandPaletteOpen,
      shortcutsOpen,
      setShortcutsOpen,
      mode,
      setMode,
      panelState,
      setPanelOpen,
      togglePanel,
    }),
    [commandPaletteOpen, mode, panelState, shortcutsOpen],
  );

  return <UiStateContext.Provider value={value}>{children}</UiStateContext.Provider>;
}

export function useUiState() {
  const context = useContext(UiStateContext);
  if (!context) {
    throw new Error("useUiState must be used within UiStateProvider");
  }
  return context;
}
