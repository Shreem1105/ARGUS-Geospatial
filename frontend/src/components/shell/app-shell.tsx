"use client";

import clsx from "clsx";
import { Activity, Command, Earth, HelpCircle, Layers, Radar, Satellite } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { PropsWithChildren, useEffect, useMemo, useRef } from "react";

import { CommandPalette } from "@/components/shell/command-palette";
import { ShortcutsDialog } from "@/components/shell/shortcuts-dialog";
import { SystemStatusPill } from "@/components/shell/system-status-pill";
import { isTextEntryTarget } from "@/lib/keyboard";
import { emptyShortcutSequence, resolveShortcutAction } from "@/lib/shortcuts";
import { UiStateProvider, useUiState } from "@/state/ui-state";

const links = [
  { href: "/", label: "Product", icon: Satellite },
  { href: "/explore", label: "Explore", icon: Earth },
  { href: "/monitors", label: "Monitors", icon: Radar },
  { href: "/events", label: "Events", icon: Layers },
  { href: "/runs", label: "Runs", icon: Activity },
];

function isActivePath(pathname: string, href: string): boolean {
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

function emitWorkspaceEvent(name: string, detail?: unknown) {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new CustomEvent(name, { detail }));
}

function AppShellInner({ children }: PropsWithChildren) {
  const pathname = usePathname();
  const router = useRouter();
  const sequenceRef = useRef(emptyShortcutSequence());

  const { commandPaletteOpen, setCommandPaletteOpen, shortcutsOpen, setShortcutsOpen, panelState, togglePanel } = useUiState();

  const modeLabel = useMemo(() => {
    if (pathname.startsWith("/explore")) {
      return "Explore";
    }
    if (pathname.startsWith("/monitors")) {
      return "Monitor";
    }
    if (pathname.startsWith("/events")) {
      return "Events";
    }
    if (pathname.startsWith("/runs")) {
      return "Runs";
    }
    return "Product";
  }, [pathname]);

  useEffect(() => {
    const openSelectedEvent = () => {
      const params = new URLSearchParams(window.location.search);
      const eventId = params.get("eventId");
      const monitorFromQuery = params.get("monitorId");
      const monitorFromPath = /^\/monitors\/([^/]+)/.exec(window.location.pathname)?.[1] ?? null;
      const monitorId = monitorFromQuery ?? monitorFromPath;

      if (!eventId) {
        router.push("/events");
        return;
      }

      if (!monitorId) {
        router.push(`/events?eventId=${encodeURIComponent(eventId)}`);
        return;
      }

      router.push(`/monitors/${monitorId}?eventId=${encodeURIComponent(eventId)}`);
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (isTextEntryTarget(event.target)) {
        return;
      }

      const result = resolveShortcutAction({
        key: event.key,
        ctrlKey: event.ctrlKey,
        metaKey: event.metaKey,
        altKey: event.altKey,
        shiftKey: event.shiftKey,
        now: Date.now(),
        sequence: sequenceRef.current,
      });

      sequenceRef.current = result.sequence;

      if (!result.handled || !result.action) {
        return;
      }

      event.preventDefault();

      if (result.action.type === "open_palette") {
        setShortcutsOpen(false);
        setCommandPaletteOpen(true);
        return;
      }

      if (result.action.type === "open_shortcuts") {
        setCommandPaletteOpen(false);
        setShortcutsOpen(true);
        return;
      }

      if (result.action.type === "close_overlays") {
        setCommandPaletteOpen(false);
        setShortcutsOpen(false);
        return;
      }

      if (result.action.type === "navigate") {
        router.push(result.action.path);
        return;
      }

      if (result.action.type === "fit_selection") {
        emitWorkspaceEvent("argus:fit-selection");
        return;
      }

      if (result.action.type === "event_nav") {
        emitWorkspaceEvent("argus:event-nav", result.action);
        return;
      }

      if (result.action.type === "toggle_panel") {
        togglePanel(result.action.panel);
        return;
      }

      if (result.action.type === "copy_deep_link") {
        void navigator.clipboard?.writeText(window.location.href).catch(() => undefined);
        return;
      }

      if (result.action.type === "open_selected_event") {
        openSelectedEvent();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [router, setCommandPaletteOpen, setShortcutsOpen, togglePanel]);

  return (
    <div className="min-h-screen text-argus-text">
      <div className="pointer-events-none fixed inset-0 -z-10">
        <div className="absolute inset-0 argus-ambient-grid opacity-35" />
        <div className="absolute inset-0 argus-scan-sweep opacity-70" />
      </div>

      <header className="sticky top-0 z-40 border-b border-argus-border/80 bg-argus-bg/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1920px] items-center justify-between gap-4 px-3 py-3 md:px-4">
          <div className="flex items-center gap-3">
            <div className="rounded-lg border border-argus-border bg-argus-panel p-2">
              <Satellite size={17} className="text-argus-accent" />
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-[0.22em] text-argus-muted">ARGUS</p>
              <p className="hidden text-sm font-semibold leading-tight sm:block">Geospatial Intelligence Workspace</p>
              <p className="text-sm font-semibold leading-tight sm:hidden">ARGUS Workspace</p>
              <p className="text-[11px] text-argus-muted">{modeLabel}</p>
            </div>
          </div>

          <nav className="hidden items-center gap-1 xl:flex" aria-label="Primary">
            {links.map((link) => {
              const active = isActivePath(pathname, link.href);
              const Icon = link.icon;

              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={clsx(
                    "argus-soft-lift inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm",
                    active
                      ? "border border-argus-accent/60 bg-argus-accent/15 text-argus-text"
                      : "border border-transparent text-argus-muted hover:border-argus-border hover:bg-argus-panel hover:text-argus-text",
                  )}
                >
                  <Icon size={14} />
                  {link.label}
                </Link>
              );
            })}
          </nav>

          <div className="flex items-center gap-1.5 sm:gap-2">
            <button
              type="button"
              onClick={() => togglePanel("left")}
              className={clsx("argus-control hidden lg:inline-flex", panelState.left && "argus-control-active")}
              aria-label="Toggle left panel"
            >
              L
            </button>
            <button
              type="button"
              onClick={() => togglePanel("right")}
              className={clsx("argus-control hidden lg:inline-flex", panelState.right && "argus-control-active")}
              aria-label="Toggle intelligence panel"
            >
              I
            </button>
            <button
              type="button"
              onClick={() => togglePanel("timeline")}
              className={clsx("argus-control hidden lg:inline-flex", panelState.timeline && "argus-control-active")}
              aria-label="Toggle timeline panel"
            >
              T
            </button>
            <button
              type="button"
              onClick={() => setShortcutsOpen(true)}
              className="argus-control hidden lg:inline-flex"
              aria-label="Open keyboard shortcuts"
            >
              <HelpCircle size={14} />
              <span className="hidden xl:inline">Shortcuts</span>
            </button>
            <button
              type="button"
              onClick={() => setCommandPaletteOpen(true)}
              className="argus-control !px-2.5 sm:!px-3"
              aria-label="Open command palette"
            >
              <Command size={14} />
              <span className="hidden sm:inline">Palette</span>
              <span className="argus-kbd hidden xl:inline-flex">Ctrl K</span>
            </button>
            <div className="hidden md:block">
              <SystemStatusPill />
            </div>
            <div className="md:hidden">
              <SystemStatusPill compact />
            </div>
          </div>
        </div>
      </header>

      <main key={pathname} className="argus-route-transition mx-auto w-full max-w-[1920px] px-3 pb-4 pt-3 md:px-4">
        {children}
      </main>

      <nav className="fixed bottom-3 left-1/2 z-40 flex -translate-x-1/2 items-center gap-1 rounded-full border border-argus-border/90 bg-argus-panel/95 px-2 py-1 backdrop-blur xl:hidden">
        {links.map((link) => {
          const Icon = link.icon;
          const active = isActivePath(pathname, link.href);

          return (
            <Link
              key={`mobile-${link.href}`}
              href={link.href}
              className={clsx(
                "inline-flex items-center rounded-full px-2 py-1 text-xs",
                active ? "bg-argus-accent/20 text-argus-text" : "text-argus-muted",
              )}
            >
              <Icon size={13} />
            </Link>
          );
        })}
      </nav>

      <CommandPalette />
      <ShortcutsDialog open={shortcutsOpen} onOpenChange={setShortcutsOpen} />

      {(commandPaletteOpen || shortcutsOpen) && (
        <div className="sr-only" aria-live="polite">
          Overlay open
        </div>
      )}
    </div>
  );
}

export function AppShell({ children }: PropsWithChildren) {
  return (
    <UiStateProvider>
      <AppShellInner>{children}</AppShellInner>
    </UiStateProvider>
  );
}



