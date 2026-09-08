"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import area from "@turf/area";
import { feature as turfFeature, polygon as turfPolygon } from "@turf/helpers";
import * as maplibregl from "maplibre-gl";
import type { Map } from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";

import { MAP_STYLE } from "@/lib/constants";
import { formatArea } from "@/lib/format";
import type { GeoJsonPolygon } from "@/types/geojson";

type AoiDrawMapProps = {
  onGeometryChange: (geometry: GeoJsonPolygon | null) => void;
  initialGeometry?: GeoJsonPolygon | null;
};

const DRAW_SOURCE_ID = "argus-draw-source";

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

  useEffect(() => {
    onGeometryChange(geometry);
  }, [geometry, onGeometryChange]);

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
        data: {
          type: "FeatureCollection",
          features: geometry
            ? [
                {
                  type: "Feature",
                  geometry,
                  properties: {},
                },
              ]
            : [],
        },
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
          const polygon = snapshot.find((entry: any) => entry.geometry?.type === "Polygon")?.geometry;
          if (polygon && polygon.coordinates) {
            const casted = polygon as GeoJsonPolygon;
            setGeometry(casted);

            const source = map.getSource(DRAW_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
            source?.setData({
              type: "FeatureCollection",
              features: [{ type: "Feature", geometry: casted, properties: {} }],
            } as never);
          }
        };

        draw.on("finish", syncFromSnapshot);
        draw.on("change", syncFromSnapshot);
        draw.on("delete", () => {
          setGeometry(null);
          const source = map.getSource(DRAW_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
          source?.setData({ type: "FeatureCollection", features: [] } as never);
        });
      } catch {
        setDrawError("AOI drawing tools unavailable in this environment.");
      }
    });

    mapRef.current = map;

    return () => {
      if (drawRef.current) {
        drawRef.current.stop?.();
      }
      map.remove();
      mapRef.current = null;
    };
  }, [geometry]);

  const startPolygonMode = () => {
    drawRef.current?.setMode?.("polygon");
  };

  const clearGeometry = () => {
    drawRef.current?.clear?.();
    setGeometry(null);
    const source = mapRef.current?.getSource(DRAW_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
    source?.setData({ type: "FeatureCollection", features: [] } as never);
  };

  const setRectanglePreset = () => {
    const preset: GeoJsonPolygon = turfPolygon([
      [
        [-80.85, 35.22],
        [-80.84, 35.22],
        [-80.84, 35.23],
        [-80.85, 35.23],
        [-80.85, 35.22],
      ],
    ]).geometry as GeoJsonPolygon;

    setGeometry(preset);
    const source = mapRef.current?.getSource(DRAW_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
    source?.setData({ type: "FeatureCollection", features: [{ type: "Feature", geometry: preset, properties: {} }] } as never);
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
          onClick={clearGeometry}
          className="rounded-md border border-argus-border bg-argus-panel px-3 py-1.5 text-xs text-argus-muted"
        >
          Clear
        </button>
        <button
          type="button"
          onClick={setRectanglePreset}
          className="rounded-md border border-argus-border bg-argus-panel px-3 py-1.5 text-xs text-argus-muted"
        >
          Quick Charlotte preset
        </button>
        <span className="text-xs text-argus-muted">AOI area: {formatArea(areaM2)}</span>
      </div>
      {drawError ? <p className="text-xs text-argus-warn">{drawError}</p> : null}
      <div ref={containerRef} className="h-[360px] w-full overflow-hidden rounded-lg border border-argus-border" />
    </div>
  );
}
