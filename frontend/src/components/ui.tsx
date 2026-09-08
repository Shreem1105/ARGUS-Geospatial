import clsx from "clsx";
import { PropsWithChildren, ReactNode } from "react";

export function Panel({ children, className }: PropsWithChildren<{ className?: string }>) {
  return <section className={clsx("argus-panel", className)}>{children}</section>;
}

export function PanelHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="flex items-start justify-between gap-2 border-b border-argus-border px-4 py-3">
      <div>
        <h2 className="text-sm font-semibold text-argus-text">{title}</h2>
        {subtitle ? <p className="mt-0.5 text-xs text-argus-muted">{subtitle}</p> : null}
      </div>
      {actions ? <div className="shrink-0">{actions}</div> : null}
    </header>
  );
}

export function Metric({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-md border border-argus-border bg-argus-panelMuted p-3">
      <p className="text-[11px] uppercase tracking-wide text-argus-muted">{label}</p>
      <p className="mt-1 text-lg font-semibold text-argus-text">{value}</p>
      {hint ? <p className="mt-1 text-xs text-argus-muted">{hint}</p> : null}
    </div>
  );
}

export function EmptyState({
  title,
  detail,
  action,
}: {
  title: string;
  detail: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex min-h-[180px] flex-col items-center justify-center gap-3 rounded-md border border-dashed border-argus-border bg-argus-panel px-6 py-8 text-center">
      <h3 className="text-base font-semibold text-argus-text">{title}</h3>
      <p className="max-w-xl text-sm text-argus-muted">{detail}</p>
      {action ? <div>{action}</div> : null}
    </div>
  );
}

export function ErrorState({ detail }: { detail: string }) {
  return (
    <div className="rounded-md border border-red-500/50 bg-red-500/10 px-4 py-3 text-sm text-red-200" role="alert">
      {detail}
    </div>
  );
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-argus-border bg-argus-panel px-3 py-2 text-sm text-argus-muted">
      <span className="h-2 w-2 animate-pulse rounded-full bg-argus-accent" />
      {label}
    </div>
  );
}

export function Badge({ children, tone = "default" }: PropsWithChildren<{ tone?: "default" | "good" | "warn" | "danger" }>) {
  const toneClass =
    tone === "good"
      ? "border-argus-good/40 bg-argus-good/10 text-argus-good"
      : tone === "warn"
        ? "border-argus-warn/40 bg-argus-warn/10 text-argus-warn"
        : tone === "danger"
          ? "border-argus-danger/40 bg-argus-danger/10 text-argus-danger"
          : "border-argus-border bg-argus-panelMuted text-argus-muted";
  return <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs ${toneClass}`}>{children}</span>;
}
