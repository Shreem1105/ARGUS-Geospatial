# ARGUS Backend

Initial FastAPI backend setup for ARGUS.

## Run locally

1. Install dependencies:

```bash
pip install -e .
```

2. Start the API:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Endpoints

- `GET /`
- `GET /health`
- `GET /ready` (checks PostgreSQL + PostGIS readiness)

## Database (Development)

ARGUS uses PostgreSQL with PostGIS for spatial support.

From the ARGUS root directory:

```bash
docker compose up -d db
docker compose ps
docker compose down
```

## Satellite Observations (STAC)

ARGUS can discover Sentinel-2 observation metadata for a Monitor AOI using the Microsoft Planetary Computer STAC API.

- **Search + persist**: `POST /monitors/{monitor_id}/observations/search`
  - Searches Sentinel-2 L2A observations for the Monitor geometry (`intersects`) and requested date range.
  - Applies cloud filtering via `max_cloud_cover` (`eo:cloud_cover`).
  - Normalizes and stores observation metadata (no raster downloads in this stage).
  - Repeated searches avoid duplicates via unique constraints + upsert behavior.
- **List stored observations**: `GET /monitors/{monitor_id}/observations`
  - Supports pagination (`limit`, `offset`) and optional filters (`start_date`, `end_date`, `max_cloud_cover`, `platform`).
- **Get one stored observation**: `GET /monitors/{monitor_id}/observations/{observation_id}`

This pipeline is observation-driven and supports near-real-time monitoring where source imagery availability permits.

## Raster Preprocessing (Sentinel-2)

ARGUS can prepare a stored Sentinel-2 observation into local analysis-ready raster artifacts.

- **Prepare observation**: `POST /monitors/{monitor_id}/observations/{observation_id}/prepare`
  - Uses Sentinel-2 assets `B02`, `B03`, `B04`, `B08`, and `SCL`.
  - Signs Planetary Computer asset URLs, performs windowed COG reads, crops to Monitor AOI, and aligns all outputs to a 10m reference grid derived from `B04`.
  - Resolves reflectance conversion as `reflectance = raw * scale + offset` using dataset metadata when available, then STAC raster metadata, then provider-aware fallback for Planetary Computer Sentinel-2 L2A.
  - Applies SCL cloud classes (`3, 8, 9, 10, 11`) and excludes SCL invalid classes (`0, 1, 255`).
  - Writes local artifacts under `ARGUS_DATA_DIR/prepared/<monitor_id>/<observation_id>/`:
    - `multispectral.tif` (4-band float32)
    - `valid_mask.tif` (1-band uint8)
    - `preview.png` (RGB quicklook)
  - Enforces `max(preview.width, preview.height) <= 1024` for previews only.
  - Stores processing metadata including `processing_version=sentinel2-preprocess-v1`, reflectance scaling source, cloud-fraction/valid-fraction definitions, and target grid details.
- **Get prepared product**: `GET /monitors/{monitor_id}/observations/{observation_id}/prepared`

Prepared-product idempotency is artifact-aware: if an existing `ready` row points to missing/corrupt artifacts (`multispectral.tif`, `valid_mask.tif`, `preview.png`), ARGUS automatically reprocesses and repairs metadata.

Definitions:
- `cloud_fraction = cloud_or_shadow_or_snow_pixels / usable_scl_pixels_within_aoi`
- `valid_fraction = valid_pixels / total_aoi_pixels`

## Temporal Change Analysis

ARGUS supports deterministic before/after analysis over two prepared observations of the same monitor.

- **Manual analysis**: `POST /monitors/{monitor_id}/analyses`
- **Auto pair selection**: `POST /monitors/{monitor_id}/analyses/auto`
- **List analyses**: `GET /monitors/{monitor_id}/analyses`
- **Get one analysis**: `GET /monitors/{monitor_id}/analyses/{analysis_id}`

Behavior and method:
- Enforces chronology: `before.acquired_at < after.acquired_at`.
- Requires both prepared products to be `ready` and artifact-valid.
- Uses a common comparison grid (deterministically the **after** grid).
- Reprojects before reflectance bands with `bilinear` and masks with `nearest`.
- Builds `valid_comparison_mask` where before/after are mutually valid and inside AOI.
- Computes baseline indicators:
  - NDVI (`(NIR - RED) / (NIR + RED)`)
  - 4-band spectral distance (`sqrt(mean((after-before)^2))`)
  - Combined normalized change score (robust percentile normalization + weighted blend).
