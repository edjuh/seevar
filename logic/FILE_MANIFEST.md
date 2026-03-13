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
| core/postflight/accountant.py | 2.0.0 | Sweeps local_buffer, runs full Bayer differential photometry via |
| core/postflight/bayer_photometry.py | 2.0.0 | Bayer-channel aperture photometry engine for the IMX585 (GRBG pattern). |
| core/postflight/calibration_engine.py | 2.0.0 | Orchestrates differential photometry for a single FITS frame. |
| core/postflight/gaia_resolver.py | 1.0.0 | Resolve Gaia DR3 comparison stars for a given field. |
| core/postflight/librarian.py | 2.2.0 | Securely harvest binary FITS to RAID1; prepare for NAS archival. |
| core/postflight/master_analyst.py | 2.0.0 | High-level plate-solving coordinator executing astrometry.net's solve-field. |
| core/postflight/pastinakel_math.py | 1.1.1 | Logic for saturation detection and dynamic aperture scaling. |
| core/postflight/post_to_pre_feedback.py | 1.2.1 | Updates the master targets.json with successful observation dates extracted from QC reports. |
| core/postflight/psf_models.py | 1.0.0 | PSF fitting for stellar profiles on IMX585 Bayer frames. |
| core/postflight/__pycache__/__init__.cpython-313.pyc | N/A | No objective defined. |
| core/postflight/__pycache__/bayer_photometry.cpython-313.pyc | N/A | No objective defined. |
| core/postflight/__pycache__/calibration_engine.cpython-313.pyc | N/A | No objective defined. |
| core/postflight/__pycache__/gaia_resolver.cpython-313.pyc | N/A | No objective defined. |
| core/postflight/__pycache__/pastinakel_math.cpython-313.pyc | N/A | No objective defined. |
| core/postflight/__pycache__/psf_models.cpython-313.pyc | N/A | No objective defined. |
| core/postflight/data/qc_report.json | JSON | Data/Configuration file. |
| core/flight/camera_control.py | 2.0.0 | Hardware status interface for ZWO S30-Pro via Sovereign TCP. |
| core/flight/exposure_planner.py | 1.0.0 | Estimate optimal exposure time for a target given magnitude, |
| core/flight/fsm.py | 1.0.0 | The Finite State Machine governing S30-PRO Sovereign Operations. |
| core/flight/mission_chronicle.py | 4.2.0 | Orchestrates the Preflight Funnel (Janitor -> Librarian -> Auditor -> Planner). |
| core/flight/neutralizer.py | 3.0.0 | Hardware reset — stops any active S30-Pro session and verifies |
| core/flight/orchestrator.py | 1.7.3 | Full pipeline state machine wired to the TCP Diamond Sequence with detailed 12-step mock telemetry. |
| core/flight/pilot.py | 4.1.2 | Direct TCP control of ZWO S30-Pro for AAVSO-compliant Sovereign RAW acquisition. Fixes 16-bit integer overflow via standard FITS BZERO offsetting. |
| core/flight/vault_manager.py | 1.4.1 | Secure metadata access with actual bi-directional tomli_w syncing. |
| core/flight/__pycache__/__init__.cpython-311.pyc | N/A | No objective defined. |
| core/flight/__pycache__/__init__.cpython-313.pyc | N/A | No objective defined. |
| core/flight/__pycache__/exposure_planner.cpython-313.pyc | N/A | No objective defined. |
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
| core/preflight/horizon.py | 2.0.0 | Veto targets based on local obstructions using Az/Alt mapping. |
| core/preflight/ledger_manager.py | 2.1.2 | The High-Authority Mission Brain. Manages target cadence and observation history. |
| core/preflight/librarian.py | 4.3.0 | The Single Source of Truth. Parses raw AAVSO haul, checks for VSP charts, and writes the Federation Catalog. |
| core/preflight/nightly_planner.py | 2.6.1 | Filters the audited Federation Catalog by Cadence, Horizon, and Altitude (Unified Config). |
| core/preflight/preflight_checklist.py | 1.0.1 | Verify bridge connectivity, mount orientation, and imaging pipeline status prior to flight. |
| core/preflight/schedule_compiler.py | 1.0.1 | Translates tonights_plan.json into a native SSC JSON payload using the 1x1 mosaic hack for dithering. |
| core/preflight/state_flusher.py | 1.1.1 | Preflight utility to flush stale system state and reset the dashboard to IDLE before a new flight. |
| core/preflight/sync_location.py | 1.3.1 | Synchronize S30 location using dynamic config coordinates to the verified open Port 80. |
| core/preflight/target_evaluator.py | 1.0.1 | Audits the nightly plan for freshness and quantity to update dashboard UI. |
| core/preflight/vsx_catalog.py | 2.0.0 | Fetch magnitude ranges from AAVSO VSX for all campaign targets. |
| core/preflight/weather.py | 1.4.2 | Tri-source weather consensus daemon. |
| core/preflight/__pycache__/__init__.cpython-313.pyc | N/A | No objective defined. |
| core/preflight/__pycache__/gps.cpython-313.pyc | N/A | No objective defined. |
| core/preflight/__pycache__/horizon.cpython-313.pyc | N/A | No objective defined. |
| core/preflight/__pycache__/vsx_catalog.cpython-313.pyc | N/A | No objective defined. |
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
| logic/PHOTOMETRICS.MD | N/A | No objective defined. |
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
| data/horizon_mask.json | JSON | Data/Configuration file. |
| data/ledger.json | JSON | Data/Configuration file. |
| data/science_starlist.csv | N/A | No objective defined. |
| data/ssc_payload.json | JSON | Data/Configuration file. |
| data/system_state.json | JSON | Data/Configuration file. |
| data/tonights_plan.json | JSON | Data/Configuration file. |
| data/vsx_catalog.json | JSON | Data/Configuration file. |
| data/weather_state.json | JSON | Data/Configuration file. |
| data/raw/PSI_1_AUR_1773257515.fit | N/A | No objective defined. |
| data/gaia_cache/ra000.300_decpp60.400.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra002.400_decpp64.000.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra005.800_decpp55.800.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra006.000_decpp38.600.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra009.200_decpp63.100.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra013.700_decpp58.600.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra019.900_decpp72.600.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra023.000_decpp62.300.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra023.400_decpp60.600.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra024.700_decpp38.700.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra026.800_decpp60.400.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra029.600_decpp59.300.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra029.900_decpp54.800.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra030.400_decpp64.100.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra030.800_decpp55.200.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra032.600_decpp56.600.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra033.800_decpp58.100.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra034.000_decpp25.100.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra034.400_decpp44.300.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra034.700_decpp57.400.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra034.800_decpp59.000.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra035.100_decpp57.000.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra035.200_decpp57.200.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra035.500_decpp56.600.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra035.600_decpp57.100.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra035.700_decpp58.600.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra039.300_decpp34.300.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra039.600_decpp57.000.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra042.100_decpp17.500.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra042.700_decpp57.000.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra042.800_decpp57.900.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra046.900_decpp60.500.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra048.500_decpp54.900.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra048.800_decpp54.900.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra051.900_decpp44.200.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra055.500_decpp62.600.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra057.400_decpp80.300.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra058.700_decpp48.600.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra067.000_decpp16.000.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra070.000_decpp66.100.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra071.400_decpp75.100.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra075.500_decpp43.800.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra079.300_decpp53.600.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra081.800_decpp34.100.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra083.600_decpp25.600.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra085.200_decpp31.900.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra089.900_decpp44.900.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra090.400_decpp53.300.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra093.100_decpp50.200.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra096.200_decpp49.300.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra096.600_decpp56.300.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra099.100_decpp38.400.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra138.600_decpp67.300.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra161.200_decpp68.800.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra161.300_decpp67.400.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra164.800_decpp70.000.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra203.700_decpp73.400.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra214.300_decpp66.800.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra214.500_decpp83.800.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra283.800_decpp43.900.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra287.000_decpp36.400.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra288.100_decpp41.300.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra290.000_decpp37.900.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra292.600_decpp46.100.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra295.900_decpp48.800.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra296.500_decpp49.100.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra297.600_decpp32.900.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra299.300_decpp39.800.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra300.400_decpp50.000.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra301.500_decpp25.600.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra303.300_decpp38.700.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra303.900_decpp31.100.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra304.600_decpp34.400.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra304.600_decpp37.400.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra304.900_decpp47.900.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra305.300_decpp36.900.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra305.400_decpp37.500.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra306.000_decpp33.900.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra306.400_decpp38.700.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra307.200_decpp40.000.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra307.300_decpp39.700.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra309.500_decpp18.300.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra309.700_decpp23.300.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra310.300_decpp48.100.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra310.400_decpp51.200.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra310.800_decpp17.100.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra310.900_decpp38.200.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra311.400_decpp18.100.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra312.300_decpp50.500.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra313.000_decpp34.700.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra313.000_decpp47.400.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra314.500_decpp46.500.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra316.100_decpp23.800.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra317.400_decpp68.500.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra317.900_decpp48.200.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra319.800_decpp58.600.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra321.400_decpp62.600.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra323.800_decpp78.600.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra324.000_decpp45.400.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra325.200_decpp54.300.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra325.900_decpp58.800.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra329.000_decpp48.300.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra329.200_decpp63.600.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra331.700_decpp48.500.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra332.200_decpp12.500.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra333.200_decpp43.800.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra336.400_decpp30.500.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra339.100_decpp58.400.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra341.900_decpp55.200.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra342.300_decpp58.600.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra342.700_decpp64.300.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra342.900_decpp85.000.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra343.300_decpp61.300.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra346.700_decpp10.500.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra347.500_decpp61.200.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra347.900_decpp59.700.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra350.000_decpp26.300.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra354.400_decpp58.800.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra354.700_decpp35.800.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra354.800_decpp52.300.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra356.000_decpp61.800.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra356.100_decpp56.600.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra358.000_decpp61.800.json | JSON | Data/Configuration file. |
| data/gaia_cache/ra359.600_decpp51.400.json | JSON | Data/Configuration file. |
| systemd/seevar-dashboard.service | N/A | No objective defined. |
| systemd/seevar-orchestrator.service | N/A | No objective defined. |
| systemd/seevar-weather.service | N/A | No objective defined. |
| catalogs/campaign_targets.json | JSON | Data/Configuration file. |
| catalogs/de421.bsp | N/A | No objective defined. |
| catalogs/federation_catalog.json | JSON | Data/Configuration file. |
