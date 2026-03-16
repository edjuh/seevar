# 🧠 SeeVar: Logic & Protocols

> **Objective:** Definitive entry point and table of contents for the
> foundational rules, schemas, and communication protocols that govern
> the observatory pipeline.
> **Version:** 2026.03.12 (Praw revision)
> **Path:** `~/seevar/logic/`

---

## Core Documentation

| Document | Purpose |
|----------|---------|
| [../WORKFLOW.md](../WORKFLOW.md) | Master pipeline — preflight → flight → postflight → oversight |
| [CORE.MD](./CORE.MD) | Chain of command, 10-step pipeline, fleet |
| [ARCHITECTURE_OVERVIEW.md](./ARCHITECTURE_OVERVIEW.md) | Structural map — hangar, postflight, data vault, logic board |
| [STATE_MACHINE.md](./STATE_MACHINE.md) | Diamond Sequence — deterministic hardware state transitions |
| [API_PROTOCOL.MD](./API_PROTOCOL.MD) | Confirmed JSON-RPC methods, wire format, error codes |
| [ALPACA_BRIDGE.MD](./ALPACA_BRIDGE.MD) | Bridge role — port 5432, health-check only |
| [PREFLIGHT.MD](./PREFLIGHT.MD) | Go/No-Go pillars, data pipeline, cadence rules |
| [AAVSO_LOGIC.MD](./AAVSO_LOGIC.MD) | Targeting, cadence, photometry channel, WebObs format |
| [CADENCE.md](./CADENCE.md) | 1/20th period rule — LPV / Mira / SR / CV sampling |
| [DATA_DICTIONARY.MD](./DATA_DICTIONARY.MD) | Strict JSON schemas and filesystem authority rules |
| [DATA_MAPPING.MD](./DATA_MAPPING.MD) | Data flow from AAVSO fetch to FITS custody |
| [DATALOGIC.MD](./DATALOGIC.MD) | Data structure roles and RAID1 transformation logic |
| [DISCOVERY_PROTOCOL.MD](./DISCOVERY_PROTOCOL.MD) | Network discovery and home/field grid detection |
| [PICKERING_PROTOCOL.MD](./PICKERING_PROTOCOL.MD) | Fleet naming and founding principles |
| [SEEVAR_DICT.PSV](./SEEVAR_DICT.PSV) | Empirical hardware vocabulary — bridge-era method reference |
| [COMMUNICATION.md](./COMMUNICATION.md) | ⚠️ RETIRED — see API_PROTOCOL.MD |
| [SIMULATORLOGIC.MD](./SIMULATORLOGIC.MD) | ⚠️ RETIRED — historical bridge/simulator record |

---

## Implementation Rules

1. **Science First** — No target is observed without a matching sequence
   in `catalogs/reference_stars/`.

2. **Sovereignty Rule** — All hardware control goes direct TCP port 4700
   (JSON-RPC) and port 4801 (binary frame stream). No consumer UI.
   No method_sync. No Alpaca for capture.

3. **Path Awareness** — All scripts resolve paths via `PROJECT_ROOT`
   from `__file__`, never hardcoded. RAID1 symlink at `data/`.

4. **Throttling** — AAVSO VSP API: 31.4s between requests to
   `apps.aavso.org`. Non-negotiable.

5. **Ledger Authority** — `orchestrator.py` is the sole writer of
   `data/ledger.json`. Append-only per target. Never overwrite wholesale.

6. **Oversight Always** — Dashboard, logs, and notifier run permanently
   across all phases. Alerts fire on any pipeline exception.

---

*Observer: JO22hj — Haarlem, NL*
