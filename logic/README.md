# 🧠 S30-PRO Federation: Logic & Protocols

> **Objective:** Definitive entry point and Table of Contents for the Seestar Federation’s foundational rules, schemas, and communication protocols.
> **Version:** 1.2.0 (Garmt)

**Path:** `~/seestar_organizer/logic/`

This directory houses the foundational rules, schemas, and communication protocols that govern the observatory's state machine.

## 📄 Core Documentation (Knowledge Graph)
* **[WORKFLOW.md](./WORKFLOW.md)**: The master "Arrow Logic" roadmap. Defines the Phase 1-4 lifecycle from AAVSO Harvest to Post-Flight Analysis.
* **[data_mapping.md](./data_mapping.md)**: High-level overview of the "Funnel" pattern, tracking data from raw AAVSO fetch to acquisition.
* **[data_dictionary.md](./data_dictionary.md)**: The definitive Data Dictionary. Defines strict JSON schemas and filesystem contracts for master and reference files.
* **[api_protocol.md](./api_protocol.md)**: The VSP/AAVSO handshake rules. Includes the mandatory 188.4s (Pi-Minute) throttling logic.
* **[aavso_logic.md](./aavso_logic.md)**: Verified 2026 Authentication handshake. Bypasses 301/302 redirect chains via `apps.aavso.org`.
* **[alpaca_bridge.md](./alpaca_bridge.md)**: Command protocol for Port 5555. Mandates `PUT` actions and specific transaction parameters.
* **[SIMULATORLOGIC.md](./SIMULATORLOGIC.md)**: The "ET Protocol." Defines fixed-IP alignment (192.168.178.55) for bridge-to-simulator synchronization.
* **[core.md](./core.md)**: The operational sequence and guiding principles of the SeestarJoost chain of command.

## 🛠️ Implementation Rules
1. **Science First**: No target is integrated without a matching sequence in `data/sequences/`.
2. **Path Awareness**: All logic must resolve paths via `config.toml` to support the RAID1/Lifeboat architecture.
3. **Throttling**: Respect AAVSO servers; the 3.14-minute (188.4s) delay is non-negotiable.
