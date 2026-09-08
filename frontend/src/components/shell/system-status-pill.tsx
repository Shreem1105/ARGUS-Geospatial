"use client";

import { useSystemHealthQueries } from "@/hooks/queries";

export function SystemStatusPill() {
  const { health, ready, worker } = useSystemHealthQueries();

  const appHealthy = health.data?.status === "healthy";
  const dbReady = ready.data?.status === "ready";
  const workerHealthy = worker.data?.status === "healthy";

  const classes = [
    "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs",
    appHealthy && dbReady ? "border-argus-good/70 text-argus-good" : "border-argus-warn/70 text-argus-warn",
  ].join(" ");

  return (
    <div className={classes} title="Backend, database, and worker status">
      <span className="h-2 w-2 rounded-full bg-current" />
      <span>
        API {appHealthy ? "up" : "degraded"} · DB {dbReady ? "ready" : "not-ready"} · Worker {workerHealthy ? "up" : "degraded"}
      </span>
    </div>
  );
}
