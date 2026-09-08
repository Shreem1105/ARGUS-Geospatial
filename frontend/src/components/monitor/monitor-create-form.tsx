"use client";

import { FormEvent, useMemo, useState } from "react";

import { AoiDrawMap } from "@/components/map/aoi-draw-map";
import { ErrorState, Panel, PanelHeader } from "@/components/ui";
import { validateMonitorPolygon } from "@/lib/monitor-validation";
import type { GeoJsonPolygon } from "@/types/geojson";

export type MonitorCreateInput = {
  name: string;
  description: string | null;
  monitor_type: string;
  sensitivity: number;
  minimum_change_area_m2: number;
  geometry: GeoJsonPolygon;
};

type MonitorCreateFormProps = {
  onSubmit: (payload: MonitorCreateInput) => Promise<void>;
  submitting?: boolean;
  error?: string | null;
};

export function MonitorCreateForm({ onSubmit, submitting, error }: MonitorCreateFormProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [monitorType, setMonitorType] = useState("general");
  const [sensitivity, setSensitivity] = useState(0.5);
  const [minimumChangeAreaM2, setMinimumChangeAreaM2] = useState(250);
  const [geometry, setGeometry] = useState<GeoJsonPolygon | null>(null);
  const [geometryError, setGeometryError] = useState<string | null>(null);

  const canSubmit = useMemo(() => {
    return Boolean(name.trim()) && geometry != null && !geometryError;
  }, [name, geometry, geometryError]);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();

    const geoError = validateMonitorPolygon(geometry);
    setGeometryError(geoError);
    if (geoError || !geometry || !name.trim()) {
      return;
    }

    await onSubmit({
      name: name.trim(),
      description: description.trim() || null,
      monitor_type: monitorType.trim().toLowerCase(),
      sensitivity,
      minimum_change_area_m2: minimumChangeAreaM2,
      geometry,
    });

    setName("");
    setDescription("");
    setMonitorType("general");
    setGeometry(null);
    setGeometryError(null);
  };

  return (
    <Panel>
      <PanelHeader title="Create Monitor" subtitle="Draw AOI and create a monitor linked to real backend analysis workflows" />
      <form className="space-y-3 p-4" onSubmit={handleSubmit}>
        {error ? <ErrorState detail={error} /> : null}
        {geometryError ? <ErrorState detail={geometryError} /> : null}

        <div className="grid gap-3 md:grid-cols-2">
          <label className="space-y-1 text-xs text-argus-muted">
            Name
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-md border border-argus-border bg-argus-panel px-3 py-2 text-sm text-argus-text outline-none"
              required
            />
          </label>

          <label className="space-y-1 text-xs text-argus-muted">
            Monitor type
            <input
              value={monitorType}
              onChange={(e) => setMonitorType(e.target.value)}
              className="w-full rounded-md border border-argus-border bg-argus-panel px-3 py-2 text-sm text-argus-text outline-none"
              required
            />
          </label>

          <label className="space-y-1 text-xs text-argus-muted md:col-span-2">
            Description
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="h-20 w-full rounded-md border border-argus-border bg-argus-panel px-3 py-2 text-sm text-argus-text outline-none"
            />
          </label>

          <label className="space-y-1 text-xs text-argus-muted">
            Sensitivity ({sensitivity.toFixed(2)})
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={sensitivity}
              onChange={(e) => setSensitivity(Number(e.target.value))}
              className="w-full"
            />
          </label>

          <label className="space-y-1 text-xs text-argus-muted">
            Minimum change area (m²)
            <input
              type="number"
              min={0}
              value={minimumChangeAreaM2}
              onChange={(e) => setMinimumChangeAreaM2(Number(e.target.value))}
              className="w-full rounded-md border border-argus-border bg-argus-panel px-3 py-2 text-sm text-argus-text outline-none"
            />
          </label>
        </div>

        <AoiDrawMap
          onGeometryChange={(nextGeometry) => {
            setGeometry(nextGeometry);
            if (nextGeometry) {
              setGeometryError(validateMonitorPolygon(nextGeometry));
            } else {
              setGeometryError("AOI polygon is required.");
            }
          }}
        />

        <button
          type="submit"
          disabled={!canSubmit || submitting}
          className="rounded-md border border-argus-border bg-argus-accent px-4 py-2 text-sm font-semibold text-black disabled:cursor-not-allowed disabled:opacity-40"
        >
          {submitting ? "Creating monitor…" : "Create monitor"}
        </button>
      </form>
    </Panel>
  );
}
