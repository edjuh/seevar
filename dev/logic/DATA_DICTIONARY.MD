# 🗂️ SEEVAR DATA DICTIONARY

> **Objective:** Strict schema and ownership rules for every file in the
> data/ and catalogs/ directories. Prevents corruption and write conflicts.
> **Version:** 2.0.0 (Praw)
> **Path:** `logic/DATA_DICTIONARY.MD`

Data flow between files: `DATA_MAPPING.MD`.
Authority rules summary: `DATA_MAPPING.MD` § Authority Rules.

**Golden rule:** every file has exactly one writer. If two scripts write
the same file, one of them is wrong.

---

## 📂 catalogs/ — Reference Data (not nightly)

### `catalogs/campaign_targets.json`
- **Writer:** `core/preflight/aavso_fetcher.py`
- **Readers:** `core/preflight/librarian.py`
- **Schema:** `name`, `ra` (hourangle str), `dec` (deg str), `type`,
  `auid`, `recommended_cadence_days`
- **Notes:** Raw AAVSO harvest. May contain duplicates. Updated weekly
  or on-demand. Never read by the flight loop.

### `catalogs/federation_catalog.json`
- **Writer:** `core/preflight/librarian.py` (structure),
  `core/preflight/audit.py` (cadence annotation)
- **Readers:** `core/preflight/nightly_planner.py`, `core/preflight/audit.py`
- **Schema:** `name`, `ra`, `dec`, `type`, `auid`,
  `recommended_cadence_days`, `cadence_due` (bool), `last_success` (ISO UTC)
- **Notes:** 409 stars. Immutable source of truth for the catalog.
  Never written by the flight loop.

### `catalogs/reference_stars/*.json`
- **Writer:** `core/preflight/chart_fetcher.py`
- **Readers:** `PhotometryPipeline` in `core/flight/pilot.py`
- **Schema:** `auid`, `label`, `ra_deg`, `dec_deg`, `mag_v`, `mag_b`
- **Notes:** One file per target. VSP API (`apps.aavso.org`).
  FOV ~300 arcmin — matches S30-Pro 4.6° field.
  Never read by the acquisition loop, only by photometry.

---

## 📂 data/ — Operational Files (nightly)

### `data/tonights_plan.json`
- **Writer:** `core/preflight/nightly_planner.py` (initial plan),
  `core/flight/orchestrator.py` (re-scored at flight time)
- **Readers:** `core/flight/orchestrator.py`
- **Schema:** `name`, `ra`, `dec`, `type`, `auid`,
  `_alt` (deg), `_az` (deg), `_ha` (hour angle, hours),
  `_score` (meridian-aware priority float)
- **Notes:** `_ha` < 0 = east of meridian. `_ha` > 0 = west of meridian.
  `_score` range 0–100. Sorted descending by score at flight time.

### `data/ledger.json`
- **Writer:** `core/flight/orchestrator.py` **ONLY** — one entry per
  target per acquisition attempt
- **Readers:** `core/preflight/audit.py`, `core/ledger_manager.py`
- **Schema:**
  ```json
  {
    "entries": {
      "SS_CYG": {
        "attempts": 14,
        "last_success": "2026-04-12T21:30:45+00:00",
        "status": "OK"
      }
    }
  }
  ```
- **Notes:** `TARGET_KEY` = `name.upper().replace(" ", "_")`.
  Append-only — never overwrite wholesale. `status` is `OK` or `FAILED`.
  `last_success` is only updated on successful acquisition.

### `data/system_state.json`
- **Writer:** `core/flight/orchestrator.py` **ONLY**
- **Readers:** dashboard, external monitoring
- **Schema:** `state`, `sub`, `msg`, `timestamp` (ISO UTC)
- **States:** `IDLE`, `PREFLIGHT`, `PLANNING`, `FLIGHT`, `SLEWING`,
  `TRACKING`, `POSTFLIGHT`, `PARKED`, `ABORTED`
- **Notes:** Volatile — reflects live pipeline state. Reset to `IDLE`
  each night by `core/preflight/state_flusher.py`.

### `data/weather_state.json`
- **Writer:** `core/preflight/weather.py`
- **Readers:** `core/flight/orchestrator.py` (`_check_weather`)
- **Schema:** `status` (str), `clouds_pct` (int), `humidity_pct` (int),
  `timestamp` (ISO UTC)
- **Abort thresholds:**
  - `clouds_pct` > 70
  - `humidity_pct` > 90
  - `status` in `RAIN`, `STORM`, `SNOW`, `OVERCAST`, `CLOUDY`, `WINDY`

---

## 📂 data/local_buffer/ — Transient FITS Store

- **Writer:** `core/flight/pilot.py` `DiamondSequence.acquire()`
- **Readers:** `core/postflight/science_processor.py`, NAS rsync
- **Contents:**
  ```
  {TARGET}_{YYYYMMDDTHHMMSS}_Raw.fits    ← sovereign acquisition output
  {TARGET}_{YYYYMMDDTHHMMSS}_Green.fits  ← science processor output
  ```
- **Notes:** Symlink → `/mnt/raid1/data/local_buffer/` (RAID1 USB).
  Transient — FITS move to `/mnt/astronas/{TARGET}/` after NAS rsync.
  Never treat as archival storage. FITS are `BITPIX=16`, uint16,
  big-endian, GRBG Bayer, `NAXIS1=2160`, `NAXIS2=3840`.

---

## 🗄️ /dev/shm/env_status.json — GPS RAM File

- **Writer:** `core/utils/gps_monitor.py`
- **Readers:** `core/flight/orchestrator.py` (`_check_gps`),
  `core/flight/vault_manager.py`
- **Schema:** `gps_status`, `lat`, `lon`, `elevation`, `timestamp`
- **Notes:** RAM filesystem (`/dev/shm`) — fast, no SD wear.
  Populated by `gps_monitor.py` daemon from `gpsd` on `127.0.0.1:2947`.
  Null Island guard: `lat=0.0, lon=0.0` is rejected as invalid.
  If file absent or stale, preflight GPS pillar returns `NO-DATA`.
