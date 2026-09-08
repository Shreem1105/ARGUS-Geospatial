"use client";

import { AlertTriangle, Database, Route, Users, Waves } from "lucide-react";

import { Badge, LoadingState, Panel, PanelHeader } from "@/components/ui";
import { formatArea, formatMeters, formatNumber } from "@/lib/format";
import type { EventIntelligence } from "@/types/api";

type EventIntelligencePanelProps = {
  loading: boolean;
  error?: string | null;
  intelligence?: EventIntelligence | null;
};

export function EventIntelligencePanel({ loading, error, intelligence }: EventIntelligencePanelProps) {
  return (
    <Panel className="h-full overflow-hidden">
      <PanelHeader
        title="Event Intelligence"
        subtitle="Spatial intersections and contextual exposure"
        actions={intelligence ? <Badge tone="default">Scientific severity: {intelligence.scientific_severity}</Badge> : null}
      />
      <div className="argus-scroll max-h-[560px] space-y-4 overflow-y-auto p-4">
        {loading ? <LoadingState label="Loading intelligence…" /> : null}
        {error ? (
          <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200">{error}</div>
        ) : null}
        {!loading && !error && !intelligence ? (
          <p className="text-sm text-argus-muted">Select an event to inspect context and exposure insights.</p>
        ) : null}
        {intelligence ? (
          <>
            <section className="space-y-2">
              <h3 className="flex items-center gap-2 text-sm font-semibold"><Route size={14} /> Roads</h3>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <MetricRow label="Intersecting count" value={formatNumber(intelligence.roads.intersecting_count, 0)} />
                <MetricRow label="Intersection length" value={formatMeters(intelligence.roads.intersecting_length_m)} />
                <MetricRow label="Nearby count" value={formatNumber(intelligence.roads.nearby_count, 0)} />
                <MetricRow label="Nearest distance" value={formatMeters(intelligence.roads.nearest_distance_m)} />
              </div>
            </section>

            <section className="space-y-2">
              <h3 className="flex items-center gap-2 text-sm font-semibold"><Database size={14} /> Buildings</h3>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <MetricRow label="Intersecting count" value={formatNumber(intelligence.buildings.intersecting_count, 0)} />
                <MetricRow label="Intersection area" value={formatArea(intelligence.buildings.intersection_area_m2)} />
                <MetricRow label="Nearby count" value={formatNumber(intelligence.buildings.nearby_count, 0)} />
                <MetricRow label="Nearest distance" value={formatMeters(intelligence.buildings.nearest_distance_m)} />
              </div>
            </section>

            <section className="space-y-2">
              <h3 className="flex items-center gap-2 text-sm font-semibold"><Waves size={14} /> Waterways</h3>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <MetricRow label="Intersecting count" value={formatNumber(intelligence.waterways.intersecting_count, 0)} />
                <MetricRow label="Intersection length" value={formatMeters(intelligence.waterways.intersection_length_m)} />
                <MetricRow label="Nearby count" value={formatNumber(intelligence.waterways.nearby_count, 0)} />
                <MetricRow label="Nearest distance" value={formatMeters(intelligence.waterways.nearest_distance_m)} />
              </div>
            </section>

            <section className="space-y-2">
              <h3 className="flex items-center gap-2 text-sm font-semibold"><Users size={14} /> Population Exposure</h3>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <MetricRow
                  label="Estimated exposed"
                  value={formatNumber(intelligence.population.estimated_exposed_population, 0)}
                />
                <MetricRow label="Intersecting units" value={formatNumber(intelligence.population.intersecting_units, 0)} />
              </div>
            </section>

            <section className="space-y-2">
              <h3 className="flex items-center gap-2 text-sm font-semibold"><AlertTriangle size={14} /> Significance</h3>
              <div className="rounded-md border border-argus-border bg-argus-panelMuted p-3 text-xs">
                <p>Context significance: <strong>{intelligence.context_significance}</strong></p>
                <p>Exposure significance: <strong>{intelligence.exposure_significance}</strong></p>
                <p className="mt-2 text-argus-muted">
                  Spatial overlap/proximity is contextual evidence only and does not by itself prove physical damage.
                </p>
              </div>
            </section>
          </>
        ) : null}
      </div>
    </Panel>
  );
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-argus-border bg-argus-panelMuted p-2">
      <p className="text-[11px] uppercase tracking-wide text-argus-muted">{label}</p>
      <p className="mt-1 text-sm font-semibold">{value}</p>
    </div>
  );
}
