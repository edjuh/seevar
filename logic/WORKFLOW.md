# 🗺️ SEEVAR: MISSION WORKFLOW

> **Version:** 1.0.0
> **Path:** `logic/WORKFLOW.md`
>
> SeeVar runs autonomously from dusk to dawn. This document describes the
> complete mission from catalog preparation through AAVSO report delivery.
> It is written for anyone who needs to understand what the system is doing
> and why — not just how.
>
> Wire protocol: `API_PROTOCOL.MD`
> Hardware state transitions: `STATE_MACHINE.md`
> Preflight pillar detail: `PREFLIGHT.MD`
>
> **Pending documents:** `FLIGHT.MD`, `POSTFLIGHT.MD` — phases 3 and 4
> are implemented in code but not yet documented in full detail files.
> This document records what is confirmed until those are written.

---

## State machine overview

```
IDLE → PREFLIGHT → PLANNING → FLIGHT → POSTFLIGHT → PARKED
                                  ↓
                               ABORTED ← veto (any state)
```

Each state has a single entry condition and a single exit condition.
No state is skipped. No state runs twice in a session.

---

## PHASE 1: PREFLIGHT

SeeVar is a precision instrument operating in the dark, unsupervised.
Before any hardware moves, the pipeline must know three things with
certainty: where it is, what it is looking at tonight, and whether the
hardware is fit to operate. Preflight answers all three.

**Entry condition:** Sun altitude < -18.0° (astronomical dark)
**Exit condition:** All 5 Go/No-Go pillars GREEN → transition to PLANNING
**Abort condition:** Any pillar RED → transition to ABORTED

---

### 1a — Build the observation catalog (weekly / on-demand)

AAVSO maintains a list of variable stars that need monitoring. SeeVar
pulls that list and cross-references it with the S30-Pro's capabilities.

The telescope has a 4.6° field of view. For each target, AAVSO provides
a sequence of comparison stars — known, stable stars in the same field
used to calibrate the brightness measurement. The chart fetch radius
must be ~300 arcminutes to cover that field correctly. Too small and
the pipeline has no comp stars to work with.

