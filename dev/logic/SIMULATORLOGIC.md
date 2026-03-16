# SeeStar Simulator & ALP Bridge Logic (The ET Protocol)

> **Objective:** Outlines networking and state logic required to synchronize the SeeStar ALP Bridge with the Raspberry Pi Simulator environment.
> **Version:** 1.2.0 (Garmt)

## 🔍 1. The Core Conflict
By default, the Bridge and Simulator were locked in a "Loopback Prison." The Bridge searched for a hostname (`seestar.local`) that didn't resolve, while the Simulator listened only on a local address (`127.0.0.1`) invisible to the Bridge's network threads.

## ⚙️ 2. Networking Logic
To establish a stable "Federation," we moved from dynamic discovery to **Fixed IP Alignment**.

### Binding Strategy
* **Simulator Bind**: The Simulator is forced to listen on `0.0.0.0` (all interfaces). This allows it to receive UDP broadcasts and TCP commands regardless of origin.
* **Bridge Targeting**: The Bridge `config.toml` was updated to point directly to the physical IP `192.168.178.55`.

## 🛰️ 3. State & Location Logic (The Bouncer)
The ALP Bridge implements a "Presence-First" requirement. It rejects configuration commands if a live socket connection to a telescope is not detected.

### Location Injection Method
1.  **Handshake**: A `PUT` request to `/connected` is sent to flip the internal state to `true`.
2.  **Memory Overwrite**: While the connection is live, `SiteLatitude` and `SiteLongitude` are injected via the Alpaca API.
3.  **Synchronization**: The Simulator internal state was patched to Haarlem coordinates (52.3874, 4.6462) to ensure accurate Sidereal Time.

## 📋 4. Verified Capabilities
As of 2026-02-26, the following features are operational:
* **Device Status**: Reporting as Seestar S50, Firmware 4.70, EQ Mode.
* **Vitals**: 100% Battery, 49.2 GB Free Storage.
* **Scheduler**: Successfully processing Mosaic JSON templates.

## 🚀 5. Automation Hook
Future scripts should use the API sequence: `CONNECT` -> `SET LAT` -> `SET LON` -> `VERIFY LST`.
