# 🔭 SeeVar: File Manifest

> **System State**: Diamond Revision (Sovereign)

| Path | Version | Objective |
| :--- | :--- | :--- |
| catalogs/campaign_targets.json | JSON | Data/Configuration file. |
| catalogs/de421.bsp | N/A | No objective defined. |
| catalogs/federation_catalog.json | JSON | Data/Configuration file. |
| config.toml | N/A | No objective defined. |
| core/dashboard/dashboard.py | 5.0.1 | Fleet-ready dashboard with Alpaca REST telemetry on port 32323 and nightly-plan funnel visibility. |
| core/dashboard/templates/index.html | N/A | No objective defined. |
| core/fed-mission | N/A | No objective defined. |
| core/federation-dashboard.service | N/A | No objective defined. |
| core/flight/camera_control.py | 3.0.0 | Hardware status interface for ZWO S30-Pro via Alpaca REST. |
| core/flight/dark_library.py | 2.0.0 | Post-session dark frame acquisition via Alpaca REST. |
| core/flight/exposure_planner.py | 1.2.0 | Estimate safe science exposure parameters for a target using brightness, sky quality, and flight constraints. |
| core/flight/field_rotation.py | 1.0.0 | Calculate Alt/Az field rotation limits and derive maximum safe exposure times before rotation blur becomes unacceptable. |
| core/flight/fsm.py | 1.1.0 | The Finite State Machine governing S30-PRO Sovereign Operations. |
| core/flight/mission_chronicle.py | 4.2.0 | Orchestrates the Preflight Funnel (Janitor -> Librarian -> Auditor -> Planner). |
| core/flight/neutralizer.py | 2.0.0 | Hardware reset via Alpaca REST — parks telescope and verifies |
| core/flight/orchestrator.py | 1.7.3 | Autonomous night daemon consuming tonights_plan.json as the canonical mission order and executing the A1-A12 flight c... |
| core/flight/pilot.py | 3.0.0 | Sovereign Alpaca acquisition engine for the Seestar S30-Pro, owning session init, slew, exposure, image download, and... |
| core/flight/sim_runner.py | 1.0.0 | Execute a full realtime nightly simulation against tonights_plan.json |
| core/flight/vault_manager.py | 1.4.1 | Secure metadata access with actual bi-directional tomli_w syncing. |
| core/hardware/fleet_mapper.py | N/A | No objective defined. |
| core/hardware/hardware_loader.py | 1.2.0 | Auto-detect Seestar hardware via Alpaca UDP discovery beacon (port 32227), fingerprint sensor via HTTP Alpaca API, lo... |
| core/hardware/ladies.txt | N/A | No objective defined. |
| core/hardware/models/S30-Pro.json | JSON | Data/Configuration file. |
| core/hardware/models/S30.json | JSON | Data/Configuration file. |
| core/hardware/models/S50.json | JSON | Data/Configuration file. |
| core/hardware/ssh_monitor.py | 1.1.0 | Establish an SSH connection to the Seestar SOC (ARM) to stream real-time logs for reverse-engineering port 4700 Sover... |
| core/ledger_manager.py | 1.6.1 | The High-Authority Mission Brain. Manages target cadence and observation history. Filters tonights_plan.json by caden... |
| core/postflight/aavso_reporter.py | 1.2.1 | Generate AAVSO Extended Format reports in the dedicated data/reports/ |
| core/postflight/accountant.py | 2.0.1 | Sweeps local_buffer, runs full Bayer differential photometry via calibration_engine, and stamps complete results into... |
| core/postflight/bayer_photometry.py | 2.0.1 | Bayer-channel aperture photometry engine for the IMX585 (GRBG pattern). Extracted from pilot.py and elevated to a sta... |
| core/postflight/calibration_engine.py | 2.0.0 | Orchestrates differential photometry for a single FITS frame. |
| core/postflight/data/qc_report.json | JSON | Data/Configuration file. |
| core/postflight/gaia_resolver.py | 1.0.0 | Resolve Gaia DR3 comparison stars for a given field. |
| core/postflight/librarian.py | 2.2.1 | Securely harvest binary FITS to RAID1; prepare for NAS archival using dynamic paths. |
| core/postflight/master_analyst.py | 2.0.1 | High-level plate-solving coordinator executing astrometry.net's solve-field. |
| core/postflight/pastinakel_math.py | 1.1.2 | Logic for saturation detection and dynamic aperture scaling. |
| core/postflight/post_to_pre_feedback.py | 1.2.2 | Updates the master targets.json with successful observation dates extracted from QC reports. |
| core/postflight/psf_models.py | 1.0.1 | PSF fitting for stellar profiles on IMX585 Bayer frames. Provides FWHM estimation feeding dynamic aperture and SNR ca... |
| core/preflight/aavso_fetcher.py | 1.6.8 | Haul AAVSO targets with nested dictionary support and strict error-message reporting. |
| core/preflight/audit.py | 1.4.0 | Enforces scientific cadence (1/20th rule) by properly parsing ledger dictionaries. |
| core/preflight/chart_fetcher.py | 1.4.2 | Step 2 - Fetch AAVSO VSP comparison star sequences. |
| core/preflight/disk_monitor.py | 1.1.2 | Verifies storage availability. Respects location context: NAS is only audited when on the Home Grid. |
| core/preflight/disk_usage_monitor.py | 1.1.1 | Monitor S30 internal storage via SMB mount and update system state with Go/No-Go veto. |
| core/preflight/fog_monitor.py | 1.0.1 | Infrared sky-clarity monitor using MLX90614 to prevent imaging in fog. Acts as a safety gate for photometry. |
| core/preflight/gps.py | 1.5.1 | Bi-directional GPS provider with lazy initialization. Reads from RAM status and actively syncs to config.toml via Vau... |
| core/preflight/hardware_audit.py | 3.0.0 | Alpaca REST hardware audit — reads telescope and camera state |
| core/preflight/horizon.py | 2.1.1 | Veto and score targets based on local obstructions using Az/Alt mapping. |
| core/preflight/horizon_scanner_v2.py | 2.0.7 | Rooftop-aware daytime horizon scanner using burst-median wide-camera frames and vectorized skyline detection. |
| core/preflight/horizon_stellarium_export.py | 1.1.0 | Exports horizon_mask.json into a Stellarium-ready polygonal landscape zip. |
| core/preflight/horizon_stellarium_panorama.py | 1.0.0 | Builds a spherical Stellarium panorama landscape zip from horizon scanner v2 frame captures. |
| core/preflight/stellarium_panorama_from_media.py | 1.2.0 | Builds a spherical Stellarium panorama package from normal RGB photos or a video capture, preferring azimuth-tagged layout for 360° capture sets. |
| core/preflight/stellarium_panorama_capture.py | 1.5.0 | Slews the Seestar around the horizon, auto-watches scenery captures on share storage, and defaults to finer 15° spacing with azimuth correction. |
| core/preflight/ledger_manager.py | 2.3.1 | Applies cadence history to the canonical nightly plan while preserving nightly-planner metadata and contract. |
| core/preflight/librarian.py | 4.3.0 | The Single Source of Truth. Parses raw AAVSO haul, checks for VSP charts, and writes the Federation Catalog. |
| core/preflight/nightly_planner.py | 2.7.7 | Builds the canonical nightly plan in data/tonights_plan.json using astronomical dark, local horizon clearance, and Al... |
| core/preflight/preflight_checklist.py | 2.0.0 | Sovereign preflight gate — verifies hardware is alive and at |
| core/preflight/schedule_compiler.py | 1.1.1 | Translates canonical tonights_plan.json into a native SSC JSON payload while preserving planner ordering and metadata. |
| core/preflight/state_flusher.py | 1.1.1 | Preflight utility to flush stale system state and reset the dashboard to IDLE before a new flight. |
| core/preflight/target_evaluator.py | 1.2.1 | Audits canonical nightly artifacts for freshness and quantity to update dashboard UI with funnel-aware counts. |
| core/preflight/vsx_catalog.py | 2.1.0 | Fetch magnitude ranges from AAVSO VSX for all campaign targets. |
| core/preflight/weather.py | 1.8.0 | Tri-source weather consensus daemon providing dark-window timing and hard-abort imaging veto state for preflight and... |
| core/seeing-scraper.service | N/A | No objective defined. |
| core/seeing-scraper.timer | N/A | No objective defined. |
| core/seestar_env_lock.service | N/A | No objective defined. |
| core/utils/aavso_client.py | 1.2.2 | Low-level API client for authenticated AAVSO VSX and WebObs data retrieval. Returns JSON-ready dictionaries with #obj... |
| core/utils/astro.py | 1.2.1 | Core library for RA/Dec parsing, sidereal time, and coordinate math. |
| core/utils/coordinate_converter.py | 1.2.2 | Ensures data validity by converting sexagesimal AAVSO coordinates into decimal degrees, appending #objective to JSON... |
| core/utils/env_loader.py | 1.1.0 | Single source of truth for SeeVar environment paths and TOML configuration loading. |
| core/utils/gps_monitor.py | 1.5.0 | Continuous native GPSD socket monitor with full resource safety, |
| core/utils/notifier.py | 1.4.0 | Outbound alert management via Telegram and system bell. |
| core/utils/observer_math.py | 1.0.3 | Mathematical utilities for observational astronomy, including Maidenhead grid calculations dynamically tested against... |
| core/utils/platesolve_analyst.py | 1.2.2 | Quantitative reporter for plate-solving success rates, performing blind solves to compare header coordinates against... |
| data/hardware_telemetry.json | JSON | Data/Configuration file. |
| data/horizon_mask.json | JSON | Data/Configuration file. |
| data/ledger.json | JSON | Data/Configuration file. |
| data/science_starlist.csv | N/A | No objective defined. |
| data/ssc_payload.json | JSON | Data/Configuration file. |
| data/system_state.json | JSON | Data/Configuration file. |
| data/tonights_plan.json | JSON | Data/Configuration file. |
| data/vsx_catalog.json | JSON | Data/Configuration file. |
| data/weather_state.json | JSON | Data/Configuration file. |
| dev/CONTRIBUTING.md | 1.2.0 (Garmt) | Defines the strict technical standards, workflow protocols, and "Garmt" purified header requirements for all project... |
| dev/logic/AAVSO_LOGIC.MD | 2.0.0 (Praw) | Rules for scientific targeting, cadence, photometry |
| dev/logic/BAA_LOGIC.MD | 1.0.0 | Rules for BAA VSS export formats and Seestar-specific output defaults |
| dev/logic/AI_CONTEXT.MD | 2.0.0 | The absolute architectural law, environment standards, and logic constraints for AI-assisted development of the SeeVa... |
| dev/logic/ALPACA_BRIDGE.MD | 2.0.0 | No objective defined. |
| dev/logic/API_PROTOCOL.MD | 4.0.0 (Haarlem / March 2026) | Definitive ZWO JSON-RPC method mapping for SeeVar. |
| dev/logic/ARCHITECTURE_OVERVIEW.MD | 4.0.0 (Alpaca Sovereign) | High-precision AAVSO photometry via direct hardware control. |
| dev/logic/CADENCE.MD | 2.0.0 (Praw) | Ensure science-grade sampling of variable stars by |
| dev/logic/COMMUNICATION.MD | 3.0.0 | No objective defined. |
| dev/logic/CORE.MD | 3.0.0 (Alpaca) | Defines the chain of command and guiding principles for |
| dev/logic/DATA_DICTIONARY.MD | 2.0.0 (Praw) | Strict schema and ownership rules for every file in the |
| dev/logic/DATA_MAPPING.MD | 2.0.0 (Praw) | Concise map of data flow from AAVSO fetch to FITS custody. |
| dev/logic/DATALOGIC.MD | N/A | No objective defined. |
| dev/logic/DISCOVERY_PROTOCOL.MD | 2.0.0 (Alpaca) | Network discovery and hardware identification for Seestar telescopes. |
| dev/logic/FLIGHT.MD | 3.0.0 | No objective defined. |
| dev/logic/PHOTOMETRICS.MD | N/A | No objective defined. |
| dev/logic/PICKERING_PROTOCOL.MD | 2026.03.12 | No objective defined. |
| dev/logic/POSTFLIGHT.MD | 1.0.0 | No objective defined. |
| dev/logic/PREFLIGHT.MD | 2.0.0 | No objective defined. |
| dev/logic/README.MD | 2.0.0 (Alpaca) | Definitive entry point and table of contents for the |
| dev/logic/SEEVAR_DICT.PSV | N/A | No objective defined. |
| dev/logic/SEEVAR_SKILL/SKILL.md | N/A | No objective defined. |
| dev/logic/SIMULATORLOGIC.MD | 2.0.0 (Sovereign A1-A12) | Outlines networking and state logic required to synchronize the SeeStar ALP Bridge with the Raspberry Pi Simulator en... |
| dev/logic/STATE_MACHINE.MD | 5.0.0 (Sovereign A1-A12) | Deterministic hardware transitions for AAVSO acquisition |
| dev/logic/WORKFLOW.MD | 1.0.0 | No objective defined. |
| dev/tools/aavso_reporter_test.py | 1.0.0 | Generate a small dummy AAVSO Extended Format report for WebObs |
| dev/tools/horizon_audit.py | 1.0.0 | Audit tonights_plan.json against the real camera-scanned horizon |
| dev/tools/refresh_manifest_headers.sh | N/A | No objective defined. |
| dev/tools/rpc_client.py | 2.0.1 | Interactive JSON-RPC client for Seestar port 4700 using pre-built sovereign payloads. |
| dev/utils/comp_purger.py | 1.1.1 | Prunes orphaned comparison star charts in the SeeVar catalog. |
| dev/utils/generate_manifest.py | 1.6.2 | Generate FILE_MANIFEST.md for SeeVar and mirror it to NAS while excluding transient runtime data, generated science p... |
| dev/utils/harvest_manager.py | 1.3.1 | SeeVar Harvester - Supports simulation data (.fit) and real FITS. |
| dev/utils/mount_guard.py | 1.1.1 | Check if the specified target is mounted and the required data directory exists. |
| dev/utils/nas_backup.sh | N/A | No objective defined. |
| requirements.txt | N/A | No objective defined. |
| systemd/seeing-scraper.service | N/A | No objective defined. |
| systemd/seeing-scraper.timer | N/A | No objective defined. |
| systemd/seestar_env_lock.service | N/A | No objective defined. |
| systemd/seevar-dashboard.service | N/A | No objective defined. |
| systemd/seevar-gps.service | N/A | No objective defined. |
| systemd/seevar-orchestrator.service | N/A | No objective defined. |
| systemd/seevar-telescope.service | N/A | No objective defined. |
| systemd/seevar-weather.service | N/A | No objective defined. |
