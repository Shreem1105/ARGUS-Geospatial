"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import area from "@turf/area";
import { feature as turfFeature } from "@turf/helpers";
import * as maplibregl from "maplibre-gl";
import type { Map } from "maplibre-gl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { MAP_STYLE } from "@/lib/constants";
import { formatArea } from "@/lib/format";
import type { GeoJsonPolygon } from "@/types/geojson";

type AoiDrawMapProps = {
  onGeometryChange: (geometry: GeoJsonPolygon | null) => void;
  initialGeometry?: GeoJsonPolygon | null;
};

const DRAW_SOURCE_ID = "argus-draw-source";

function toFeatureCollection(geometry: GeoJsonPolygon | null) {
  return {
    type: "FeatureCollection" as const,
    features: geometry
      ? [
          {
            type: "Feature" as const,
            geometry,
            properties: {},
          },
        ]
      : [],
  };
}

export function AoiDrawMap({ onGeometryChange, initialGeometry = null }: AoiDrawMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const drawRef = useRef<any>(null);
  const [geometry, setGeometry] = useState<GeoJsonPolygon | null>(initialGeometry);
  const [drawReady, setDrawReady] = useState(false);
  const [drawError, setDrawError] = useState<string | null>(null);

  const areaM2 = useMemo(() => {
    if (!geometry) {
      return 0;
    }
    return area(turfFeature(geometry));
  }, [geometry]);

  const updateMapSource = useCallback((value: GeoJsonPolygon | null) => {
    const source = mapRef.current?.getSource(DRAW_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
    source?.setData(toFeatureCollection(value) as never);
  }, []);

  useEffect(() => {
    onGeometryChange(geometry);
    updateMapSource(geometry);
  }, [geometry, onGeometryChange, updateMapSource]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) {
      return;
    }

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: MAP_STYLE,
      center: [-80.84, 35.23],
      zoom: 10,
      attributionControl: {},
    });

    map.addControl(new maplibregl.NavigationControl(), "top-right");

    map.on("load", async () => {
      map.addSource(DRAW_SOURCE_ID, {
        type: "geojson",
        data: toFeatureCollection(initialGeometry),
      });

      map.addLayer({
        id: "draw-fill",
        type: "fill",
        source: DRAW_SOURCE_ID,
        paint: { "fill-color": "#3da9fc", "fill-opacity": 0.2 },
      });

      map.addLayer({
        id: "draw-outline",
        type: "line",
        source: DRAW_SOURCE_ID,
        paint: { "line-color": "#3da9fc", "line-width": 2 },
      });

      try {
        const terra = await import("terra-draw");
        const adapterModule = await import("terra-draw-maplibre-gl-adapter");

        const TerraDrawCtor = terra.TerraDraw as any;
        const SelectMode = (terra as any).TerraDrawSelectMode;
        const PolygonMode = (terra as any).TerraDrawPolygonMode;
        const adapter = new (adapterModule as any).TerraDrawMapLibreGLAdapter({ map, lib: maplibregl });

        const draw = new TerraDrawCtor({
          adapter,
          modes: [new SelectMode(), new PolygonMode()],
        });

        draw.start();
        drawRef.current = draw;
        setDrawReady(true);

        const syncFromSnapshot = () => {
          const snapshot = draw.getSnapshot();
          const polygon = snapshot
            .map((entry: any) => entry.geometry)
            .findLast((value: any) => value?.type === "Polygon" && Array.isArray(value.coordinates));

          setGeometry((polygon as GeoJsonPolygon | undefined) ?? null);
        };

        draw.on("finish", syncFromSnapshot);
        draw.on("change", syncFromSnapshot);
        draw.on("delete", syncFromSnapshot);
      } catch {
        setDrawError("AOI drawing tools unavailable in this environment.");
      }
    });

    mapRef.current = map;

    return () => {
      drawRef.current?.stop?.();
      drawRef.current = null;
      map.remove();
      mapRef.current = null;
    };
  }, [initialGeometry]);

  const startPolygonMode = () => {
    drawRef.current?.setMode?.("polygon");
  };

  const startEditMode = () => {
    drawRef.current?.setMode?.("select");
  };

  const clearGeometry = () => {
    drawRef.current?.clear?.();
    setGeometry(null);
  };

  const resetGeometry = () => {
    drawRef.current?.clear?.();
    setGeometry(initialGeometry ?? null);
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={startPolygonMode}
          disabled={!drawReady}
          className="rounded-md border border-argus-border bg-argus-panel px-3 py-1.5 text-xs text-argus-text disabled:cursor-not-allowed disabled:opacity-40"
        >
          Draw polygon
        </button>
        <button
          type="button"
          onClick={startEditMode}
          disabled={!drawReady || !geometry}
          className="rounded-md border border-argus-border bg-argus-panel px-3 py-1.5 text-xs text-argus-muted disabled:cursor-not-allowed disabled:opacity-40"
        >
          Edit polygon
        </button>
        <button
          type="button"
          onClick={clearGeometry}
          className="rounded-md border border-argus-border bg-argus-panel px-3 py-1.5 text-xs text-argus-muted"
        >
          Clear
        </button>
        <button
          type="button"
          onClick={resetGeometry}
          className="rounded-md border border-argus-border bg-argus-panel px-3 py-1.5 text-xs text-argus-muted"
        >
          Reset
        </button>
        <span className="text-xs text-argus-muted">AOI area: {formatArea(areaM2)}</span>
      </div>
      {drawError ? <p className="text-xs text-argus-warn">{drawError}</p> : null}
      <div ref={containerRef} className="h-[360px] w-full overflow-hidden rounded-lg border border-argus-border" />
    </div>
  );
}
