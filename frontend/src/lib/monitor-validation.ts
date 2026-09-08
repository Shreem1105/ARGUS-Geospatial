import type { GeoJsonPolygon } from "@/types/geojson";

export function validateMonitorPolygon(geometry: GeoJsonPolygon | null): string | null {
  if (!geometry) {
    return "AOI polygon is required.";
  }

  if (geometry.type !== "Polygon" || !Array.isArray(geometry.coordinates) || geometry.coordinates.length === 0) {
    return "AOI must be a valid GeoJSON Polygon.";
  }

  const outer = geometry.coordinates[0];
  if (!Array.isArray(outer) || outer.length < 4) {
    return "AOI polygon ring must include at least 4 positions.";
  }

  const first = outer[0];
  const last = outer[outer.length - 1];
  if (!Array.isArray(first) || !Array.isArray(last) || first.length < 2 || last.length < 2) {
    return "AOI polygon coordinates are invalid.";
  }

  if (first[0] !== last[0] || first[1] !== last[1]) {
    return "AOI polygon must be closed (first and last coordinate must match).";
  }

  return null;
}
