# 🛰️ SEESTAR SIMULATOR & ALP BRIDGE LOGIC

> **Status:** RETIRED (historical record)
> **Superseded by:** Direct TCP to S30-Pro on port 4700.
> **Version:** 2.0.0 (Praw)
> **Path:** `logic/SIMULATORLOGIC.MD`

The Alpaca bridge/simulator networking protocol described below was the
operational path during the Garmt and Kriel eras. It is no longer used
for science acquisition or location injection.

**What replaced it:**

- Location push → `set_user_location {"lat": X, "lon": Y, "force": true}`
  sent directly to port 4700 JSON-RPC. No Alpaca handshake required.
- Hardware control → `DiamondSequence` in `core/flight/pilot.py` via
  port 4700 (control) and port 4801 (frame stream).
- Simulator testing → `tests/phantom_bridge.py` v2.0.0.

See `API_PROTOCOL.MD` for the current confirmed method list.

---

## Historical Record (Garmt v1.2.0 — 2026-02)

### The Core Conflict
The Bridge and Simulator were locked in a "Loopback Prison." The Bridge
searched for a hostname (`seestar.local`) that didn't resolve, while the
Simulator listened only on `127.0.0.1`, invisible to the Bridge's network
threads.

### Resolution — Fixed IP Alignment
- Simulator bound to `0.0.0.0` (all interfaces).
- Bridge `config.toml` pointed directly to `192.168.178.55`.

### Location Injection (Bridge era)
1. PUT `/connected` → flip internal state to `true`.
2. Inject `SiteLatitude` and `SiteLongitude` via Alpaca API.
3. Patch Simulator internal state to Haarlem (52.3874°N, 4.6462°E).

### Verified State (2026-02-26)
- Device reporting as Seestar S50, Firmware 4.70, EQ Mode.
- Battery 100%, 49.2 GB free storage.
- Scheduler processing Mosaic JSON templates successfully.

This configuration is preserved here for diagnostic reference only.
The fixed IP `192.168.178.55` remains correct for Wilhelmina.
