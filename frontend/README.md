# ARGUS Frontend

ARGUS frontend is a map-first operational UI built with Next.js App Router.

## Canonical routes

- `/`
- `/explore`
- `/explore/[caseId]`
- `/monitors`
- `/monitors/new`
- `/monitors/[monitorId]`
- `/events`
- `/runs`

Legacy aliases still exist as redirects:

- `/monitor` → `/monitors`
- `/monitor/[monitorId]` → `/monitors/[monitorId]`

## Product surfaces

- **Explore**: public-style map workspace using persisted backend data; no fake curated science values.
- **Monitors list/create**: real monitor creation flow with AOI draw/edit/reset and backend validation.
- **Monitor detail workspace**: AOI + change-event map, event intelligence panel, run history, active job progress, schedule editor, observations, and before/after imagery artifacts.
- **Global Events / Runs**: cross-monitor operational feeds.

## Visual system and motion

- ARGUS uses a restrained dark geospatial palette with map-first layouts and docked/floating workspace panels.
- Route transitions, panel transitions, scan overlays, and map ambience are intentionally subtle and non-blocking.
- Keyboard shortcuts support rapid navigation and investigation workflows (`Ctrl/Cmd+K`, `G then E/M`, `[` / `]`, `F`, `L/I/T`, `?`).
- `prefers-reduced-motion` is respected in CSS and map animation behavior.

## Workspace structure

- **Shell**: sticky workspace nav, command palette, system health pill, and keyboard-shortcut overlay.
- **Explore**: left controls + dominant map + right intelligence inspector + bottom event timeline.
- **Monitor detail**: dominant map, collapsible intelligence panel, observation timeline, and layer-mode controls.
- **Monitor creation**: guided map-first flow (draw AOI → configure → review).

## Backend integration

- Frontend API calls go through `/api/backend/*` rewrite to `NEXT_PUBLIC_ARGUS_API_BASE_URL`.
- Manual run action uses `POST /monitors/{monitor_id}/runs` and polls `GET /jobs/{job_id}` for real stage progress.
- Pipeline stages shown in UI are mapped from backend `progress_stage` values:
  - Satellite → Prepare → Detect → Vectorize → Context → Exposure.

## Local development

From `W:\Projects\Argus\frontend`:

```bash
npm install
npm run dev
```

## Quality checks

```bash
npm run lint
npm run typecheck
npm run test
npm run build
```
