# 🔭 SeeVar: File Manifest

> **System State**: Diamond Revision (Sovereign)

| Path | Version | Objective |
| :--- | :--- | :--- |
| core/fed-mission | N/A | Full cycle automation including Postflight FITS Verification. |
| core/federation-dashboard.service | N/A | No objective defined. |
| core/seeing-scraper.service | N/A | No objective defined. |
| core/seeing-scraper.timer | N/A | No objective defined. |
| core/seestar_env_lock.service | N/A | No objective defined. |
| core/hardware/fleet_mapper.py | 1.4.17 | Dynamically reads upstream ALP config, verifies the 'seestar.service', and maps hardware indices to a static schema. |
| core/hardware/ladies.txt | N/A | No objective defined. |
| core/postflight/aavso_reporter.py | 1.1.0 | Generate AAVSO Extended Format reports in the dedicated data/reports/ directory. |
| core/postflight/accountant.py | 1.1.0 | Sweeps local_buffer, performs resilient QC photometry with historical header fallbacks, and stamps Ledger. |
| core/postflight/analyst.py | 1.0.0 | Analyzes FITS image quality, FWHM, and basic observational metrics. |
| core/postflight/analyzer.py | 1.0.1 | Validates FITS headers and calculates basic QC metrics. |
| core/postflight/calibration_engine.py | 1.0.1 | Manages Zero-Point (ZP) offsets and flat-field corrections for the IMX585. |
| core/postflight/debayer.py | 1.0.0 | Reference Siril script for fotometrie (Master-Flat -> Green extraction -> Stacking). |
| core/postflight/librarian.py | 2.2.0 | Securely harvest binary FITS to RAID1; prepare for NAS archival. |
| core/postflight/master_analyst.py | 2.0.0 | High-level plate-solving coordinator executing astrometry.net's solve-field. |
| core/postflight/pastinakel_math.py | 1.1.1 | Logic for saturation detection and dynamic aperture scaling. |
| core/postflight/photometry_engine.py | 1.5.0 | Executes precision aperture photometry on specific X/Y pixel coordinates. |
| core/postflight/photometry_targeter.py | 1.0.0 | Use WCS headers to translate celestial RA/Dec into exact X/Y image pixels. |
| core/postflight/pixel_mapper.py | 1.0.1 | Converts celestial WCS coordinates to local sensor pixel X/Y coordinates. |
| core/postflight/post_to_pre_feedback.py | 1.2.1 | Updates the master targets.json with successful observation dates extracted from QC reports. |
| core/postflight/science_processor.py | 3.1.0 | Automate Siril Green-channel extraction matching the Sovereign Pilot handoff. |
| core/postflight/data/qc_report.json | JSON | Data/Configuration file. |
| core/flight/camera_control.py | 2.0.0 | Hardware status interface for ZWO S30-Pro via Sovereign TCP. |
| core/flight/fsm.py | 1.0.0 | The Finite State Machine governing S30-PRO Sovereign Operations. |
| core/flight/mission_chronicle.py | 4.2.0 | Orchestrates the Preflight Funnel (Janitor -> Librarian -> Auditor -> Planner). |
| core/flight/neutralizer.py | 3.0.0 | Hardware reset — stops any active S30-Pro session and verifies |
| core/flight/orchestrator.py | 1.7.3 | Full pipeline state machine wired to the TCP Diamond Sequence with detailed 12-step mock telemetry. |
| core/flight/pilot.py | 4.0.3 | Direct TCP control of ZWO S30-Pro for AAVSO-compliant Sovereign RAW acquisition with Dashboard Telemetry Callbacks. |
| core/flight/vault_manager.py | 1.4.1 | Secure metadata access with actual bi-directional tomli_w syncing. |
| core/flight/__pycache__/__init__.cpython-311.pyc | N/A | No objective defined. |
| core/flight/__pycache__/__init__.cpython-313.pyc | N/A | No objective defined. |
| core/flight/__pycache__/pilot.cpython-313.pyc | N/A | No objective defined. |
| core/flight/__pycache__/vault_manager.cpython-311.pyc | N/A | No objective defined. |
| core/flight/__pycache__/vault_manager.cpython-313.pyc | N/A | No objective defined. |
| core/dashboard/dashboard.py | 4.4.9 | Dynamic Astronomical Twilight (-18.0°) flight window calculations and KNVWS removal. |
| core/dashboard/templates/index.html | N/A | No objective defined. |
| core/preflight/aavso_fetcher.py | 12.3.0 | Step 1 - Haul scientific targets from AAVSO Target Tool API |
| core/preflight/audit.py | 1.4.0 | Enforces scientific cadence (1/20th rule) by properly parsing ledger dictionaries. |
| core/preflight/chart_fetcher.py | 1.4.2 | Step 2 - Fetch AAVSO VSP comparison star sequences. |
| core/preflight/disk_monitor.py | 1.1.2 | Verifies storage availability. Respects location context: NAS is only audited when on the Home Grid. |
| core/preflight/disk_usage_monitor.py | 1.1.1 | Monitor S30 internal storage via SMB mount and update system state with Go/No-Go veto. |
| core/preflight/fog_monitor.py | 1.0.0 | Infrared sky-clarity monitor using MLX90614 to prevent imaging in fog. |
| core/preflight/gps.py | 1.4.1 | Bi-directional GPS provider with lazy initialization and Null Island protection. |
| core/preflight/hardware_audit.py | 1.3.1 | Deep hardware audit using the get_event_state bus, exporting to hardware_telemetry.json for Dashboard vitals. |
| core/preflight/horizon.py | 1.1.0 | Veto targets based on local obstructions using Az/Alt mapping. |
| core/preflight/ledger_manager.py | 2.1.2 | The High-Authority Mission Brain. Manages target cadence and observation history. |
| core/preflight/librarian.py | 4.3.0 | The Single Source of Truth. Parses raw AAVSO haul, checks for VSP charts, and writes the Federation Catalog. |
| core/preflight/nightly_planner.py | 2.6.1 | Filters the audited Federation Catalog by Cadence, Horizon, and Altitude (Unified Config). |
| core/preflight/preflight_checklist.py | 1.0.1 | Verify bridge connectivity, mount orientation, and imaging pipeline status prior to flight. |
| core/preflight/schedule_compiler.py | 1.0.1 | Translates tonights_plan.json into a native SSC JSON payload using the 1x1 mosaic hack for dithering. |
| core/preflight/state_flusher.py | 1.1.1 | Preflight utility to flush stale system state and reset the dashboard to IDLE before a new flight. |
| core/preflight/sync_location.py | 1.3.1 | Synchronize S30 location using dynamic config coordinates to the verified open Port 80. |
| core/preflight/target_evaluator.py | 1.0.1 | Audits the nightly plan for freshness and quantity to update dashboard UI. |
| core/preflight/weather.py | 1.4.2 | Tri-source weather consensus daemon. |
| core/preflight/__pycache__/__init__.cpython-313.pyc | N/A | No objective defined. |
| core/preflight/__pycache__/gps.cpython-313.pyc | N/A | No objective defined. |
| core/preflight/__pycache__/horizon.cpython-313.pyc | N/A | No objective defined. |
| core/utils/aavso_client.py | 1.2.1 | Low-level API client for authenticated AAVSO VSX and WebObs data retrieval. Returns JSON-ready dictionaries with #objective tags. |
| core/utils/astro.py | 1.2.1 | Core library for RA/Dec parsing, sidereal time, and coordinate math. |
| core/utils/coordinate_converter.py | 1.2.1 | Ensures data validity by converting sexagesimal AAVSO coordinates into decimal degrees, appending #objective to JSON writes. |
| core/utils/env_loader.py | 1.1.0 | Single source of truth for SeeVar environment paths and TOML configuration loading. |
| core/utils/gps_monitor.py | 1.5.0 | Continuous native GPSD socket monitor with full resource safety, |
| core/utils/notifier.py | 1.4.0 | Outbound alert management via Telegram and system bell. |
| core/utils/observer_math.py | 1.0.2 | Mathematical utilities for observational astronomy, including Maidenhead grid calculations dynamically tested against config.toml. |
| core/utils/platesolve_analyst.py | 1.2.1 | Quantitative reporter for plate-solving success rates, performing blind solves to compare header coordinates against reality. |
| core/utils/__pycache__/__init__.cpython-311.pyc | N/A | No objective defined. |
| core/utils/__pycache__/__init__.cpython-313.pyc | N/A | No objective defined. |
| core/utils/__pycache__/env_loader.cpython-311.pyc | N/A | No objective defined. |
| core/utils/__pycache__/env_loader.cpython-313.pyc | N/A | No objective defined. |
| core/utils/__pycache__/notifier.cpython-313.pyc | N/A | No objective defined. |
| core/utils/__pycache__/observer_math.cpython-313.pyc | N/A | No objective defined. |
| core/__pycache__/__init__.cpython-311.pyc | N/A | No objective defined. |
| core/__pycache__/__init__.cpython-313.pyc | N/A | No objective defined. |
| logic/AAVSO_LOGIC.MD | N/A | ** Rules for scientific targeting, cadence, photometry |
| logic/ALPACA_BRIDGE.MD | N/A | No objective defined. |
| logic/API_PROTOCOL.MD | N/A | ** Definitive ZWO JSON-RPC method mapping for SeeVar. |
| logic/ARCHITECTURE_OVERVIEW.md | N/A | ** High-precision AAVSO photometry via direct hardware control. |
| logic/CADENCE.md | N/A | ** Ensure science-grade sampling of variable stars by |
| logic/COMMUNICATION.md | N/A | No objective defined. |
| logic/CORE.MD | N/A | ** Defines the chain of command and guiding principles for |
| logic/DATALOGIC.MD | N/A | ** Defines the role, origin, and transformation logic for all JSON data structures within the RAID1 repository. |
| logic/DATA_DICTIONARY.MD | N/A | ** Strict schema and ownership rules for every file in the |
| logic/DATA_MAPPING.MD | N/A | ** Concise map of data flow from AAVSO fetch to FITS custody. |
| logic/DISCOVERY_PROTOCOL.MD | N/A | UDP broadcast protocol for locating the Seestar S30 on the local network. |
| logic/FILE_MANIFEST.md | N/A | No objective defined. |
| logic/PICKERING_PROTOCOL.MD | N/A | No objective defined. |
| logic/PREFLIGHT.MD | N/A | No objective defined. |
| logic/README.MD | N/A | ** Definitive entry point and table of contents for the |
| logic/README.md | N/A | ** Definitive entry point and table of contents for the foundational |
| logic/SEEVAR_DICT.PSV | 2026.03 | No objective defined. |
| logic/SIMULATORLOGIC.MD | N/A | No objective defined. |
| logic/SIMULATORLOGIC.md | N/A | ** Outlines networking and state logic required to synchronize the SeeStar ALP Bridge with the Raspberry Pi Simulator environment. |
| logic/STATE_MACHINE.md | N/A | ** Deterministic hardware transitions for sovereign AAVSO |
| tests/alpaca_simulator.py | 1.0.0 | Mock Alpaca bridge to simulate Seestar hardware responses and state transitions for safe indoor logic testing. |
| tests/audit_names.py | 1.0.0 | Validates target names against the AAVSO VSX catalog for formatting errors. |
| tests/ch-cyg.json | JSON | Data/Configuration file. |
| tests/full_mission_simulator.py | 53.0.0 | Integrated Master Simulator executing the complete Sovereign Loop (Chronicle -> Orchestrator -> Accountant). |
| tests/header_medic.py | 1.1.0 | Batch injects mandatory celestial and instrument headers into bare FITS files. |
| tests/mission_chronicle.py | 3.7.0 | Autonomous End-to-End Orchestration: Fetch -> Auto-Provision Charts -> Triage. |
| tests/mock_fits_generator.py | 2.0.0 | Generates mathematically valid, AAVSO-compliant synthetic FITS arrays with full WCS headers. |
| tests/mock_night_shift.py | 4.0.0 | High-fidelity "Ask/Check" simulation of the JSON-RPC handshake for Seestar hardware. |
| tests/monitor_mission.py | 1.0.0 | Parse the SSC schedule feedback and Alpaca telemetry to verify mission execution. |
| tests/park_mount.py | 1.0.0 | Safely fold the physical mount, disengage tracking, and disconnect the Alpaca bridge. |
| tests/phantom_bridge.py | 2.0.0 | Advanced Hardware-in-the-Loop simulator mocking the 12-step Alpaca/TCP state machine. |
| tests/simulator.txt | N/A | No objective defined. |
| tests/star_tour.json | JSON | Data/Configuration file. |
| tests/test_aavso_api.py | 1.0.0 | Diagnostic probe to verify AAVSO Target API authentication and payload structure. |
| tests/test_alp_bridge.py | 1.0.0 | Surgical JSON-RPC probe to test command execution against the ALP Bridge endpoint. |
| tests/test_bruno_api.py | 1.0.0 | Validate Bruno's SeestarAPI class against the ALP bridge. |
| tests/test_form_post.py | 1.0.0 | Mimic the ALP bridge web UI by sending x-www-form-urlencoded commands. |
| tests/test_html_parser.py | 1.0.0 | Extract telemetry JSON directly from the synchronous HTML POST response. |
| tests/test_htmx_poll.py | 1.1.0 | Trigger a command with extended timeouts and poll the HTMX event queue. |
| tests/test_logic_gates.py | 1.0.0 | Unit tests to verify Seestar API dialect consistency and safety gates. |
| tests/test_science_extraction.py | N/A | Batch process all test FITS files, locate targets, and extract instrumental flux. |
| tests/test_session_manager.py | 1.0.0 | Validate active state-machine polling for GoTo and Plate Solving sequences. |
| tests/test_sim_mission.py | 1.0.0 | End-to-End Dry Run using Simulated Bridge logic. |
| tests/test_slew.py | 1.2.0 | Execute Alpaca sequence with explicit UNPARK command to bypass hardware safety locks. |
| tests/test_sun.py | 1.0.0 | Execute a direct daytime Alpaca slew to the Sun's exact coordinates for March 6, 2026. |
| tests/test_sync_haarlem.py | 1.0.0 | Synchronize S30 location (Haarlem) via Port 5555 Alpaca using PSV vocabulary. |
| tests/test_vitals_polling.py | 1.5.0 | Use the absolute PSV strings to poll the S30 via Port 5555. |
| tests/fits/algol-indx.xyls | N/A | No objective defined. |
| tests/fits/algol.axy | N/A | No objective defined. |
| tests/fits/algol.corr | N/A | No objective defined. |
| tests/fits/algol.fits | N/A | No objective defined. |
| tests/fits/algol.match | N/A | No objective defined. |
| tests/fits/algol.new | N/A | No objective defined. |
| tests/fits/algol.rdls | N/A | No objective defined. |
| tests/fits/algol.solved | N/A | No objective defined. |
| tests/fits/algol.wcs | N/A | No objective defined. |
| tests/fits/mu_cam-indx.xyls | N/A | No objective defined. |
| tests/fits/mu_cam.axy | N/A | No objective defined. |
| tests/fits/mu_cam.corr | N/A | No objective defined. |
| tests/fits/mu_cam.fits | N/A | No objective defined. |
| tests/fits/mu_cam.match | N/A | No objective defined. |
| tests/fits/mu_cam.new | N/A | No objective defined. |
| tests/fits/mu_cam.rdls | N/A | No objective defined. |
| tests/fits/mu_cam.solved | N/A | No objective defined. |
| tests/fits/mu_cam.wcs | N/A | No objective defined. |
| tests/fits/rr_lyrae-indx.xyls | N/A | No objective defined. |
| tests/fits/rr_lyrae.axy | N/A | No objective defined. |
| tests/fits/rr_lyrae.corr | N/A | No objective defined. |
| tests/fits/rr_lyrae.fits | N/A | No objective defined. |
| tests/fits/rr_lyrae.match | N/A | No objective defined. |
| tests/fits/rr_lyrae.new | N/A | No objective defined. |
| tests/fits/rr_lyrae.rdls | N/A | No objective defined. |
| tests/fits/rr_lyrae.solved | N/A | No objective defined. |
| tests/fits/rr_lyrae.wcs | N/A | No objective defined. |
| tests/fits/seestar_spoof.fits | N/A | No objective defined. |
| tests/fits/ss_cyg-indx.xyls | N/A | No objective defined. |
| tests/fits/ss_cyg.axy | N/A | No objective defined. |
| tests/fits/ss_cyg.corr | N/A | No objective defined. |
| tests/fits/ss_cyg.fits | N/A | No objective defined. |
| tests/fits/ss_cyg.match | N/A | No objective defined. |
| tests/fits/ss_cyg.new | N/A | No objective defined. |
| tests/fits/ss_cyg.rdls | N/A | No objective defined. |
| tests/fits/ss_cyg.solved | N/A | No objective defined. |
| tests/fits/ss_cyg.wcs | N/A | No objective defined. |
| utils/comp_purger.py | 1.1.0 | Prunes orphaned comparison star charts in the SeeVar catalog. |
| utils/generate_manifest.py | 1.5.0 | Generate FILE_MANIFEST.md for SeeVar and mirror it to NAS for quick reference. |
| utils/harvest_manager.py | 1.3.0 | SeeVar Harvester - Supports simulation data (.fit) and real FITS. |
| utils/mount_guard.py | 1.1.0 | Check if /mnt/raid1 is mounted and /mnt/raid1/data exists. |
| utils/nas_backup.sh | 1.3.0 | Backup SeeVar code and logic to NAS. |
| data/hardware_telemetry.json | JSON | Data/Configuration file. |
| data/ledger.json | JSON | Data/Configuration file. |
| data/ssc_payload.json | JSON | Data/Configuration file. |
| data/system_state.json | JSON | Data/Configuration file. |
| data/tonights_plan.json | JSON | Data/Configuration file. |
| data/weather_state.json | JSON | Data/Configuration file. |
| data/raw/PSI_1_AUR_1773257515.fit | N/A | No objective defined. |
| systemd/seevar-dashboard.service | N/A | No objective defined. |
| systemd/seevar-orchestrator.service | N/A | No objective defined. |
| systemd/seevar-weather.service | N/A | No objective defined. |
| catalogs/campaign_targets.json | JSON | Data/Configuration file. |
| catalogs/de421.bsp | N/A | No objective defined. |
| catalogs/federation_catalog.json | JSON | Data/Configuration file. |
