"use client";

import Link from "next/link";
import { Compass, Radar, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { ArgusMap } from "@/components/map/argus-map";

type FocusMode = "explore" | "monitor" | null;

export default function ProductHomePage() {
  const [focusMode, setFocusMode] = useState<FocusMode>(null);

  return (
    <section className="relative -mx-3 overflow-hidden rounded-xl border border-argus-border md:-mx-4">
      <ArgusMap
        className="!min-h-[calc(100vh-8.2rem)] !rounded-none !border-0"
        interactive={false}
        ambientMotion
        fitOnSelection={false}
        showEvents={false}
        showMonitor={false}
        initialCenter={[4, 20]}
        initialZoom={1.8}
      />

      <div className="pointer-events-none absolute inset-0 argus-map-vignette" />
      <div
        className={`pointer-events-none absolute inset-0 transition-colors duration-300 ease-argus ${
          focusMode === "explore"
            ? "bg-[radial-gradient(circle_at_22%_34%,rgba(95,140,221,0.24),transparent_48%)]"
            : focusMode === "monitor"
              ? "bg-[radial-gradient(circle_at_72%_34%,rgba(124,173,255,0.22),transparent_52%)]"
              : ""
        }`}
      />

      <div className="pointer-events-none absolute inset-0 z-10 flex">
        <div className="mx-auto flex min-h-[calc(100vh-8.2rem)] w-full max-w-6xl flex-col justify-center px-6 py-10">
          <p className="text-xs uppercase tracking-[0.34em] text-argus-muted">Autonomous Geospatial Intelligence Platform</p>
          <h1 className="mt-3 max-w-4xl text-4xl font-semibold leading-tight md:text-6xl">ARGUS</h1>
          <p className="mt-4 max-w-3xl text-sm text-argus-muted md:text-base">
            Observation-driven geospatial operations with real Sentinel-2 scenes, asynchronous change workflows, and
            persistent spatial intelligence.
          </p>

          <div className="pointer-events-auto mt-8 flex flex-wrap gap-3">
            <Link
              href="/explore"
              onMouseEnter={() => setFocusMode("explore")}
              onFocus={() => setFocusMode("explore")}
              onMouseLeave={() => setFocusMode(null)}
              className="argus-soft-lift inline-flex min-w-[170px] items-center justify-between rounded-lg border border-argus-border bg-argus-panel/92 px-4 py-3"
            >
              <span>
                <span className="block text-[11px] uppercase tracking-[0.2em] text-argus-muted">Public mode</span>
                <span className="mt-1 block text-base font-semibold">Explore</span>
              </span>
              <Compass size={18} className="text-argus-accent" />
            </Link>

            <Link
              href="/monitors"
              onMouseEnter={() => setFocusMode("monitor")}
              onFocus={() => setFocusMode("monitor")}
              onMouseLeave={() => setFocusMode(null)}
              className="argus-soft-lift inline-flex min-w-[170px] items-center justify-between rounded-lg border border-argus-border bg-argus-panel/92 px-4 py-3"
            >
              <span>
                <span className="block text-[11px] uppercase tracking-[0.2em] text-argus-muted">Operational mode</span>
                <span className="mt-1 block text-base font-semibold">Monitor</span>
              </span>
              <Radar size={18} className="text-argus-accent" />
            </Link>
          </div>

          <div className="pointer-events-auto mt-8 grid gap-2 text-xs text-argus-muted md:grid-cols-3">
            <div className="argus-panel-muted flex items-center gap-2 px-3 py-2">
              <ShieldCheck size={13} className="text-argus-good" />
              System integrates live backend health and readiness checks.
            </div>
            <a
              href="https://github.com/Shreem1105/ARGUS-Geospatial"
              target="_blank"
              rel="noreferrer"
              className="argus-panel-muted argus-soft-lift flex items-center gap-2 px-3 py-2 hover:border-argus-accent/45"
            >
              Source and architecture are available on GitHub.
            </a>
            <Link href="/monitors/new" className="argus-panel-muted argus-soft-lift flex items-center gap-2 px-3 py-2 hover:border-argus-accent/45">
              Begin monitor setup with map-first AOI workflow.
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
