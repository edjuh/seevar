# AI Project Context - SeeVar Federation

> **Objective:** The absolute architectural law, environment standards, and logic constraints for AI-assisted development of the SeeVar Federation.
> **Version:** 2.0.0
> **Last verified against codebase:** 2026-03-30

## 🛑 1. The Prime Directives (Rules of Engagement)
1. **No "Vibe-Coding":** All logic must map directly to the defined schemas and protocols in `~/seevar/dev/logic/`. No guessing API endpoints or hardware states.
2. **Infrastructure as Code (IaC):** Python 3.13.5 environment is strictly locked via `bootstrap.sh` and `requirements.txt`.
3. **The "Garmt" Header Standard:** Every script must contain a PEP 257 docstring stating: Filename, Version, and a single-sentence Objective.
4. **The Alpaca Principle:** All hardware control uses the official ZWO ASCOM Alpaca REST API on port 32323. No proprietary TCP. No phone app. No session master lock.
5. **Guiding Principle:** "Do not live in the moment. Plan for the astronomical night."
6. **Deploy via Heredoc:** All new or modified files are deployed to the Pi via bash heredoc scripts. No manual editing on the Pi. Scripts are idempotent where possible.

## 🏗️ 2. The Master Workflow (The Funnel)
The application stack is a strict, linear 3-Phase State Machine.
* **Phase 1: Pre-Flight (The Funnel)**
  * **Harvest & Refine:** `targets.json` (Master) is filtered by `nightly_planner.py` to generate `tonights_plan.json`.
  * **Cadence Logic:** Target priority is calculated using the **1/20th Period Rule** (Miras 5-10d, SRs 3-5d).
  * **AAVSO Throttling:** API calls must respect a strict **188.4s (Pi-Minute) delay**. Do not reduce.
  * **Exposure Planning:** Per-target exposure via `exposure_planner.plan_exposure(get_target_mag(name))`. No hardcoded exposure times.
  * **Horizon Veto:** All targets gated against `data/horizon_mask.json` — 360° per-degree profile derived from site photos. West (240°–300°) blocked by own building.
* **Phase 2: The Handover (The Gatekeeper)**
  * **System Audit:** 5-minute loop validating weather, disk vitals, and plan integrity. Passes control (GREEN) or scrubs mission (RED).
* **Phase 3: Flight (The Acquisition Loop)**
  * **Control Path:** Alpaca REST on port 32323 — telescope, camera, filter wheel, focuser, dew heater. All confirmed working 2026-03-30.
  * **Action:** Orchestrator commands slew, expose, download. FITS to Active Storage Path.

## 📡 3. Hardware & Network Logic
* **Seestar S30-Pro (Wilhelmina):**
  * **Alpaca REST:** Port 32323, v1.2.0-3 — 7 devices exposed
  * **Telescope #0:** Slew, track, park, unpark, pulse guide
  * **Camera #0 (Telephoto):** IMX585, 3840×2160, 2.9µm pixels, gain 0-600
  * **Camera #1 (Wide Angle):** IMX586, 3840×2160 — context/finder
  * **FilterWheel #0:** Dark (pos 0), IR (pos 1), LP (pos 2)
  * **Focuser #0/1:** Telephoto and wide angle, absolute position
  * **Switch #0:** Dew heater control
  * **Event stream:** Port 4700 retained for battery/charger telemetry via WilhelminaMonitor
  * **IP:** Read from `config.toml [[seestars]] ip` — never hardcoded
  * **IMX585 sensor:** GRBG Bayer (offset 1,0), 3840×2160, 16-bit, 2.9µm, 3.74"/px
  * **Optics:** 160mm f/5.3, 30mm aperture, quadruplet APO with ED element
  * **Science channel:** G → AAVSO filter TG
  * **Saturation ceiling:** 60000 ADU
* **Veto Logic:**
  * **Battery:** Mandatory Park at **< 10%** (from WilhelminaMonitor event stream)
  * **Thermal:** Mandatory Park at **> 55.0°C** (from Alpaca CCD temperature)
  * **Leveling:** Mandatory Pre-flight FAIL at **> 1.5° (Science-grade cutoff)**
* **Temporal & Positional Awareness:**
  * **Time:** GPS PPS (`/dev/pps0`) via `chrony`. Pre-flight FAILS if offset > 0.5s.
  * **Location:** Live GPS data writes strictly to RAM (`/dev/shm/env_status.json`) to prevent SD wear.

## 🔬 4. Photometry Stack
See `logic/PHOTOMETRICS.MD` for full rationale and roadmap.

* **Engine:** `core/postflight/bayer_photometry.py` v2.0.0
  * Aperture: dynamic — 1.7 × Moffat PSF FWHM (`psf_models.fit_psf()`)
  * ZP ensemble: **SNR²-weighted mean** of all valid comp stars
  * Comp minimum SNR: 5.0
  * All comp stars measured at same aperture radius as target
* **Calibration:** `core/postflight/calibration_engine.py` v2.0.0
  * Comp stars: Gaia DR3 via `gaia_resolver.py` (cached per field in `data/gaia_cache/`)
  * Returns: `{mag, err, snr, zp, zp_std, n_comps, filter, peak_adu}`
* **Ledger:** `data/ledger.json` schema **v2026.2**
* **Next improvement:** Sigma clipping on ZP ensemble (2.5σ iterative rejection)

## 🗂️ 5. Data Dictionary Rules
* **Science First:** No target is integrated without a matching sequence in `data/sequences/comp_stars/`.
* **Path Awareness:** All logic resolves paths via `PROJECT_ROOT` from `__file__`. Config at `~/seevar/config.toml`.
* **VSX Cache:** `data/vsx_catalog.json` — 723 targets, incremental save, caller=REDA on all requests.
* **Horizon Mask:** `data/horizon_mask.json` — 360° profile, SE–S corridor is prime science window (min_alt 12°).
* **Gaia Cache:** `data/gaia_cache/` — per-field JSON, keyed by ra/dec rounded to 0.1°.
