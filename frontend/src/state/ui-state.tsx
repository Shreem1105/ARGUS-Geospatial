"use client";

import { createContext, PropsWithChildren, useContext, useMemo, useState } from "react";

export type AppMode = "explore" | "monitor";

type UiStateContextValue = {
  commandPaletteOpen: boolean;
  setCommandPaletteOpen: (next: boolean) => void;
  mode: AppMode;
  setMode: (mode: AppMode) => void;
};

const UiStateContext = createContext<UiStateContextValue | null>(null);

export function UiStateProvider({ children }: PropsWithChildren) {
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [mode, setMode] = useState<AppMode>("explore");

  const value = useMemo(
    () => ({
      commandPaletteOpen,
      setCommandPaletteOpen,
      mode,
      setMode,
    }),
    [commandPaletteOpen, mode],
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
