import type { StyleSpecification } from "maplibre-gl";

export const ARGUS_API_PROXY_BASE = "/api/backend";
export const DEFAULT_MONITOR_LIMIT = 50;
export const DEFAULT_LIST_LIMIT = 50;
export const MAX_LIST_LIMIT = 100;
export const DEFAULT_EVENT_BUFFER_M = 100;

export const MAP_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    darkBase: {
      type: "raster",
      tiles: [
        "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
      ],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors © CARTO",
    },
  },
  layers: [
    {
      id: "dark-base",
      type: "raster",
      source: "darkBase",
      minzoom: 0,
      maxzoom: 22,
    },
  ],
};
