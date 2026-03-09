# 🔭 SeeVar

> **Objective:** Primary documentation and entry gate for the automated S30-PRO variable star observation pipeline.
> **Version:** 1.5.1 (Diamond & Cadence Integration)

Welcome to the **SeeVar**, an advanced, headless, and fully automated orchestration system for the Seestar smart telescope ecosystem.
 Dedicated to the Pickering Clade Clan

## 🎯 Scientific Mission Profile & Hardware Constraints
The **SeeVar** is an autonomous photometric pipeline engineered for the IMX585 colour sensor.

**Target Acquisition Strategy:**
* **Primary Focus:** Long-Period Variables (Miras, Semi-Regulars) following the **1/20th Period Cadence Rule**.
* **Triggered Observations:** Cataclysmic Variables (CVs) in outburst.

**Photometric Output:**
Submissions to the AAVSO are strictly reported as **"TG"** or **"CV"** to ensure absolute scientific integrity.

---

## 🏗️ The Sovereignty State Machine
Unlike standard operation, this system utilizes a deterministic logic gate system to bypass internal ZWO stacking locks.
* **Phase 1 (Initialization)**: Force-clear UI/App locks via `iscope_stop_view`.
* **Phase 2 (Navigation)**: `scope_sync` using strict **Keyed Object Dialect** `{"ra": X, "dec": Y}`.
* **Phase 3 (Science)**: Bypassing the consumer stacker for pure RAW data via `start_exposure`.
* **Phase 4 (Harvest)**: Single-frame FITS retrieval with midpoint UTC JDATE logging.


---

## ✨ The Crown Jewel: The Tactical Dashboard
* **Live Hardware Vitals:** Dynamic polling for sub-second battery and storage updates.
* **Tri-Source Weather Sentinel:** Aggregates data from Open-Meteo, 7Timer!, and Meteoblue.
* **Dynamic Target Ticker:** Cycles through flight plans with live altitude and priority scores.

---

## 🏰 Architecture: The 5-Block State Machine
1. **Block 1: Hardware & OS Foundation** (Debian Bookworm, `ssc-3.13.5`).
2. **Block 2: Seestar ALP Bridge** (Deterministic hardware mapping).
3. **Block 3: Preflight Gatekeeper** (Safety check: Battery >10%, Temp <55C, Level <4.0°).
4. **Block 4: Flight Acquisition** (AAVSO target sequence and 1/20th Cadence loop).
5. **Block 5: Postflight Teardown** (Safe parking and RAW FITS transfer).

---

## 🚀 Getting Started
To initialize the environment:
* **`bootstrap.sh`**: Verify Python OS layer and dependencies.
* **`core/flight/orchestrator.py`**: Managing the active observatory loop.

For technical deep-dives into networking and AAVSO handshake protocols, see **[Logic Directory](./logic/)**.

---

## 🍷 Slotwoord van een Heer van Stand
"Het is een hele zorg, nietwaar? De sterrenhemel is onmetelijk en de techniek staat voor niets... !"
