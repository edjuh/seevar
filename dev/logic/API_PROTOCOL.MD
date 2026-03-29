# 📡 SEESTAR S30-PRO HARDWARE PROTOCOL

> **Objective:** Definitive ZWO JSON-RPC method mapping for SeeVar.
> **Version:** 4.0.0 (Haarlem / March 2026)
> **Path:** `logic/API_PROTOCOL.MD`

Science acquisition uses **direct TCP to the S30-Pro** on port 4700 (control)
and port 4801 (frame stream). Hardware control (slew, park, track) uses the
**native Alpaca HTTP API on port 32323** — confirmed March 2026 against
Wilhelmina firmware 7.18. See `ALPACA_BRIDGE.MD` for bridge vs native distinction.

---

## Port Architecture

| Port | Host | Protocol | Purpose |
|------|------|----------|---------|
| `4700` | `<telescope_ip>` | JSON-RPC over TCP (`\r\n`) | Event stream + session commands |
| `4801` | `<telescope_ip>` | Binary frame stream | Science capture (preview frames) |
| `4800` | `<telescope_ip>` | Binary frame stream | ZIP stacks — not used for science |
| `32323` | `<telescope_ip>` | HTTP Alpaca (ASCOM) | Native hardware control ✅ confirmed |
| `32227` | broadcast | UDP | Alpaca discovery beacon |
| `5432` | `127.0.0.1` | HTTP (Alpaca bridge) | seestar_alp middleware — not used |

`<telescope_ip>` is read from `config.toml [[seestars]] ip` at runtime.

**Port 5555 does not exist. Port 4720 does not exist. Do not use either.**

---

## Control Path Architecture

Two independent control paths exist. Both confirmed on Wilhelmina fw 7.18:

### Path A — Alpaca HTTP (port 32323) ✅ Primary control
Standard ASCOM Alpaca REST API. No session lock. Works regardless of phone
app connection state. Use for: slew, park, unpark, tracking, sync.

```
PUT http://<ip>:32323/api/v1/telescope/0/<endpoint>
    ClientID=1&ClientTransactionID=<n>&<params>

GET http://<ip>:32323/api/v1/telescope/0/<endpoint>
    ?ClientID=1&ClientTransactionID=<n>
```

### Path B — JSON-RPC TCP (port 4700) ✅ Telemetry + session commands
Event bus. All clients receive broadcast events. Commands require session
master (first connected client). Use for: telemetry monitoring, science
commands when master is held.

### Path C — Binary stream (port 4801) ✅ Science frames
Raw frame data only. No JSON. Active when `ContinuousExposure` event fires.

---

## Alpaca Confirmed Methods (port 32323)

### GET — Read state

| Endpoint | Returns | Notes |
|----------|---------|-------|
| `connected` | bool | Connection state |
| `name` | str | "Seestar Wilhelmina Telescope" |
| `description` | str | Same as name |
| `driverinfo` | str | "Telescope V3" |
| `driverversion` | str | "1.2.0-3" |
| `interfaceversion` | int | 3 |
| `rightascension` | float | Current RA (hours) |
| `declination` | float | Current Dec (degrees) |
| `altitude` | float | Current altitude (degrees) |
| `azimuth` | float | Current azimuth (degrees) |
| `siderealtime` | float | Local sidereal time |
| `tracking` | bool | Tracking state |
| `athome` | bool | At home position |
| `atpark` | bool | At park position |
| `slewing` | bool | Slewing in progress |
| `sitelatitude` | float | Observer latitude |
| `sitelongitude` | float | Observer longitude |
| `equatorialsystem` | int | 1 = J2000 |
| `alignmentmode` | int | 0 = AltAz |
| `canpark` | bool | true |
| `canunpark` | bool | true |
| `canslew` | bool | true |
| `canslewasync` | bool | true |
| `canslewaltaz` | bool | false |
| `cansettracking` | bool | true |
| `cansync` | bool | true |
| `canpulseguide` | bool | true |

### PUT — Commands

| Endpoint | Params | Notes |
|----------|--------|-------|
| `connected` | `Connected=true` | Connect device |
| `tracking` | `Tracking=true/false` | Enable/disable tracking. ERR 1279 if below horizon |
| `park` | — | Park mount |
| `unpark` | — | Unpark — physically deploys arm, triggers `ScopeMoveToHorizon` event |
| `slewtocoordinatesasync` | `RightAscension=<h>&Declination=<d>` | Async slew. ERR 1032 if not initialised |
| `synctocoordinates` | `RightAscension=<h>&Declination=<d>` | Sync pointing model |
| `abortslew` | — | Abort active slew |

