"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { MonitorCreateForm } from "@/components/monitor/monitor-create-form";
import { MonitorList } from "@/components/monitor/monitor-list";
import { ErrorState, Panel, PanelHeader } from "@/components/ui";
import { useMonitorMutations, useMonitorsQuery } from "@/hooks/queries";

export default function NewMonitorPage() {
  const router = useRouter();
  const [createError, setCreateError] = useState<string | null>(null);

  const monitorsQuery = useMonitorsQuery({ limit: 30, offset: 0 });
  const { createMonitor } = useMonitorMutations();

  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <div className="xl:col-span-2 space-y-3">
        <Panel className="p-3">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-lg font-semibold">Create Monitor</h1>
              <p className="text-xs text-argus-muted">Draw a valid AOI polygon and create a monitor through the real API</p>
            </div>
            <Link href="/monitors" className="inline-flex items-center gap-1 rounded border border-argus-border bg-argus-panel px-2 py-1 text-xs text-argus-muted">
              <ArrowLeft size={12} /> Back
            </Link>
          </div>
        </Panel>

        <MonitorCreateForm
          submitting={createMonitor.isPending}
          error={createError}
          onSubmit={async (payload) => {
            setCreateError(null);
            try {
              const created = await createMonitor.mutateAsync(payload);
              await monitorsQuery.refetch();
              router.push(`/monitors/${created.id}`);
            } catch (error) {
              setCreateError((error as Error).message);
            }
          }}
        />

        {createMonitor.isError && !createError ? <ErrorState detail="Unable to create monitor" /> : null}
      </div>

      <Panel className="overflow-hidden">
        <PanelHeader title="Recent Monitors" subtitle="Quick navigation after creation" />
        <MonitorList monitors={monitorsQuery.data ?? []} />
      </Panel>
    </div>
  );
}
