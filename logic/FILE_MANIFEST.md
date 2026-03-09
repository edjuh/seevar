# 🔭 S30-PRO Federation: File Manifest

> **System State**: Diamond Revision (Sovereign)

| Path | Version | Objective |
| :--- | :--- | :--- |
| core/preflight/__init__.py | N/A | No objective defined. |
| core/preflight/aavso_fetcher.py | 12.1.0 | Step 1 - Haul AAVSO targets and strictly filter by 30-degree horizon physics, with metadata injection. |
| core/preflight/audit.py | 1.2.0 | Enforces scientific cadence by cross-referencing the Federation catalog with ledger.json. |
| core/preflight/chart_fetcher.py | 1.3.0 | Fetch missing AAVSO VSP charts. Supports targeted fetch via CLI or full audit. |
| core/preflight/disk_monitor.py | N/A | Verifies NAS and local USB/buffer storage availability across all flight phases. |
| core/preflight/disk_usage_monitor.py | 1.1.0 | Monitor S30 internal storage via SMB mount and update system state with Go/No-Go veto. |
| core/preflight/fog_monitor.py | 1.0.0 | Infrared sky-clarity monitor using MLX90614 to prevent imaging in fog. |
| core/preflight/gps.py | 1.2.0 | Bi-directional GPS provider. Reads from and writes hardware coordinates to config.toml. |
| core/preflight/gps_monitor.py | 1.3.0 | Monitor GPSD natively via TCP socket (bypassing broken pip libraries), |
| core/preflight/hardware_audit.py | 1.2.0 | Deep hardware audit using the get_event_state bus to catch internal ZWO errors (501/502). |
| core/preflight/horizon.py | 1.1.0 | Veto targets based on local obstructions using Az/Alt mapping. |
| core/preflight/ledger_manager.py | 2.1.1 | The High-Authority Mission Brain. Manages target cadence and observation history. |
| core/preflight/librarian.py | 4.2.0 | The Single Source of Truth. Manages metadata, purges corruption, |
| core/preflight/nightly_planner.py | 2.5.2 | Executes the 6-step filtering funnel using the Federated Catalog and enforces the 30-degree horizon limit. |
| core/preflight/preflight_checklist.py | 1.0.0 | Verify bridge connectivity, mount orientation, and imaging pipeline status prior to flight. |
| core/preflight/schedule_compiler.py | 1.0.0 | Translates tonights_plan.json into a native SSC JSON payload using the 1x1 mosaic hack for dithering. |
| core/preflight/state_flusher.py | 1.1.0 | Preflight utility to flush stale system state and reset the dashboard to IDLE before a new flight. |
| core/preflight/sync_location.py | 1.3.0 | Synchronize S30 location using the verified open Port 80. |
| core/preflight/target_evaluator.py | N/A | Audits the nightly plan for freshness and quantity. |
| core/preflight/weather.py | 2.0.2 | Tri-Source Emoticon Aggregator for astronomical weather prediction (Strictly Dynamic Coordinates). |
| core/flight/__init__.py | N/A | No objective defined. |
| core/flight/camera_control.py | 1.0.0 | Interface for Seestar/ALP camera sensors. |
| core/flight/fsm.py | 1.0.0 | The Finite State Machine governing S30-PRO Sovereign Operations. |
| core/flight/mission_chronicle.py | 4.1.0 | Orchestrates the Sovereign funnel from Library Purge to Ledger Sync to Flight. |
| core/flight/neutralizer.py | 2.5.0 | Optimized hardware reset (Neutralizer) with smart-polling and state verification. |
| core/flight/orchestrator.py | 3.0.0 | The Supreme Gatekeeper. Executes the 6-step polite handshake and uploads the pre-compiled SSC schedule. |
| core/flight/pilot.py | 2.4.0 | Executive control of the S30-PRO with integrated Simulation Mode. |
| core/flight/session_orchestrator.py | 1.2.0 | Executive Orchestrator. Ties Flight operations to Postflight science. |
| core/flight/vault_manager.py | 1.2.0 | Manages secure access to observational metadata and synchronizes GPS coordinates with config.toml. |
| core/postflight/__init__.py | N/A | No objective defined. |
| core/postflight/analyst.py | N/A | Analyzes FITS image quality, FWHM, and basic observational metrics. |
| core/postflight/analyzer.py | N/A | Validates FITS headers and calculates basic QC metrics. |
| core/postflight/calibration_engine.py | N/A | Manages Zero-Point (ZP) offsets and flat-field corrections for the IMX585. |
| core/postflight/debayer.py | N/A | No objective defined. |
| core/postflight/librarian.py | 2.2.0 | Securely harvest binary FITS to RAID1; prepare for NAS archival. |
| core/postflight/master_analyst.py | 2.0.0 | High-level plate-solving coordinator executing astrometry.net's solve-field. |
| core/postflight/pastinakel_math.py | N/A | Logic for saturation detection and dynamic aperture scaling. |
| core/postflight/photometry_engine.py | 1.5.0 | Executes precision aperture photometry on specific X/Y pixel coordinates. |
| core/postflight/photometry_targeter.py | 1.0.0 | Use WCS headers to translate celestial RA/Dec into exact X/Y image pixels. |
| core/postflight/pixel_mapper.py | N/A | Converts celestial WCS coordinates to local sensor pixel X/Y coordinates. |
| core/postflight/post_to_pre_feedback.py | 1.2.0 | Updates the master targets.json with successful observation dates extracted from QC reports. |
| core/postflight/science_processor.py | 3.0.0 | Automate Siril Green-channel extraction with dynamic flat-field detection. |
| logic/ARCHITECTURE_OVERVIEW.md | N/A | ** High-precision AAVSO Photometry via direct hardware control. |
| logic/CADENCE.md | N/A | ** Ensure "Science-Grade" sampling of Variable Stars (LPVs/Miras/SRs) by adhering to AAVSO cadence requirements. |
| logic/COMMUNICATION.md | N/A | No objective defined. |
| logic/DATALOGIC.md | N/A | ** Defines the role, origin, and transformation logic for all JSON data structures within the RAID1 repository. |
| logic/README.md | N/A | ** Definitive entry point and Table of Contents for the Seestar Federation’s foundational rules, schemas, and communication protocols. |
| logic/SIMULATORLOGIC.md | N/A | ** Outlines networking and state logic required to synchronize the SeeStar ALP Bridge with the Raspberry Pi Simulator environment. |
| logic/STATE_MACHINE.md | N/A | ** Deterministic control over hardware transitions via JSON-RPC. |
| logic/WORKFLOW.md | N/A | ** Outlines the end-to-end human-readable data lifecycle and pointers for the S30-PRO Federation. |
| logic/aavso_logic.md | N/A | No objective defined. |
| logic/alpaca_bridge.md | N/A | ** Mandates the communication protocol, service verification, and routing for the Seestar ALP bridge. |
| logic/api_protocol.md | N/A | ** Definitive ZWO JSON-RPC method mapping. |
| logic/core.md | N/A | ** Defines the linear chain of command and the guiding principles for the operational observatory pipeline. |
| logic/data_dictionary.md | N/A | ** Defines the strict schema and purpose of every file in the data/ directory to prevent corruption. |
| logic/data_mapping.md | N/A | ** Tracking data from AAVSO fetch to FITS acquisition. |
| logic/discovery_protocol.md | N/A | No objective defined. |
| logic/preflight.md | N/A | No objective defined. |
| logic/seestar_dict.psv | N/A | No objective defined. |
| tests/alpaca_simulator.py | 1.0.0 | Mock Alpaca bridge to simulate Seestar hardware responses and state transitions for safe indoor logic testing. |
| tests/audit_names.py | N/A | No objective defined. |
| tests/full_mission_simulator.py | 43.0.0 | Grand End-to-End Orchestrator. Boot -> Data Funnel -> Compiler -> Flight Handover. |
| tests/header_medic.py | 1.1.0 | Batch injects mandatory celestial and instrument headers into bare FITS files. |
| tests/mission_chronicle.py | 3.7.0 | Autonomous End-to-End Orchestration: Fetch -> Auto-Provision Charts -> Triage. |
| tests/mock_fits_generator.py | 1.0.0 | Generates synthetic Seestar-compliant RAW FITS files to test the Siril Debayer/Green extraction pipeline. |
| tests/monitor_mission.py | 1.0.0 | Parse the SSC schedule feedback and Alpaca telemetry to verify mission execution. |
| tests/park_mount.py | 1.0.0 | Safely fold the physical mount, disengage tracking, and disconnect the Alpaca bridge. |
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
| utils/comp_purger.py | 1.0.0 | Prunes orphaned or corrupted comparison star charts to ensure a clean Librarian sync. |
| utils/generate_manifest.py | 1.2.5 | Generate a comprehensive FILE_MANIFEST.md in logic/ while excluding reference catalogs. |
| utils/nas_backup.sh | 1.2.0 | Point-in-time code and logic backup to NAS with symlink rotation. |
| utils/notifier.py | 1.2.0 | Outbound notification manager that generates morning reports and sends mission summaries via Telegram. |
