# AI Project Context - Sovereign SeeVar Federation

> **Objective:** The absolute architectural law, environment standards, and logic constraints for AI-assisted development of the SeeVar Federation.
> **Version:** 1.5.2 (We Survived Null Island)
> **Last verified against codebase:** 2026-03-11

## 🛑 1. The Prime Directives (Rules of Engagement)
1. **No "Vibe-Coding":** All logic must map directly to the defined schemas and protocols in `~/seevar/logic/`. No guessing API endpoints or hardware states.
2. **Infrastructure as Code (IaC):** Python 3.13.5 environment is strictly locked via `bootstrap.sh` and `requirements.txt`.
3. **The "Garmt" Header Standard:** Every script must contain a PEP 257 docstring stating: Filename, Version, and a single-sentence Objective.
4. **The Sovereignty Principle:** All hardware control must bypass consumer UI via the Alpaca Bridge to ensure deterministic RAW data capture.
5. **Guiding Principle:** "Do not live in the moment. Plan for the astronomical night."

## 🏗️ 2. The Master Workflow (The Funnel)
The application stack is a strict, linear 3-Phase State Machine.
* **Phase 1: Pre-Flight (The Funnel)**
  * **Harvest & Refine:** `targets.json` (Master) is filtered by `nightly_planner.py` to generate `tonights_plan.json`.
  * **Cadence Logic:** Target priority is calculated using the **1/20th Period Rule** (Miras 5-10d, SRs 3-5d).
  * **AAVSO Throttling:** API calls for sequences must respect a strict **318.4s (Pi-Minute) delay** to prevent IP bans.
* **Phase 2: The Handover (The Gatekeeper)**
  * **System Audit:** 5-minute loop validating weather, disk vitals, and plan integrity. Passes control (GREEN) or scrubs mission (RED).
* **Phase 3: Flight (The Acquisition Loop)**
  * **Control Path Decision Matrix:** * **Alpaca bridge (`/0/schedule`)**: Primary control path. Use strictly for standard AAVSO target scheduling and science acquisition.
    * **Native TCP (port 4700, JSON-RPC)**: Use ONLY for hardware health checks (`get_device_state`) and bridge-bypass diagnostics. Never use for science acquisition.
  * **Action:** Orchestrator commands slew, plate solve, track, and expose via the Alpaca bridge. FITS stream is routed to the Active Storage Path.

## 📡 3. Hardware & Network Logic
* **Alpaca Bridge (The ET Protocol):**
  * **Target IP:** Fixed local bridge at `127.0.0.1` (Port 5432).
  * **Communication:** Strict `PUT`/`POST` method for Actions. `ClientID` (fixed to 42) and `ClientTransactionID` are mandatory.
* **Veto Logic (Sovereignty Limits):**
  * **Battery**: Mandatory Park at **< 10%**.
  * **Thermal**: Mandatory Park at **> 55.0°C**.
  * **Leveling**: Mandatory Pre-flight FAIL at **> 1.5° (Science-grade cutoff)**.
* **Temporal & Positional Awareness:**
  * **Time:** GPS PPS (`/dev/pps0`) via `chrony`. Pre-flight FAILS if offset > 0.5s.
  * **Location:** Live GPS data writes strictly to RAM (`/dev/shm/env_status.json`) to prevent SD wear.

## 🗂️ 4. Data Dictionary Rules
* **Science First:** No target is integrated without a matching sequence in `data/sequences/comp_stars/`.
* **Path Awareness:** All logic must resolve paths dynamically via `core/utils/env_loader.py` and `config.toml`.
