"use client";

import { FormEvent, useState } from "react";

import { Panel, PanelHeader } from "@/components/ui";
import { formatDate } from "@/lib/format";
import type { MonitorSchedule } from "@/types/api";

type ScheduleEditorProps = {
  schedule: MonitorSchedule | null;
  onSave: (payload: Partial<MonitorSchedule>) => Promise<void>;
  saving: boolean;
};

export function ScheduleEditor({ schedule, onSave, saving }: ScheduleEditorProps) {
  const [enabled, setEnabled] = useState(schedule?.enabled ?? false);
  const [intervalHours, setIntervalHours] = useState(schedule?.interval_hours ?? 24);
  const [lookbackDays, setLookbackDays] = useState(schedule?.lookback_days ?? 60);
  const [maxCloudCover, setMaxCloudCover] = useState(schedule?.max_cloud_cover ?? 40);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    await onSave({
      enabled,
      interval_hours: intervalHours,
      lookback_days: lookbackDays,
      max_cloud_cover: maxCloudCover,
    });
  };

  return (
    <Panel>
      <PanelHeader title="Schedule" subtitle="Monitor cadence and search window controls" />
      <form className="space-y-3 p-4" onSubmit={onSubmit}>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          Schedule enabled
        </label>

        <div className="grid grid-cols-2 gap-3">
          <label className="space-y-1 text-xs text-argus-muted">
            Interval (hours)
            <input
              type="number"
              min={1}
              max={168}
              value={intervalHours}
              onChange={(e) => setIntervalHours(Number(e.target.value))}
              className="argus-field w-full"
            />
          </label>
          <label className="space-y-1 text-xs text-argus-muted">
            Lookback (days)
            <input
              type="number"
              min={1}
              max={365}
              value={lookbackDays}
              onChange={(e) => setLookbackDays(Number(e.target.value))}
              className="argus-field w-full"
            />
          </label>
          <label className="space-y-1 text-xs text-argus-muted col-span-2">
            Max cloud cover (%)
            <input
              type="number"
              min={0}
              max={100}
              value={maxCloudCover ?? 40}
              onChange={(e) => setMaxCloudCover(Number(e.target.value))}
              className="argus-field w-full"
            />
          </label>
        </div>

        <button
          type="submit"
          disabled={saving}
          className="rounded-md border border-argus-border bg-argus-accent px-3 py-2 text-sm font-semibold text-black"
        >
          {saving ? "Saving…" : "Save schedule"}
        </button>

        {schedule ? (
          <p className="text-xs text-argus-muted">
            Last run: {formatDate(schedule.last_run_at)} · Next run: {formatDate(schedule.next_run_at)}
          </p>
        ) : null}
      </form>
    </Panel>
  );
}
