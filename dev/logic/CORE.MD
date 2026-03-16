# 🧠 SEEVAR CORE LOGIC FLOW

> **Objective:** Defines the chain of command and guiding principles for
> the SeeVar autonomous AAVSO photometry pipeline.
> **Version:** 2.0.0 (Praw)
> **Path:** `logic/CORE.MD`

Full phase diagram and nightly timeline: `WORKFLOW.MD`.
Hardware wire protocol: `API_PROTOCOL.MD`.
Fleet naming and founding principles: `PICKERING_PROTOCOL.MD`.

## 🛰️ Operational Pipeline

The system follows a linear chain of command across three phases:

### Phase 1 — Preflight (weekly catalog + nightly planning)

1. **The Harvest** — `core/preflight/aavso_fetcher.py` pulls LPV, Mira,
   SR, CV, and outburst alert targets from AAVSO TargetTool into
   `catalogs/campaign_targets.json`.

2. **The Curation** — `core/preflight/librarian.py` deduplicates,
   validates, and stamps targets into `catalogs/federation_catalog.json`.
   409 stars. Immutable source of truth.

3. **The Audit** — `core/preflight/audit.py` applies per-type cadence
   rules against `data/ledger.json`. Marks targets due tonight.
   See `PREFLIGHT.MD` for cadence table.

4. **The Plan** — `core/preflight/nightly_planner.py` filters to targets
   above 30° during the astronomical dark window for Haarlem
   (52.39°N, 4.65°E). Writes `data/tonights_plan.json`.

### Phase 2 — Flight (autonomous nightly execution)

5. **The Gate** — `core/flight/orchestrator.py` runs Go/No-Go checks:
   storage, hardware (`get_device_state` on port 4700), GPS clock,
   weather, fog. Any RED = scrub.

6. **The Scoring** — Orchestrator scores observable targets by meridian-
   aware priority: west-of-meridian targets get urgency boost, flip-zone
   targets are deprioritised. See `API_PROTOCOL.MD` for mount geometry.

7. **The Acquisition** — `core/flight/pilot.py` `DiamondSequence.acquire()`
   executes per target via direct TCP to the S30-Pro:
   - `iscope_stop_view` → `scope_sync` → settle → `iscope_start_view`
   - Port 4801 binary stream → frame_id 21 → raw uint16 Bayer GRBG
   - `sovereign_stamp()` → `write_fits()` → `data/local_buffer/`
   No Alpaca. No intermediate layer.

8. **The Handoff** — On acquisition success, orchestrator calls
   `core/postflight/science_processor.py` for green channel extraction
   (Johnson V proxy), then updates `data/ledger.json` with `last_success`.

### Phase 3 — Postflight (data custody)

9. **The Custody** — NAS rsync moves FITS from `data/local_buffer/` to
   `/mnt/astronas/` for long-term storage. Local buffer is transient.

10. **The Report** — Differential photometry via `PhotometryPipeline`
    in `pilot.py`. AAVSO WebObs extended format submission.
    Comp star sequences from `catalogs/reference_stars/`.

## 🏛️ Guiding Principles

*Do not live in the moment. Plan for the astronomical night.*

*The Alpaca bridge is not the capture path. It is a health-check.*

*One source of truth per constant. Port numbers live in `pilot.py`.*

## 🔭 Hardware Identity

| Item | Value |
|------|-------|
| Instrument | ZWO S30-Pro |
| Sensor | IMX585, 2160×3840, uint16 |
| Bayer pattern | GRBG |
| Pixel scale | 3.74″/px |
| Field of view | 4.6° (~276′) |
| Control port | `192.168.178.55:4700` (JSON-RPC) |
| Frame stream | `192.168.178.55:4801` (binary) |
| Platform | Raspberry Pi 5, Debian Bookworm |
| Observer | Haarlem, NL — 52.39°N 4.65°E — JO22hj |

## 🚢 Fleet

| Name | Unit | Status |
|------|------|--------|
| Wilhelmina | S30-Pro #1 | Arriving April 2026 |
| Anna | S30-Pro #2 | Arriving April 2026 |
| Henrietta | S30-Pro #3 | Future |
| Annie | Spectrograph (Star Analyser 100) | Future |

Named after the Harvard Computers. See `PICKERING_PROTOCOL.MD`.
