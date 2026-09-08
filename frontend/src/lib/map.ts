import type { GeoJsonGeometry, GeoJsonPolygon } from "@/types/geojson";

export function extractCoordinates(geometry: GeoJsonGeometry): Array<[number, number]> {
  const toPair = (coordinate: number[]): [number, number] => [Number(coordinate[0]), Number(coordinate[1])];

  switch (geometry.type) {
    case "Point":
      return [geometry.coordinates as [number, number]];
    case "LineString":
      return (geometry.coordinates as number[][]).map(toPair);
    case "MultiLineString":
      return (geometry.coordinates as number[][][]).flatMap((line) => line.map(toPair));
    case "Polygon":
      return (geometry.coordinates as number[][][]).flatMap((ring) => ring.map(toPair));
    case "MultiPolygon":
      return (geometry.coordinates as number[][][][]).flatMap((poly) => poly.flatMap((ring) => ring.map(toPair)));
    default:
      return [];
  }
}

export function bboxFromGeometry(geometry: GeoJsonGeometry): [number, number, number, number] | null {
  const coordinates = extractCoordinates(geometry);
  if (coordinates.length === 0) {
    return null;
  }

  let minLon = Number.POSITIVE_INFINITY;
  let minLat = Number.POSITIVE_INFINITY;
  let maxLon = Number.NEGATIVE_INFINITY;
  let maxLat = Number.NEGATIVE_INFINITY;

  for (const [lon, lat] of coordinates) {
    minLon = Math.min(minLon, lon);
    minLat = Math.min(minLat, lat);
    maxLon = Math.max(maxLon, lon);
    maxLat = Math.max(maxLat, lat);
  }

  return [minLon, minLat, maxLon, maxLat];
}

export function bboxFromPolygon(polygon: GeoJsonPolygon): [number, number, number, number] | null {
  return bboxFromGeometry(polygon);
}

export function safeJsonParse<T>(value: string): T | null {
  try {
    return JSON.parse(value) as T;
  } catch {
    return null;
  }
}