### Alpaca Error Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1024` | Property not implemented |
| `1032` | Not initialised — unpark first |
| `1036` | Action not implemented |
| `1279` | Command rejected by firmware (e.g. below horizon) |

---

## JSON-RPC Wire Format (port 4700)

```python
msg  = {"jsonrpc": "2.0", "id": <int>, "method": "<method>"}
wire = (json.dumps(msg) + "\r\n").encode("utf-8")
```

`id` starts at 10000 per session. `params` omitted when not required.
`jsonrpc: "2.0"` field required — firmware rejects without it on fw 7.18.

## Session Ownership (port 4700)

Port 4700 is a publish/subscribe event bus. The first client to connect
receives `Event: Client` with `is_master: True` and can send commands.
All subsequent clients receive only broadcast events.

```json
{"Event": "Client", "Timestamp": "28.663", "connected": ["192.168.x.x"],
 "master_index": 0, "is_master": true}
```

**Resolution:** Use Alpaca (port 32323) for control — no session lock.
Port 4700 is best used as a passive event monitor via `WilhelminaMonitor`.

## Confirmed JSON-RPC Methods

### Session control
| Method | Params | Effect |
|--------|--------|--------|
| `get_device_state` | — | Health probe. |
| `iscope_stop_view` | — | Abort all active camera/mount operations. Terminates connection. |
| `iscope_start_view` | `{"mode": "star"}` | Begin continuous exposure stream. |

### Mount
| Method | Params | Effect |
|--------|--------|--------|
| `scope_sync` | `[ra_hours, dec_deg]` | Sync mount pointing model. |
| `scope_goto` | `[ra_hours, dec_deg]` | Slew to coordinates. |
| `scope_park` | — | Park mount. |
| `set_user_location` | `{"lat": float, "lon": float, "force": true}` | Push GPS fix to mount. |
| `scope_get_track_state` | — | Query tracking state. |
| `scope_set_track_state` | `[true]` | Engage sidereal tracking. |
| `scope_get_ra_dec` | — | Query current mount position. |

### Camera
| Method | Params | Effect |
|--------|--------|--------|
| `set_control_value` | `["gain", 80]` | Set sensor gain. |
| `set_setting` | `{"exp_ms": {"stack_l": ms}}` | Set exposure time (ms). |
| `start_solve` | — | Trigger plate solve. |
| `get_solve_result` | — | Poll plate solve result. `code` 0=success, 207=fail. |
| `start_auto_focuse` | — | Trigger autofocus. Firmware typo — one `s`. |
| `stop_auto_focuse` | — | Stop autofocus. Firmware typo — one `s`. |

## Unconfirmed / Removed Methods

| Method | Status |
|--------|--------|
| `start_exposure` | ❌ Not confirmed |
| `get_last_frame` | ❌ Not confirmed |
| `method_sync` | ❌ seestar_alp middleware only — not native |
| `action_start_up_sequence` | ❌ Not implemented natively — use Alpaca unpark |
| `iscope_get_app_state` | ❌ Not confirmed — use `get_device_state` |

---

## Binary Frame Protocol (port 4801)

Active when `ContinuousExposure` event fires on port 4700.

```
Header format (big-endian, first 20 bytes used):
  fmt    = ">HHHIHHBBHH"
  fields = _s1, _s2, _s3, size, _s5, _s6, code, frame_id, width, height

Frame IDs:
  21  Preview  — raw uint16 Bayer GRBG  ← science target
  23  Stack    — ZIP (not used for science)

Payload < 1000 bytes = heartbeat — skip.
```

Expected payload: `width × height × 2` bytes (uint16, big-endian).
Sensor: IMX585, 2160 × 3840 px, GRBG Bayer, 3.74″/px.

---

## Sovereign Acquisition Sequence

```
1. Alpaca PUT unpark             — deploy arm → ScopeMoveToHorizon event
2. Alpaca PUT slewtocoordinatesasync [ra, dec]  — slew to target
3. Monitor event stream: wait for ScopeGoto complete
4. JSON-RPC iscope_start_view    — begin ContinuousExposure
5. Monitor event stream: wait for ContinuousExposure working
6. port 4801: read frames until frame_id == 21
7. JSON-RPC iscope_stop_view     — end session
8. reshape uint16 array → write_fits()
```

