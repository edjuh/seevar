# 🤖 SEEVAR: THE STATE MACHINE

> **Objective:** Deterministic hardware transitions for sovereign AAVSO
> acquisition via direct TCP to the S30-Pro.
> **Version:** 3.0.0 (Praw)
> **Path:** `logic/STATE_MACHINE.md`

Implementation: `core/flight/pilot.py` `DiamondSequence.acquire()`.
Pipeline state machine: `core/flight/orchestrator.py`.
Confirmed methods: `API_PROTOCOL.MD`.

---

## 🏗️ PHASE 1: INITIALISATION (IDLE → READY)

Force a clean slate before any science begins.

| Action | Method (port 4700) | Params | Notes |
|--------|-------------------|--------|-------|
| **Clear session** | `iscope_stop_view` | — | Breaks any active ZWO stacking lock. Always first. |
| **Set gain** | `set_control_value` | `["gain", 80]` | Fixed sensitivity for photometry. |
| **Set exposure** | `set_setting` | `{"exp_ms": {"stack_l": 5000}}` | Pre-sets timing before stream opens. |
| **Health check** | `get_device_state` | — | Any valid JSON response = device alive. |

---

## 🔭 PHASE 2: NAVIGATION (READY → TRACKING)

We point the mount. We do not poll — we settle.

### Slew
- **Method**: `scope_sync [ra_hours, dec_deg]` on port 4700
- **Wait**: `SETTLE_SECONDS = 8` fixed sleep post-sync
- **Rationale**: Sovereign path does not poll `get_event_state`.
  The settle window absorbs mount motion reliably for the S30-Pro.

### Plate Solve (optional — post-slew verification)
- **Method**: `start_solve` on port 4700
- **Poll**: `get_solve_result` until `code` is returned
- **Outcome 0**: Centred. Proceed to Phase 3.
- **Outcome 207**: Fail to operate. Recovery: offset mount 0.5° and retry.
- **Outcome 400/500**: Bridge error. Recovery: restart `seestar.service`.

Plate solving is not part of the standard `DiamondSequence` loop.
It is available as a recovery step when acquisition fails repeatedly
on a target.

---

## 📸 PHASE 3: SCIENCE (TRACKING → INTEGRATING)

Bypassing the consumer stacker for pure RAW data.

| Step | Action | Detail |
|------|--------|--------|
| **Open stream** | `iscope_start_view {"mode": "star"}` port 4700 | Begins ContinuousExposure stage |
| **Wait** | sleep 2.0s | Allow first frame to arrive on port 4801 |
| **Receive** | Binary stream port 4801 | Read 80-byte header → parse frame_id |
| **Filter** | `frame_id == 21` | Preview frame — raw uint16 Bayer GRBG |
| **Validate** | `len(data) == width × height × 2` | Payload size check — mismatch = skip frame |
| **Close stream** | `iscope_stop_view` port 4700 | End session cleanly |

Heartbeat packets (`payload < 1000 bytes`) are silently skipped.
Stack frames (`frame_id == 23`) are silently skipped.
`FRAME_TIMEOUT = 60s` — if no frame_id 21 arrives within timeout,
acquisition fails and target is removed from tonight's queue.

---

## 📦 PHASE 4: HARVEST (INTEGRATING → COMPLETED)

The Diamond lands on RAID1.

1. **Reshape** — `np.frombuffer(raw, dtype=np.uint16).reshape(height, width)`
2. **Stamp** — `sovereign_stamp()` writes AAVSO-compliant FITS header:
   `OBJECT`, `OBJCTRA`, `OBJCTDEC`, `DATE-OBS`, `EXPTIME`, `INSTRUME`,
   `TELESCOP`, `FILTER=CV`, `BAYERPAT=GRBG`, `OBSERVER`, `AUID`.
3. **Write** — `write_fits()` → `data/local_buffer/{TARGET}_{TS}_Raw.fits`
   Pure struct + numpy — no astropy dependency.
4. **Log** — `data/ledger.json` updated with `last_success` (ISO UTC).
5. **Handoff** — `science_processor.py` extracts green channel →
   `*_Green.fits` for aperture photometry.

---

## ⚠️ VETO LOGIC (ANY STATE)

If any of these conditions occur, transition to **PARKED** immediately
and alert via notifier:

| Condition | Source | Threshold | Action |
|-----------|--------|-----------|--------|
| Low battery | `get_device_state` result | `battery_capacity < 10%` | Park + alert |
| Overheating | `get_device_state` result | `temp > 55.0°C` | Park + alert |
| Heartbeat lost | port 4700 TCP | No response > 10s | Park + alert |
| Dawn | Sun altitude | `>= -18.0°` | Postflight transition |
| Weather | `data/weather_state.json` | clouds > 70% or humidity > 90% | Postflight + alert |

Battery and temperature are readable from the `get_device_state`
response payload. Poll once per target cycle — not per frame.
