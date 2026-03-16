---
name: seevar
description: >
  Use this skill for ALL work on the SeeVar autonomous variable star
  observatory project. Trigger on any mention of: SeeVar, pilot.py,
  orchestrator.py, DiamondSequence, S30-Pro telescope, AAVSO photometry,
  Seestar, port 4700, port 4801, scope_goto, iscope_start_view, Wilhelmina,
  REDA observer code, or any request to write heredoc deploy scripts for
  the Pi. This skill contains the complete architectural law, confirmed
  hardware constants, wire protocol, and session rules. Never write a
  single line of SeeVar code without consulting this skill first.
---

# SeeVar — Autonomous Variable Star Observatory

## Who and where
- Observer: Ed, Haarlem NL, JO22hj, 52.38°N 4.65°E
- Hardware: ZWO Seestar S30-Pro + Raspberry Pi 5
- Pi: s30-pro.local, Python env ssc-3.13.5 (pyenv)
- Project root: ~/seevar
- GitHub: https://github.com/edjuh/seevar
- AAVSO observer code: **REDA** — 4 characters, never substitute

## Prime Directives — non-negotiable
1. No vibe-coding — all logic maps to logic/ documents
2. Deploy via heredoc .sh scripts — idempotent, Garmt header standard
3. Garmt header: Filename, Version, Objective in every .py file
4. Sovereignty Principle: all hardware via direct TCP port 4700 (JSON-RPC)
5. AAVSO API throttle: **188.4s** — Pi was blocked at 3.14s on 2026-03-13
6. Read logic/ documents BEFORE writing code — always request them first
7. Never invent key names, port numbers, method names, response shapes
8. Delivery method: `cp ~/seevar/$path/$file /mnt/astronas` — Ed runs it

## Session behaviour rules
- Request files before writing code — never guess content
- Give Ed the exact cp command to run, wait for upload
- Raise conflicts immediately — never let them pass into deployed code
- All code as heredoc .sh deploy scripts
- Verify anchor strings against actual file before writing patches
- If anchor not found: show file content, fix anchor, never guess

## Port architecture
| Port | Host | Purpose |
|------|------|---------|
| 4700 | `<telescope_ip>` | JSON-RPC sovereign control — ALL hardware |
| 4801 | `<telescope_ip>` | Binary frame stream — science capture only |
| 5432 | 127.0.0.1 | Alpaca bridge health-check ONLY |

`<telescope_ip>` from config.toml `[[seestars]] ip` — never hardcoded.
Port 5555 does not exist. Port 4720 does not exist. Never use either.

## JSON-RPC wire format (port 4700)
```python
msg  = {"id": <int>, "method": "<method>", "params": <value>}
wire = (json.dumps(msg) + "\r\n").encode("utf-8")
```
`id` starts at 10000, increments per session. `params` omitted if not needed.

## Confirmed methods — port 4700
### Session
- `get_device_state` — health probe, parse TelemetryBlock
- `iscope_stop_view` — abort all active operations (always first)
- `iscope_start_view {"mode": "star"}` — begin continuous exposure

### Mount
- `scope_goto [ra_hours, dec_deg]` — slew (NOT scope_sync)
- `scope_sync [ra_hours, dec_deg]` — pointing model sync only
- `scope_park` — park mount
- `set_user_location {"lat": f, "lon": f, "force": true}` — push GPS
- `scope_get_track_state` — returns false when parked
- `scope_set_track_state [true]` — unpark, engage tracking
- `scope_get_ra_dec` — current position [ra, dec, ...]

### Camera
- `set_control_value ["gain", 80]` — set sensor gain
- `set_setting {"exp_ms": {"stack_l": ms}}` — set exposure
- `start_solve` — plate solve
- `get_solve_result` — poll solve result
- `start_auto_focuse` — autofocus (**firmware typo: one 's' — preserved**)
- `stop_auto_focuse` — stop autofocus (same typo)

### NOT confirmed — never use
- start_exposure, get_last_frame, get_stacked_img, method_sync,
  iscope_get_app_state

## Session init S1–S7 (once per night)
```
S1: iscope_stop_view          — clear active session
S2: set_user_location         — push GPS from /dev/shm/env_status.json
S3: set_control_value gain=80 — fix gain
S4: get_device_state          — TelemetryBlock, veto on bat<10% temp>55°C
S5: scope_get_track_state     — confirm parked
S6: scope_set_track_state [true] — explicit unpark
S7: scope_get_ra_dec          — confirm mount live
```

