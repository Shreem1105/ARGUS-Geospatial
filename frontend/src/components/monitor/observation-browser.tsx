"use client";

import { Panel, PanelHeader } from "@/components/ui";
import { formatDate, formatPercent } from "@/lib/format";
import type { SatelliteObservation } from "@/types/api";

type ObservationBrowserProps = {
  observations: SatelliteObservation[];
  selectedObservationId?: string | null;
  onSelectObservation?: (observationId: string) => void;
  onPrepareObservation?: (observationId: string) => void;
  preparingObservationId?: string | null;
};

export function ObservationBrowser({
  observations,
  selectedObservationId,
  onSelectObservation,
  onPrepareObservation,
  preparingObservationId,
}: ObservationBrowserProps) {
  return (
    <Panel>
      <PanelHeader title="Observation Browser" subtitle="Stored Sentinel-2 metadata for this monitor" />
      {!observations.length ? (
        <p className="px-3 py-4 text-sm text-argus-muted">No observations persisted yet.</p>
      ) : (
        <ul className="argus-scroll max-h-[320px] space-y-2 overflow-y-auto p-3">
          {observations.map((observation) => {
            const active = selectedObservationId === observation.id;
            return (
              <li key={observation.id}>
                <button
                  type="button"
                  onClick={() => onSelectObservation?.(observation.id)}
                  className={`w-full rounded-md border px-3 py-2 text-left ${
                    active ? "border-argus-accent bg-argus-accent/10" : "border-argus-border bg-argus-panel"
                  }`}
                >
                  <p className="truncate text-sm font-semibold">{observation.item_id}</p>
                  <div className="mt-1 grid grid-cols-2 gap-y-1 text-xs text-argus-muted">
                    <span>Platform: {observation.platform ?? "—"}</span>
                    <span>Cloud: {observation.cloud_cover == null ? "—" : formatPercent(observation.cloud_cover, 1)}</span>
                    <span>Acquired: {formatDate(observation.acquired_at)}</span>
                    <span>Collection: {observation.collection}</span>
                  </div>
                </button>
                {onPrepareObservation ? (
                  <button
                    type="button"
                    onClick={() => onPrepareObservation(observation.id)}
                    disabled={preparingObservationId === observation.id}
                    className="mt-1 rounded-md border border-argus-border bg-argus-panel px-2 py-1 text-xs text-argus-muted"
                  >
                    {preparingObservationId === observation.id ? "Preparing…" : "Prepare raster"}
                  </button>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
