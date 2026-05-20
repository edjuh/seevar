# 📡 COMMUNICATION PROTOCOL

> **Status:** ⚠️ RETIRED (historical record)
> **Superseded by:** Alpaca REST on port 32323. See `ALPACA_BRIDGE.MD`.
> **Version:** 3.0.0

The TCP JSON-RPC protocol described below was the operational path
during the Sovereign era (v1.0–v1.7). As of v3.0.0 (2026-03-30), all
hardware control uses the official ZWO ASCOM Alpaca REST API.

Port 4700 may still be used by explicit diagnostics/RPC tools where documented,
but it is not the current production flight-control law.

---

## Historical Record (below)

wire format, the connection model, and the three tiers of control.

For the full confirmed method list, response shapes, and error codes
see `API_PROTOCOL.MD`.

---

## Historical three-tier model

The S30-Pro speaks JSON-RPC on port 4700 regardless of who is talking
to it. Three tiers of control exist, all using the same wire format:

| Tier | Controller | Route | Status |
|------|-----------|-------|--------|
| 1 | ZWO phone app | Proprietary, closed | Not used by SeeVar |
| 2 | seestar_alp on Pi | JSON-RPC/API bridge | Historical / diagnostic |
| 3 | SeeVar direct TCP | JSON-RPC direct to telescope | Historical |

These notes describe the pre-Alpaca direct-control era and must not be used as
current production doctrine.

The telescope IP is set in `config.toml` under `[[seestars]]`.
It is never hardcoded in application logic or documentation.

---

## Port architecture

| Port | Host | Protocol | Purpose |
|------|------|----------|---------|
| `4700` | `<telescope_ip>` | JSON-RPC over TCP (`\r\n`) | Historical / diagnostics |
| `4801` | `<telescope_ip>` | Binary frame stream | Historical frame diagnostics |
| `4800` | `<telescope_ip>` | Binary frame stream | Historical ZIP stacks |
| `5432` | `127.0.0.1` | HTTP | Historical bridge / current seestar_alp workbench |

`<telescope_ip>` is read from `config.toml [[seestars]] ip` at runtime.

Port `5555` exists only as a `seestar_alp` Alpaca action wrapper on the DEV RPI
when that service is running. It is not native Seestar firmware.

---

## Connection model

Two separate TCP connections are maintained per session:

**Control connection (port 4700)**
Opened at session start by `ControlSocket`. Kept open for the duration
of the session. All JSON-RPC commands go here. Closed after T6.

**Frame connection (port 4801)**
Opened at T5 by the old `ImageSocket`. Binary stream only — no JSON.
This is historical behavior; current science acquisition uses Alpaca camera
exposure/download paths.

These are independent sockets. A failure on one does not close the other.

---

## Wire format — port 4700

Every command sent is a UTF-8 JSON string terminated with `\r\n`.
Every response from the telescope terminates with `\r\n`.

**Command structure:**
```
{"id": <int>, "method": "<method_name>", "params": <value>}\r\n
```

- `id` is an auto-incrementing integer, starting at 10000 per session.
- `params` is omitted entirely when the method takes no arguments.
- `params` is a list `[...]` for positional arguments (scope_goto, set_control_value).
- `params` is a dict `{...}` for named arguments (set_user_location, iscope_start_view).

**Example commands on the wire:**
```json
{"id": 10001, "method": "get_device_state"}\r\n
{"id": 10002, "method": "iscope_stop_view"}\r\n
{"id": 10003, "method": "set_user_location", "params": {"lat": 52.38, "lon": 4.65, "force": true}}\r\n
{"id": 10004, "method": "set_control_value", "params": ["gain", 80]}\r\n
{"id": 10005, "method": "scope_goto", "params": [6.4025, 22.0145]}\r\n
{"id": 10006, "method": "set_setting", "params": {"exp_ms": {"stack_l": 5000}}}\r\n
{"id": 10007, "method": "start_auto_focuse"}\r\n
{"id": 10008, "method": "iscope_start_view", "params": {"mode": "star"}}\r\n
```

**Example responses:**
```json
{"id": 10001, "result": {"pi_status": {"battery_capacity": 85, "temp": 32.1, ...}, "device": {...}}}\r\n
{"id": 10002, "result": 0}\r\n
{"id": 10005, "result": 0}\r\n
```

**Error responses:**
```json
{"id": 10009, "error": {"code": 103, "message": "method not found"}}\r\n
{"id": 10010, "error": {"code": 1031, "message": "not connected"}}\r\n
```

A response of 0 bytes means a silent failure — the telescope may have
a session lock. Send `iscope_stop_view` and retry.

---

## Historical wire format — port 4801

Binary stream. No JSON. No `\r\n` terminator.

Every packet on this port is structured as:
```
[80-byte header][payload]
```

**Header parse (big-endian, first 20 bytes used):**
```
format: >HHHIHHBBHH
fields: _s1, _s2, _s3, size, _s5, _s6, code, frame_id, width, height
```

**frame_id values:**
| frame_id | Content | Action |
|----------|---------|--------|
| 21 | Raw uint16 Bayer GRBG preview | Historical science frame |
| 23 | ZIP stack | Not used for science — skip |
| any | payload < 1000 bytes | Heartbeat packet — skip |

**Payload validation for frame_id 21:**
Expected size = `width × height × 2` bytes (uint16, big-endian).
A size mismatch means a corrupt or partial frame — discard and wait
for the next packet.

---

## Error codes (port 4700)

| Code | Meaning | Resolution |
|------|---------|------------|
| `103` | Method not found | Malformed JSON or unrecognised method name |
| `1031` | Not connected | Device dropped — reconnect and retry |
| `0 bytes` | Silent failure / session lock | Send `iscope_stop_view` first, then retry |

<!-- SeeVar-COMMUNICATION-v3.0.0 -->
