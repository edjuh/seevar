# 🧠 SeeVar: Logic & Protocols

> **Objective:** Definitive entry point and table of contents for the foundational
> rules, schemas, and communication protocols that govern the observatory pipeline.
> **Version:** 2026.03.13
> **Path:** `~/seevar/logic/`

---

## Core Documentation

| Document | Purpose |
|----------|---------|
| [WORKFLOW.md](./WORKFLOW.md) | Master pipeline — preflight → flight → postflight → oversight |
| [STATE_MACHINE.md](./STATE_MACHINE.md) | Sovereignty Diamond — deterministic hardware state transitions |
| [CADENCE.md](./CADENCE.md) | 1/20th period rule — LPV / Mira / SR / CV sampling frequency |
| [ARCHITECTURE_OVERVIEW.md](./ARCHITECTURE_OVERVIEW.md) | High-level structural map of the software stack |
| [COMMUNICATION.md](./COMMUNICATION.md) | Inter-process communication and pipeline messaging |
| [data_dictionary.md](./data_dictionary.md) | Strict JSON schemas and filesystem contracts |
| [data_mapping.md](./data_mapping.md) | Data flow from AAVSO fetch to FITS acquisition |
| [DATALOGIC.md](./DATALOGIC.md) | Backend logic for RAID1 writing and data lifecycle |
| [api_protocol.md](./api_protocol.md) | VSP/AAVSO handshake — includes Pi-Minute (31.4s) throttle |
| [aavso_logic.md](./aavso_logic.md) | AAVSO authentication — direct apps.aavso.org endpoint |
| [alpaca_bridge.md](./alpaca_bridge.md) | Alpaca bridge protocol — port 5432, device index /0/ |
| [discovery_protocol.md](./discovery_protocol.md) | UDP broadcast for S30-Pro network discovery |
| [SIMULATORLOGIC.md](./SIMULATORLOGIC.md) | Fixed-IP alignment (192.168.178.55) for simulator sync |
| [core.md](./core.md) | Chain of command and guiding principles |
| [PHOTOMETRICS.MD](./PHOTOMETRICS.MD) | Differential photometry — decisions, error budget & roadmap |
| [seestar_dict.psv](./seestar_dict.psv) | PSV hardware key mappings and status codes |
| [FILE_MANIFEST.md](./FILE_MANIFEST.md) | Auto-generated file manifest (do not edit by hand) |

---

## Implementation Rules

1. **Science First** — No target is observed without a matching sequence
   in `catalogs/reference_stars/`.

2. **Sovereignty Rule** — All hardware control goes direct TCP port 4700
   (JSON-RPC) and port 4801 (binary frame stream). No consumer UI.
   No method_sync. No Alpaca for capture.

3. **Path Awareness** — All scripts resolve paths via `PROJECT_ROOT`
   from `__file__`, never hardcoded. RAID1 symlink at `data/`.

4. **Throttling** — AAVSO VSX/VSP API: **31.4s (Pi-Minute)** between requests.
   Non-negotiable. Pi IP was blocked at 3.14s — do not reduce.

5. **Ledger Authority** — Postflight writes to the ledger. Preflight reads
   from it. No other component modifies `data/ledger.json`.

6. **Oversight Always** — Dashboard, logs, and notifier run permanently
   across all phases. Alerts fire on any pipeline exception.

---

*Observer: REDA — JO22hj — Haarlem, NL*