## Per-target Diamond Sequence T1–T7
```
T1: set_setting exp_ms        — from exposure_planner
T2: scope_goto [ra_h, dec_d]  — slew + sleep 8s settle
T3: start_auto_focuse         — autofocus (typo preserved)
T4: iscope_start_view star    — open stream + sleep 2s
T5: port 4801 frame_id=21     — 60s timeout, validate width×height×2
T6: iscope_stop_view          — close + get_device_state veto check
T7: write_fits sovereign_stamp — RAID1 local_buffer
```

## Binary frame protocol (port 4801)
```
Header: 80 bytes, fmt ">HHHIHHBBHH", first 20 bytes used
frame_id 21 = RAW uint16 Bayer GRBG (science)
frame_id 23 = ZIP stack (skip)
payload < 1000 bytes = heartbeat (skip)
Expected: width × height × 2 bytes
```

## Veto thresholds
- battery_capacity < 10% → PARKED
- temp > 55.0°C → PARKED
- Sun altitude ≥ -18.0° → POSTFLIGHT (dawn)

## Hardware constants (S30-Pro)
```
FOCALLEN = 160mm  |  APERTURE = 30mm  |  INSTRUMENT = IMX585
SENSOR_W = 3840   |  SENSOR_H = 2160  |  BAYER = GRBG
PIXSCALE = 3.74   |  GAIN = 80        |  FILTER = CV → TG (AAVSO)
SETTLE_SECONDS = 8  |  FRAME_TIMEOUT = 60
SATURATION_CEILING = 60000 ADU
```

## State machine
```
IDLE → PREFLIGHT → PLANNING → FLIGHT → POSTFLIGHT → PARKED
                                  ↓
                               ABORTED ← veto (any state)
```

## Key files
```
core/flight/pilot.py          — DiamondSequence S1-S7 + T1-T7
core/flight/orchestrator.py   — State machine, ledger wiring
core/flight/sim_runner.py     — Full realtime simulation
core/ledger_manager.py        — Period-based cadence, 5% of period
core/hardware/fleet_mapper.py — Sovereign TCP, no Alpaca
core/postflight/accountant.py — Quality gate, ledger authority
core/postflight/calibration_engine.py — Gaia DR3 photometry
core/postflight/bayer_photometry.py   — 4-channel Bayer extraction
core/postflight/psf_models.py         — Moffat PSF, dynamic aperture
tools/sim_reset.py            — Reset plan targets to PENDING
```

## Logic documents (request before writing code)
```
logic/API_PROTOCOL.MD    — confirmed methods, wire format, error codes
logic/STATE_MACHINE.md   — hardware transitions, veto logic
logic/FLIGHT.MD          — Diamond Sequence detail
logic/POSTFLIGHT.MD      — Dark frames, photometry, accountant
logic/PREFLIGHT.MD       — Go/No-Go pillars, cadence rules
logic/WORKFLOW.MD        — Full pipeline narrative
logic/COMMUNICATION.md   — TCP connection model, three tiers
logic/SEEVAR_DICT.PSV    — Empirical method vocabulary
```

## Photometry approach
- Direct Bayer-matrix extraction — no debayering
- 2D Moffat PSF → dynamic aperture = 1.7 × FWHM
- Same aperture for all stars in field (target + comps)
- Gaia DR3 comp stars via VizieR — cached to data/gaia_cache/
- SNR²-weighted ZP ensemble
- G channel → AAVSO filter TG
- R, B, L channels extracted, available for STWG starlist format

## Config structure
```toml
[location]  lat, lon, elevation, bortle=8, horizon_limit=30.0
[aavso]     observer_code="REDA", webobs_token, target_key
[planner]   sun_altitude_limit=-18.0, simulation_mode=false
[network]   nas_ip, nas_port
[storage]   source_dir, primary_dir, lifeboat_dir
[[seestars]] name, model, ip, mount="altaz"
```

## Fleet
- Wilhelmina — S30-Pro #1 (arriving April 2026)
- Anna       — S30-Pro #2 (arriving April 2026)
- Henrietta  — S50 (TBD)
Named after Harvard Computers per PICKERING_PROTOCOL.MD.

## First light actions (unconfirmed until April)
- get_event_state response shape
- BalanceSensor keys (tilt_x, tilt_y)
- start_auto_focuse completion polling
- S30-Pro exact boot time (~60s estimated)
- AUID field in FITS (aavso_fetcher patch in place, catalog needs rebuild)

## Current version: v1.6.1 (Jochem)
Next: v1.7.0 (Oene) — clean slate install + catalog_localiser.py

<!-- SeeVar-SKILL-v1.0.0 -->
