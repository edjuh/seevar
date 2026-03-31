# 🚀 PREFLIGHT

> **Version:** 2.0.0
> **Path:** `dev/logic/PREFLIGHT.MD`

Preflight is Phase 1 of the pipeline. Full phase diagram: `WORKFLOW.md`.

## Two Sub-Phases

### 1a — Data Pipeline (weekly / on-demand)

| Script | Action | Output |
|--------|--------|--------|
| `core/preflight/aavso_fetcher.py` | Pull targets from AAVSO TargetTool | `catalogs/campaign_targets.json` |
| `core/preflight/chart_fetcher.py` | Fetch VSP comp star sequences (FOV: ~300') | `catalogs/reference_stars/*.json` |
| `core/preflight/librarian.py` | Validate and cross-reference | `catalogs/federation_catalog.json` |
| `core/preflight/audit.py` | Apply cadence rules per type | `catalogs/federation_catalog.json` (annotated) |

### 1b — Nightly Planning (daily @ 17:00)

| Script | Action | Output |
|--------|--------|--------|
| `core/preflight/state_flusher.py` | Reset `system_state.json` to IDLE | `data/system_state.json` |
| `core/ledger_manager.py` | Filter to targets due tonight by cadence | (in-memory) |
| `core/preflight/nightly_planner.py` | Apply altitude (>30°) + astronomical dark window | `data/tonights_plan.json` |

## Go / No-Go Gate

All checks must return GREEN. Any RED = scrub.

| Pillar | Script | Check |
|--------|--------|-------|
| 1 — Storage | `core/preflight/disk_monitor.py` | Local buffer + RAID1 space |
| 2 — Hardware | `core/preflight/preflight_checklist.py` | Alpaca management API on port 32323 |
| 3 — Time | `core/utils/gps_monitor.py` | GPS lock + PPS clock offset < 0.5s |
| 4 — Weather | `core/preflight/weather.py` | Tri-source consensus, imaging_go flag |
| 5 — Fog | `core/preflight/fog_monitor.py` | MLX90614 IR sky temperature |

## Cadence Rules

| Type | Window |
|------|--------|
| M / LPV | 7 days |
| SR | 4 days |
| SRC | 5 days |
| CV / UG / RR | 1 day |