| Step | What happens | Produces |
|------|-------------|----------|
| Fetch targets | Pull campaign targets from AAVSO TargetTool | `catalogs/campaign_targets.json` |
| Fetch comp stars | Pull VSP comparison star sequences (FOV 300') | `catalogs/reference_stars/*.json` |
| Validate | Cross-reference targets against comp star availability | `catalogs/federation_catalog.json` |
| Apply cadence | Mark which targets are due for observation | `catalogs/federation_catalog.json` (annotated) |

This step does not run nightly. It runs when the catalog needs refreshing.

---

### 1b — Nightly planning (daily @ 17:00)

Every evening before dark, the pipeline builds the night's target list.
It needs to know: which targets are due, which will be above the horizon,
and which fall within the astronomical dark window.

**Location matters here.** The observer is in Haarlem, Netherlands
(52.38°N, 4.65°E). Altitude calculations — which stars are visible,
when they rise and set, whether the sun is far enough below the horizon
— all depend on the observer's precise coordinates. These coordinates
come from the GPS unit on the Pi, stored in `/dev/shm/env_status.json`.
The same coordinates are pushed to the telescope at session start (S2).

The astronomical dark window is when the sun is more than 18° below
the horizon. Observations outside this window are excluded — sky
brightness from twilight contaminates photometry.

| Step | What happens | Produces |
|------|-------------|----------|
| Reset state | Clear last night's pipeline state | `data/system_state.json` |
| Filter by cadence | Keep only targets due tonight | *(in-memory)* |
| Score and filter | Remove targets below 30° altitude, rank the rest | `data/tonights_plan.json` |

---

### 1c — Go / No-Go gate

Five pillars. All must be GREEN. The first RED scrubs the mission.
The telescope does not move until this gate passes.

| Pillar | What is checked | Why |
|--------|----------------|-----|
| 1 — Storage | Free space on RAID1 and local buffer | A full disk mid-session corrupts FITS files |
| 2 — Hardware | Telescope responds on port 4700 | No response = no control authority |
| 3 — Time | GPS lock, clock offset < 0.5s | DATE-OBS in FITS header must be accurate for AAVSO |
| 4 — Weather | Cloud cover below threshold | Clouds make photometry unreliable |
| 5 — Fog | MLX90614 IR sky temperature | Fog is invisible to weather APIs |

---

### 1d — Session initialisation (hardware, S1–S4)

Once the gate passes, the telescope is prepared for the night.
These four commands are sent once, before the first target.

| Step | Command | What it does |
|------|---------|-------------|
| S1 | `iscope_stop_view` | Clears any leftover session state from the telescope |
| S2 | `set_user_location` | Tells the telescope where it is (from GPS) |
| S3 | `set_control_value gain=80` | Fixes the sensor sensitivity for the night |
| S4 | `get_device_state` | Reads battery and temperature — aborts if either is unsafe |

Battery below 10% or temperature above 55°C = immediate abort.
The telescope does not slew until S4 returns clean.

---

## PHASE 2: PLANNING

**Entry condition:** PREFLIGHT complete, S4 returned clean
**Exit condition:** Scored target list locked → transition to FLIGHT
**Abort condition:** No targets above 30° altitude → transition to ABORTED

Planning answers one question: of the targets in tonight's plan, which
ones can the telescope actually see right now, and in what order?

The nightly planner (1b) already filtered by cadence and dark window.
Planning filters again — in real time — by current altitude. A star
that was above 30° at 17:00 may have set by 22:00.

The scoring function is meridian-aware. Targets to the west of the
meridian (azimuth 180°–350°) are prioritised — they are setting, and
the window to observe them is closing. Targets to the east are rising
and can wait.

| Step | What happens | Produces |
|------|-------------|----------|
| Load plan | Read tonight's target list | from `data/tonights_plan.json` |
| Recalculate altitude | Current alt/az for each target | *(in-memory)* |
| Filter | Remove targets below 30° | *(in-memory)* |
| Score | Meridian-aware priority score | *(in-memory)* |
| Sort and lock | Highest score first | `data/tonights_plan.json` (re-written with scores) |

If no targets survive the altitude filter the mission aborts cleanly.
No hardware has moved at this point.

---

## PHASE 3: FLIGHT

**Entry condition:** PLANNING complete, target list non-empty
**Exit condition:** Target list exhausted or dawn (sun ≥ -18.0°) → POSTFLIGHT
**Abort condition:** Hardware veto at T6 → transition to PARKED

> Detail document: `logic/FLIGHT.MD` (pending)

Flight is the core of the mission. For each target in the scored list,
the pipeline executes a fixed seven-step sequence — the Diamond Sequence
— and writes one raw FITS frame per target to RAID1.

The Diamond Sequence is executed by `DiamondSequence.acquire()` in
`core/flight/pilot.py`. It communicates exclusively via direct TCP:
port 4700 for JSON-RPC commands, port 4801 for the raw frame stream.
No Alpaca. No intermediate layer.

**Exposure time** is calculated per target by the exposure planner,
based on the target's magnitude and the local Bortle class (7 for
Haarlem). The result is passed to the telescope at T1.

### Per-target sequence (T1–T7)

| Step | Command / action | Detail |
|------|-----------------|--------|
| T1 | `set_setting exp_ms` | Exposure time from planner (target mag + Bortle 7) |
| T2 | `scope_goto [ra_hours, dec_deg]` | Slew to target · sleep 8s to settle mount |
| T3 | `start_auto_focuse` | Autofocus — firmware typo preserved (one 's') |
| T4 | `iscope_start_view mode:star` | Open continuous exposure stream · sleep 2s |
| T5 | Port 4801 — receive frame | Wait for frame_id=21 · validate payload size · 60s timeout |
| T6 | `iscope_stop_view` + `get_device_state` | Close stream · check battery and temperature |
| T7 | `write_fits` + `sovereign_stamp` | Write AAVSO-compliant FITS to RAID1 |

Frame_id 21 is the raw uint16 Bayer GRBG preview frame — the science
target. Frame_id 23 (ZIP stack) and heartbeat packets (payload < 1000
bytes) are silently skipped. If no valid frame arrives within 60 seconds,
the target is removed from the queue and the loop continues with the next.

After T6, if battery is below 10% or temperature above 55°C, the
pipeline transitions immediately to PARKED. The frame is still written
if it was received — no data is discarded on a veto.

| Output | Path |
|--------|------|
| Raw FITS frame | `data/local_buffer/{TARGET}_{TS}_Raw.fits` |
| Observation record | `data/ledger.json` |
| Live pipeline state | `data/system_state.json` |

---

## PHASE 4: POSTFLIGHT

**Entry condition:** Target list exhausted or dawn (sun ≥ -18.0°)
**Exit condition:** Dark acquisition complete, accountant finished → PARKED

> Detail document: `logic/POSTFLIGHT.MD` (pending)

