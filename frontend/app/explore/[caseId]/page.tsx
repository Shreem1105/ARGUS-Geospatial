import Link from "next/link";
import { notFound } from "next/navigation";

import { EmptyState, Panel } from "@/components/ui";
import { curatedScenarios } from "@/lib/curated-scenarios";

type ExploreCasePageProps = {
  params: Promise<{ caseId: string }>;
};

export default async function ExploreCasePage({ params }: ExploreCasePageProps) {
  const { caseId } = await params;
  const scenario = curatedScenarios.find((entry) => entry.id === caseId) ?? null;

  if (!scenario) {
    if (curatedScenarios.length === 0) {
      return (
        <Panel className="p-6">
          <EmptyState
            title="No curated ARGUS case studies have been published yet."
            detail="This route is ready for curated, precomputed public case studies. No case data is fabricated when the curated catalog is empty."
            action={
              <div className="flex gap-2">
                <Link href="/explore" className="rounded border border-argus-border bg-argus-panel px-3 py-1.5 text-xs">
                  Back to Explore
                </Link>
                <Link href="/monitors" className="rounded border border-argus-border bg-argus-panel px-3 py-1.5 text-xs">
                  Open Monitors
                </Link>
              </div>
            }
          />
        </Panel>
      );
    }

    notFound();
  }

  const monitorHref = scenario.preview_event_id
    ? `/monitors/${scenario.monitor_id}?eventId=${encodeURIComponent(scenario.preview_event_id)}`
    : `/monitors/${scenario.monitor_id}`;

  return (
    <Panel className="p-6">
      <p className="text-xs uppercase tracking-[0.2em] text-argus-muted">Curated Explore Case</p>
      <h1 className="mt-2 text-2xl font-semibold">{scenario.title}</h1>
      <p className="mt-2 text-sm text-argus-muted">{scenario.headline}</p>
      <div className="mt-4 grid gap-2 text-xs text-argus-muted md:grid-cols-2">
        <p>Region: {scenario.region_label}</p>
        <p>Monitor: {scenario.monitor_id}</p>
        <p>Start: {scenario.time_window?.start_date ?? "—"}</p>
        <p>End: {scenario.time_window?.end_date ?? "—"}</p>
      </div>
      <div className="mt-4 flex gap-2">
        <Link href="/explore" className="rounded border border-argus-border bg-argus-panel px-3 py-1.5 text-xs">
          Back to Explore
        </Link>
        <Link href={monitorHref} className="rounded border border-argus-border bg-argus-panel px-3 py-1.5 text-xs">
          Open Monitor Workspace
        </Link>
      </div>
    </Panel>
  );
}
