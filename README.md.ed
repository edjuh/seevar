# 🔭 Seestar Federation Command (S30-PRO)

> **Objective:** Primary documentation and entry gate for the automated S30-PRO variable star observation pipeline.
> **Version:** 1.4.17 (Infrastructure Baseline / Oene's Clean Slate)

**Automated Variable Star Observation Pipeline**

## 🏰 Architecture: The 5-Block State Machine
This project has transitioned from a scattered daemon approach to a strict **5-Block Linear State Machine**. All logic follows a unidirectional flow to ensure hardware synchronicity and prevent desynchronization errors (such as the "Grey Williamina / Red GPS" UI disconnects).

1. **Block 1: Hardware & OS Foundation** (Debian Bookworm 64-bit, `ssc-3.13.5` virtual environment).
2. **Block 2: Seestar ALP Bridge** (Deterministic hardware mapping, zero-guess endpoints).
3. **Block 3: Preflight Gatekeeper** (Environment, storage, and GPS auditing).
4. **Block 4: Flight Acquisition** (The AAVSO target sequence loop).
5. **Block 5: Postflight Teardown** (Safe parking, FITS transfer, and log generation).

## 🛠️ Infrastructure as Code (IaC)
To guarantee reproducibility ("Installation from GitHub, no tricks"), this project relies on a rigid bootstrap protocol. 
* **The Environment Guardian:** The system environment is strictly enforced by `bootstrap.sh` and `requirements.txt`. Execution on unauthorized OS versions or corrupted virtual environments will be automatically halted.

## 🧠 The ET Protocol (Logic Hub)
For technical deep-dives into our networking, state-machine logic, and AAVSO handshake protocols, see the **[Logic Directory](./logic/)**.

* **[Master Workflow](./logic/WORKFLOW.md)**: The end-to-end data lifecycle (The Funnel).
* **[Data Mapping](./logic/data_mapping.md)**: Understanding the transition from raw JSON to FITS buffer.
* **[API Protocols](./logic/api_protocol.md)**: Mandatory throttling (188.4s) and connection rules for AAVSO.
* **[Discovery & GPS](./logic/discovery_protocol.md)**: AP Fallback rules and in-memory spatial awareness.

## 🛫 System Entry Points
* **`bootstrap.sh`**: The mandatory initial execution to build and verify the Python OS layer.
* **`core/flight/orchestrator.py`**: The primary state-machine controller managing the active observatory loop.

## 🍷 Slotwoord van een Heer van Stand
"Het is een hele zorg, nietwaar? De sterrenhemel is onmetelijk en de techniek staat voor niets... wij handelen hier volgens de regelen van het fatsoen!"