- Applies a heuristic threshold (default `0.30`) and removes small connected components using monitor/request minimum area.
- Persists artifacts under `data/analyses/<monitor_id>/<analysis_id>/`:
  - `change_score.tif` (float32)
  - `change_mask.tif` (uint8)
  - `valid_comparison_mask.tif` (uint8)
  - `preview.png` (max dimension `<= 1024`)
- Stores quantitative metrics and summary statistics in `change_analyses.statistics`.
- Reuses identical existing ready analyses when artifacts are healthy; repairs/reprocesses if metadata exists but files are missing/corrupt.

Current limitation:

ARGUS currently identifies candidate spectral/vegetation changes. It does not yet infer the real-world cause of a detected change.

## GIS Change Events

ARGUS converts cleaned raster change masks into persistent PostGIS GIS events.

- **Generate events**: `POST /monitors/{monitor_id}/analyses/{analysis_id}/events`
  - Polygonizes `change_mask.tif` changed regions (`value == 1`) with Rasterio/GDAL-backed shape extraction.
  - Repairs invalid geometries, keeps disconnected components as separate events, and stores final geometries in PostGIS as `geometry(Polygon, 4326)`.
  - Computes per-event area/perimeter in projected meters and event-level spectral stats from analysis rasters (`mean_change_score`, `max_change_score`, `mean_abs_delta_ndvi`, `mean_spectral_distance`, `pixel_count`).
  - Computes deterministic event confidence and severity and persists lifecycle status (`new`, `reviewed`, `dismissed`, `confirmed`).
  - Is idempotent by generation version: if the same completed event-generation version already exists, ARGUS returns stored events without duplicate inserts.
- **List monitor events**: `GET /monitors/{monitor_id}/events`
  - Supports pagination and filters (`severity`, `status`, `min_confidence`, `min_area_m2`, `analysis_id`).
- **List analysis events**: `GET /monitors/{monitor_id}/analyses/{analysis_id}/events`
- **Get one event**: `GET /monitors/{monitor_id}/events/{event_id}`
- **Patch event status**: `PATCH /monitors/{monitor_id}/events/{event_id}`
- **Event spatial summary**: `GET /monitors/{monitor_id}/events/{event_id}/summary`
  - Returns GeometryType/SRID, geography area/perimeter, stored area/perimeter, centroid, and bounding box.
- **Spatial intersection query**: `POST /monitors/{monitor_id}/events/intersects`
- **Monitor aggregate summary**: `GET /monitors/{monitor_id}/events/summary`

ChangeEvent confidence represents the strength and consistency of detected change evidence. It is not a calibrated probability that a real-world event occurred.

Severity currently represents relative magnitude of detected geographic change, not danger, damage, or infrastructure impact.

## Context and Impact Intelligence

ARGUS can enrich ChangeEvents with real external GIS context sourced from OpenStreetMap data.

- **Context refresh**: `POST /monitors/{monitor_id}/context/refresh`
  - Uses the Monitor AOI to query roads, buildings, waterways, and administrative boundaries.
  - Normalizes and persists provider features in PostGIS as `context_features`.
  - Refresh behavior is additive/update-based (upsert); missing later-provider features are not auto-deleted in this stage.
- **Context list + summary**:
  - `GET /monitors/{monitor_id}/context`
  - `GET /monitors/{monitor_id}/context/summary`

Impact computation is local/PostGIS-only after context is loaded.

- **Compute one event impact**: `POST /monitors/{monitor_id}/events/{event_id}/impact`
- **Read one event impact**: `GET /monitors/{monitor_id}/events/{event_id}/impact`
- **Compute one analysis impacts (bulk events)**: `POST /monitors/{monitor_id}/analyses/{analysis_id}/impact`
- **Monitor impact aggregate**: `GET /monitors/{monitor_id}/impact/summary`

Current impact outputs include:

- road intersections + nearby roads (default nearby buffer: 100 m)
- building overlap area + nearby buildings
- waterway intersections/proximity
- administrative areas intersecting detected changes

PostGIS is used for geometric relationships and metrics (e.g., `ST_Intersects`, `ST_Intersection`, `ST_DWithin`, geography-based distance/length/area in meters).

Important interpretation notes:

- A spatial intersection indicates that a mapped feature overlaps a detected change region. It does not by itself prove that the feature was damaged, blocked, destroyed, or otherwise physically affected.
- Nearby features are contextual information only.

Provider attribution for contextual map data:

- © OpenStreetMap contributors
