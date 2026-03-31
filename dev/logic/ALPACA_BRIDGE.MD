# 🔭 ALPACA REST INTERFACE

> **Version:** 2.0.0
> **Path:** `dev/logic/ALPACA_BRIDGE.MD`

## Role (Post-Alpaca Breakthrough, 2026-03-30)

The ZWO official ASCOM Alpaca driver is the **primary and sole** control
interface for all science acquisition. It runs inside the Seestar firmware
on port 32323, exposed via standard HTTP REST.

No phone app required. No session master lock. No JSON-RPC encryption.
No seestar_alp middleware.

Confirmed working: slew, track, park, unpark, expose, gain control,
filter wheel, image download — all without any ZWO cooperation or
special developer access.

## Device Map (Alpaca v1.2.0-3)

| Device | # | Name | Capabilities |
|--------|---|------|-------------|
| Telescope | 0 | Seestar Wilhelmina Telescope | Slew, track, park, unpark, pulse guide |
| Camera | 0 | Seestar Wilhelmina Telephoto Camera | IMX585, 3840×2160, gain 0-600, expose |
| Camera | 1 | Seestar Wilhelmina Wide Angle Camera | IMX586, context/finder |
| Focuser | 0 | Seestar Wilhelmina Telephoto Focuser | Absolute position |
| Focuser | 1 | Seestar Wilhelmina Wide Angle Focuser | Absolute position |
| FilterWheel | 0 | Seestar Wilhelmina Filter Wheel | Dark(0), IR(1), LP(2) |
| Switch | 0 | Seestar Wilhelmina Switch | Dew heater on/off |

## Port Architecture

| Port | Host | Protocol | Purpose |
|------|------|----------|---------|
| `32323` | `<telescope_ip>` | HTTP REST (Alpaca) | **All hardware control and science acquisition** |
| `4700` | `<telescope_ip>` | TCP event stream | Battery/charger telemetry via WilhelminaMonitor |

Port 4700 is retained read-only for battery_pct and charger_status,
which are not exposed via Alpaca. WilhelminaMonitor listens passively.
No commands are sent to port 4700.

**Ports 4801, 4800, 5432, 5555 — no longer used.**

## Alpaca REST Conventions

- Management API: `http://<ip>:32323/management/v1/configureddevices`
- Device API: `http://<ip>:32323/api/v1/<device_type>/<device_number>/<property>`
- `ClientID`: integer `42` (SeeVar)
- `ClientTransactionID`: auto-incrementing integer per session
- GET for property reads, PUT for commands and property writes
- All responses are JSON with `ErrorNumber` and `Value` fields

## Discovery

UDP broadcast discovery on port 32227 does not work on the S30-Pro
(no response observed). Use direct HTTP probe instead:

```bash
curl http://192.168.178.251:32323/management/apiversions
```

The IP is read from `config.toml [[seestars]] ip` at runtime.

## Implementation

All Alpaca client classes live in `core/flight/pilot.py` v3.0.0:
- `AlpacaClient` — base HTTP REST wrapper
- `AlpacaTelescope` — slew, track, park, unpark
- `AlpacaCamera` — gain, expose, download image array
- `AlpacaFilterWheel` — position control (Dark/IR/LP)

## Known Limitations

- **Image download speed:** ~33s for 8.3MP via JSON imagearray. Binary
  ImageBytes transfer (Alpaca v3) not yet confirmed on ZWO firmware.
- **LastExposureDuration:** Not implemented in driver. Use requested duration.
- **SiteElevation:** Not implemented. Set via GPS in FITS header.
- **SupportedActions:** Empty — no custom plan upload yet (see tom-dd132's
  ZWO forum proposal for future UploadSeestarPlan action).
- **Battery/charger:** Not available via Alpaca. Read from port 4700 event stream.
