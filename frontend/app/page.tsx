import Link from "next/link";

import { Panel } from "@/components/ui";

export default function ProductHomePage() {
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <Panel className="xl:col-span-2 p-6">
        <p className="text-xs uppercase tracking-[0.2em] text-argus-muted">ARGUS</p>
        <h1 className="mt-2 text-3xl font-bold">Geospatial intelligence for real monitoring operations</h1>
        <p className="mt-3 max-w-3xl text-sm text-argus-muted">
          ARGUS combines real Sentinel-2 observations, change analysis, vectorized events, infrastructure context,
          population exposure, and environmental overlays into a map-first operational workflow.
        </p>

        <div className="mt-6 grid gap-3 md:grid-cols-2">
          <Link href="/explore" className="rounded-lg border border-argus-border bg-argus-panelMuted p-4 hover:border-argus-accent">
            <p className="text-xs uppercase text-argus-muted">Public mode</p>
            <h2 className="mt-1 text-lg font-semibold">Explore</h2>
            <p className="mt-2 text-sm text-argus-muted">
              Inspect existing monitors and change events without triggering expensive backend jobs.
            </p>
          </Link>
          <Link href="/monitor" className="rounded-lg border border-argus-border bg-argus-panelMuted p-4 hover:border-argus-accent">
            <p className="text-xs uppercase text-argus-muted">Operational mode</p>
            <h2 className="mt-1 text-lg font-semibold">Monitor</h2>
            <p className="mt-2 text-sm text-argus-muted">
              Create AOIs, run analyses, inspect runs/events, and manage schedules against real backend workflows.
            </p>
          </Link>
        </div>
      </Panel>

      <Panel className="p-4">
        <h3 className="text-sm font-semibold">Keyboard shortcuts</h3>
        <ul className="mt-3 space-y-2 text-xs text-argus-muted">
          <li>
            <span className="argus-kbd">Ctrl K</span> Open command palette
          </li>
          <li>
            <span className="argus-kbd">Alt 1</span> Explore mode
          </li>
          <li>
            <span className="argus-kbd">Alt 2</span> Monitor mode
          </li>
          <li>
            <span className="argus-kbd">Alt 3</span> Global events
          </li>
          <li>
            <span className="argus-kbd">Alt 4</span> Global runs
          </li>
        </ul>
      </Panel>
    </div>
  );
}
