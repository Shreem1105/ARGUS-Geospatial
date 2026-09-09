"use client";

import { Panel, PanelHeader } from "@/components/ui";
import { formatDateUtc, formatPercent } from "@/lib/format";
import type { SatelliteObservation } from "@/types/api";

type ObservationTimelineProps = {
  observations: SatelliteObservation[];
  selectedObservationId?: string | null;
  beforeObservationId?: string | null;
  afterObservationId?: string | null;
  onSelectObservation?: (observationId: string) => void;
};

function sortedObservations(observations: SatelliteObservation[]): SatelliteObservation[] {
  return [...observations].sort((left, right) => new Date(left.acquired_at).getTime() - new Date(right.acquired_at).getTime());
}

export function ObservationTimeline({
  observations,
  selectedObservationId,
  beforeObservationId,
  afterObservationId,
  onSelectObservation,
}: ObservationTimelineProps) {
  const timeline = sortedObservations(observations);

  return (
    <Panel>
      <PanelHeader title="Observation Timeline" subtitle="Chronological Sentinel-2 acquisitions and selection state" />

      {!timeline.length ? (
        <p className="px-3 py-4 text-sm text-argus-muted">No observations persisted yet.</p>
      ) : (
        <div className="argus-scroll flex gap-2 overflow-x-auto px-3 py-3">
          {timeline.map((observation) => {
            const active = selectedObservationId === observation.id;
            const isBefore = beforeObservationId === observation.id;
            const isAfter = afterObservationId === observation.id;

            return (
              <button
                key={observation.id}
                type="button"
                onClick={() => onSelectObservation?.(observation.id)}
                className={`argus-soft-lift min-w-[220px] rounded-lg border px-3 py-2 text-left ${
                  active ? "border-argus-accent bg-argus-accent/16" : "border-argus-border bg-argus-panel"
                }`}
              >
                <div className="mb-1 flex items-center justify-between gap-2">
                  <p className="truncate text-xs font-semibold">{observation.item_id}</p>
                  <div className="flex items-center gap-1">
                    {isBefore ? <span className="argus-kbd">Before</span> : null}
                    {isAfter ? <span className="argus-kbd">After</span> : null}
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-y-1 text-[11px] text-argus-muted">
                  <span>{formatDateUtc(observation.acquired_at)}</span>
                  <span>Cloud: {observation.cloud_cover == null ? "—" : formatPercent(observation.cloud_cover, 1)}</span>
                  <span>{observation.platform ?? "unknown"}</span>
                  <span>{observation.collection}</span>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </Panel>
  );
}

