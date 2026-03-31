# 🧠 SeeVar: Logic & Protocols

> **Objective:** Definitive entry point and table of contents for the
> foundational rules, schemas, and communication protocols that govern
> the observatory pipeline.
> **Version:** 2.0.0 (Alpaca)
> **Path:** `~/seevar/dev/logic/`

---

## Core Documentation

| Document | Purpose |
|----------|---------|
| [CORE.MD](./CORE.MD) | Chain of command, 10-step pipeline, fleet identity |
| [ALPACA_BRIDGE.MD](./ALPACA_BRIDGE.MD) | Alpaca REST device map, port 32323, all endpoints |
| [STATE_MACHINE.md](./STATE_MACHINE.md) | Alpaca Diamond Sequence — A1-A7 hardware transitions |
| [FLIGHT.MD](./FLIGHT.MD) | Full flight operations — per-target acquisition loop |
| [PREFLIGHT.MD](./PREFLIGHT.MD) | Go/No-Go pillars, data pipeline, cadence rules |
| [DISCOVERY_PROTOCOL.MD](./DISCOVERY_PROTOCOL.MD) | Network discovery — HTTP probe + UDP fallback |
| [AAVSO_LOGIC.MD](./AAVSO_LOGIC.MD) | Targeting, cadence, photometry channel, WebObs format |
| [CADENCE.md](./CADENCE.md) | 1/20th period rule — LPV / Mira / SR / CV sampling |
| [DATA_DICTIONARY.MD](./DATA_DICTIONARY.MD) | Strict JSON schemas and filesystem authority rules |
| [DATA_MAPPING.MD](./DATA_MAPPING.MD) | Data flow from AAVSO fetch to FITS custody |
| [DATALOGIC.MD](./DATALOGIC.MD) | Data structure roles and RAID1 transformation logic |
| [PICKERING_PROTOCOL.MD](./PICKERING_PROTOCOL.MD) | Fleet naming and founding principles |
| [COMMUNICATION.md](./COMMUNICATION.md) | ⚠️ RETIRED — historical TCP wire format reference |
| [SIMULATORLOGIC.MD](./SIMULATORLOGIC.MD) | ⚠️ RETIRED — historical bridge/simulator record |
| [API_PROTOCOL.MD](./API_PROTOCOL.MD) | ⚠️ RETIRED — historical JSON-RPC method list (port 4700) |

---

## Implementation Rules

1. **Science First** — No target is observed without a matching sequence
   in `catalogs/reference_stars/`.

2. **Alpaca Rule** — All hardware control uses the official ZWO ASCOM Alpaca
   REST API on port 32323. No proprietary TCP for commands. Port 4700 is
   retained read-only for battery/charger telemetry via WilhelminaMonitor.

3. **Path Awareness** — All scripts resolve paths via `PROJECT_ROOT`
   from `__file__`, never hardcoded. RAID1 symlink at `data/`.

4. **Throttling** — AAVSO VSP API: 188.4s between requests.
   Non-negotiable.

5. **Ledger Authority** — `orchestrator.py` is the sole writer of
   `data/ledger.json`. Append-only per target. Never overwrite wholesale.

6. **Oversight Always** — Dashboard, logs, and notifier run permanently
   across all phases. Alerts fire on any pipeline exception.

---

*Observer: JO22hj — Haarlem, NL*
