"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import clsx from "clsx";
import type { FeatureCollection as GeoJsonFeatureCollection, Geometry } from "geojson";
import * as maplibregl from "maplibre-gl";
import type { LngLatBoundsLike, Map } from "maplibre-gl";
import { useEffect, useMemo, useRef } from "react";

import { formatArea, formatPercent } from "@/lib/format";
import { bboxFromGeometry } from "@/lib/map";
import { motionDuration, prefersReducedMotion } from "@/lib/motion";
import type { ChangeEvent, Monitor } from "@/types/api";

import { MAP_STYLE } from "@/lib/constants";

type ArgusMapProps = {
  monitor?: Monitor | null;
  events?: ChangeEvent[];
  selectedEventId?: string | null;
  onSelectEvent?: (eventId: string) => void;
  className?: string;
  initialCenter?: [number, number];
  initialZoom?: number;
  interactive?: boolean;
  ambientMotion?: boolean;
  fitOnSelection?: boolean;
  showMonitor?: boolean;
  showEvents?: boolean;
  focusNonce?: number;
};

const MONITOR_SOURCE_ID = "argus-monitor-source";
const EVENTS_SOURCE_ID = "argus-events-source";

function buildMonitorGeoJson(monitor?: Monitor | null): GeoJsonFeatureCollection {
  if (!monitor) {
    return { type: "FeatureCollection", features: [] };
  }

  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        id: monitor.id,
        geometry: monitor.geometry as unknown as Geometry,
        properties: {
          id: monitor.id,
          name: monitor.name,
        },
      },
    ],
  };
}

function buildEventsGeoJson(events: ChangeEvent[] = []): GeoJsonFeatureCollection {
  return {
    type: "FeatureCollection",
    features: events.map((event) => ({
      type: "Feature",
      id: event.id,
      geometry: event.geometry as unknown as Geometry,
      properties: {
        id: event.id,
        severity: event.severity,
        confidence: event.confidence,
        status: event.status,
        area_m2: event.area_m2,
      },
    })),
  };
}

function toBounds(bbox: [number, number, number, number]): LngLatBoundsLike {
  return [
    [bbox[0], bbox[1]],
    [bbox[2], bbox[3]],
  ];
}

