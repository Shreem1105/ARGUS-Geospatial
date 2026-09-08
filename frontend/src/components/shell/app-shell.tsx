"use client";

import clsx from "clsx";
import { Activity, Command, Earth, Layers, Radar, Satellite } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { PropsWithChildren, useEffect } from "react";

import { CommandPalette } from "@/components/shell/command-palette";
import { SystemStatusPill } from "@/components/shell/system-status-pill";
import { isTextEntryTarget } from "@/lib/keyboard";
import { UiStateProvider, useUiState } from "@/state/ui-state";

const links = [
  { href: "/", label: "Product", icon: Satellite },
  { href: "/explore", label: "Explore", icon: Earth },
  { href: "/monitors", label: "Monitors", icon: Radar },
  { href: "/events", label: "Events", icon: Layers },
  { href: "/runs", label: "Runs", icon: Activity },
];

function AppShellInner({ children }: PropsWithChildren) {
  const pathname = usePathname();
  const router = useRouter();
  const { setCommandPaletteOpen } = useUiState();

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (isTextEntryTarget(event.target)) {
        return;
      }

      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandPaletteOpen(true);
        return;
      }

      if (event.altKey && event.key === "1") {
        event.preventDefault();
        router.push("/explore");
        return;
      }
      if (event.altKey && event.key === "2") {
        event.preventDefault();
        router.push("/monitors");
        return;
      }
      if (event.altKey && event.key === "3") {
        event.preventDefault();
        router.push("/events");
        return;
      }
      if (event.altKey && event.key === "4") {
        event.preventDefault();
        router.push("/runs");
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [router, setCommandPaletteOpen]);

  return (
    <div className="min-h-screen text-argus-text">
      <header className="sticky top-0 z-40 border-b border-argus-border/80 bg-argus-bg/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1800px] items-center justify-between gap-4 px-4 py-3">
          <div className="flex items-center gap-3">
            <div className="rounded-lg border border-argus-border bg-argus-panel p-2">
              <Satellite size={18} />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-argus-muted">ARGUS</p>
              <p className="text-sm font-semibold">Geospatial Intelligence Workspace</p>
            </div>
          </div>

          <nav className="hidden items-center gap-1 lg:flex" aria-label="Primary">
            {links.map((link) => {
              const active = pathname === link.href || pathname.startsWith(`${link.href}/`);
              const Icon = link.icon;
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={clsx(
                    "inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm transition",
                    active ? "bg-argus-panelMuted text-white" : "text-argus-muted hover:bg-argus-panel hover:text-argus-text",
                  )}
                >
                  <Icon size={14} />
                  {link.label}
                </Link>
              );
            })}
          </nav>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setCommandPaletteOpen(true)}
              className="inline-flex items-center gap-2 rounded-md border border-argus-border bg-argus-panel px-3 py-1.5 text-xs text-argus-muted hover:text-argus-text"
              aria-label="Open command palette"
            >
              <Command size={14} />
              Palette
              <span className="argus-kbd">Ctrl K</span>
            </button>
            <SystemStatusPill />
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-[1800px] px-4 py-4">{children}</main>
      <CommandPalette />
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
