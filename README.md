# ARGUS

**Autonomous Geospatial Intelligence Platform**

ARGUS monitors geographic areas using real satellite imagery, detects temporal change, converts detections into GIS events, enriches them with infrastructure/population/land-cover context, and runs observation-driven monitoring workflows.

[Architecture](#architecture) · [Local Setup](#local-development) · [API](#api) · [Testing](#testing)

| Status Area | Current State |
| --- | --- |
| Backend | Operational |
| Async monitoring (Redis + Celery) | Operational |
| Frontend | Operational |

## What ARGUS Does

ARGUS runs an end-to-end geospatial workflow:

AOI → satellite discovery → preprocessing → temporal analysis → GIS event generation → contextual spatial analysis → exposure intelligence → asynchronous monitoring.

## Core Capabilities

- Sentinel-2 observation discovery through Microsoft Planetary Computer STAC.
- AOI-aware raster preparation with cloud/validity masking.
- Temporal spectral + NDVI change analysis over prepared observations.
- Raster-to-vector ChangeEvent generation in PostGIS.
- OSM-based contextual enrichment (roads, buildings, waterways, administrative context).
- Census-based population exposure estimation (areal-weighted).
- ESA WorldCover-based land-cover exposure summarization.
- Environmental/protected-area contextual overlap and proximity analysis.
- Redis + Celery-backed asynchronous monitor runs and scheduler scans.
- Idempotent persistence patterns across observations, preparation, analyses, events, and enrichment records.

## Architecture

```mermaid
flowchart TD
    user[User / API Client] --> api[FastAPI]
    api --> db[(PostgreSQL + PostGIS)]

    api --> redis[(Redis)]
    redis --> worker[Celery Worker]

    worker --> stac[Planetary Computer STAC]
    worker --> prep[Raster Preprocessing]
    prep --> analysis[ChangeAnalysis]
    analysis --> events[ChangeEvents]
    events --> enrich[Spatial Enrichment\n(Context + Exposure)]
    enrich --> db

    scheduler[Celery Beat Scheduler] --> due[Due Monitor Scan]
    due --> redis
```

## Processing Pipeline

1. A Monitor AOI is validated and stored in PostGIS.
2. ARGUS queries Sentinel-2 STAC metadata intersecting the AOI and date window.
3. Selected observations are prepared into aligned multispectral analysis artifacts.
4. Before/after prepared observations are compared to produce a change score and change mask.
5. Raster change regions are vectorized into ChangeEvents.
6. ChangeEvents are enriched against stored contextual geospatial layers.
7. Exposure summaries are computed and persisted for downstream retrieval APIs.
8. Manual or scheduled monitor runs orchestrate the above asynchronously via Celery.

## Technology Stack

| Area | Stack |
| --- | --- |
| Backend | Python 3.11, FastAPI, Pydantic v2 |
| Geospatial | PostGIS, Shapely, GeoAlchemy2, PyProj |
| Satellite / Remote Sensing | Microsoft Planetary Computer STAC, pystac-client, rasterio |
| Database | PostgreSQL 16 + PostGIS 3.4, SQLAlchemy 2.x, Alembic |
| Async Infrastructure | Redis 7, Celery 5 |
| Frontend | Next.js 16 App Router, React 19, TypeScript, Tailwind CSS, MapLibre GL JS, TanStack Query |

## Example Real Validation

Example local validation run (September 7, 2026):

- `336` backend tests passed with `python -m pytest -q` (latest local verification).
- A live Sentinel-2 monitor run discovered and stored real observations from STAC.
- A real before/after pair was prepared and analyzed into persisted ChangeEvents.
- PostGIS readiness (`/ready`) and worker health (`/worker/health`) were validated.

These are example development-run results, not scale benchmarks.

## Data Sources

- Microsoft Planetary Computer (STAC APIs)
- Sentinel-2 L2A catalog items
- OpenStreetMap context features
- U.S. Census Bureau population datasets
- ESA WorldCover land-cover datasets

Attribution:

- © OpenStreetMap contributors
- Source: U.S. Census Bureau
- Contains modified Copernicus Sentinel data

## Local Development

From `W:\Projects\Argus`:

```bash
docker compose up -d db redis
docker compose up -d worker scheduler
```

From `W:\Projects\Argus\backend` (API):

```bash
C:\Users\shree\AppData\Local\Programs\Python\Python311\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

From `W:\Projects\Argus\frontend` (UI):

```bash
npm install
npm run dev
```

Stop services:

```bash
docker compose down
```

## API

Major endpoint groups:

- Monitor management and AOI operations.
- Satellite observations (search, persist, list, detail).
- Observation preparation and prepared artifact metadata retrieval.
- Change analyses and ChangeEvent retrieval.
- Context refresh/list/summary and impact endpoints.
- Population/land-cover/environment exposure endpoints.
- Async monitor runs, schedules, and job status endpoints.

## Testing

Primary command:

```bash
C:\Users\shree\AppData\Local\Programs\Python\Python311\python.exe -m pytest -q
```

Platform-neutral alternative:

```bash
python -m pytest -q
```

Latest confirmed result: `332 passed`.

## Limitations

- Optical imagery is affected by clouds, haze, and shadows.
- Monitoring depends on source imagery availability and latency.
- Current change scoring is heuristic evidence, not a calibrated probability.
- Population exposure is areal-weighted estimation, not person-level truth.
- Spatial overlap indicates geographic relationship, not proven damage or causation.
- Environmental overlap does not by itself prove ecological harm.
- ARGUS is observation-driven rather than true continuous real-time monitoring.

## Roadmap

Planned next steps:

- Curated public Explore showcase datasets (precomputed).
- Public Explore mode with curated scenarios.
- Constrained authenticated Monitor mode.
- Notifications.
- Cloud deployment.
- Known-event evaluation workflows.
- Performance benchmarking.
- Optional stronger semantic/ML models.

Roadmap items are planned work, not currently complete features.
