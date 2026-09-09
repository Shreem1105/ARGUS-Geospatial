"use client";

import { Keyboard, X } from "lucide-react";

import { shortcutReferenceRows } from "@/lib/shortcuts";

type ShortcutsDialogProps = {
  open: boolean;
  onOpenChange: (next: boolean) => void;
};

export function ShortcutsDialog({ open, onOpenChange }: ShortcutsDialogProps) {
  if (!open) {
    return null;
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Keyboard shortcuts"
      className="fixed inset-0 z-[65] flex items-center justify-center bg-black/65 px-4"
      onClick={() => onOpenChange(false)}
    >
      <div
        className="w-full max-w-xl overflow-hidden rounded-xl border border-argus-border bg-argus-panel shadow-workspace"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-argus-border px-4 py-3">
          <div className="flex items-center gap-2">
            <Keyboard size={16} className="text-argus-accent" />
            <h2 className="text-sm font-semibold">Keyboard shortcuts</h2>
          </div>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="argus-control"
            aria-label="Close keyboard shortcuts"
          >
            <X size={14} />
            Close
          </button>
        </header>

        <div className="argus-scroll max-h-[70vh] space-y-2 overflow-y-auto p-4">
          {shortcutReferenceRows.map((entry) => (
            <div key={entry.keys} className="argus-panel-muted flex items-center justify-between gap-3 px-3 py-2 text-xs">
              <span className="text-argus-muted">{entry.detail}</span>
              <span className="argus-kbd whitespace-nowrap">{entry.keys}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

