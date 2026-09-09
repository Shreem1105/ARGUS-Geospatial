"use client";

import { useSystemHealthQueries } from "@/hooks/queries";

type SystemStatusPillProps = {
  compact?: boolean;
};

export function SystemStatusPill({ compact = false }: SystemStatusPillProps) {
  const { health, ready, worker } = useSystemHealthQueries();

  const appHealthy = health.data?.status === "healthy";
  const dbReady = ready.data?.status === "ready";
  const workerHealthy = worker.data?.status === "healthy";

  const healthy = appHealthy && dbReady && workerHealthy;

  const classes = [
    "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs",
    healthy ? "border-argus-good/70 text-argus-good" : "border-argus-warn/70 text-argus-warn",
    compact ? "h-9 w-9 justify-center rounded-md px-0" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={classes} title="Backend, database, and worker status" aria-label="Backend, database, and worker status">
      <span className="argus-status-dot h-2 w-2 rounded-full bg-current" />
      {!compact ? (
        <span>
          API {appHealthy ? "up" : "degraded"} · DB {dbReady ? "ready" : "not-ready"} · Worker {workerHealthy ? "up" : "degraded"}
        </span>
      ) : null}
    </div>
  );
}
