# AI Project Context - S30-PRO Federation (Diamond Edition)

> **Objective:** The absolute architectural law, environment standards, and logic constraints for AI-assisted development of the Seestar Federation.
> **Version:** 1.5.0 (Diamond Revision)

## 🛑 1. The Prime Directives (Rules of Engagement)
1. **No "Vibe-Coding":** All logic must map directly to the defined schemas and protocols in `~/seevar/logic/`. No guessing API endpoints or hardware states.
2. **Infrastructure as Code (IaC):** Python 3.13.5 environment is strictly locked via `bootstrap.sh` and `requirements.txt`.
3. **The "Garmt" Header Standard:** Every script must contain a PEP 257 docstring stating: Filename, Version, and a single-sentence Objective.
4. **The Sovereignty Principle:** All hardware control must bypass consumer UI via `iscope_stop_view` and `start_exposure` to ensure deterministic RAW data capture.
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
  * **The Diamond Sequence:** 1. `iscope_stop_view` (AutoStack) -> 2. `scope_sync` (Keyed) -> 3. `start_solve` -> 4. `start_exposure`.
  * **Action:** Commands slew, plate solve, track, and expose. FITS stream is routed to the Active Storage Path.

## 📡 3. Hardware & Network Logic
* **Alpaca Bridge (The ET Protocol):**
  * **Target IP:** Fixed alignment at `192.168.178.55` (Port 5555).
  * **Communication:** Strict `PUT` method for Actions. `ClientID` and `ClientTransactionID` are mandatory.
  * **The Three Dialects:**
    * **Keyed Objects**: Required for `scope_sync` and `set_setting` (e.g., `{"ra": X, "dec": Y}`).
    * **Positional Arrays**: Required for `set_control_value` (e.g., `["gain", 80]`).
    * **Primitives**: Required for toggles like `scope_set_track_state` (e.g., `True`).
* **Veto Logic (Sovereignty Limits):**
  * **Battery**: Mandatory Park at **< 10%**.
  * **Thermal**: Mandatory Park at **> 55.0°C**.
  * **Leveling**: Mandatory Pre-flight FAIL at **> 4.0°**.
* **Temporal & Positional Awareness:**
  * **Time:** GPS PPS (`/dev/pps0`) via `chrony`. Pre-flight FAILS if offset > 0.5s.
  * **Location:** Live GPS data writes strictly to RAM (`/dev/shm/discovery.json`) to prevent SD wear.

## 🗂️ 4. Data Dictionary Rules
* **Science First:** No target is integrated without a matching sequence in `data/sequences/comp_stars/`.
* **Path Awareness:** All logic must resolve paths dynamically via `config.toml` (NAS vs. Lifeboat).
