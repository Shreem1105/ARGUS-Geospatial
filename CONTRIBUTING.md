# Contributing to ARGUS

Thanks for contributing.

## Local setup

1. Copy `.env.example` to `.env` and adjust local values.
2. Start infrastructure from the repository root:
   - `docker compose up -d db redis`
   - `docker compose up -d worker scheduler`
3. Start API from `backend/`:
   - `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`

## Branching

- Branch from `main`.
- Use focused commits with descriptive messages.
- Keep pull requests scoped to one concern when possible.

## Testing before PR

Run from `backend/`:

- `python -m pytest -q`

Include test notes in the PR.

## Secrets and data safety

- Never commit `.env`, credentials, tokens, or signed URLs.
- Never commit generated raster artifacts, local caches, or temporary live-validation outputs.
- Keep provider query/output dumps out of version control unless intentionally sanitized for fixtures.

## Geospatial/source attribution

- Preserve attribution when using OSM, Census, Sentinel, and related public sources.
- Keep provider usage aligned with each source terms/licensing.

## Semantic safety

- Do not describe spatial overlap/proximity as confirmed physical damage.
- Use language such as “intersects,” “overlaps,” or “near detected change.”
