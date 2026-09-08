export type Position = [number, number];

export type GeoJsonPolygon = {
  type: "Polygon";
  coordinates: number[][][];
};

export type GeoJsonMultiPolygon = {
  type: "MultiPolygon";
  coordinates: number[][][][];
};

export type GeoJsonLineString = {
  type: "LineString";
  coordinates: number[][];
};

export type GeoJsonMultiLineString = {
  type: "MultiLineString";
  coordinates: number[][][];
};

export type GeoJsonPoint = {
  type: "Point";
  coordinates: Position;
};

export type GeoJsonGeometry =
  | GeoJsonPolygon
  | GeoJsonMultiPolygon
  | GeoJsonLineString
  | GeoJsonMultiLineString
  | GeoJsonPoint
  | {
      type: string;
      coordinates?: unknown;
      geometries?: GeoJsonGeometry[];
    };

export type Feature<G = GeoJsonGeometry, P = Record<string, unknown>> = {
  type: "Feature";
  geometry: G;
  properties: P;
  id?: string;
};

export type FeatureCollection<G = GeoJsonGeometry, P = Record<string, unknown>> = {
  type: "FeatureCollection";
  features: Array<Feature<G, P>>;
};
