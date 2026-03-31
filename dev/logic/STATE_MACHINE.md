# 🤖 SEEVAR: THE STATE MACHINE

> **Objective:** Deterministic hardware transitions for AAVSO acquisition
> via ASCOM Alpaca REST on port 32323.
> **Version:** 4.0.0 (Alpaca)
> **Path:** `dev/logic/STATE_MACHINE.md`

Implementation: `core/flight/pilot.py` v3.0.0 `DiamondSequence.acquire()`.
Pipeline state machine: `core/flight/orchestrator.py`.
Alpaca device map: `ALPACA_BRIDGE.MD`.

---

## PHASE 1: INITIALISATION (IDLE → READY)

Force a clean slate before any science begins.

| Action | Alpaca Endpoint | Notes |
|--------|----------------|-------|
| **Connect telescope** | PUT telescope/0/connected | Establish Alpaca session |
| **Connect camera** | PUT camera/0/connected | |
| **Connect filter wheel** | PUT filterwheel/0/connected | |
| **Unpark** | PUT telescope/0/unpark | Opens arm if parked |
| **Enable tracking** | PUT telescope/0/tracking Tracking=true | Sidereal rate |
| **Set gain** | PUT camera/0/gain Gain=80 | HCG sweet spot |
| **Health check** | GET management/v1/configureddevices | 7 devices = alive |

---

## PHASE 2: NAVIGATION (READY → TRACKING)

### Slew
- **Method**: PUT telescope/0/slewtocoordinatesasync
- **Params**: RightAscension (hours), Declination (degrees)
- **Poll**: GET telescope/0/slewing → until False
- **Timeout**: 60 seconds
- **Settle**: 8 seconds post-slew

---

## PHASE 3: SCIENCE (TRACKING → INTEGRATING)

| Step | Endpoint | Detail |
|------|----------|--------|
| **Set gain** | PUT camera/0/gain | Gain=80 |
| **Expose** | PUT camera/0/startexposure | Duration (sec), Light=true |
| **Poll** | GET camera/0/imageready | Until True |
| **Download** | GET camera/0/imagearray | 2160×3840 int32, ~33s JSON |
| **Read temp** | GET camera/0/ccdtemperature | For FITS header |

---

## PHASE 4: HARVEST (INTEGRATING → COMPLETED)

1. **Clip** — np.clip(array, 0, 65535).astype(np.uint16)
2. **Stamp** — `sovereign_stamp()` writes AAVSO-compliant FITS header:
   OBJECT, OBJCTRA, OBJCTDEC, DATE-OBS, EXPTIME, INSTRUME=IMX585,
   TELESCOP=ZWO Seestar S30-Pro, FILTER=TG, BAYERPAT=GRBG,
   OBSERVER, AUID, GAIN=80, FOCALLEN=160, APERTURE=30, PIXSCALE=3.74.
3. **Write** — `write_fits()` → `data/local_buffer/{TARGET}_{TS}_Raw.fits`
4. **Log** — `data/ledger.json` updated with `last_success` (ISO UTC).

---

## VETO LOGIC (ANY STATE)

| Condition | Source | Threshold | Action |
|-----------|--------|-----------|--------|
| Overheating | Alpaca camera/0/ccdtemperature | > 55.0°C | Park + alert |
| Low battery | WilhelminaMonitor (port 4700 event stream) | < 10% | Park + alert |
| Dawn | Sun altitude | >= -18.0° | Postflight transition |
| Weather | data/weather_state.json | imaging_go: false | Postflight + alert |
