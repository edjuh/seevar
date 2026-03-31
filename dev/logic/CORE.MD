# 🧠 SEEVAR CORE LOGIC FLOW

> **Objective:** Defines the chain of command and guiding principles for
> the SeeVar autonomous AAVSO photometry pipeline.
> **Version:** 3.0.0 (Alpaca)
> **Path:** `dev/logic/CORE.MD`

Full phase diagram and nightly timeline: `WORKFLOW.MD`.
Alpaca device map: `ALPACA_BRIDGE.MD`.
Fleet naming and founding principles: `PICKERING_PROTOCOL.MD`.

## Operational Pipeline

### Phase 1 — Preflight (weekly catalog + nightly planning)

1. **The Harvest** — `core/preflight/aavso_fetcher.py` pulls targets from AAVSO TargetTool.
2. **The Curation** — `core/preflight/librarian.py` deduplicates and stamps into `federation_catalog.json`.
3. **The Audit** — `core/preflight/audit.py` applies cadence rules against `data/ledger.json`.
4. **The Plan** — `core/preflight/nightly_planner.py` filters to targets above 30° during astronomical dark.

### Phase 2 — Flight (autonomous nightly execution)

5. **The Gate** — `core/flight/orchestrator.py` runs Go/No-Go checks:
   storage, hardware (Alpaca management API on port 32323), GPS clock, weather, fog.
6. **The Scoring** — Orchestrator scores observable targets by meridian-aware priority.
7. **The Acquisition** — `core/flight/pilot.py` v3.0.0 `DiamondSequence.acquire()` executes
   per target via Alpaca REST:
   - SlewToCoordinatesAsync → settle → SetGain → StartExposure → poll imageready
   - Download imagearray (2160×3840 int32) → sovereign_stamp() → write_fits()
   - Output: `data/local_buffer/{TARGET}_{TS}_Raw.fits`
8. **The Handoff** — On success, orchestrator updates ledger and triggers postflight.

### Phase 3 — Postflight (data custody)

9. **The Custody** — NAS rsync moves FITS to `/mnt/astronas/`.
10. **The Report** — Differential photometry via calibration_engine → AAVSO WebObs submission.

## Guiding Principles

*Do not live in the moment. Plan for the astronomical night.*

*The Alpaca REST API on port 32323 is the sole control path for all science acquisition.*

*Port 4700 is retained read-only for battery/charger telemetry via WilhelminaMonitor.*

## Hardware Identity

| Item | Value |
|------|-------|
| Instrument | ZWO Seestar S30-Pro |
| Sensor | IMX585, 2160×3840, uint16, 2.9µm |
| Bayer pattern | GRBG (offset 1,0) |
| Optics | 160mm f/5.3, 30mm aperture, quadruplet APO |
| Pixel scale | 3.74″/px |
| Field of view | 4.6° (~276′) |
| Alpaca port | `<telescope_ip>:32323` (REST, v1.2.0-3) |
| Event stream | `<telescope_ip>:4700` (TCP, read-only) |
| Platform | Raspberry Pi 5, Debian Bookworm |
| Observer | Haarlem, NL — 52.38°N 4.60°E — JO22hj |

## Fleet

| Name | Unit | Status |
|------|------|--------|
| Wilhelmina | S30-Pro #1 | Active — Alpaca confirmed 2026-03-30 |
| Anna | S30-Pro #2 | Arriving 2026 |
| Henrietta | S30-Pro #3 | Future |
| Annie | Spectrograph (Star Analyser 100) | Future |

Named after the Harvard Computers. See `PICKERING_PROTOCOL.MD`.
