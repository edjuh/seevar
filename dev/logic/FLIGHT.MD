# 🚀 FLIGHT

> **Version:** 3.0.0
> **Path:** `dev/logic/FLIGHT.MD`

Flight is the reason the observatory exists. Everything in PREFLIGHT
was preparation. Everything in POSTFLIGHT is consequence. This phase
is the telescope doing science.

For each target in the canonical nightly plan, the pipeline executes
one fixed twelve-step sequence — the Sovereign Flight Sequence.
One raw FITS frame per target. No stacking. No consumer processing.
Sovereign RAW data only, written directly to RAID1.

All hardware communication is via ASCOM Alpaca REST on port 32323.
The pilot speaks directly to the telescope's built-in Alpaca driver.
No phone app. No session master. No intermediate middleware.

**Entry condition:** PLANNING complete, target list non-empty
**Exit conditions:**
- Target list exhausted → POSTFLIGHT
- Sun altitude >= -18.0° (dawn) → POSTFLIGHT
- Hardware veto (thermal / battery / safety) → PARKED immediately

---

## The Sovereign Flight Sequence (A1–A12, per target)

Each target gets one deterministic pass through the Sovereign Flight
Sequence. The sequence is designed to prove not only that a frame was
captured, but that the telescope pointed correctly, the frame is valid,
and the observation can be trusted scientifically.

One target may fail without aborting the night. Hard safety vetoes
remain global and may terminate the mission immediately.

### A1 — Target Lock

Load the next target from `data/tonights_plan.json`.

The target must carry:
- `recommended_order`
- `best_start_utc`
- `best_end_utc`
- target coordinates
- planning metadata needed for execution

This is the authoritative handoff from PREFLIGHT to FLIGHT.
Flight does not re-score the sky.

### A2 — Safety Gate

Before any movement, refresh all hard vetoes:
- weather go/no-go
- thermal safety
- battery safety
- telescope reachability
- neutralizer / zero-state result

If any hard veto fails, the target is not executed.

### A3 — Session Init

Establish live Alpaca session state:
- connect telescope
- connect camera
- connect filter wheel
- unpark if required
- enable tracking
- set gain/filter defaults
- read telemetry baseline

This step confirms the telescope is ready to act.

### A4 — Slew Command

Command the telescope to slew to the target coordinates.

Method: PUT /api/v1/telescope/0/slewtocoordinatesasync
Params: RightAscension=<hours>, Declination=<degrees>


### A5 — Slew Verify

Poll the telescope until motion is complete.

This is a mechanical confirmation only: the mount reports that slew
has ended. It does not yet prove that the target is centred.

Poll: GET /api/v1/telescope/0/slewing → until False
Timeout: 60 seconds


### A6 — Settle

Wait for post-slew mechanical stability.

Wait: 8 seconds (SETTLE_SECONDS)


### A7 — Pointing Verify

Take or derive a verification frame and confirm that the telescope is
actually pointed where the plan expects it to be.

Preferred implementation:
- plate solve the verification frame
- compare solved centre to intended target coordinates
- compute pointing error in arcminutes

This is the missing trust anchor between slew and science.

### A8 — Corrective Nudge

If the pointing error exceeds tolerance:
- sync / nudge / re-slew
- re-run A7
- abort target if retry budget is exceeded

This step protects the night from silent mispointing.

### A9 — Exposure Plan

Choose the science exposure parameters for the target using:
- target brightness
- field rotation safety
- sky quality / bortle
- mount constraints

This step produces the actual acquisition block.

### A10 — Acquire

Capture the science frame:
- set gain
- start exposure
- wait for image ready
- download image array
- write FITS

PUT camera/0/gain
PUT camera/0/startexposure
GET camera/0/imageready
GET camera/0/imagearray


### A11 — Quality Gate

Apply immediate in-flight QC before declaring success.

Minimum required checks:
- FITS file written successfully
- array shape sane
- pixel statistics sane
- no gross download failure
- optional quick plate-solve / centroid sanity

This is a flight verdict, not the full postflight science reduction.

### A12 — Commit

Record the outcome:
- update `ledger.json`
- update `system_state.json`
- update in-memory mission status
- advance to next target or enter POSTFLIGHT

Only here is a target considered observed by the night daemon.

---

## After A12

The orchestrator checks whether targets remain and whether dawn has
arrived. If targets remain and the sun is below -18.0°, it loops back to
A1 for the next target. If the list is exhausted or dawn arrives, it
transitions to POSTFLIGHT.

---

## Timing Budget (per target, typical)

| Step | Duration |
|------|----------|
| A1 Target Lock | <1s |
| A2 Safety Gate | <1s |
| A3 Session Init | 1-3s |
| A4 Slew Command | <1s |
| A5 Slew Verify | 5-60s |
| A6 Settle | 8s |
| A7 Pointing Verify | TBD |
| A8 Corrective Nudge | TBD |
| A9 Exposure Plan | <1s |
| A10 Acquire | exposure + readout + download |
| A11 Quality Gate | <5s |
| A12 Commit | <1s |

Real timing depends mainly on slew distance, verification strategy,
exposure length, and Alpaca image download speed.

---

## Veto logic during flight

| Condition | Source | Threshold | Action |
|-----------|--------|-----------|--------|
| Overheating | Alpaca CCD temp | > 55.0°C | Park + alert |
| Low battery | Telemetry / monitor | < 10% | Park + alert |
| Weather hard abort | `data/weather_state.json` | imaging_go = false | Abort target / postflight |
| Pointing error too large | A7 solve result | beyond tolerance after retries | Skip target |
| No image | A10 timeout | exposure + timeout budget | Skip target |
| Dawn | Sun altitude | >= -18.0° | POSTFLIGHT |
