"use client";

import area from "@turf/area";
import { feature as turfFeature } from "@turf/helpers";
import { FormEvent, useMemo, useState } from "react";

import { AoiDrawMap } from "@/components/map/aoi-draw-map";
import { ErrorState, Panel, PanelHeader } from "@/components/ui";
import { formatArea } from "@/lib/format";
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

type SetupStep = "aoi" | "configure" | "review";

function stepNumber(step: SetupStep): number {
  if (step === "aoi") {
    return 1;
  }
  if (step === "configure") {
    return 2;
  }
  return 3;
}

export function MonitorCreateForm({ onSubmit, submitting, error }: MonitorCreateFormProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [monitorType, setMonitorType] = useState("general");
  const [sensitivity, setSensitivity] = useState(0.5);
  const [minimumChangeAreaM2, setMinimumChangeAreaM2] = useState(250);
  const [geometry, setGeometry] = useState<GeoJsonPolygon | null>(null);
  const [geometryError, setGeometryError] = useState<string | null>("AOI polygon is required.");
  const [step, setStep] = useState<SetupStep>("aoi");

  const geometryArea = useMemo(() => {
    if (!geometry) {
      return 0;
    }
    return area(turfFeature(geometry));
  }, [geometry]);

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
    setGeometryError("AOI polygon is required.");
    setStep("aoi");
  };

  return (
    <Panel>
      <PanelHeader title="Create Monitor" subtitle="Locate area → draw AOI → configure monitor → review and create" />
      <form className="space-y-3 p-4" onSubmit={handleSubmit}>
        {error ? <ErrorState detail={error} /> : null}
        {geometryError ? <ErrorState detail={geometryError} /> : null}

        <div className="grid gap-2 md:grid-cols-3">
          {[
            { key: "aoi", label: "1. Draw AOI" },
            { key: "configure", label: "2. Configure" },
            { key: "review", label: "3. Review" },
          ].map((entry) => {
            const active = step === entry.key;
            return (
              <button
                key={entry.key}
                type="button"
                onClick={() => setStep(entry.key as SetupStep)}
                className={`rounded-md border px-3 py-2 text-left text-xs ${
                  active ? "border-argus-accent bg-argus-accent/16 text-argus-text" : "border-argus-border bg-argus-panel text-argus-muted"
                }`}
              >
                {entry.label}
              </button>
            );
          })}
        </div>

        <div className="argus-panel-muted p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <p className="text-xs text-argus-muted">Step {stepNumber(step)} of 3</p>
            <p className="text-xs text-argus-muted">AOI area: {geometry ? formatArea(geometryArea) : "—"}</p>
          </div>

          <AoiDrawMap
            heightClassName="h-[460px]"
            onGeometryChange={(nextGeometry) => {
              setGeometry(nextGeometry);
              if (nextGeometry) {
                setGeometryError(validateMonitorPolygon(nextGeometry));
              } else {
                setGeometryError("AOI polygon is required.");
              }
            }}
          />
        </div>

        {step !== "aoi" ? (
          <div className="grid gap-3 md:grid-cols-2">
            <label className="space-y-1 text-xs text-argus-muted">
              Name
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="argus-field w-full"
                required
              />
            </label>

            <label className="space-y-1 text-xs text-argus-muted">
              Monitor type
              <input
                value={monitorType}
                onChange={(event) => setMonitorType(event.target.value)}
                className="argus-field w-full"
                required
              />
            </label>

            <label className="space-y-1 text-xs text-argus-muted md:col-span-2">
              Description
              <textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                className="argus-field h-24 w-full"
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
                onChange={(event) => setSensitivity(Number(event.target.value))}
                className="w-full"
              />
            </label>

            <label className="space-y-1 text-xs text-argus-muted">
              Minimum change area (m²)
              <input
                type="number"
                min={0}
                value={minimumChangeAreaM2}
                onChange={(event) => setMinimumChangeAreaM2(Number(event.target.value))}
                className="argus-field w-full"
              />
            </label>
          </div>
        ) : null}

        {step === "review" ? (
          <div className="argus-panel-muted grid gap-2 px-3 py-2 text-xs text-argus-muted sm:grid-cols-2">
            <p>Name: <span className="text-argus-text">{name || "—"}</span></p>
            <p>Monitor type: <span className="text-argus-text">{monitorType || "—"}</span></p>
            <p>Sensitivity: <span className="text-argus-text">{sensitivity.toFixed(2)}</span></p>
            <p>Minimum area: <span className="text-argus-text">{minimumChangeAreaM2} m²</span></p>
          </div>
        ) : null}

        <div className="flex flex-wrap justify-between gap-2">
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setStep((current) => (current === "review" ? "configure" : current === "configure" ? "aoi" : "aoi"))}
              className="argus-control"
              disabled={step === "aoi"}
            >
              Back
            </button>

            <button
              type="button"
              onClick={() =>
                setStep((current) => {
                  if (current === "aoi") {
                    return "configure";
                  }
                  if (current === "configure") {
                    return "review";
                  }
                  return "review";
                })
              }
              className="argus-control"
              disabled={step === "review" || !geometry || Boolean(geometryError)}
            >
              Next
            </button>
          </div>

          <button
            type="submit"
            disabled={!canSubmit || submitting || step !== "review"}
            className="rounded-md border border-argus-border bg-argus-accent px-4 py-2 text-sm font-semibold text-black disabled:cursor-not-allowed disabled:opacity-40"
          >
            {submitting ? "Creating monitor…" : "Create monitor"}
          </button>
        </div>
      </form>
    </Panel>
  );
}
