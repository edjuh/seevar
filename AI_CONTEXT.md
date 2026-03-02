# AI Project Context - S30-PRO Federation (Rommeldam Edition)

> **Objective:** The absolute architectural law, environment standards, and logic constraints for AI-assisted development of the Seestar Federation.
> **Version:** 1.4.17 (Infrastructure Baseline)

## 🛑 1. The Prime Directives (Rules of Engagement)
1. **No "Vibe-Coding":** All logic must map directly to the defined schemas and protocols in `~/seestar_organizer/logic/`. No guessing API endpoints or hardware states.
2. **Infrastructure as Code (IaC):** Python 3.13.5 environment is strictly locked via `bootstrap.sh` and `requirements.txt`.
3. **The "Garmt" Header Standard:** Every script must contain a PEP 257 docstring stating: Filename, Version, and a single-sentence Objective.
4. **Guiding Principle:** "Do not live in the moment. Plan for the astronomical night."

## 🏗️ 2. The Master Workflow (The Funnel)
The application stack is a strict, linear 3-Phase State Machine.
* **Phase 1: Pre-Flight (The Funnel)**
  * **Harvest & Refine:** `targets.json` (Master) is filtered by `nightly_planner.py` to generate `tonights_plan.json`.
  * **AAVSO Throttling:** API calls for sequences must respect a strict **188.4s (Pi-Minute) delay** to prevent IP bans.
* **Phase 2: The Handover (The Gatekeeper)**
  * **System Audit:** 5-minute loop validating weather, disk vitals, and plan integrity. Passes control (GREEN) or scrubs mission (RED).
* **Phase 3: Flight (The Acquisition Loop)**
  * **Execution:** Orchestrator reads `tonights_plan.json`.
  * **Action:** Commands slew, plate solve, track, and expose. FITS stream is routed to the Active Storage Path.

## 📡 3. Hardware & Network Logic
* **Discovery & AP Fallback:**
  * **Home Profile:** `192.168.178.0/24` subnet detected -> Mount NAS (`/mnt/astronas/`).
  * **Field Profile:** Fallback to `lifeboat_dir` -> `nmcli` hosts "Seestar_Sentry_AP" -> Dashboard served at `10.42.0.1`.
* **Alpaca Bridge (The ET Protocol):**
  * **Target IP:** Fixed alignment at `192.168.178.55` (Port 5555).
  * **Communication:** Strict `PUT` method for Actions. `ClientID` and `ClientTransactionID` are mandatory.
  * **Sequence:** `CONNECT` -> `SET LAT` -> `SET LON` -> `VERIFY LST`.
* **Temporal & Positional Awareness:**
  * **Time:** GPS PPS (`/dev/pps0`) via `chrony`. Pre-flight FAILS if offset > 0.5s.
  * **Location:** Live GPS data writes strictly to RAM (`/dev/shm/discovery.json`) to prevent SD wear. Physical writes to `config.toml` only happen upon manual "Confirm Site".
* **Storage Sentinel:**
  * Continuous audit of `lifeboat_dir`. If disk usage **> 85%**, FITS acquisition is halted; only metadata generation is permitted.

## 🗂️ 4. Data Dictionary Rules
* **Science First:** No target is integrated without a matching sequence in `data/sequences/comp_stars/`.
* **Path Awareness:** All logic must resolve paths dynamically via `config.toml` (NAS vs. Lifeboat).