Implementation: `core/flight/pilot.py` — `DiamondSequence`, `ControlSocket`, `ImageSocket`.

---

## Event Vocabulary (port 4700 broadcast stream)

28 event types confirmed on S30-Pro firmware 7.18, Haarlem March 2026.
All events carry: `Event` (str), `Timestamp` (str, seconds since boot).

### System & Power

| Event | Key Fields | Notes |
|-------|-----------|-------|
| `PiStatus` | `battery_capacity` (int %), `temp` (float °C) | Alternates battery/temp each broadcast |
| `DiskSpace` | `used_percent` (int) | eMMC usage |
| `Sleep` | `state`, `route` | Low-power state |
| `Setting` | `wide_cam` (bool), `stack` (dict) | Settings broadcast |

### Mount & Motion

| Event | Key Fields | Notes |
|-------|-----------|-------|
| `ScopeGoto` | `state`, `lapse_ms`, `close` | working/complete/fail |
| `ScopeTrack` | `state`, `tracking` (bool), `error`, `code` | `code 270` = below horizon |
| `ScopeHome` | `state`, `lapse_ms`, `close` | Homing sequence |
| `ScopeMoveToHorizon` | `state`, `lapse_ms`, `close` | Arm deploying — triggered by Alpaca unpark |
| `BalanceSensor` | `code`, `data.x/y/z/angle` (float) | `angle > 1.5°` = veto |
| `GSensorMove` | — | Gyro movement |
| `CompassCalibration` | `state`, `route` | `fail` common indoors |
| `AutoGoto` | `state`, `count`, `hint`, `route` | Automated goto |

### Camera & Optics

| Event | Key Fields | Notes |
|-------|-----------|-------|
| `SelectCamera` | `selected_cam` | Active camera |
| `View` | `state`, `mode`, `cam_id`, `target_ra_dec`, `target_name`, `lp_filter`, `gain`, `route` | Science session |
| `SecondView` | `state`, `mode`, `cam_id`, `gain`, `route` | Wide-angle camera |
| `ContinuousExposure` | `state`, `fps`, `route` | **Frames on port 4801** |
| `Exposure` | `state`, `exp_ms`, `port`, `route` | Single exposure |
| `FocuserMove` | `state`, `lapse_ms`, `position`, `route` | Focus position |
| `AutoFocus` | `state`, `lapse_ms`, `route` | Autofocus |
| `WheelMove` | `state` | Filter wheel |
| `RTSP` | — | Video stream |
| `GoPixel` | — | Pixel-level positioning |
| `ScanSun` | `state`, `error`, `code`, `lapse_ms`, `route` | `code 316` = no star found |
| `SaveImage` | — | Image saved to eMMC |

### Alignment & Calibration

| Event | Key Fields | Notes |
|-------|-----------|-------|
| `PlateSolve` | `state`, `lapse_ms`, `route` | Plate solving |
| `3PPA` | `state`, `percent`, `calib_fail_autogoto`, `route` | 3-point polar alignment |
| `Initialise` | `state`, `lapse_ms`, `route` | Telescope initialisation |

### Session

| Event | Key Fields | Notes |
|-------|-----------|-------|
| `Client` | `connected`, `master_index`, `is_master` (bool) | Session ownership |
| `Demonstrate` | `state` (working/cancel), `lapse_ms`, `route` | Demo mode |

### WilhelminaMonitor State Mapping

| Event field | → `/dev/shm/wilhelmina_state.json` |
|-------------|-----------------------------------|
| `PiStatus.battery_capacity` | `battery_pct` |
| `PiStatus.temp` | `temp_c` |
| `ScopeTrack.tracking` | `tracking` |
| `ScopeGoto.state` | `slew_state`, `slewing` |
| `BalanceSensor.data.angle` | `level_angle`, `level_ok` |
| `Demonstrate.state` | `demo_mode` |
| `CompassCalibration.state` | `compass_cal` |
| `ScopeHome.state` | `homing` |

---

## JSON-RPC Error Codes

| Code | Meaning | Resolution |
|------|---------|------------|
| `103` | Method not found | Check method name spelling |
| `1031` | Not connected | Reconnect and retry |
| `0 bytes` | Session lock | Use Alpaca instead |

<!-- SeeVar-API_PROTOCOL-v4.0.0 -->
