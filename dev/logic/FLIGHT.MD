# 🚀 FLIGHT

> **Version:** 1.0.0
> **Path:** `logic/FLIGHT.MD`

Flight is the reason the observatory exists. Everything in PREFLIGHT
was preparation. Everything in POSTFLIGHT is consequence. This phase
is the telescope doing science.

For each target in the scored and cadence-filtered list, the pipeline
executes one fixed seven-step sequence — the Diamond Sequence. One raw
FITS frame per target. No stacking. No consumer processing. Sovereign
RAW data only, written directly to RAID1.

All hardware communication is direct TCP. Port 4700 for JSON-RPC
commands. Port 4801 for the raw frame stream. No Alpaca. No
intermediate layer. The pilot speaks directly to the telescope.

**Entry condition:** PLANNING complete, target list non-empty
**Exit conditions:**
- Target list exhausted → POSTFLIGHT
- Sun altitude ≥ -18.0° (dawn) → POSTFLIGHT
- Hardware veto at T6 → PARKED immediately

---

## The Diamond Sequence (T1–T7, per target)

Each target gets exactly one pass through the sequence. There is no
retry on failure — the target is logged as failed and the loop moves
to the next. Time is the limiting resource on a clear night.

### T1 — Set exposure time

Before the mount moves, the telescope is told how long to expose.
Exposure time is calculated per target by the exposure planner, using
the target's magnitude from the VSX catalog and the local Bortle class
(8 for Haarlem). A brighter target at a darker site needs less time.
A faint target in a light-polluted sky needs more.

```
Command:  set_setting {"exp_ms": {"stack_l": N}}
Source:   exposure_planner.plan_exposure(mag, bortle)
Output:   telescope configured — no file written yet
```

### T2 — Slew to target

The mount is commanded to point at the target's coordinates.
Coordinates arrive from the plan as decimal degrees (RA and Dec).
The pilot converts RA to hours before sending — the telescope expects
[ra_hours, dec_deg] exactly.

After the slew command the pipeline waits 8 seconds. This settle
window is fixed — confirmed sufficient for the S30-Pro altaz mount.
The pipeline does not poll for slew completion; the settle absorbs
mount motion reliably.

```
Command:  scope_goto [ra_hours, dec_deg]
Wait:     8 seconds (SETTLE_SECONDS — fixed)
Output:   mount pointing at target
```

### T3 — Autofocus

The telescope firmware runs its autofocus routine. The command name
contains a deliberate firmware typo — one `s` not two. Sending the
corrected spelling returns error 103 (method not found). The typo
must be preserved exactly.

```
Command:  start_auto_focuse
Output:   telescope focused
Note:     get_event_state response shape unconfirmed — first light action
```

### T4 — Open the frame stream

The continuous exposure stream is started. After this command the
telescope begins exposing. The pipeline waits 2 seconds to allow the
first frame to arrive on port 4801.

```
Command:  iscope_start_view {"mode": "star"}
Wait:     2 seconds
Output:   frame stream open on port 4801
```

### T5 — Receive the science frame

The pipeline listens on port 4801. Every packet has an 80-byte header.
The header field `frame_id` identifies what is in the payload.

Only `frame_id 21` is science data — raw uint16 Bayer GRBG.
`frame_id 23` (ZIP stack) is silently skipped.
Packets with payload smaller than 1000 bytes are heartbeats — skipped.

If no valid frame_id 21 arrives within 60 seconds the target is
abandoned. No data is written. The loop continues with the next target.

When a valid frame arrives, the payload size is validated:
width × height × 2 bytes. A size mismatch = corrupt frame, skip.

```
Port:     4801 (binary stream — separate TCP connection)
Timeout:  60 seconds
Frame:    raw uint16 Bayer GRBG, 3840 × 2160 pixels (S30-Pro)
Output:   raw bytes in memory
```

### T6 — Close the stream and check hardware

The exposure stream is closed. The pipeline immediately reads the
hardware state. Battery and temperature are checked against the
veto thresholds.

If battery is below 10% or temperature above 55°C the pipeline
transitions to PARKED after T7. The frame already received is not
discarded — it is written first.

```
Commands: iscope_stop_view → get_device_state
Output:   TelemetryBlock (battery, temp, charger status)
Veto:     battery < 10% OR temp > 55.0°C → PARKED after T7
```

### T7 — Write the FITS frame

The raw bytes are reshaped into a 2D uint16 array and written to RAID1
as a FITS file. The FITS header is written by sovereign_stamp() and
contains everything AAVSO requires for a valid photometry submission.

The header includes:
OBJECT, AUID, DATE-OBS (GPS-accurate UTC), EXPTIME,
INSTRUME, TELESCOP, FILTER=CV, BAYERPAT=GRBG,
OBSERVER=REDA, GAIN, FOCALLEN, APERTURE, PIXSCALE,
AIRMASS, MOONPHASE, MOONALT, SITELAT, SITELONG,
SITEELEV, CCD-TEMP (from T6 telemetry).

```
Output:   data/local_buffer/{TARGET}_{TS}_Raw.fits
Updates:  data/ledger.json       — last_success timestamp
Updates:  data/system_state.json — live dashboard state
```

---

## After T7

The orchestrator checks whether targets remain and whether dawn has
arrived. If targets remain and sun is below -18.0°, it loops back to
T1 for the next target. If the list is exhausted or dawn arrives, it
transitions to POSTFLIGHT.

---

## Veto logic during flight

Any veto detected at T6 transitions to PARKED after the current frame
is written. The telescope does not move to another target after a veto.

| Condition | Threshold | Action |
|-----------|-----------|--------|
| Low battery | battery_capacity < 10% | Write frame → PARKED |
| Overheating | temp > 55.0°C | Write frame → PARKED |
| No frame received | T5 timeout 60s | Skip target → next |
| Dawn | Sun altitude ≥ -18.0° | POSTFLIGHT |

---

## First light actions

These items cannot be confirmed until real hardware is connected:

- `start_auto_focuse` completion — `get_event_state` response shape
  not confirmed. Currently the pipeline fires T3 and proceeds
  without waiting for autofocus completion. First light: confirm
  whether a poll loop is needed or whether T4 timing is sufficient.
- S30-Pro exact boot time — estimated 60s based on S30 testing.
  Confirm on first power-on.
- BalanceSensor key names (tilt_x, tilt_y) — absent from
  `get_device_state`. Confirm via first `get_event_state` call.

<!-- SeeVar-FLIGHT-v1.0.0 -->
