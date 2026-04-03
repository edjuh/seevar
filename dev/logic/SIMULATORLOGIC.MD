# SeeStar Simulator & ALP Bridge Logic (The ET Protocol)

> **Objective:** Outlines networking and state logic required to synchronize the SeeStar ALP Bridge with the Raspberry Pi Simulator environment.
> **Version:** 2.0.0 (Sovereign A1-A12)

## 🔍 1. The Core Conflict
By default, the Bridge and Simulator were locked in a "Loopback Prison." The Bridge searched for a hostname (`seestar.local`) that didn't resolve, while the Simulator listened only on a local address (`127.0.0.1`) invisible to the Bridge's network threads.

## ⚙️ 2. Networking Logic
To establish a stable "Federation," we moved from dynamic discovery to **Fixed IP Alignment**.

### Binding Strategy
- **Simulator Bind**: The Simulator is forced to listen on `0.0.0.0` (all interfaces). This allows it to receive UDP broadcasts and TCP commands regardless of origin.
- **Bridge Targeting**: The Bridge `config.toml` was updated to point directly to the physical IP `192.168.178.55`.

## 🛰️ 3. State & Location Logic (The Bouncer)
The ALP Bridge implements a "Presence-First" requirement. It rejects configuration commands if a live socket connection to a telescope is not detected.

### Location Injection Method
1. **Handshake**: A `PUT` request to `/connected` is sent to flip the internal state to `true`.
2. **Memory Overwrite**: While the connection is live, `SiteLatitude` and `SiteLongitude` are injected via the Alpaca API.
3. **Synchronization**: The Simulator internal state was patched to Haarlem coordinates to ensure accurate Sidereal Time.

## 📋 4. Verified Capabilities
As of 2026-02-26, the following features are operational:
- **Device Status**: Reporting as Seestar hardware through the bridge
- **Vitals**: telemetry and configured devices reachable
- **Scheduler**: Successfully processing nightly plans and simulator runs

## 🚀 5. Automation Hook
Future scripts should use the API sequence:
`CONNECT -> SET LAT -> SET LON -> VERIFY LST`

---

## Flight Simulation Contract (A1–A12)

The simulator must mirror the real flight sequence names even when
hardware calls are mocked.

Simulation must emit the same step labels as flight:
`A1` through `A12`.

At minimum, the simulator must model:

- **A1 Target Lock**
- **A2 Safety Gate**
- **A3 Session Init**
- **A4 Slew Command**
- **A5 Slew Verify**
- **A6 Settle**
- **A7 Pointing Verify** (simulated if no real solver is attached)
- **A8 Corrective Nudge** (simulated or no-op if centred)
- **A9 Exposure Plan**
- **A10 Acquire**
- **A11 Quality Gate**
- **A12 Commit**

## Simulation Rules

- Simulation may bypass real wall-clock observing windows.
- Simulation must not collapse the target sequence into a single fake exposure event if the goal is workflow verification.
- Simulation logs must resemble real flight logs closely enough that step-by-step validation is possible.
- The simulator should prove orchestration logic, not just FITS file creation.

## Minimum Acceptable Output

For each simulated target, the log should show the A1-A12 chain explicitly,
even if some steps are mocked.

This ensures that:
- the dashboard reflects real mission progress
- the FSM is exercised in realistic order
- future contributors do not confuse simulator shortcuts with real flight design
