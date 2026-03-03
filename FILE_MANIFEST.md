# 📑 Seestar Organizer: Purified Manifest
**Audit Timestamp:** 2026-03-03 17:21:52

## 🗄️ RAID1 DATA REPOSITORY
| Filename | Objective | Status/Count |
| :--- | :--- | :--- |
| `data/campaign_targets.json` | Data file | 409 Targets |
| `data/ledger.json` | Master Observational Register and Status Ledger | N/A Targets |
| `data/observable_targets.json` | The Menu: Astrophysical Reality Filter | 409 Targets |
| `data/system_state.json` | Data file | N/A Targets |
| `data/targets.json` | Error reading JSON metadata. | ERR Targets |
| `data/tonights_plan.json` | The Flight Contract for 2026-03-03 | 45 Targets |

## 🛫 PREFLIGHT
* `core/preflight/audit.py`: Enforces scientific cadence. Cross-references targets with ledger.json.
* `core/preflight/fog_monitor.py`: Infrared sky-clarity monitor using MLX90614 to prevent imaging in fog.
* `core/preflight/gps.py`: Manages geographic coordinates using config.toml as the source of truth.
* `core/preflight/harvester.py`: No script objective defined.
* `core/preflight/horizon.py`: Veto targets based on local obstructions (Trees, Buildings) using Az/Alt mapping.
* `core/preflight/librarian.py`: Reconciles verified FITS data and reports Bayer/Gain status.
* `core/preflight/seeing_scraper.py`: No script objective defined.
* `core/preflight/target_evaluator.py`: Audits the nightly plan for freshness and quantity.
* `core/preflight/weather.py`: No script objective defined.
* `core/planning/nightly_planner.py`: Score 1,240 targets against tonights sky and pick the Top 20.

## 🚀 FLIGHT
* `core/flight/env_loader.py`: Centralized configuration and environment variable manager.
* `core/flight/flight-to-post-handover.py`: Secures data after a mission, stops hardware bridges, and triggers post-flight analysis workflows.
* `core/flight/hardware_profiles.py`: Define sensor specs for Annie (S50), Williamina (S30-Pro), and Henrietta (S30-Pro Fast).
* `core/flight/librarian.py`: No script objective defined.
* `core/flight/librarian_check.py`: No script objective defined.
* `core/flight/orchestrator.py`: Single-Point Flight Master.
* `core/flight/vault_manager.py`: Manages secure access to observational metadata and synchronizes GPS coordinates with config.toml.

## 🧪 POSTFLIGHT
* `core/postflight/analyst.py`: Analyzes FITS image quality, FWHM, and basic observational metrics.
* `core/postflight/analyzer.py`: Validates FITS headers and calculates basic QC metrics.
* `core/postflight/calibration_engine.py`: Manages Zero-Point (ZP) offsets and flat-field corrections for the IMX585.
* `core/postflight/fits_auditor.py`: Scrapes full AAVSO-relevant keyword set for scientific submission.
* `core/postflight/knvws_reporter.py`: No script objective defined.
* `core/postflight/master_analyst.py`: High-level plate-solving coordinator for narrow-field Seestar frames.
* `core/postflight/notifier.py`: Outbound alert management via Telegram and system bells.
* `core/postflight/pastinakel_math.py`: Logic for saturation detection and dynamic aperture scaling.
* `core/postflight/photometry_engine.py`: Instrumental flux extraction and science-grade lightcurve generation.
* `core/postflight/pixel_mapper.py`: Converts celestial WCS coordinates to local sensor pixel X/Y coordinates.
* `core/postflight/post_to_pre_feedback.py`: Updates the master targets.json with successful observation dates extracted from QC reports.
* `core/postflight/sync_manager.py`: Manages file synchronization between Seestar, Local Buffer, and NAS.

## 🛠️ UTILS
* `utils/aavso_client.py`: Low-level API client for authenticated AAVSO VSX and WebObs data retrieval.
* `utils/astro.py`: Core library for RA/Dec parsing, sidereal time, and coordinate math.
* `utils/audit_setup.py`: Dumps current Horizon and Target configuration for architectural review.
* `utils/auto_header.py`: Injects standardized file headers into Python scripts across the project.
* `utils/campaign_auditor.py`: Unpacks the JSON envelope and cross-references campaign targets with available AAVSO comparison charts via coordinates.
* `utils/campaign_cleaner.py`: Deduplicates root campaign targets and securely links them via robust coordinate parsing.
* `utils/cleanup.py`: Housekeeping utility for purging temporary files and rotating stale logs to prevent storage bloat.
* `utils/comp_purger.py`: Scans comparison charts and deletes any file that is empty, malformed, or missing coordinate data.
* `utils/coordinate_converter.py`: Ensures data validity by converting sexagesimal AAVSO coordinates into decimal degrees for internal computational use and plate-solving.
* `utils/factory_rebuild.py`: No script objective defined.
* `utils/fix_imports.py`: Automated namespace correction utility for project-wide absolute import resolution.
* `utils/generate_manifest.py`: Audits both Python scripts (via regex) and JSON data (via internal keys), then mirrors to NAS.
* `utils/history_tracker.py`: Scans the Seestar observation storage to update last_observed timestamps in the campaign database.
* `utils/init_ledger.py`: Initializes the master Ledger with proper headers and PENDING status.
* `utils/inject_location.py`: Dynamically synchronizes Bridge/Simulator location using config.toml as the source of truth.
* `utils/manifest_auditor.py`: Audits target lists against comparison charts to link active targets with canonical AUIDs and coordinates.
* `utils/migrate_schema.py`: No script objective defined.
* `utils/notifier.py`: Outbound notification manager that generates morning reports and sends mission summaries via Telegram.
* `utils/platesolve_analyst.py`: Quantitative reporter for plate-solving success rates, performing blind solves to compare header coordinates against reality.
* `utils/purify_catalog.py`: Wraps the raw 409-target list into a Federation-standard JSON with metadata.
* `utils/quick_phot.py`: Lightweight instrumental photometry script for rapid magnitude estimation and zero-point offset calculation.
* `utils/setup_wizard.py`: Automates hardware discovery using the alpacadiscovery1 handshake.
* `utils/test_coords.py`: Verifies target acquisition readiness for existing decimal coordinates.
* `utils/wvs_ingester.py`: Downloads and parses the KNVWS Werkgroep Veranderlijke Sterren program list to automate local campaign alignment.
* `core/utils/chrony_monitor.py`: No script objective defined.
* `core/utils/disk_monitor.py`: Verifies NAS and local USB/buffer storage availability across all flight phases.
* `core/utils/env_vampire_hunter.py`: No script objective defined.
* `core/utils/gps_monitor.py`: Monitor GPSD natively via TCP socket (bypassing broken pip libraries),
* `core/utils/observer_math.py`: Calculate the 6-character Maidenhead Locator (e.g., JO22hj).
* `core/flight-to-post-handover.py`: Secures data after a mission, stops hardware bridges, and triggers post-flight analysis.
* `core/post_to_pre_feedback.py`: Updates targets.json with successful observation dates.
* `core/pre-to-flight-handover.py`: Evaluates final preflight vitals to authorize the transition to the FLIGHT phase or abort the mission if unsafe.
* `core/selector.py`: Prioritize targets setting in the West during the dark window.
* `core/sequence_repository.py`: Local cache manager for AAVSO V-band comparison sequences, reducing API overhead for offline planning.

