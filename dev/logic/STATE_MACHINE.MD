# 🤖 SEEVAR: THE STATE MACHINE

> **Objective:** Deterministic hardware transitions for AAVSO acquisition
> via ASCOM Alpaca REST on port 32323.
> **Version:** 5.0.0 (Sovereign A1-A12)
> **Path:** `dev/logic/STATE_MACHINE.MD`

Implementation:
- `core/flight/orchestrator.py` — mission order, vetoes, commit
- `core/flight/fsm.py` — state transitions and per-target control
- `core/flight/pilot.py` — hardware execution
- `core/flight/exposure_planner.py` — exposure logic

Alpaca device map: `ALPACA_BRIDGE.MD`.

---

## THE SOVEREIGN FLIGHT STATE CHAIN (A1–A12)

The telescope executes one deterministic per-target sequence.
The orchestrator owns mission order and veto logic.
The pilot owns hardware execution.
The FSM owns state transitions and failure handling.

### A1 — Target Lock
**Owner:** `core/flight/orchestrator.py`  
**Source:** `data/tonights_plan.json`

Load the next planned target in canonical order.

### A2 — Safety Gate
**Owner:** `core/flight/orchestrator.py`  
**Sources:**
- `data/weather_state.json`
- Alpaca telemetry
- neutralizer result

Any hard veto blocks target execution.

### A3 — Session Init
**Owner:** `core/flight/pilot.py`

| Action | Alpaca Endpoint | Notes |
|--------|------------------|-------|
| Connect telescope | PUT telescope/0/connected | Establish control |
| Connect camera | PUT camera/0/connected | |
| Connect filter wheel | PUT filterwheel/0/connected | |
| Unpark | PUT telescope/0/unpark | If parked |
| Enable tracking | PUT telescope/0/tracking | Tracking=true |
| Set gain / defaults | PUT camera/0/gain | Baseline state |
| Read telemetry | GET telescope/camera properties | Baseline health |

### A4 — Slew Command
**Owner:** `core/flight/pilot.py`

| Action | Endpoint | Notes |
|--------|----------|-------|
| Slew to target | PUT telescope/0/slewtocoordinatesasync | RA hours, Dec degrees |

### A5 — Slew Verify
**Owner:** `core/flight/pilot.py`

| Action | Endpoint | Notes |
|--------|----------|-------|
| Poll slew state | GET telescope/0/slewing | Until False or timeout |

This is a mechanical verification only.

### A6 — Settle
**Owner:** `core/flight/pilot.py`

Fixed post-slew stability wait.

### A7 — Pointing Verify
**Owner:** `core/flight/pilot.py` or dedicated verifier module

Verify actual field centre against intended target coordinates.

Preferred method:
- verification frame
- plate solve
- solved centre vs target centre
- offset in arcminutes

### A8 — Corrective Nudge
**Owner:** `core/flight/pilot.py`

If pointing error exceeds tolerance:
- apply correction
- re-slew or sync
- re-run A7
- abort target if retry budget is exhausted

### A9 — Exposure Plan
**Owner:** `core/flight/exposure_planner.py`

Determine safe science exposure block based on:
- target brightness
- sky quality
- field rotation
- mount constraints

### A10 — Acquire
**Owner:** `core/flight/pilot.py`

| Step | Endpoint | Detail |
|------|----------|--------|
| Set gain | PUT camera/0/gain | Gain baseline or planned value |
| Start exposure | PUT camera/0/startexposure | Duration, Light=true |
| Poll readiness | GET camera/0/imageready | Until True |
| Download | GET camera/0/imagearray | Science frame |
| Read temp | GET camera/0/ccdtemperature | Header telemetry |
| Write FITS | local filesystem | Raw science custody |

### A11 — Quality Gate
**Owner:** `core/flight/fsm.py` plus downstream QC hooks

Immediate flight-level validation of the newly acquired frame.

Minimum checks:
- FITS file exists
- array shape valid
- pixel stats sane
- no gross transport failure
- optional fast solve or centroid sanity

### A12 — Commit
**Owner:** `core/flight/orchestrator.py`

Record result to:
- `data/ledger.json`
- `data/system_state.json`

Then continue or transition to POSTFLIGHT.

---

## VETO LOGIC (ANY STATE)

| Condition | Source | Threshold | Action |
|-----------|--------|-----------|--------|
| Overheating | Alpaca camera/0/ccdtemperature | > 55.0°C | Park + alert |
| Low battery | Telemetry / monitor | < 10% | Park + alert |
| Dawn | Sun altitude | >= -18.0° | Postflight transition |
| Weather | `data/weather_state.json` | hard abort | Abort target / postflight |
| Pointing failure | A7/A8 | retry budget exceeded | Skip target |
