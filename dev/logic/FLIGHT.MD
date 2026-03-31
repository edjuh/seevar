# 🚀 FLIGHT

> **Version:** 2.0.0
> **Path:** `dev/logic/FLIGHT.MD`

Flight is the reason the observatory exists. Everything in PREFLIGHT
was preparation. Everything in POSTFLIGHT is consequence. This phase
is the telescope doing science.

For each target in the scored and cadence-filtered list, the pipeline
executes one fixed seven-step sequence — the Alpaca Diamond Sequence.
One raw FITS frame per target. No stacking. No consumer processing.
Sovereign RAW data only, written directly to RAID1.

All hardware communication is via ASCOM Alpaca REST on port 32323.
The pilot speaks directly to the telescope's built-in Alpaca driver.
No phone app. No session master. No intermediate middleware.

**Entry condition:** PLANNING complete, target list non-empty
**Exit conditions:**
- Target list exhausted → POSTFLIGHT
- Sun altitude >= -18.0° (dawn) → POSTFLIGHT
- Hardware veto (thermal) → PARKED immediately

---

## The Alpaca Diamond Sequence (A1–A7, per target)

Each target gets exactly one pass through the sequence. There is no
retry on failure — the target is logged as failed and the loop moves
to the next. Time is the limiting resource on a clear night.

### A1 — Slew to target

The telescope is commanded to slew via SlewToCoordinatesAsync.
Coordinates arrive from the plan as decimal degrees (RA and Dec).
The pilot converts RA to hours before sending — the Alpaca telescope
expects RA in hours and Dec in degrees.

The pipeline polls the `slewing` property until it returns False
or the timeout (60s) expires.

```
Method:   PUT /api/v1/telescope/0/slewtocoordinatesasync
Params:   RightAscension=<hours>, Declination=<degrees>
Poll:     GET /api/v1/telescope/0/slewing → until False
Timeout:  60 seconds
```

### A2 — Settle

Post-slew settle window. 8 seconds fixed. Allows mechanical
vibration and tracking to stabilise.

```
Wait:     8 seconds (SETTLE_SECONDS)
```

### A3 — Set exposure parameters

Camera gain is set to 80 (HCG sweet spot for IMX585 — 12 stops
dynamic range per community consensus). Exposure time is calculated
per target by the exposure planner.

```
Method:   PUT /api/v1/camera/0/gain  Gain=80
Source:   exposure_planner.plan_exposure(mag, bortle)
```

### A4 — Start exposure

The camera begins a light exposure. Duration is in seconds (float).

```
Method:   PUT /api/v1/camera/0/startexposure
Params:   Duration=<seconds>, Light=true
```

### A5 — Wait for image

The pipeline polls `imageready` until the exposure completes and
the image is available for download. Camera state transitions
through Exposing → Reading → Idle.

```
Poll:     GET /api/v1/camera/0/imageready → until True
Timeout:  exposure_seconds + 120s
```

### A6 — Download image

The full sensor array is downloaded via the Alpaca imagearray
endpoint. The IMX585 at 3840×2160 returns ~33s over JSON on LAN.
The array arrives as a 2D int32 array in row-major order.

```
Method:   GET /api/v1/camera/0/imagearray
Returns:  JSON with Value: [[row0], [row1], ...]
Shape:    (2160, 3840) int32
Time:     ~33 seconds over LAN (JSON transfer)
```

CCD temperature is read post-exposure for the FITS header:
```
Method:   GET /api/v1/camera/0/ccdtemperature
```

### A7 — Write the FITS frame

The array is clipped to uint16 range and written to RAID1 as a FITS
file. The FITS header is written by `sovereign_stamp()` and contains
everything AAVSO requires for a valid photometry submission.

The header includes:
OBJECT, AUID, DATE-OBS (GPS-accurate UTC), EXPTIME,
INSTRUME=IMX585, TELESCOP=ZWO Seestar S30-Pro, FILTER=TG,
BAYERPAT=GRBG, OBSERVER=REDA, GAIN=80, FOCALLEN=160,
APERTURE=30, PIXSCALE=3.74, AIRMASS, MOONPHASE, MOONALT,
SITELAT, SITELONG, SITEELEV, CCD-TEMP, JD

```
Output:   data/local_buffer/{TARGET}_{TS}_Raw.fits
Updates:  data/ledger.json       — last_success timestamp
Updates:  data/system_state.json — live dashboard state
```

---

## After A7

The orchestrator checks whether targets remain and whether dawn has
arrived. If targets remain and sun is below -18.0°, it loops back to
A1 for the next target. If the list is exhausted or dawn arrives, it
transitions to POSTFLIGHT.

---

## Timing Budget (per target, typical)

| Step | Duration |
|------|----------|
| A1 Slew | 5-15s |
| A2 Settle | 8s |
| A3 Gain | <1s |
| A4 Start exposure | <1s |
| A5 Wait for image | exposure + readout (~2s) |
| A6 Download | ~33s (JSON) |
| A7 Write FITS | <1s |
| **Total overhead** | **~50s + exposure time** |

For a 5s exposure: ~55s per target. 195 targets × 55s ≈ 3 hours.
A clear Haarlem night gives ~7 hours of astronomical darkness in winter.

---

## Veto logic during flight

| Condition | Source | Threshold | Action |
|-----------|--------|-----------|--------|
| Overheating | Alpaca CCD temp | > 55.0°C | Write frame → PARKED |
| Low battery | WilhelminaMonitor (port 4700) | < 10% | Write frame → PARKED |
| No image | A5 timeout | exposure + 120s | Skip target → next |
| Dawn | Sun altitude | >= -18.0° | POSTFLIGHT |
