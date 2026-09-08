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
