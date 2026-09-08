"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import type { FeatureCollection as GeoJsonFeatureCollection, Geometry } from "geojson";
import * as maplibregl from "maplibre-gl";
import type { LngLatBoundsLike, Map } from "maplibre-gl";
import { useEffect, useMemo, useRef } from "react";

import { formatArea, formatPercent } from "@/lib/format";
import { bboxFromGeometry } from "@/lib/map";
import type { ChangeEvent, Monitor } from "@/types/api";

import { MAP_STYLE } from "@/lib/constants";

type ArgusMapProps = {
  monitor?: Monitor | null;
  events?: ChangeEvent[];
  selectedEventId?: string | null;
  onSelectEvent?: (eventId: string) => void;
  className?: string;
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

export function ArgusMap({ monitor, events = [], selectedEventId, onSelectEvent, className }: ArgusMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);

  const monitorCollection = useMemo(() => buildMonitorGeoJson(monitor), [monitor]);
  const eventsCollection = useMemo(() => buildEventsGeoJson(events), [events]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) {
      return;
    }

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: MAP_STYLE,
      center: [-80.84, 35.23],
      zoom: 9,
      attributionControl: {},
    });

    map.addControl(new maplibregl.NavigationControl(), "top-right");

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
          "fill-color": "#3da9fc",
          "fill-opacity": 0.12,
        },
      });

      map.addLayer({
        id: "monitor-outline",
        type: "line",
        source: MONITOR_SOURCE_ID,
        paint: {
          "line-color": "#3da9fc",
          "line-width": 2,
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
            "#ff3b30",
            "high",
            "#ff8a00",
            "medium",
            "#f5b642",
            "#2cc58a",
          ],
          "fill-opacity": 0.34,
        },
      });

      map.addLayer({
        id: "events-outline",
        type: "line",
        source: EVENTS_SOURCE_ID,
        paint: {
          "line-color": "#f8fbff",
          "line-width": 1,
        },
      });

      map.addLayer({
        id: "events-selected",
        type: "line",
        source: EVENTS_SOURCE_ID,
        filter: ["==", ["get", "id"], selectedEventId ?? ""],
        paint: {
          "line-color": "#3da9fc",
          "line-width": 4,
        },
      });

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
          <div style="font-size:12px;line-height:1.35">
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
    });

    mapRef.current = map;

    return () => {
      popupRef.current?.remove();
      popupRef.current = null;
      map.remove();
      mapRef.current = null;
    };
  }, [eventsCollection, monitorCollection, onSelectEvent, selectedEventId]);

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

    const selectedEvent = selectedEventId ? events.find((item) => item.id === selectedEventId) ?? null : null;
    const targetGeometry = selectedEvent?.geometry ?? monitor?.geometry;

    if (!targetGeometry) {
      return;
    }

    const bbox = bboxFromGeometry(targetGeometry);
    if (!bbox) {
      return;
    }

    map.fitBounds(toBounds(bbox), { padding: 50, duration: 500, maxZoom: selectedEvent ? 15 : 14 });
  }, [monitorCollection, eventsCollection, selectedEventId, monitor, events]);

  return <div ref={containerRef} className={className ?? "h-full min-h-[360px] w-full rounded-lg"} aria-label="ARGUS map" />;
}
