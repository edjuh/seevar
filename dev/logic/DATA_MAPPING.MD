# 🗺️ SEEVAR DATA LIFECYCLE

> **Objective:** Concise map of data flow from AAVSO fetch to FITS custody.
> **Version:** 2.0.0 (Praw)
> **Path:** `logic/DATA_MAPPING.MD`

Full pipeline narrative: `CORE.MD`.
File schemas and ownership rules: `DATA_DICTIONARY.MD`.
Cadence and targeting logic: `AAVSO_LOGIC.MD`.

## Data Flow

| Step | Script | Input | Output |
|------|--------|-------|--------|
| 1. Harvest | `core/preflight/aavso_fetcher.py` | AAVSO TargetTool API | `catalogs/campaign_targets.json` |
| 2. Curate | `core/preflight/librarian.py` | `campaign_targets.json` | `catalogs/federation_catalog.json` |
| 3. Sequence | `core/preflight/chart_fetcher.py` | VSP API (`apps.aavso.org`) | `catalogs/reference_stars/*.json` |
| 4. Audit | `core/preflight/audit.py` | `federation_catalog.json` + `ledger.json` | `federation_catalog.json` (annotated) |
| 5. Plan | `core/preflight/nightly_planner.py` | `federation_catalog.json` + GPS | `data/tonights_plan.json` |
| 6. Acquire | `core/flight/pilot.py` `DiamondSequence` | `tonights_plan.json` + TCP port 4801 | `data/local_buffer/{TARGET}_{TS}_Raw.fits` |
| 7. Extract | `core/postflight/science_processor.py` | `*_Raw.fits` | `*_Green.fits` (Johnson V proxy) |
| 8. Ledger | `core/flight/orchestrator.py` | acquisition result | `data/ledger.json` (`last_success`, `attempts`) |
| 9. Custody | NAS rsync | `data/local_buffer/` | `/mnt/astronas/{TARGET}/` |
| 10. Report | `PhotometryPipeline` + WebObs | `*_Green.fits` + `reference_stars/*.json` | AAVSO extended format submission |

## Authority Rules

- `federation_catalog.json` — written by `librarian.py` and `audit.py` only.
  Never written by the flight loop.
- `tonights_plan.json` — written by `nightly_planner.py` (planning) and
  re-written by `orchestrator.py` (scored + annotated at flight time).
- `ledger.json` — written by `orchestrator.py` only, append-style per target.
  Never overwritten wholesale. See `DATA_DICTIONARY.MD`.
- `system_state.json` — written by `orchestrator.py` only. Volatile.
  Reset to IDLE each night by `state_flusher.py`.
- `local_buffer/` — transient. FITS files move to NAS after custody step.
  Never treat local buffer as archival storage.

## FITS Filename Convention

```
{TARGET}_{YYYYMMDDTHHMMSS}_Raw.fits    ← sovereign acquisition output
{TARGET}_{YYYYMMDDTHHMMSS}_Green.fits  ← science processor output
```

Example: `SS_CYG_20260412T213045_Raw.fits`
