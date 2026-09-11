"use client";

import { AlertTriangle, BrainCircuit, Database, Leaf, Route, Shield, Users, Waves } from "lucide-react";

import { Badge, LoadingState, Panel, PanelHeader } from "@/components/ui";
import { formatArea, formatDateUtc, formatMeters, formatNumber, formatPercent } from "@/lib/format";
import type { ChangeEvent, EventIntelligence } from "@/types/api";

type EventIntelligencePanelProps = {
  loading: boolean;
  error?: string | null;
  intelligence?: EventIntelligence | null;
  event?: ChangeEvent | null;
};

export function EventIntelligencePanel({ loading, error, intelligence, event }: EventIntelligencePanelProps) {
  return (
    <Panel className="h-full overflow-hidden">
      <PanelHeader
        title="Event Intelligence"
        subtitle="Spatial overlap/proximity + exposure context"
        actions={
          intelligence ? (
            <Badge tone="default">Scientific severity: {intelligence.scientific_severity}</Badge>
          ) : null
        }
      />

      <div className="argus-scroll max-h-[62vh] space-y-3 overflow-y-auto p-3">
        {loading ? <LoadingState label="Loading intelligence…" /> : null}
        {error ? <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200">{error}</div> : null}

        {!loading && !error && !intelligence ? (
          <p className="text-sm text-argus-muted">Select a change event to inspect evidence, context intersections, and exposure.</p>
        ) : null}

        {intelligence ? (
          <>
            <section className="argus-panel-muted space-y-2 px-3 py-2.5">
              <SectionTitle icon={<AlertTriangle size={13} />} title="Overview" />
              <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-argus-muted">
                <KeyValue label="Status" value={event?.status ?? "—"} />
                <KeyValue label="Confidence" value={formatPercent(intelligence.change_confidence * 100, 1)} />
                <KeyValue label="Area" value={formatArea(event?.area_m2 ?? null)} />
                <KeyValue label="Event time" value={formatDateUtc(event?.first_detected_at)} />
                <KeyValue label="Analysis" value={intelligence.analysis_id.slice(0, 8)} mono />
                <KeyValue label="Event" value={intelligence.event_id.slice(0, 8)} mono />
              </div>
            </section>

            <section className="argus-panel-muted space-y-2 px-3 py-2.5">
              <SectionTitle icon={<Route size={13} />} title="Change Evidence" />
              <CompactBar label="Confidence" value={Math.min(100, Math.max(0, intelligence.change_confidence * 100))} />
              <CompactBar
                label="Mean ΔNDVI"
                value={Math.min(100, Math.max(0, (Math.abs(event?.mean_abs_delta_ndvi ?? 0) / 0.6) * 100))}
                annotation={formatNumber(event?.mean_abs_delta_ndvi)}
              />
              <CompactBar
                label="Spectral distance"
                value={Math.min(100, Math.max(0, (Math.abs(event?.mean_spectral_distance ?? 0) / 0.6) * 100))}
                annotation={formatNumber(event?.mean_spectral_distance)}
              />
            </section>

            <section className="argus-panel-muted space-y-2 px-3 py-2.5">
              <SectionTitle icon={<BrainCircuit size={13} />} title="Semantic Change" />
              {intelligence.semantic ? (
                <>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-argus-muted">
                    <KeyValue label="Label" value={intelligence.semantic.semantic_label} />
                    <KeyValue label="Abstained" value={intelligence.semantic.abstained ? "yes" : "no"} />
                    <KeyValue
                      label="Evidence confidence"
                      value={formatPercent(intelligence.semantic.semantic_confidence * 100, 1)}
                    />
                    <KeyValue
                      label="Valid pixel coverage"
                      value={
                        intelligence.semantic.valid_pixel_coverage === null
                          ? "—"
                          : formatPercent(intelligence.semantic.valid_pixel_coverage * 100, 1)
                      }
                    />
                    <KeyValue label="Model" value={intelligence.semantic.model_name} />
                    <KeyValue label="Version" value={intelligence.semantic.model_version} />
                  </div>
                  {intelligence.semantic.explanation.length ? (
                    <ul className="space-y-1 rounded-md border border-argus-border/45 bg-argus-panel px-2 py-2 text-[11px] text-argus-muted">
                      {intelligence.semantic.explanation.slice(0, 3).map((line, index) => (
                        <li key={`${index}-${line}`}>• {line}</li>
                      ))}
                    </ul>
                  ) : null}
                  <p className="text-[11px] text-argus-muted">
                    Semantic labels describe observable land-surface transitions only and do not by themselves establish
                    cause, damage, or intent.
                  </p>
                </>
              ) : (
                <p className="text-[11px] text-argus-muted">
                  Semantic analysis has not been computed for this event yet.
                </p>
              )}
            </section>

            <section className="argus-panel-muted space-y-2 px-3 py-2.5">
              <SectionTitle icon={<Shield size={13} />} title="Spatial Context" />
              <div className="space-y-1.5 text-[11px] text-argus-muted">
                <MetricLine icon={<Route size={12} />} label="Road intersections" value={formatNumber(intelligence.roads.intersecting_count, 0)} detail={formatMeters(intelligence.roads.intersecting_length_m)} />
                <MetricLine icon={<Database size={12} />} label="Building intersections" value={formatNumber(intelligence.buildings.intersecting_count, 0)} detail={formatArea(intelligence.buildings.intersection_area_m2)} />
                <MetricLine icon={<Waves size={12} />} label="Waterway intersections" value={formatNumber(intelligence.waterways.intersecting_count, 0)} detail={formatMeters(intelligence.waterways.intersection_length_m)} />
                <MetricLine icon={<Shield size={12} />} label="Administrative matches" value={formatNumber(intelligence.administrative_areas.length, 0)} detail="intersecting levels" />
              </div>
              <p className="text-[11px] text-argus-muted">
                Road classes: {Object.keys(intelligence.roads.classes).length ? Object.entries(intelligence.roads.classes).map(([key, value]) => `${key}:${value}`).join(", ") : "—"}
              </p>
            </section>

            <section className="argus-panel-muted space-y-2 px-3 py-2.5">
              <SectionTitle icon={<Users size={13} />} title="Exposure" />
              <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-argus-muted">
                <KeyValue label="Population estimate" value={formatNumber(intelligence.population.estimated_exposed_population, 0)} />
                <KeyValue label="Intersecting units" value={formatNumber(intelligence.population.intersecting_units, 0)} />
                <KeyValue label="Dominant land cover" value={intelligence.land_cover.dominant_class ?? "—"} />
                <KeyValue label="Dominant fraction" value={formatPercent(intelligence.land_cover.dominant_fraction * 100, 1)} />
                <KeyValue label="Protected overlap" value={formatPercent(intelligence.environment.protected_area_fraction * 100, 1)} />
                <KeyValue label="Env intersections" value={formatNumber(intelligence.environment.intersecting_count, 0)} />
              </div>
            </section>

            <section className="argus-panel-muted space-y-2 px-3 py-2.5">
              <SectionTitle icon={<Leaf size={13} />} title="Significance + Technical" />
              <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-argus-muted">
                <KeyValue label="Context significance" value={intelligence.context_significance} />
                <KeyValue label="Exposure significance" value={intelligence.exposure_significance} />
                <KeyValue label="Nearest road" value={formatMeters(intelligence.roads.nearest_distance_m)} />
                <KeyValue label="Nearest building" value={formatMeters(intelligence.buildings.nearest_distance_m)} />
                <KeyValue label="Nearest waterway" value={formatMeters(intelligence.waterways.nearest_distance_m)} />
                <KeyValue
                  label="Admin areas"
                  value={
                    intelligence.administrative_areas.length
                      ? intelligence.administrative_areas
                          .map((entry) => `${entry.name ?? "unnamed"} (${entry.admin_level ?? "—"})`)
                          .join("; ")
                      : "—"
                  }
                />
              </div>
              <p className="text-[11px] text-argus-muted">
                Spatial overlap/proximity indicates contextual intersection only; it does not by itself prove physical
                damage, blockage, or destruction.
              </p>
            </section>
          </>
        ) : null}
      </div>
    </Panel>
  );
}

function SectionTitle({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.14em] text-argus-text">
      {icon}
      {title}
    </h3>
  );
}

function KeyValue({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-argus-border/45 pb-1">
      <span>{label}</span>
      <span className={mono ? "font-mono text-[10px] text-argus-text" : "text-argus-text"}>{value}</span>
    </div>
  );
}

function CompactBar({ label, value, annotation }: { label: string; value: number; annotation?: string }) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-[11px] text-argus-muted">
        <span>{label}</span>
        <span>{annotation ?? `${Math.round(clamped)}%`}</span>
      </div>
      <div className="h-1.5 rounded-full bg-argus-panel">
        <div className="h-full rounded-full bg-argus-accent" style={{ width: `${clamped}%` }} />
      </div>
    </div>
  );
}

function MetricLine({
  icon,
  label,
  value,
  detail,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="flex items-center justify-between gap-2 rounded-md border border-argus-border/45 bg-argus-panel px-2 py-1.5">
      <span className="flex items-center gap-1">{icon} {label}</span>
      <span className="text-argus-text">
        {value} <span className="text-argus-muted">({detail})</span>
      </span>
    </div>
  );
}
