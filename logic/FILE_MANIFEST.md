# 🔭 SeeVar: File Manifest

> **System State**: Diamond Revision (Sovereign)

| Path | Version | Objective |
| :--- | :--- | :--- |
| requirements.txt | 2026.03.18 | SeeVar runtime dependencies — delta on top of seestar_alp. |
| config.toml | N/A | No objective defined. |
| core/fed-mission | 2.6.1 | Full cycle automation including Postflight FITS Verification. |
| core/federation-dashboard.service | N/A | No objective defined. |
| core/ledger_manager.py | 1.6.1 | The High-Authority Mission Brain. Manages target cadence and observation history. Filters tonights_plan.json by cadence, records attempts and successes during flight. |
| core/seeing-scraper.service | N/A | No objective defined. |
| core/seeing-scraper.timer | N/A | No objective defined. |
| core/seestar_env_lock.service | N/A | No objective defined. |
| core/hardware/fleet_mapper.py | 2.0.0 | Read [[seestars]] from config.toml, load hardware constants |
| core/hardware/hardware_loader.py | 1.2.0 | Auto-detect Seestar hardware via Alpaca UDP discovery beacon (port 32227), fingerprint sensor via HTTP Alpaca API, load the matching hardware profile. |
| core/hardware/ladies.txt | N/A | No objective defined. |
| core/hardware/ssh_monitor.py | 1.1.0 | Establish an SSH connection to the Seestar SOC (ARM) to stream real-time logs for reverse-engineering port 4700 Sovereign commands. Includes an interactive menu for log selection. |
| core/hardware/wilhelmina_monitor.py | 1.0.2 | Persistent event stream listener for ZWO Seestar port 4700. |
| core/hardware/models/S30-Pro.json | JSON | Data/Configuration file. |
| core/hardware/models/S30.json | JSON | Data/Configuration file. |
| core/hardware/models/S50.json | JSON | Data/Configuration file. |
| core/postflight/aavso_reporter.py | 1.2.1 | Generate AAVSO Extended Format reports in the dedicated data/reports/ |
| core/postflight/accountant.py | 2.0.1 | Sweeps local_buffer, runs full Bayer differential photometry via calibration_engine, and stamps complete results into the ledger. |
| core/postflight/bayer_photometry.py | 2.0.1 | Bayer-channel aperture photometry engine for the IMX585 (GRBG pattern). Extracted from pilot.py and elevated to a standalone science module. Provides single-star flux extraction and multi-star differential photometry. |
| core/postflight/calibration_engine.py | 2.0.0 | Orchestrates differential photometry for a single FITS frame. |
| core/postflight/gaia_resolver.py | 1.0.0 | Resolve Gaia DR3 comparison stars for a given field. |
| core/postflight/librarian.py | 2.2.1 | Securely harvest binary FITS to RAID1; prepare for NAS archival using dynamic paths. |
| core/postflight/master_analyst.py | 2.0.1 | High-level plate-solving coordinator executing astrometry.net's solve-field. |
| core/postflight/pastinakel_math.py | 1.1.2 | Logic for saturation detection and dynamic aperture scaling. |
| core/postflight/post_to_pre_feedback.py | 1.2.2 | Updates the master targets.json with successful observation dates extracted from QC reports. |
| core/postflight/psf_models.py | 1.0.1 | PSF fitting for stellar profiles on IMX585 Bayer frames. Provides FWHM estimation feeding dynamic aperture and SNR calculations. |
| core/postflight/data/qc_report.json | JSON | Data/Configuration file. |
| core/flight/camera_control.py | 2.0.0 | Hardware status interface for ZWO S30-Pro via Sovereign TCP. |
| core/flight/dark_library.py | 1.0.0 | Post-session dark frame acquisition via firmware start_create_dark. |
| core/flight/exposure_planner.py | 1.2.0 | Estimate optimal exposure time and frame count for a target given |
| core/flight/field_rotation.py | 1.0.0 | Calculate field rotation rate and maximum safe exposure time for |
| core/flight/fsm.py | 1.1.0 | The Finite State Machine governing S30-PRO Sovereign Operations. |
| core/flight/mission_chronicle.py | 4.2.0 | Orchestrates the Preflight Funnel (Janitor -> Librarian -> Auditor -> Planner). |
| core/flight/neutralizer.py | 3.0.1 | Hardware reset — stops any active S30-Pro session and verifies idle state before handing control to the pilot. |
| core/flight/orchestrator.py | 1.7.0 | Full pipeline state machine wired to the TCP Diamond Sequence via the SovereignFSM. |
| core/flight/pilot.py | 1.7.1 | Direct TCP control of ZWO S30-Pro for AAVSO-compliant Sovereign RAW acquisition. Dynamically routes network IP from config. |
| core/flight/sim_runner.py | 1.0.0 | Execute a full realtime nightly simulation against tonights_plan.json |
| core/flight/vault_manager.py | 1.4.1 | Secure metadata access with actual bi-directional tomli_w syncing. |
| core/dashboard/dashboard.py | 4.6.1 | Wire wilhelmina_state.json (WilhelminaMonitor event stream) |
| core/dashboard/templates/index.html | N/A | No objective defined. |
| core/preflight/aavso_fetcher.py | 1.6.8 | Haul AAVSO targets with nested dictionary support and strict error-message reporting. |
| core/preflight/audit.py | 1.4.0 | Enforces scientific cadence (1/20th rule) by properly parsing ledger dictionaries. |
| core/preflight/chart_fetcher.py | 1.4.2 | Step 2 - Fetch AAVSO VSP comparison star sequences. |
| core/preflight/disk_monitor.py | 1.1.2 | Verifies storage availability. Respects location context: NAS is only audited when on the Home Grid. |
| core/preflight/disk_usage_monitor.py | 1.1.1 | Monitor S30 internal storage via SMB mount and update system state with Go/No-Go veto. |
| core/preflight/fog_monitor.py | 1.0.1 | Infrared sky-clarity monitor using MLX90614 to prevent imaging in fog. Acts as a safety gate for photometry. |
| core/preflight/gps.py | 1.5.1 | Bi-directional GPS provider with lazy initialization. Reads from RAM status and actively syncs to config.toml via VaultManager to maintain a live last_refresh heartbeat. |
| core/preflight/hardware_audit.py | 2.0.0 | Sovereign TCP hardware audit via get_device_state on port 4700. |
| core/preflight/horizon.py | 2.0.0 | Veto targets based on local obstructions using Az/Alt mapping. |
| core/preflight/ledger_manager.py | 2.2.1 | The High-Authority Mission Brain. Manages dynamic target cadence |
| core/preflight/librarian.py | 4.3.0 | The Single Source of Truth. Parses raw AAVSO haul, checks for VSP charts, and writes the Federation Catalog. |
| core/preflight/nightly_planner.py | 2.6.1 | Filters the audited Federation Catalog by Cadence, Horizon, and Altitude (Unified Config). |
| core/preflight/preflight_checklist.py | 2.0.0 | Sovereign preflight gate — verifies hardware is alive and at |
| core/preflight/schedule_compiler.py | 1.0.2 | Translates tonights_plan.json into a native SSC JSON payload using the 1x1 mosaic hack for dithering. |
| core/preflight/state_flusher.py | 1.1.1 | Preflight utility to flush stale system state and reset the dashboard to IDLE before a new flight. |
| core/preflight/target_evaluator.py | 1.0.2 | Audits the nightly plan for freshness and quantity to update dashboard UI. |
| core/preflight/vsx_catalog.py | 2.1.0 | Fetch magnitude ranges from AAVSO VSX for all campaign targets. |
| core/preflight/weather.py | 1.8.0 | Tri-source weather consensus daemon. Evaluates hard-abort |
| core/utils/aavso_client.py | 1.2.2 | Low-level API client for authenticated AAVSO VSX and WebObs data retrieval. Returns JSON-ready dictionaries with #objective tags. |
| core/utils/astro.py | 1.2.1 | Core library for RA/Dec parsing, sidereal time, and coordinate math. |
| core/utils/coordinate_converter.py | 1.2.2 | Ensures data validity by converting sexagesimal AAVSO coordinates into decimal degrees, appending #objective to JSON writes. |
| core/utils/env_loader.py | 1.1.0 | Single source of truth for SeeVar environment paths and TOML configuration loading. |
| core/utils/gps_monitor.py | 1.5.0 | Continuous native GPSD socket monitor with full resource safety, |
| core/utils/notifier.py | 1.4.0 | Outbound alert management via Telegram and system bell. |
| core/utils/observer_math.py | 1.0.3 | Mathematical utilities for observational astronomy, including Maidenhead grid calculations dynamically tested against config.toml. |
| core/utils/platesolve_analyst.py | 1.2.2 | Quantitative reporter for plate-solving success rates, performing blind solves to compare header coordinates against reality. |
| logic/FILE_MANIFEST.md | N/A | No objective defined. |
| dev/CONTRIBUTING.md | N/A | ** Defines the strict technical standards, workflow protocols, and "Garmt" purified header requirements for all project contributors (AI or Human). |
| dev/tools/Kaspar.mp4 | N/A | No objective defined. |
| dev/tools/SeeVar_The_Movie.mp4 | N/A | No objective defined. |
| dev/tools/aavso_reporter_test.py | 1.0.0 | Generate a small dummy AAVSO Extended Format report for WebObs |
| dev/tools/build_trailer.sh | 1.0.2 | Robustly normalize and concatenate all SeeVar movie phases. |
| dev/tools/edfilx.mp4 | N/A | No objective defined. |
| dev/tools/postflight_movie.py | 1.0.1 | Manim script visualizing the SeeVar Postflight pipeline: FITS ingestion, differential photometry, and AAVSO reporting. |
| dev/tools/rpc_client.py | 2.0.1 | Interactive JSON-RPC client for Seestar port 4700 using pre-built sovereign payloads. |
| dev/tools/seestar_active_poll.py | 1.3.0 | Actively poll the Seestar Sovereign telemetry by first breaking the session lock (S1). |
| dev/tools/seestar_heartbeat.py | N/A | Maintain persistent TCP connection to Seestar via 5-second polling |
| dev/tools/seestar_telemetry_poll.py | 1.0.0 | Standalone diagnostic tool to poll real-time JSON-RPC 2.0 telemetry and status data directly from the Seestar on port 4700. |
| dev/tools/seestar_telemetry_top.py | 1.0.0 | Live, continuous CLI dashboard (like 'top') for Seestar Sovereign telemetry via JSON-RPC 2.0 on port 4700. |
| dev/tools/sim_reset.py | 2.0.0 | Reset ledger entries for targets in tonights_plan.json to |
| dev/tools/sovereign_flow.py | 2.0.0 | Manim visualization of a 3-target JSON-RPC TCP sequence with an animated Seestar model and 12-second integration. |
| dev/tools/test_mutex_heartbeat.py | 1.0.0 | Verify that ControlSocket's background heartbeat keeps port 4700 alive during a 60s+ simulated exposure without corrupting the command stream. |
| dev/utils/comp_purger.py | 1.1.1 | Prunes orphaned comparison star charts in the SeeVar catalog. |
| dev/utils/generate_manifest.py | 1.5.2 | Generate FILE_MANIFEST.md for SeeVar and mirror it to NAS for quick reference. Ignores transient runtime data caches. |
| dev/utils/harvest_manager.py | 1.3.1 | SeeVar Harvester - Supports simulation data (.fit) and real FITS. |
| dev/utils/mount_guard.py | 1.1.1 | Check if the specified target is mounted and the required data directory exists. |
| dev/utils/nas_backup.sh | 1.3.2 | Backup SeeVar code and logic to dynamically defined NAS targets. |
| dev/logic/AAVSO_LOGIC.MD | N/A | ** Rules for scientific targeting, cadence, photometry |
| dev/logic/AI_CONTEXT.md | N/A | ** The absolute architectural law, environment standards, and logic constraints for AI-assisted development of the SeeVar Federation. |
| dev/logic/ALPACA_BRIDGE.MD | N/A | No objective defined. |
| dev/logic/API_PROTOCOL.MD | N/A | ** Definitive ZWO JSON-RPC method mapping for SeeVar. |
| dev/logic/ARCHITECTURE_OVERVIEW.md | N/A | ** High-precision AAVSO photometry via direct hardware control. |
| dev/logic/CADENCE.md | N/A | ** Ensure science-grade sampling of variable stars by |
| dev/logic/COMMUNICATION.md | N/A | No objective defined. |
| dev/logic/CORE.MD | N/A | ** Defines the chain of command and guiding principles for |
| dev/logic/DATALOGIC.MD | N/A | ** Defines the role, origin, and transformation logic for all JSON data structures within the RAID1 repository. |
| dev/logic/DATA_DICTIONARY.MD | N/A | ** Strict schema and ownership rules for every file in the |
| dev/logic/DATA_MAPPING.MD | N/A | ** Concise map of data flow from AAVSO fetch to FITS custody. |
| dev/logic/DISCOVERY_PROTOCOL.MD | N/A | UDP broadcast protocol for locating the Seestar S30 on the local network. |
| dev/logic/FILE_MANIFEST.md | N/A | No objective defined. |
| dev/logic/FLIGHT.MD | N/A | No objective defined. |
| dev/logic/PHOTOMETRICS.MD | N/A | No objective defined. |
| dev/logic/PICKERING_PROTOCOL.MD | N/A | No objective defined. |
| dev/logic/POSTFLIGHT.MD | N/A | No objective defined. |
| dev/logic/PREFLIGHT.MD | N/A | No objective defined. |
| dev/logic/README.MD | N/A | ** Definitive entry point and table of contents for the |
| dev/logic/README.md | N/A | ** Definitive entry point and table of contents for the foundational |
| dev/logic/SEEVAR_DICT.PSV | 2026.03 | No objective defined. |
| dev/logic/SIMULATORLOGIC.MD | N/A | No objective defined. |
| dev/logic/SIMULATORLOGIC.md | N/A | ** Outlines networking and state logic required to synchronize the SeeStar ALP Bridge with the Raspberry Pi Simulator environment. |
| dev/logic/STATE_MACHINE.md | N/A | ** Deterministic hardware transitions for sovereign AAVSO |
| dev/logic/WORKFLOW.md | N/A | No objective defined. |
| dev/logic/SEEVAR_SKILL/SKILL.md | N/A | No objective defined. |
| data/hardware_telemetry.json | JSON | Data/Configuration file. |
| data/horizon_mask.json | JSON | Data/Configuration file. |
| data/ledger.json | JSON | Data/Configuration file. |
| data/science_starlist.csv | N/A | No objective defined. |
| data/ssc_payload.json | JSON | Data/Configuration file. |
| data/system_state.json | JSON | Data/Configuration file. |
| data/tonights_plan.json | JSON | Data/Configuration file. |
| data/vsx_catalog.json | JSON | Data/Configuration file. |
| data/weather_state.json | JSON | Data/Configuration file. |
| systemd/seeing-scraper.service | N/A | No objective defined. |
| systemd/seeing-scraper.timer | N/A | No objective defined. |
| systemd/seestar_env_lock.service | N/A | No objective defined. |
| systemd/seevar-dashboard.service | N/A | No objective defined. |
| systemd/seevar-gps.service | N/A | No objective defined. |
| systemd/seevar-orchestrator.service | N/A | No objective defined. |
| systemd/seevar-telescope.service | N/A | No objective defined. |
| systemd/seevar-weather.service | N/A | No objective defined. |
| catalogs/campaign_targets.json | JSON | Data/Configuration file. |
| catalogs/de421.bsp | N/A | No objective defined. |
| catalogs/federation_catalog.json | JSON | Data/Configuration file. |
