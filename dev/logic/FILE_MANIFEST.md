# 🔭 SeeVar: File Manifest

> **System State**: Diamond Revision (Sovereign)
> **Scope**: Tracked source, config templates, service units, tests, and logic docs only. Runtime data and generated science products are excluded.

| Path | Version | Objective |
| :--- | :--- | :--- |
| bootstrap.sh | 1.6.0 | Install SeeVar on fresh Debian Bookworm (Raspberry Pi). Creates Python .venv, installs dependencies, runs interactive... |
| catalogs/campaign_targets.json | JSON | Structured configuration or seed data used by SeeVar. |
| config.toml.example | 2.0.0 | Template for SeeVar configuration. bootstrap.sh copies this to config.toml and patches it interactively. You can also... |
| CONTRIBUTING.md | N/A | Repository contribution rules and expectations for SeeVar changes. |
| core/dashboard/dashboard.py | 5.0.1 | Fleet-ready dashboard with Alpaca REST telemetry on port 32323 and nightly-plan funnel visibility. |
| core/dashboard/templates/index.html | N/A | S30-PRO Federation Dashboard |
| core/fed-mission | 2.6.1 | Full cycle automation including Postflight FITS Verification. |
| core/federation-dashboard.service | N/A | S30-PRO Federation Dashboard (External Link) |
| core/flight/bias_library.py | 1.0.0 | Capture short dark-filter frames as reusable master bias assets. |
| core/flight/camera_control.py | 3.0.0 | Hardware status interface for ZWO S30-Pro via Alpaca REST. Replaces TCP port 4700 health check with Alpaca management... |
| core/flight/dark_library.py | 2.2.0 | Post-session dark frame acquisition via Alpaca REST. Captures downloadable dark frames, combines them into a master d... |
| core/flight/exposure_planner.py | 1.2.0 | Estimate safe science exposure parameters for a target using brightness, sky quality, and flight constraints. its mag... |
| core/flight/field_rotation.py | 1.2.0 | Field rotation for Alt-Az telescopes (ZWO Seestar S30/S50). Now includes accurate integrated smear via numerical inte... |
| core/flight/flat_library.py | 1.0.0 | Capture normalized master flat assets for a scope/filter pair and mark whether they are ready for science use. |
| core/flight/fsm.py | 1.3.0 | Finite State Machine governing A1-A12 target execution and failure handling for Sovereign flight operations, with liv... |
| core/flight/mission_chronicle.py | 4.2.0 | Orchestrates the Preflight Funnel (Janitor -> Librarian -> Auditor -> Planner). |
| core/flight/neutralizer.py | 2.1.0 | Hardware reset via Alpaca REST — parks telescope and verifies idle state before handing control to the pilot. |
| core/flight/orchestrator.py | 1.8.3 | Autonomous night daemon consuming tonights_plan.json as the canonical mission order, logging A1-A12, executing target... |
| core/flight/pilot.py | 3.1.0 | Sovereign Alpaca acquisition engine for the Seestar S30-Pro, owning A4-A11 including slew, pointing verification, cor... |
| core/flight/sim_runner.py | 1.0.0 | Execute a full realtime nightly simulation against tonights_plan.json with structured CLI output and live system_stat... |
| core/flight/vault_manager.py | 1.4.1 | Secure metadata access with actual bi-directional tomli_w syncing. |
| core/hardware/fleet_mapper.py | 2.0.0 | Read [[seestars]] from config.toml, load hardware constants from core/hardware/models/<model>.json, and produce data/... |
| core/hardware/fleet_monitor.py | 1.1.0 | Periodic generic fleet status logger for configured scopes, emitting stable per-scope operational telemetry into both... |
| core/hardware/hardware_loader.py | 1.2.0 | Auto-detect Seestar hardware via Alpaca UDP discovery beacon (port 32227), fingerprint sensor via HTTP Alpaca API, lo... |
| core/hardware/ladies.txt | N/A | Human-readable naming notes for configured Seestar telescopes. |
| core/hardware/live_battery.py | 1.3.0 | Poll live Seestar battery and charger state from JSON-RPC pi_get_info on port 4701, while preserving the older poll_b... |
| core/hardware/live_scope_status.py | 1.0.2 | Generic live scope-status polling helper that fuses Alpaca telescope/camera state with optional live battery telemetr... |
| core/hardware/models/S30-Pro.json | JSON | Structured configuration or seed data used by SeeVar. |
| core/hardware/models/S30.json | JSON | Structured configuration or seed data used by SeeVar. |
| core/hardware/models/S50.json | JSON | Structured configuration or seed data used by SeeVar. |
| core/ledger_manager.py | 1.6.1 | The High-Authority Mission Brain. Manages target cadence and observation history. Filters tonights_plan.json by caden... |
| core/postflight/aavso_reporter.py | 1.5.0 | Generate and validate AAVSO Extended Format reports in data/reports/ using SeeVar TG photometry defaults for OSC Baye... |
| core/postflight/accountant.py | 2.5.0 | Sweep local_buffer, build aligned stack-first science products from dark-calibrated frames, require real solved WCS,... |
| core/postflight/aperture_photometry.py | 1.0.0 | Reusable aperture-photometry helpers for SeeVar postflight QA and science measurement. |
| core/postflight/bayer_photometry.py | 2.5.0 | Bayer-channel aperture photometry engine for the IMX585 using real solved WCS products for source placement, with hea... |
| core/postflight/calibration_assets.py | 1.0.0 | Shared calibration asset registry and requirement summaries for dark, bias, and flat frames. |
| core/postflight/calibration_engine.py | 2.2.0 | Orchestrate differential photometry for a single FITS frame using a real solved WCS, Gaia/AAVSO-style comparison star... |
| core/postflight/dark_calibrator.py | 1.1.0 | Match and apply master dark calibration to science FITS frames before photometry. |
| core/postflight/data/qc_report.json | JSON | Structured configuration or seed data used by SeeVar. |
| core/postflight/deferred_dark_runner.py | 1.1.0 | Reacquire queued dark sequences only when the current camera temperature is thermally compatible with the queued scie... |
| core/postflight/gaia_resolver.py | 1.0.0 | Resolve Gaia DR3 comparison stars for a given field. Queries VizieR once per field, caches results to data/gaia_cache... |
| core/postflight/librarian.py | 2.2.1 | Securely harvest binary FITS to RAID1; prepare for NAS archival using dynamic paths. |
| core/postflight/master_analyst.py | 2.1.0 | High-level plate-solving coordinator executing astrometry.net's solve-field and returning real WCS products for postf... |
| core/postflight/pastinakel_math.py | 1.1.2 | Logic for saturation detection and dynamic aperture scaling. |
| core/postflight/post_to_pre_feedback.py | 1.2.2 | Updates the master targets.json with successful observation dates extracted from QC reports. |
| core/postflight/psf_models.py | 1.0.1 | PSF fitting for stellar profiles on IMX585 Bayer frames. Provides FWHM estimation feeding dynamic aperture and SNR ca... |
| core/preflight/aavso_fetcher.py | 1.6.8 | Haul AAVSO targets with nested dictionary support and strict error-message reporting. |
| core/preflight/audit.py | 1.4.0 | Enforces scientific cadence (1/20th rule) by properly parsing ledger dictionaries. |
| core/preflight/chart_fetcher.py | 1.4.2 | Step 2 - Fetch AAVSO VSP comparison star sequences. FOV fixed at 180' (VSP maglimit 15 requires FOV <= 180'). The S30... |
| core/preflight/disk_monitor.py | 1.1.2 | Verifies storage availability. Respects location context: NAS is only audited when on the Home Grid. |
| core/preflight/disk_usage_monitor.py | 1.1.1 | Monitor S30 internal storage via SMB mount and update system state with Go/No-Go veto. |
| core/preflight/fog_monitor.py | 1.0.1 | Infrared sky-clarity monitor using MLX90614 to prevent imaging in fog. Acts as a safety gate for photometry. |
| core/preflight/gps.py | 1.5.1 | Bi-directional GPS provider with lazy initialization. Reads from RAM status and actively syncs to config.toml via Vau... |
| core/preflight/hardware_audit.py | 3.0.0 | Alpaca REST hardware audit — reads telescope and camera state via port 32323. Exports hardware_telemetry.json for das... |
| core/preflight/horizon.py | 2.1.1 | Veto and score targets based on local obstructions using Az/Alt mapping. |
| core/preflight/horizon_scanner_v2.py | 2.0.7 | Rooftop-aware daytime horizon scanner using burst-median wide-camera frames and vectorized skyline detection for balc... |
| core/preflight/horizon_stellarium_export.py | 1.1.0 | Export SeeVar horizon_mask.json into a Stellarium-ready polygonal landscape zip containing horizon.txt, landscape.ini... |
| core/preflight/horizon_stellarium_panorama.py | 1.0.0 | Build a spherical Stellarium landscape zip from horizon scanner v2 frame captures. This is a visual panorama package,... |
| core/preflight/ledger_manager.py | 2.3.1 | Applies cadence history to the canonical nightly plan while preserving nightly-planner metadata and contract. |
| core/preflight/librarian.py | 4.3.0 | The Single Source of Truth. Parses raw AAVSO haul, checks for VSP charts, and writes the Federation Catalog. |
| core/preflight/nightly_planner.py | 2.7.7 | Builds the canonical nightly plan in data/tonights_plan.json using astronomical dark, local horizon clearance, and Al... |
| core/preflight/panorama_calibration.py | 1.1.0 | Shared compass calibration helpers for panorama capture and Stellarium panorama layout. |
| core/preflight/preflight_checklist.py | 2.0.0 | Sovereign preflight gate — verifies hardware is alive and at zero-state before flight. Uses camera_control.CameraCont... |
| core/preflight/schedule_compiler.py | 1.1.1 | Translates canonical tonights_plan.json into a native SSC JSON payload while preserving planner ordering and metadata. |
| core/preflight/state_flusher.py | 1.1.1 | Preflight utility to flush stale system state and reset the dashboard to IDLE before a new flight. |
| core/preflight/stellarium_panorama_capture.py | 1.6.0 | Capture a real visual panorama while slewing around the horizon. Supports either direct RTSP snapshots or pulling fre... |
| core/preflight/stellarium_panorama_from_media.py | 1.4.0 | Build a spherical Stellarium panorama package from normal RGB photos or a video capture. This is the visual path and... |
| core/preflight/target_evaluator.py | 1.2.1 | Audits canonical nightly artifacts for freshness and quantity to update dashboard UI with funnel-aware counts. |
| core/preflight/vsx_catalog.py | 2.4.0 | Fetch magnitude ranges from AAVSO VSX for all campaign targets, cache them safely, and serve target magnitudes effici... |
| core/preflight/weather.py | 1.8.0 | Tri-source weather consensus daemon providing dark-window timing and hard-abort imaging veto state for preflight and... |
| core/seeing-scraper.service | N/A | Meteoblue Seeing Scraper |
| core/seeing-scraper.timer | N/A | Run Seeing Scraper Hourly |
| core/seestar_env_lock.service | N/A | Federation Environment Guardian (v1.5.5 - Armored Stake) |
| core/utils/aavso_client.py | 1.2.2 | Low-level API client for authenticated AAVSO VSX and WebObs data retrieval. Returns JSON-ready dictionaries with #obj... |
| core/utils/astro.py | 1.2.1 | Core library for RA/Dec parsing, sidereal time, and coordinate math. |
| core/utils/coordinate_converter.py | 1.2.2 | Ensures data validity by converting sexagesimal AAVSO coordinates into decimal degrees, appending #objective to JSON... |
| core/utils/env_loader.py | 1.1.0 | Single source of truth for SeeVar environment paths and TOML configuration loading. |
| core/utils/gps_monitor.py | 1.5.0 | Continuous native GPSD socket monitor with full resource safety, atomic writes, SIGTERM handling, Null Island guard,... |
| core/utils/notifier.py | 1.4.0 | Outbound alert management via Telegram and system bell. Single authoritative notifier for all SeeVar pipeline compone... |
| core/utils/observer_math.py | 1.0.3 | Mathematical utilities for observational astronomy, including Maidenhead grid calculations dynamically tested against... |
| core/utils/platesolve_analyst.py | 1.3.0 | Diagnostic reporter for plate-solving success rates and pointing error, using astrometry.net with optional header hin... |
| dev/CONTRIBUTING.md | 1.3.0 | Defines the technical standards, workflow rules, and header requirements for SeeVar contributors. |
| dev/logic/AAVSO_LOGIC.MD | 2.0.0 (Praw) | Rules for scientific targeting, cadence, photometry |
| dev/logic/AI_CONTEXT.MD | 2.0.0 | The absolute architectural law, environment standards, and logic constraints for AI-assisted development of the SeeVa... |
| dev/logic/ALPACA_BRIDGE.MD | 2.0.0 | Canonical doctrine for controlling Seestar telescopes through the official ZWO ASCOM Alpaca REST API. |
| dev/logic/API_PROTOCOL.MD | 4.1.0 | Current protocol doctrine for SeeVar hardware control and acquisition. |
| dev/logic/ARCHITECTURE_OVERVIEW.MD | 4.0.0 (Alpaca Sovereign) | High-precision AAVSO photometry via direct hardware control. |
| dev/logic/BAA_LOGIC.MD | 1.0.0 | Rules for SeeVar export to BAA VSSDB formats, including the |
| dev/logic/CADENCE.MD | 2.0.0 (Praw) | Ensure science-grade sampling of variable stars by |
| dev/logic/COMMUNICATION.MD | 3.0.0 | Historical protocol record for retired JSON-RPC control paths and their Alpaca replacements. |
| dev/logic/CORE.MD | 3.0.0 (Alpaca) | Defines the chain of command and guiding principles for |
| dev/logic/DATA_DICTIONARY.MD | 2.0.0 (Praw) | Strict schema and ownership rules for every file in the |
| dev/logic/DATA_MAPPING.MD | 2.0.0 (Praw) | Concise map of data flow from AAVSO fetch to FITS custody. |
| dev/logic/DATALOGIC.MD | N/A | Defines the role, origin, and transformation logic for all JSON data structures within the RAID1 repository. |
| dev/logic/DISCOVERY_PROTOCOL.MD | 2.0.0 (Alpaca) | Network discovery and hardware identification for Seestar telescopes. |
| dev/logic/FLIGHT.MD | 3.0.0 | Operational doctrine for executing target acquisition during the science flight phase. |
| dev/logic/PHOTOMETRICS.MD | 1.9.0 | Scientific standards and roadmap for SeeVar differential photometry. |
| dev/logic/PICKERING_PROTOCOL.MD | 2026.03.12 | Historical and cultural reference explaining SeeVar naming and observatory design inspiration. |
| dev/logic/POSTFLIGHT.MD | 1.9.0 | Define the sovereign postflight science chain from raw FITS custody to ledger verdict and AAVSO-ready output. |
| dev/logic/PREFLIGHT.MD | 2.0.0 | Operational doctrine for preflight data preparation, planning, and go/no-go gates. |
| dev/logic/README.MD | 1.9.0 | Definitive entry point and table of contents for the architectural law, scientific standards, and roadmap governing t... |
| dev/logic/SEEVAR_DICT.PSV | 2026.03 (annotated) | Pipe-separated data dictionary for SeeVar runtime files, fields, owners, and lifecycle notes. |
| dev/logic/SEEVAR_SKILL/SKILL.md | N/A | Codex skill instructions for SeeVar-aware development assistance. |
| dev/logic/SIMULATORLOGIC.MD | 2.0.0 (Sovereign A1-A12) | Outlines networking and state logic required to synchronize the SeeStar ALP Bridge with the Raspberry Pi Simulator en... |
| dev/logic/STATE_MACHINE.MD | 5.0.0 (Sovereign A1-A12) | Deterministic hardware transitions for AAVSO acquisition |
| dev/logic/WORKFLOW.MD | 1.9.0 | Describe the full operational flow of SeeVar from preflight through flight, postflight, and parked state using the cu... |
| dev/test_calibration_assets.py | 1.0.0 | Smoke-test calibration asset requirement summaries without FITS dependencies. |
| dev/test_dark_postflight.py | 1.0.1 | Smoke-test the dark calibration + accountant closure path without hardware. |
| dev/test_postflight_low_snr.py | 1.0.0 | Verify postflight rejects a dark-calibrated frame when photometric SNR is too low. |
| dev/test_postflight_no_dark.py | 1.0.0 | Verify postflight fails honestly when no matching master dark exists. |
| dev/test_synthetic_imx585_field.py | 1.0.0 | End-to-end synthetic IMX585-style postflight rehearsal. |
| dev/test_tcrb_s30_s50_field.py | 1.0.0 | Rehearse postflight on T CrB-inspired synthetic S30 and S50 fields. |
| dev/tools/aavso_reporter_test.py | 1.0.0 | Generate a small dummy AAVSO Extended Format report for WebObs preview testing, or the BAA-modified AAVSO Extended va... |
| dev/tools/clean_postflight_remnants.py | N/A | Dry-run-first cleanup tool for transient astrometry solver products in SeeVar data directories. |
| dev/tools/horizon_audit.py | 1.0.1 | Audit tonights_plan.json against the real camera-scanned horizon mask. Shows how many targets are observable tonight... |
| dev/tools/install_horizon_mask.py | N/A | Install a candidate horizon_mask.json into the SeeVar runtime data dir with a timestamped backup of any existing mask. |
| dev/tools/package_sector_panorama.py | N/A | Package a pre-stitched panorama sector plus a SeeVar horizon mask into the conservative Stellarium spherical landscap... |
| dev/tools/rpc_client.py | 2.0.1 | Interactive JSON-RPC client for Seestar port 4700 using pre-built sovereign payloads. |
| dev/tools/session_triage.py | N/A | Summarise the last SeeVar observing session from logs, ledger, plan, and data buffers without touching telescope state. |
| dev/utils/comp_purger.py | 1.1.1 | Prunes orphaned comparison star charts in the SeeVar catalog. |
| dev/utils/generate_manifest.py | 1.6.2 | Generate FILE_MANIFEST.md for SeeVar and mirror it to NAS while excluding transient runtime data, generated science p... |
| dev/utils/harvest_manager.py | 1.3.1 | SeeVar Harvester - Supports simulation data (.fit) and real FITS. |
| dev/utils/mount_guard.py | 1.1.1 | Check if the specified target is mounted and the required data directory exists. |
| dev/utils/nas_backup.sh | 1.3.6 | Backup SeeVar code and logic to dynamically defined NAS targets. SMB/CIFS-safe: avoids symlinks and permission sync e... |
| docs/PRESENTATION.md | N/A | Presentation notes and visual walkthrough material for SeeVar. |
| INSTALL.md | 1.3.1 | Installation guide for deploying SeeVar onto supported systems. |
| LICENSE | N/A | Project license terms. |
| README.md | N/A | Primary project overview and operator entry point for SeeVar. |
| requirements.txt | 2026.04.06 | SeeVar runtime dependencies — delta on top of seestar_alp. Install after running the seestar_alp bootstrap. Requires... |
| ROADMAP.md | 1.9.0 (Snotolf) | Tracks the architectural journey and future versioning milestones of the Seestar Federation, mapped to the characters... |
| scripts/toml_set.py | 1.1.0 | Safely update a TOML file by dotted key path for bootstrap and upgrade workflows. |
| scripts/update_seevar.sh | 1.1.0 | Compatibility wrapper around the repo-root upgrade helper for existing local checkouts. |
| systemd/seeing-scraper.service | N/A | Meteoblue Seeing Scraper |
| systemd/seeing-scraper.timer | N/A | Run Seeing Scraper Hourly |
| systemd/seestar_env_lock.service | N/A | Federation Environment Guardian |
| systemd/seevar-dashboard.service | N/A | SeeVar Dashboard |
| systemd/seevar-gps.service | N/A | SeeVar Continuous GPS Monitor |
| systemd/seevar-orchestrator.service | N/A | SeeVar Science Orchestrator |
| systemd/seevar-orchestrator@.service | N/A | SeeVar Science Orchestrator (%i) |
| systemd/seevar-planner.service | N/A | SeeVar Nightly Planner |
| systemd/seevar-planner.timer | N/A | Run SeeVar Nightly Planner Daily |
| systemd/seevar-telescope.service | N/A | SeeVar Fleet Monitor |
| systemd/seevar-weather.service | N/A | SeeVar Weather Sentinel |
| UPGRADE.MD | N/A | Upgrade procedure and compatibility notes for existing SeeVar installations. |
| upgrade.sh | 1.0.0 | Upgrade an existing SeeVar checkout in-place without overwriting local config.toml. |
