# AI Project Context - Sovereign SeeVar Federation

> **Objective:** The absolute architectural law, environment standards, and logic constraints for AI-assisted development of the SeeVar Federation.
> **Version:** 1.5.3
> **Last verified against codebase:** 2026-03-13

## 🛑 1. The Prime Directives (Rules of Engagement)
1. **No "Vibe-Coding":** All logic must map directly to the defined schemas and protocols in `~/seevar/logic/`. No guessing API endpoints or hardware states.
2. **Infrastructure as Code (IaC):** Python 3.13.5 environment is strictly locked via `bootstrap.sh` and `requirements.txt`.
3. **The "Garmt" Header Standard:** Every script must contain a PEP 257 docstring stating: Filename, Version, and a single-sentence Objective.
4. **The Sovereignty Principle:** All hardware control must bypass consumer UI via direct TCP port 4700 (JSON-RPC) to ensure deterministic RAW data capture.
5. **Guiding Principle:** "Do not live in the moment. Plan for the astronomical night."
6. **Deploy via Heredoc:** All new or modified files are deployed to the Pi via bash heredoc scripts. No manual editing on the Pi. Scripts are idempotent where possible.

## 🏗️ 2. The Master Workflow (The Funnel)
The application stack is a strict, linear 3-Phase State Machine.
* **Phase 1: Pre-Flight (The Funnel)**
  * **Harvest & Refine:** `targets.json` (Master) is filtered by `nightly_planner.py` to generate `tonights_plan.json`.
  * **Cadence Logic:** Target priority is calculated using the **1/20th Period Rule** (Miras 5-10d, SRs 3-5d).
  * **AAVSO Throttling:** API calls must respect a strict **31.4s (Pi-Minute) delay**. Pi IP was hard-blocked by AAVSO at 3.14s on 2026-03-13. Do not reduce below 31.4s.
  * **Exposure Planning:** Per-target exposure via `exposure_planner.plan_exposure(get_target_mag(name))`. No hardcoded exposure times.
  * **Horizon Veto:** All targets gated against `data/horizon_mask.json` — 360° per-degree profile derived from site photos. West (240°–300°) blocked by own building.
* **Phase 2: The Handover (The Gatekeeper)**
  * **System Audit:** 5-minute loop validating weather, disk vitals, and plan integrity. Passes control (GREEN) or scrubs mission (RED).
* **Phase 3: Flight (The Acquisition Loop)**
  * **Control Path:** Direct TCP port 4700 (JSON-RPC) for all science acquisition.
  * **Action:** Orchestrator commands slew, plate solve, and expose. FITS stream to Active Storage Path.

## 📡 3. Hardware & Network Logic
* **Seestar S30-Pro:**
  * **Science TCP:** Port 4700 (JSON-RPC), port 4801 (binary frame stream)
  * **RTSP stream:** `rtsp://192.168.178.55:4554/stream`
  * **Fixed IP:** 192.168.178.55 (DHCP reservation by MAC)
  * **IMX585 sensor:** GRBG Bayer, 3840×2160, 16-bit unsigned (>u2), 3.75"/px
  * **Science channel:** G → AAVSO filter TG
  * **Saturation ceiling:** 60000 ADU
* **Veto Logic (Sovereignty Limits):**
  * **Battery:** Mandatory Park at **< 10%**
  * **Thermal:** Mandatory Park at **> 55.0°C**
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
  * New fields: `last_mag, last_err, last_snr, last_filter, last_comps,`
    `last_zp, last_zp_std, last_peak_adu, last_obs_utc`
* **Next improvement:** Sigma clipping on ZP ensemble (2.5σ iterative rejection)

## 🗂️ 5. Data Dictionary Rules
* **Science First:** No target is integrated without a matching sequence in `data/sequences/comp_stars/`.
* **Path Awareness:** All logic resolves paths via `PROJECT_ROOT` from `__file__`. Config at `~/seevar/config.toml`.
* **VSX Cache:** `data/vsx_catalog.json` — 723 targets, incremental save, caller=REDA on all requests.
* **Horizon Mask:** `data/horizon_mask.json` — 360° profile, SE–S corridor is prime science window (min_alt 12°).
* **Gaia Cache:** `data/gaia_cache/` — per-field JSON, keyed by ra/dec rounded to 0.1°.
