# 🗺️ SEEVAR: MISSION WORKFLOW

> **Objective:** Describe the full operational flow of SeeVar from preflight through flight, postflight, and parked state using the current sovereign architecture.
> **Version:** 1.9.0
> **Path:** `dev/logic/WORKFLOW.MD`

SeeVar runs as a deterministic observatory pipeline.

It no longer exists as a loose wrapper around Seestar tooling.
It is now a sovereign workflow with explicit authority boundaries:

- PREFLIGHT decides whether the mission may happen
- FLIGHT captures trustworthy raw science frames
- POSTFLIGHT decides whether those frames become trustworthy science
- PARKED and ABORTED preserve state and stop unsafe continuation

This document is the narrative overview.
The detailed doctrinal documents remain:

- `PREFLIGHT.MD`
- `FLIGHT.MD`
- `POSTFLIGHT.MD`
- `STATE_MACHINE.MD`

---

## State Overview

```text
IDLE → PREFLIGHT → PLANNING → FLIGHT → POSTFLIGHT → PARKED
                           ↓
                        ABORTED
Each state has one purpose.
No state should silently take over another state's responsibilities.

Phase 1 — PREFLIGHT
Entry condition: mission window approaching or simulation start
Exit condition: all hard gates pass
Abort condition: any hard veto fails

Preflight answers three questions:

is the system safe to operate?
is the observatory context valid?
what is tonight's canonical target list?
1.1 Environment and location truth
SeeVar first establishes observational context:

site coordinates
system time
astronomical dark window
local horizon constraints
storage availability
Location and time truth matter because all planning, timestamping, and altitude logic depend on them.

1.2 Catalog and cadence truth
The science catalog is filtered into an actionable mission set.

This stage includes:

target catalog readiness
comparison-star availability
cadence enforcement from the ledger
scientific due-ness for the current night
Targets that are not due should not enter the nightly plan.

1.3 Weather and hardware gate
Before motion, the observatory must pass its hard vetoes.

Typical checks include:

weather imaging go/no-go
hardware reachability
thermal safety
power safety
storage readiness
zero-state or neutralizer readiness
A failed hard veto must stop the mission before flight begins.

1.4 Nightly plan generation
Preflight then produces the authoritative mission artifact:

data/tonights_plan.json
This file is the canonical handoff into flight.

It represents the planner's truth after:

cadence
astronomical dark
local horizon clearance
required observing window
ranking and ordering
Flight must consume this plan.
It must not silently invent its own competing planner.

Phase 2 — PLANNING
Entry condition: preflight passed
Exit condition: executable target list locked
Abort condition: no viable targets remain

Planning in the modern architecture is intentionally narrow.

Its job is not to rebuild the night from scratch.
Its job is to prepare the already-approved nightly plan for execution.

That means:

load tonights_plan.json
sort by canonical planner order if needed
reject expired windows
preserve the planner's authority
hand targets into flight cleanly
This phase exists to translate preflight products into executable mission order, not to replace them.

Phase 3 — FLIGHT
Entry condition: executable targets exist
Exit condition: target list exhausted, dawn, or postflight handoff
Abort condition: hard safety veto during active mission

Flight owns one thing:
capturing trustworthy raw science frames.

It does not own deep science reduction.
It does not own final photometric acceptance.
It does not own report publication.

Its canonical per-target chain is A1-A12.

The Sovereign Flight Sequence (A1-P12? No: A1-A12)
Each target executes the same deterministic chain.

A1 — Target Lock
Load the next target from tonights_plan.json.

A2 — Safety Gate
Refresh hard veto state before movement.

A3 — Session Init
Establish live telescope, camera, and telemetry state.

A4 — Slew Command
Command the telescope to the target coordinates.

A5 — Slew Verify
Confirm that the mount has completed the commanded movement.

A6 — Settle
Allow post-slew mechanical stability.

A7 — Pointing Verify
Confirm actual pointing against intended pointing.

A8 — Corrective Nudge
Re-slew or adjust if pointing error exceeds tolerance.

A9 — Exposure Plan
Choose the actual science exposure parameters.

A10 — Acquire
Capture the science frame and write raw FITS custody.

A11 — Quality Gate
Perform immediate operational checks on the captured frame.

A12 — Commit
Record the target attempt/result and hand the frame into postflight custody.

Flight ends when a trustworthy raw frame has been captured and committed.

Flight Outputs
Flight produces operational custody artifacts, not final science verdicts.

Typical outputs include:

raw science FITS in data/local_buffer/
live mission state in data/system_state.json
updated ledger attempt/success state
flight logs and telemetry traces
The key rule is:
a frame can be operationally successful in flight and still fail scientifically in postflight.

Phase 4 — POSTFLIGHT
Entry condition: flight complete or mission halted after capture phase
Exit condition: all eligible frames judged and committed
Failure mode: individual frames may fail without invalidating the whole night

Postflight exists to establish scientific trust.

This is where SeeVar decides whether a raw frame is good enough to become an observation.

Its canonical chain is P1-P8.

The Sovereign Postflight Sequence (P1-P8)
P1 — Ingest
Read and validate the raw FITS file and recover target identity.

P2 — Calibration Match
Find the best detector calibration assets for the frame.

P3 — Calibration Apply
Apply dark subtraction and later flat correction on derived working products.

P4 — Astrometric Solve
Produce a real solved WCS for the frame.

P5 — Source Measurement
Measure target and candidate comp stars using Bayer-aware methods.

P6 — Ensemble Calibration
Compute the differential magnitude from the comparison-star ensemble.

P7 — Quality Verdict
Apply scientific pass/fail gates.

P8 — Commit And Report
Write durable ledger/archive/report products.

Postflight ends only after the frame is either accepted honestly or failed honestly.

Postflight Outputs
Postflight produces scientific custody artifacts.

Typical outputs include:

updated data/ledger.json
archived frame custody
Gaia cache products
dark-library usage records
staged AAVSO report artifacts
future QC artifacts and summary products
This is the phase that turns raw frames into scientific records.

PARKED
Entry condition: postflight finished, mission complete, or safe stop required

The observatory is no longer active.
Hardware is safe.
State is preserved.
The system waits for the next mission opportunity.

PARKED is a normal end state.

ABORTED
Entry condition: hard veto or unrecoverable mission failure

ABORTED is not a scientific judgment on all data.
It is a control-state judgment that the mission must stop.

Examples:

unsafe power state
unsafe thermal state
weather hard abort
irrecoverable hardware failure
no viable targets
If useful data was already captured before abort, that data may still proceed into postflight, depending on custody rules.

Current Scientific Boundary
The most important architectural rule is this:

Flight proves:
a trustworthy raw frame was captured
Postflight proves:
the frame supports trustworthy science
That separation protects the observatory from confusing capture success with scientific success.

Canonical Artifacts
Artifact	Authority	Meaning
data/tonights_plan.json	PREFLIGHT	canonical nightly mission list
data/system_state.json	FLIGHT / orchestrator	live mission state
data/local_buffer/*.fits	FLIGHT	raw frame custody
data/ledger.json	POSTFLIGHT	scientific outcome ledger
data/archive/*	POSTFLIGHT	archived observation custody
data/reports/*	POSTFLIGHT	publication-ready outputs
Current Version Story
1.7.x
Mission contract restoration.

1.8.x
Flight hardening and A1-A12 alignment.

1.9.x
Postflight scientific hardening:

P1-P8
astrometric truth
detector truth
robust ensemble photometry
deterministic reporting
Operating Principle
SeeVar is not allowed to pretend.

If a frame is not proven, it is not accepted.
If a mission state is not authoritative, it must not silently overrule one that is.

That principle applies to both code and science.
