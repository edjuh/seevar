# 🏛️ SEEVAR: SOVEREIGN ARCHITECTURE OVERVIEW

> **Objective:** High-precision AAVSO photometry via direct hardware control.
> **Version:** 4.0.0 (Alpaca Sovereign)
> **Path:** `logic/ARCHITECTURE_OVERVIEW.MD`

For the full pipeline narrative see `CORE.MD`.
For wire protocol detail see `API_PROTOCOL.MD`.

---

## 🛰️ 1. THE FLIGHT HANGAR (`core/flight/`)
*The cockpit. Hardware meets command here.*

- **`pilot.py`** — The sovereign acquisition engine over ASCOM Alpaca REST on port `32323`.
  Owns target execution steps `A3-A10`: session init, slew, settle, exposure, image download, and FITS write.

- **`orchestrator.py`** — The autonomous night daemon.
  Owns mission states `IDLE -> PREFLIGHT -> PLANNING -> FLIGHT -> POSTFLIGHT -> PARKED`.
  Consumes `data/tonights_plan.json` as the canonical nightly plan and must not re-score the sky independently.

- **`fsm.py`** — State transition authority for per-target execution and failure handling.

- **`camera_control.py`** — Thin Alpaca reachability and safe-stop wrapper for hardware gating, not the science acquisition path.

- **`neutralizer.py`** — Hardware reset utility securing zero-state before flight.

- **`exposure_planner.py`** — Exposure logic for step `A9`.

- **`field_rotation.py`** — Rotational safety logic constraining exposure length for Alt/Az work.

- **`dark_library.py`** — Post-session dark acquisition.

- **`mission_chronicle.py`** — Preflight funnel launcher. It prepares the night but is not the per-target flight engine.

The canonical per-target science chain is now the Sovereign Flight Sequence `A1-A12`.

---

## 📦 2. THE POSTFLIGHT BAY (`core/postflight/`)
*Cargo and science. No consumer-grade processing allowed.*

- **`accountant.py`** — Sweeps `local_buffer`, performs scientific reduction/QC, and stamps the ledger.
- **`calibration_engine.py`** — Differential photometry coordinator for a single FITS frame.
- **`bayer_photometry.py`** — Bayer-channel photometry engine for the IMX585.
- **`master_analyst.py`** — Plate-solving coordinator for postflight astrometric analysis.
- **`librarian.py`** — FITS custody and archival preparation.
- **`aavso_reporter.py`** — Generates AAVSO WebObs reports.

Postflight is the deep science phase.
Flight only needs an immediate operational quality gate (`A11`).

---

## 🧪 3. THE DATA VAULT (`data/`)
*Structured to protect the SD card and maintain data lineage.*

| Location | Storage | Purpose |
|----------|---------|---------|
| `data/local_buffer/` | RAID1 USB | Transient raw + processed FITS |
| `data/ledger.json` | RAID1 USB | Persistent per-target observation history |
| `data/system_state.json` | SD Card / runtime state | Volatile live pipeline telemetry |
| `data/tonights_plan.json` | RAID1 USB | Canonical nightly target list |
| `data/weather_state.json` | RAID1 USB | Weather consensus state |
| `/dev/shm/env_status.json` | RAM | Fast environment / GPS status |
| `/mnt/astronas/` | NAS | Final archival destination |

`tonights_plan.json` is the canonical preflight handoff into flight.

---

## 🤖 4. THE LOGIC BOARD (`logic/`)
*Protocol library and architectural record.*

| Document | Content |
|----------|---------|
| `CORE.MD` | Chain of command and system doctrine |
| `API_PROTOCOL.MD` | Confirmed protocol and endpoint detail |
| `ALPACA_BRIDGE.MD` | Alpaca role and bridge notes |
| `ARCHITECTURE_OVERVIEW.MD` | This document |
| `STATE_MACHINE.MD` | Hardware transition states and A1-A12 chain |
| `PREFLIGHT.MD` | Go/No-Go pillars, data pipeline, cadence rules |
| `FLIGHT.MD` | Canonical target execution sequence A1-A12 |
| `POSTFLIGHT.MD` | Science reduction and reporting flow |
| `SIMULATORLOGIC.MD` | Simulator obligations and flight mirroring |

---

## 5. CURRENT ARCHITECTURAL LAW

- PREFLIGHT selects and orders the night.
- FLIGHT executes the night.
- POSTFLIGHT validates the night.
- `tonights_plan.json` is the authoritative handoff.
- Flight must not silently replace planner logic with local ad-hoc scoring.
- The canonical per-target execution chain is `A1-A12`.
