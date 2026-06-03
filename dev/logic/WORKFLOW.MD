# SeeVar Mission Workflow

> **Objective:** Current operational flow from preflight to parked state.
> **Version:** 2.0.0
> **Path:** `dev/logic/WORKFLOW.MD`

SeeVar is a deterministic observatory pipeline.

The current production control layer is Alpaca-era hardware control with optional diagnostic/API workbench paths. Older direct-TCP JSON-RPC documents are historical unless explicitly marked as still used for a narrow diagnostic function.

Authority boundaries:

- `PREFLIGHT` decides whether a mission may happen.
- `PLANNING` locks the executable target order from the preflight artifact.
- `FLIGHT` captures trustworthy raw frames.
- `POSTFLIGHT` decides whether frames become trustworthy science.
- `PARKED` and `ABORTED` stop unsafe or finished operations without hiding state.

## State Chain

```text
IDLE -> PREFLIGHT -> PLANNING -> FLIGHT -> POSTFLIGHT -> PARKED
                                \
                                 -> ABORTED
```

No state may silently replace another state's responsibility.

## Canonical Artifacts

| Artifact | Owner | Meaning |
| --- | --- | --- |
| `config.toml` | Operator | Site, scope, planner, postflight, storage configuration |
| `data/weather_state.json` | Weather sentinel | Current and forecast safety context |
| `data/tonights_plan.json` | Preflight | Canonical nightly mission plan |
| `data/ssc_payload.json` | Schedule compiler | Executable Seestar/SSC-style payload |
| `data/system_state*.json` | Orchestrator/dashboard | Live mission state |
| `data/flight_runs/*.jsonl` | FSM | Per-target proof chain |
| `data/local_buffer/*.fits` | Flight | Raw frame custody |
| `data/calibrated_buffer/*` | Postflight | Working calibrated products |
| `data/archive/*` | Postflight | Durable observation custody |
| `data/ledger.json` | Postflight | Scientific outcome ledger |
| `data/reports/*` | Postflight/reporting | AAVSO/BAA/report artifacts |

## Phase 1: IDLE

`IDLE` waits for a valid observing opportunity.

It reports the dark window and current hold reason. It must re-read current configuration/weather before entering preflight so stale dashboard or planner state does not govern a live run.

## Phase 2: PREFLIGHT

Preflight answers one question: may the system attempt a mission now?

Checks include:

- current config and selected fleet mode
- system time and site coordinates
- astronomical dark window
- weather hard vetoes
- horizon/profile constraints
- storage availability
- scope reachability and telemetry
- zero-state / neutralizer readiness
- optional pre-alignment / pointing model refresh

Preflight produces or validates:

```text
data/tonights_plan.json
```

That file is the canonical handoff. Flight must not invent a competing target list.

## Phase 3: PLANNING

Planning is intentionally narrow.

It loads `tonights_plan.json`, preserves planner order, removes expired windows, applies any mission cap, and locks the executable list.

It does not redo cadence scoring or replace preflight filtering.

## Phase 4: FLIGHT

Flight owns capture, not final science.

Each target follows the canonical `A1-A12` chain:

| Step | Name | Purpose |
| --- | --- | --- |
| `A1` | Target Lock | Select next approved target |
| `A2` | Safety Gate | Refresh hard veto state before movement |
| `A3` | Session Init | Establish live telemetry and session state |
| `A4` | Slew Command | Move to intended coordinates |
| `A5` | Slew Verify | Confirm movement completed |
| `A6` | Settle | Allow mechanical/optical settling |
| `A7` | Pointing Verify | Plate-solve or otherwise verify pointing |
| `A8` | Corrective Nudge | Re-slew/sync/nudge within configured tolerance |
| `A9` | Exposure Plan | Choose exposure, gain, frame count |
| `A10` | Acquire | Capture science frame(s) |
| `A11` | Quality Gate | Operational frame sanity checks |
| `A12` | Commit | Stamp custody and ledger attempt state |

A target can pass flight and still fail postflight.
A target cannot pass flight partially by default: connect, prepare, pointing,
tracking, exposure, frame acceptance, and target completion must all be proven.
Fresh pointing proof is required before the first science frame and then at the
configured frame interval.

Flight outputs raw custody:

- FITS files in `data/local_buffer/`
- proof rows in `data/flight_runs/`
- live state in `data/system_state*.json`
- logs and telemetry
- ledger attempt/capture status

## Phase 5: POSTFLIGHT

Postflight owns scientific truth.

It follows `P1-P8`:

| Step | Name | Purpose |
| --- | --- | --- |
| `P1` | Ingest | Read raw FITS and identify target group |
| `P2` | Calibration Match | Select dark/flat/bias assets |
| `P3` | Calibration Apply | Produce calibrated working frames |
| `P4` | Astrometric Solve | Attach real WCS truth |
| `P5` | Source Measurement | Measure target and comparison stars |
| `P6` | Ensemble Calibration | Compute calibrated magnitude |
| `P7` | Quality Verdict | Apply saturation, SNR, comp, fit, residual gates |
| `P8` | Commit And Report | Archive, ledger, report, and cleanup |

Postflight must fail honestly. No report is produced from an unproven
observation. Multi-frame targets require one stacked accepted product by default.

## Optional Secondary Imaging

After photometric work, SeeVar may run a secondary imaging queue if enabled.

This is for Messier/Caldwell/Herschel-style filler targets. It must obey weather, horizon, daylight, storage, and battery guards. It is not AAVSO/BAA science unless separately reduced and proven.

## PARKED

`PARKED` is the normal completed state.

The scope is parked or shutdown according to config. State remains visible for the dashboard and logs.

## ABORTED

`ABORTED` means control must stop.

It can be caused by:

- weather hard veto
- battery/thermal/storage failure
- unrecoverable hardware or API failure
- no viable targets
- operator abort

Abort does not automatically invalidate already captured frames. Postflight may still process frames with valid custody.

## Transport Law

Current production control is Alpaca-era SeeVar control through `core/flight/pilot.py`, `core/flight/fsm.py`, and `core/flight/orchestrator.py`.

`seestar_alp` is diagnostics by default and can be enabled as a controlled
adapter only with `[seestar_alp].enabled = true` and `mode = "controlled"`.
It is documented in `SEESTAR_ALP_API.MD`.

Native Seestar SSH access is diagnostic and file-oriented only. It is documented in `SEESTAR_SSH_ACCESS.MD`.

Older direct-TCP JSON-RPC notes remain historical unless a document explicitly marks a specific method as still used for telemetry or diagnostics.

## Operating Principle

SeeVar is not allowed to pretend.

If a plan is stale, it must be refreshed or rejected.
If a frame is not proven, it must not be accepted.
If a transport path is experimental, it must not be described as production law.
