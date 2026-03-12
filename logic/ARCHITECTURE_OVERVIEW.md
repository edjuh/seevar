# 🏛️ SEEVAR: SOVEREIGN ARCHITECTURE OVERVIEW

> **Objective:** High-precision AAVSO photometry via direct hardware control.
> **Version:** 3.0.0 (Praw)
> **Path:** `logic/ARCHITECTURE_OVERVIEW.md`

For the full pipeline narrative see `CORE.MD`.
For wire protocol detail see `API_PROTOCOL.MD`.

---

## 🛰️ 1. THE FLIGHT HANGAR (`core/flight/`)
*The cockpit. Hardware meets command here.*

- **`pilot.py`** v4.0.0 — The sovereign acquisition engine. Communicates
  directly via TCP port 4700 (JSON-RPC control) and port 4801 (binary
  frame stream). No Alpaca. Handles slew (`scope_sync`), settle, frame
  capture (`iscope_start_view`), and FITS writing. Exports
  `DiamondSequence`, `AcquisitionTarget`, `FrameResult`.

- **`orchestrator.py`** v1.7.1 — The autonomous night daemon. Runs the
  full state machine: IDLE → PREFLIGHT → PLANNING → FLIGHT →
  POSTFLIGHT → PARKED. Scores targets with meridian-aware priority,
  calls `DiamondSequence.acquire()` per target, updates ledger, hands
  off to `ScienceProcessor`. Single authoritative flight entry point.

- **`camera_control.py`** v2.0.0 — Hardware gate. Wraps `ControlSocket`
  to call `get_device_state` on port 4700 for preflight health check.

- **`neutralizer.py`** v3.0.0 — Hardware reset utility. Sends
  `iscope_stop_view` and verifies the device is idle before a session.

- **`vault_manager.py`** v1.4.1 — Metadata authority. Bi-directional
  `config.toml` sync. Provides observer coordinates and AAVSO credentials
  to the flight loop.

- **`fsm.py`** v1.0.0 — Finite State Machine primitives shared across
  the flight block.

---

## 📦 2. THE POSTFLIGHT BAY (`core/postflight/`)
*Cargo and science. No consumer-grade processing allowed.*

- **`science_processor.py`** v3.1.0 — Green channel extraction via
  `pysiril`. Extracts G1+G2 from GRBG Bayer without interpolation,
  producing monochrome `*_Green.fits` for aperture photometry.

- **`photometry_engine.py`** v1.5.0 — Aperture photometry on pixel
  coordinates. Ensemble zero-point differential magnitude against AAVSO
  comp stars. Also implemented inline in `pilot.py` as
  `PhotometryPipeline` for portable offline use.

- **`librarian.py`** v2.2.0 — FITS custody. Audits binary FITS for
  header integrity, vaults to `data/local_buffer/` on RAID1.

- **`aavso_reporter.py`** v1.1.0 — Generates AAVSO WebObs extended
  format reports in `data/reports/`.

- **`accountant.py`** v1.1.0 — QC sweep of `local_buffer/`. Resilient
  photometry with header fallbacks. Stamps ledger on completion.

---

## 🧪 3. THE DATA VAULT (`data/`)
*Structured to protect the SD card and maintain data lineage.*

| Location | Storage | Purpose |
|----------|---------|---------|
| `data/local_buffer/` | RAID1 USB | Transient raw + processed FITS |
| `data/ledger.json` | RAID1 USB | Persistent per-target observation history |
| `data/system_state.json` | SD Card | Volatile live pipeline telemetry |
| `data/tonights_plan.json` | RAID1 USB | Scored nightly target list |
| `data/weather_state.json` | RAID1 USB | Weather consensus state |
| `/dev/shm/env_status.json` | RAM | GPS fix — fast, no SD wear |
| `/mnt/astronas/` | NAS | Final archival destination |

`data/` is a symlink → `/mnt/raid1/data/`. OS lives on SD card.
App data never touches the SD card directly.

---

## 🤖 4. THE LOGIC BOARD (`logic/`)
*Protocol library and architectural record.*

| Document | Content |
|----------|---------|
| `CORE.MD` | Chain of command, 10-step pipeline, fleet |
| `API_PROTOCOL.MD` | Confirmed JSON-RPC methods, wire format, error codes |
| `ALPACA_BRIDGE.MD` | Bridge role, port 5432, what Alpaca still does |
| `ARCHITECTURE_OVERVIEW.md` | This document |
| `STATE_MACHINE.md` | Hardware transition states and veto logic |
| `PREFLIGHT.MD` | Go/No-Go pillars, data pipeline, cadence rules |
| `AAVSO_LOGIC.MD` | Targeting, cadence, photometry channel, report format |
| `DATA_DICTIONARY.MD` | File schemas and write authority |
| `DATA_MAPPING.MD` | Data flow table, 10-step lifecycle |
| `PICKERING_PROTOCOL.MD` | Fleet naming, founding principles |
| `SIMULATORLOGIC.MD` | Bridge/simulator networking — historical |
