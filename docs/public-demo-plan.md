# ARGUS Public Demo Plan

This document describes the planned public product direction after the engineering frontend foundation is completed.

## Product split

ARGUS public experience is intentionally separated into **EXPLORE** and **MONITOR**.

### EXPLORE (public, no-login)

- World/regional geospatial interface.
- Curated, precomputed ARGUS scenarios.
- Instant before/after viewing.
- Real stored change polygons and event intelligence.
- Anonymous users do not trigger expensive on-demand analysis jobs.

### MONITOR (restricted, authenticated later)

- User-defined AOIs.
- Scheduled monitoring workflows.
- Constrained quotas/limits.
- Real asynchronous backend orchestration (jobs, runs, schedules).

## Why precomputed public scenarios

A precomputed Explore layer keeps public demo cost and abuse risk controlled while still showcasing real ARGUS outputs.

## Curated showcase categories (future)

- Urban development
- Construction expansion
- Wildfire aftermath (only when externally validated as a known-event case study)
- Flood-related landscape change (only when externally validated as a known-event case study)
- Vegetation change
- Coastline change
- Agricultural change

Naming guidance:

- Use descriptive labels such as “Vegetation change” and “Built-area expansion” unless authoritative external evidence confirms event cause.
- Use “Known-event case study” when validated event context is available.

## Future high-end UI direction

Target experience: high-end geospatial analytical software with restrained visuals.

Planned interaction concepts:

- Globe-to-regional map transitions
- Map-centric application shell
- Command palette and keyboard shortcuts
- Dockable intelligence panels
- Event timeline
- Before/after imagery scrubber
- Layer controls
- Change-score visualization
- Event comparison workflows
- Satellite observation browser
- Job pipeline visualization
- Shareable event URLs
- GeoJSON/report exports
- System status and architecture visualization
- Subtle motion/transitions

Design rule:

**HIGH FEATURE DEPTH + RESTRAINED VISUAL PRESENTATION**

Avoid neon/cyberpunk aesthetics, constant animation, overdone glassmorphism, or portfolio gimmicks.