Postflight handles everything after the last target is observed, before
the telescope parks for the day.

**Dark frames.** The raw FITS frames captured during flight contain
sensor noise that must be calibrated out. For each unique combination
of exposure time and gain used tonight, the pipeline requests a dark
frame from the telescope firmware using `start_create_dark`. The
firmware uses an internal dark field filter — no cap is needed. Dark
acquisition is skipped in simulation mode.

**Science processing.** The accountant runs a QC sweep of the
local_buffer. For each valid raw frame, science_processor extracts
the green channel from the GRBG Bayer data without interpolation,
producing a monochrome `*_Green.fits` for aperture photometry.

**Photometry.** The photometry engine measures the target star's
brightness against the AAVSO comparison star sequence fetched in
phase 1a. The result is a differential magnitude relative to the
ensemble of comp stars.

**AAVSO report.** The reporter generates a submission in AAVSO WebObs
extended format. Observer code: REDA.

| Step | Script | Output |
|------|--------|--------|
| Dark acquisition | `core/flight/dark_library.py` | `data/local_buffer/*_Dark.fits` |
| QC sweep | `core/postflight/accountant.py` | `data/ledger.json` (stamped) |
| Green extraction | `core/postflight/science_processor.py` | `data/local_buffer/*_Green.fits` |
| Photometry | `core/postflight/photometry_engine.py` | *(in-memory → reporter)* |
| AAVSO report | `core/postflight/aavso_reporter.py` | `data/reports/REDA_{date}.txt` |

---

## PHASE 5: PARKED

**Entry condition:** POSTFLIGHT complete, hardware veto, or dawn
**Behaviour:** Telescope parked, pipeline idle, waiting for next session

The pipeline writes a final state to `data/system_state.json` and stops.
The dashboard reflects PARKED until the next nightly plan runs at 17:00.

---

## PHASE 6: ABORTED

**Entry condition:** Any Go/No-Go pillar RED, no observable targets,
or unrecoverable hardware error
**Behaviour:** If aborted in PREFLIGHT or PLANNING — no hardware has
moved. If aborted mid-FLIGHT — current target abandoned, darks skipped,
telescope parked.

The abort reason is logged to `data/system_state.json` and the flight
log. The dashboard displays the reason.

---

## Veto logic (any state)

Any of these conditions triggers an immediate transition to PARKED.
The pipeline does not continue after a veto.

| Condition | Source | Threshold |
|-----------|--------|-----------|
| Low battery | `get_device_state` | battery_capacity < 10% |
| Overheating | `get_device_state` | temp > 55.0°C |
| Heartbeat lost | port 4700 TCP | no response > 10s |
| Dawn | Sun altitude | ≥ -18.0° |
| Weather | `data/weather_state.json` | clouds > 70% or humidity > 90% |

Battery and temperature are polled once per target cycle at T6 — not
per frame. A veto mid-sequence still writes the frame if it was received
before the veto was detected.

---

## Data files — complete reference

| File | Written by | Read by | Purpose |
|------|-----------|---------|---------|
| `catalogs/campaign_targets.json` | `aavso_fetcher.py` | `librarian.py` | Raw AAVSO target list |
| `catalogs/reference_stars/*.json` | `chart_fetcher.py` | `photometry_engine.py` | VSP comp star sequences |
| `catalogs/federation_catalog.json` | `librarian.py`, `audit.py` | `nightly_planner.py` | Validated cadence-annotated catalog |
| `data/tonights_plan.json` | `nightly_planner.py`, orchestrator | orchestrator | Scored nightly target list |
| `data/system_state.json` | orchestrator | dashboard | Live pipeline state |
| `data/ledger.json` | orchestrator, accountant | orchestrator, accountant | Per-target observation history |
| `data/local_buffer/*_Raw.fits` | `pilot.py` | `accountant.py` | Raw science frames |
| `data/local_buffer/*_Dark.fits` | `dark_library.py` | `accountant.py` | Dark calibration frames |
| `data/local_buffer/*_Green.fits` | `science_processor.py` | `photometry_engine.py` | Extracted green channel |
| `data/reports/REDA_{date}.txt` | `aavso_reporter.py` | AAVSO WebObs | Photometry submission |
| `data/weather_state.json` | `weather.py` | orchestrator | Weather consensus state |
| `/dev/shm/env_status.json` | `gps_monitor.py` | `pilot.py`, orchestrator | GPS fix (RAM — never written to SD) |

<!-- SeeVar-WORKFLOW-v1.0.0 -->