export function ArgusMap({
  monitor,
  events = [],
  selectedEventId,
  onSelectEvent,
  className,
  initialCenter = [-80.84, 35.23],
  initialZoom = 9,
  interactive = true,
  ambientMotion = false,
  fitOnSelection = true,
  showMonitor = true,
  showEvents = true,
  focusNonce,
}: ArgusMapProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);

  const monitorCollection = useMemo(() => buildMonitorGeoJson(monitor), [monitor]);
  const eventsCollection = useMemo(() => buildEventsGeoJson(events), [events]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) {
      return;
    }

    const reduceMotion = prefersReducedMotion();

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: MAP_STYLE,
      center: initialCenter,
      zoom: initialZoom,
      bearing: ambientMotion ? -4 : 0,
      pitch: ambientMotion ? 22 : 0,
      dragRotate: interactive,
      interactive,
      scrollZoom: interactive,
      doubleClickZoom: interactive,
      touchZoomRotate: interactive,
      attributionControl: {},
    });

    if (interactive) {
      map.addControl(new maplibregl.NavigationControl(), "top-right");
    }

    let ambientTimer: number | null = null;
    if (ambientMotion && !interactive && !reduceMotion) {
      let tick = 0;
      ambientTimer = window.setInterval(() => {
        tick += 1;
        const nextLng = initialCenter[0] + Math.sin(tick / 2.2) * 5.5;
        const nextLat = initialCenter[1] + Math.cos(tick / 2.8) * 1.8;
        map.easeTo({
          center: [nextLng, nextLat],
          bearing: -4 + Math.sin(tick / 2.4) * 3,
          duration: motionDuration(3200, 0, reduceMotion),
          essential: true,
        });
      }, 3600);
    }

    map.on("load", () => {
      map.addSource(MONITOR_SOURCE_ID, {
        type: "geojson",
        data: monitorCollection,
      });

      map.addLayer({
        id: "monitor-fill",
        type: "fill",
        source: MONITOR_SOURCE_ID,
        paint: {
          "fill-color": "#7cadff",
          "fill-opacity": 0.12,
        },
      });

      map.addLayer({
        id: "monitor-outline",
        type: "line",
        source: MONITOR_SOURCE_ID,
        paint: {
          "line-color": "#a9c8ff",
          "line-width": 1.7,
          "line-opacity": 0.9,
        },
      });

      map.addSource(EVENTS_SOURCE_ID, {
        type: "geojson",
        data: eventsCollection,
      });

      map.addLayer({
        id: "events-fill",
        type: "fill",
        source: EVENTS_SOURCE_ID,
        paint: {
          "fill-color": [
            "match",
            ["get", "severity"],
            "critical",
            "#ff7f7f",
            "high",
            "#ff9a63",
            "medium",
            "#edbf65",
            "#59c794",
          ],
          "fill-opacity": selectedEventId ? 0.15 : 0.3,
        },
      });

      map.addLayer({
        id: "events-selected-fill",
        type: "fill",
        source: EVENTS_SOURCE_ID,
        filter: ["==", ["get", "id"], selectedEventId ?? ""],
        paint: {
          "fill-color": "#9fc2ff",
          "fill-opacity": 0.32,
        },
      });

      map.addLayer({
        id: "events-outline",
        type: "line",
        source: EVENTS_SOURCE_ID,
        paint: {
          "line-color": "rgba(245, 249, 255, 0.82)",
          "line-width": 1,
          "line-opacity": selectedEventId ? 0.5 : 0.75,
        },
      });

      map.addLayer({
        id: "events-selected",
        type: "line",
        source: EVENTS_SOURCE_ID,
        filter: ["==", ["get", "id"], selectedEventId ?? ""],
        paint: {
          "line-color": "#dbe9ff",
          "line-width": 3.5,
          "line-opacity": 0.95,
        },
      });

      const setVisibility = (layerId: string, visible: boolean) => {
        if (map.getLayer(layerId)) {
          map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
        }
      };

      setVisibility("monitor-fill", showMonitor);
      setVisibility("monitor-outline", showMonitor);
      setVisibility("events-fill", showEvents);
      setVisibility("events-selected-fill", showEvents);
      setVisibility("events-outline", showEvents);
      setVisibility("events-selected", showEvents);

      if (showEvents) {
        map.on("click", "events-fill", (ev: any) => {
          const feature = ev.features?.[0];
          const eventId = feature?.properties?.id;
          if (typeof eventId === "string" && onSelectEvent) {
            onSelectEvent(eventId);
          }
        });

        map.on("mousemove", "events-fill", (ev: any) => {
          map.getCanvas().style.cursor = "pointer";
          const feature = ev.features?.[0];
          const props = feature?.properties;
          if (!props) {
            return;
          }

          const eventId = typeof props.id === "string" ? props.id : "unknown";
          const severity = typeof props.severity === "string" ? props.severity : "—";
          const confidence = Number(props.confidence);
          const areaM2 = Number(props.area_m2);

          const html = `
            <div style="font-size:12px;line-height:1.4">
              <div style="font-weight:600">Event ${eventId.slice(0, 8)}</div>
              <div>Severity: ${severity}</div>
              <div>Confidence: ${Number.isFinite(confidence) ? formatPercent(confidence * 100, 1) : "—"}</div>
              <div>Area: ${Number.isFinite(areaM2) ? formatArea(areaM2) : "—"}</div>
            </div>
          `;

          if (!popupRef.current) {
            popupRef.current = new maplibregl.Popup({ closeButton: false, closeOnClick: false });
          }

          popupRef.current.setLngLat(ev.lngLat).setHTML(html).addTo(map);
        });

        map.on("mouseleave", "events-fill", () => {
          map.getCanvas().style.cursor = "";
          popupRef.current?.remove();
        });
      }
    });

    mapRef.current = map;

    return () => {
      popupRef.current?.remove();
      popupRef.current = null;
      if (ambientTimer !== null) {
        window.clearInterval(ambientTimer);
      }
      map.remove();
      mapRef.current = null;
    };
  }, [ambientMotion, eventsCollection, fitOnSelection, initialCenter, initialZoom, interactive, monitorCollection, onSelectEvent, selectedEventId, showEvents, showMonitor]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) {
      return;
    }

    const source = map.getSource(MONITOR_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
    source?.setData(monitorCollection as never);

    const eventSource = map.getSource(EVENTS_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
    eventSource?.setData(eventsCollection as never);

    if (map.getLayer("events-selected")) {
      map.setFilter("events-selected", ["==", ["get", "id"], selectedEventId ?? ""]);
    }
    if (map.getLayer("events-selected-fill")) {
      map.setFilter("events-selected-fill", ["==", ["get", "id"], selectedEventId ?? ""]);
    }

    if (map.getLayer("events-fill")) {
      map.setPaintProperty("events-fill", "fill-opacity", selectedEventId ? 0.15 : 0.3);
    }
    if (map.getLayer("events-outline")) {
      map.setPaintProperty("events-outline", "line-opacity", selectedEventId ? 0.5 : 0.75);
    }

    const setVisibility = (layerId: string, visible: boolean) => {
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
      }
    };

    setVisibility("monitor-fill", showMonitor);
    setVisibility("monitor-outline", showMonitor);
    setVisibility("events-fill", showEvents);
    setVisibility("events-selected-fill", showEvents);
    setVisibility("events-outline", showEvents);
    setVisibility("events-selected", showEvents);
  }, [eventsCollection, monitorCollection, selectedEventId, showEvents, showMonitor]);

  useEffect(() => {
    if (!fitOnSelection) {
      return;
    }

    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) {
      return;
    }

    const selectedEvent = selectedEventId ? events.find((item) => item.id === selectedEventId) ?? null : null;
    const targetGeometry = selectedEvent?.geometry ?? monitor?.geometry;

    if (!targetGeometry) {
      return;
    }

    const bbox = bboxFromGeometry(targetGeometry);
    if (!bbox) {
      return;
    }

    map.fitBounds(toBounds(bbox), {
      padding: 56,
      duration: motionDuration(620, 0, prefersReducedMotion()),
      maxZoom: selectedEvent ? 15 : 14,
      essential: true,
    });

    if (map.getLayer("events-selected") && selectedEvent) {
      map.setPaintProperty("events-selected", "line-width", 5.5);
      window.setTimeout(() => {
        const currentMap = mapRef.current;
        if (!currentMap || !currentMap.getLayer("events-selected")) {
          return;
        }
        currentMap.setPaintProperty("events-selected", "line-width", 3.5);
      }, 500);
    }
  }, [events, fitOnSelection, focusNonce, monitor?.geometry, selectedEventId]);

  return (
    <div ref={rootRef} className={clsx("relative min-h-[360px] overflow-hidden rounded-xl border border-argus-border", className)}>
      <div ref={containerRef} className="absolute inset-0" aria-label="ARGUS map" />
      <div className="pointer-events-none absolute inset-0 argus-map-vignette" />
      <div className="pointer-events-none absolute inset-0 argus-scan-sweep opacity-35" />
    </div>
  );
}
