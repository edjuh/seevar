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
| core/postflight/data/qc_report.json | JSON | Data/Configuration file. |
| core/flight/camera_control.py | 2.0.0 | Hardware status interface for ZWO S30-Pro via Sovereign TCP. |
| core/flight/dark_library.py | 1.0.0 | Post-session dark frame acquisition via firmware start_create_dark. |
| core/flight/exposure_planner.py | 1.0.0 | Estimate optimal exposure time for a target given magnitude, |
| core/flight/fsm.py | 1.0.0 | The Finite State Machine governing S30-PRO Sovereign Operations. |
| core/flight/mission_chronicle.py | 4.2.0 | Orchestrates the Preflight Funnel (Janitor -> Librarian -> Auditor -> Planner). |
| core/flight/neutralizer.py | 3.0.0 | Hardware reset — stops any active S30-Pro session and verifies |
| core/flight/orchestrator.py | 2.0.0 | Full pipeline state machine wired to the TCP Diamond Sequence. M4: DarkLibrary wired into post-session flow. |
| core/flight/pilot.py | 5.2.0 | Direct TCP control of ZWO S30-Pro for AAVSO-compliant Sovereign RAW acquisition. M2: TelemetryBlock, send_and_recv, session init S1-S4, veto logic on real values. |
| core/flight/vault_manager.py | 1.4.1 | Secure metadata access with actual bi-directional tomli_w syncing. |
| core/flight/__pycache__/__init__.cpython-313.pyc | N/A | No objective defined. |
| core/flight/__pycache__/dark_library.cpython-313.pyc | N/A | No objective defined. |
| core/flight/__pycache__/exposure_planner.cpython-313.pyc | N/A | No objective defined. |
| core/flight/__pycache__/orchestrator.cpython-313.pyc | N/A | No objective defined. |
| core/flight/__pycache__/pilot.cpython-313.pyc | N/A | No objective defined. |
| core/dashboard/dashboard.py | 4.5.0 | M5: HW_CACHE reads battery_pct and temp_c from system_state.json telemetry block. |
| core/dashboard/templates/index.html | N/A | No objective defined. |
| core/dashboard/__pycache__/dashboard.cpython-313.pyc | N/A | No objective defined. |
| core/preflight/aavso_fetcher.py | 12.3.0 | Step 1 - Haul scientific targets from AAVSO Target Tool API |
| core/preflight/audit.py | 1.4.0 | Enforces scientific cadence (1/20th rule) by properly parsing ledger dictionaries. |
| core/preflight/chart_fetcher.py | 1.4.2 | Step 2 - Fetch AAVSO VSP comparison star sequences. |
| core/preflight/disk_monitor.py | 1.1.2 | Verifies storage availability. Respects location context: NAS is only audited when on the Home Grid. |
| core/preflight/disk_usage_monitor.py | 1.1.1 | Monitor S30 internal storage via SMB mount and update system state with Go/No-Go veto. |
| core/preflight/fog_monitor.py | 1.0.0 | Infrared sky-clarity monitor using MLX90614 to prevent imaging in fog. |
| core/preflight/gps.py | 1.4.1 | Bi-directional GPS provider with lazy initialization and Null Island protection. |
| core/preflight/hardware_audit.py | 2.0.0 | Sovereign TCP hardware audit via get_device_state on port 4700. |
| core/preflight/horizon.py | 2.0.0 | Veto targets based on local obstructions using Az/Alt mapping. |
| core/preflight/ledger_manager.py | 2.1.2 | The High-Authority Mission Brain. Manages target cadence and observation history. |
| core/preflight/librarian.py | 4.3.0 | The Single Source of Truth. Parses raw AAVSO haul, checks for VSP charts, and writes the Federation Catalog. |
| core/preflight/nightly_planner.py | 2.6.1 | Filters the audited Federation Catalog by Cadence, Horizon, and Altitude (Unified Config). |
| core/preflight/preflight_checklist.py | 2.0.0 | Sovereign preflight gate — verifies hardware is alive and at |
| core/preflight/schedule_compiler.py | 1.0.1 | Translates tonights_plan.json into a native SSC JSON payload using the 1x1 mosaic hack for dithering. |
| core/preflight/state_flusher.py | 1.1.1 | Preflight utility to flush stale system state and reset the dashboard to IDLE before a new flight. |
| core/preflight/sync_location.py | 1.3.1 | Synchronize S30 location using dynamic config coordinates to the verified open Port 80. |
| core/preflight/target_evaluator.py | 1.0.1 | Audits the nightly plan for freshness and quantity to update dashboard UI. |
| core/preflight/vsx_catalog.py | 2.0.0 | Fetch magnitude ranges from AAVSO VSX for all campaign targets. |
| core/preflight/weather.py | 1.4.2 | Tri-source weather consensus daemon. |
| core/preflight/__pycache__/__init__.cpython-313.pyc | N/A | No objective defined. |
| core/preflight/__pycache__/hardware_audit.cpython-313.pyc | N/A | No objective defined. |
| core/preflight/__pycache__/preflight_checklist.cpython-313.pyc | N/A | No objective defined. |
| core/preflight/__pycache__/vsx_catalog.cpython-313.pyc | N/A | No objective defined. |
| core/utils/aavso_client.py | 1.2.1 | Low-level API client for authenticated AAVSO VSX and WebObs data retrieval. Returns JSON-ready dictionaries with #objective tags. |
| core/utils/astro.py | 1.2.1 | Core library for RA/Dec parsing, sidereal time, and coordinate math. |
| core/utils/coordinate_converter.py | 1.2.1 | Ensures data validity by converting sexagesimal AAVSO coordinates into decimal degrees, appending #objective to JSON writes. |
| core/utils/env_loader.py | 1.1.0 | Single source of truth for SeeVar environment paths and TOML configuration loading. |
| core/utils/gps_monitor.py | 1.5.0 | Continuous native GPSD socket monitor with full resource safety, |
| core/utils/notifier.py | 1.4.0 | Outbound alert management via Telegram and system bell. |
| core/utils/observer_math.py | 1.0.2 | Mathematical utilities for observational astronomy, including Maidenhead grid calculations dynamically tested against config.toml. |
| core/utils/platesolve_analyst.py | 1.2.1 | Quantitative reporter for plate-solving success rates, performing blind solves to compare header coordinates against reality. |
| core/utils/__pycache__/__init__.cpython-313.pyc | N/A | No objective defined. |
| core/utils/__pycache__/env_loader.cpython-313.pyc | N/A | No objective defined. |
| core/utils/__pycache__/observer_math.cpython-313.pyc | N/A | No objective defined. |
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
| data/local_buffer/SIM_AB_Dra_20260314T192956_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_AC_And_20260314T193347_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_AD_Per_20260314T193057_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_AD_Tau_20260314T193338_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_AF_Cam_20260314T193026_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_AG_Dra_20260314T192715_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_AL_Cep_20260314T193307_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_AM_Cas_20260314T193153_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_AR_And_20260314T192702_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_AR_Cep_20260314T193035_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_AT_Cnc_20260314T192859_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_AX_Per_20260314T192556_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_BH_Aur_20260314T192947_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_BI_Ori_20260314T193356_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_BU_Per_20260314T193018_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_BZ_UMa_20260314T193259_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_CC_Cnc_20260314T193140_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_CE_Tau_20260314T193351_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_CH_UMa_20260314T192855_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_CI_UMa_20260314T193005_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_DO_Dra_20260314T192930_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_EG_And_20260314T193202_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_EG_Cnc_20260314T193237_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_EX_Dra_20260314T192850_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_FI_Per_20260314T193052_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_FO_Per_20260314T193422_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_FX_Mon_20260314T192710_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_FZ_Per_20260314T193110_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_GK_Per_20260314T192925_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_GOTO065054.49+593624.51_20260314T193329_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_GU_Cep_20260314T193119_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_GX_Cas_20260314T193211_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_HD_232766_20260314T192631_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_IM_Cas_20260314T192605_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_IR_Gem_20260314T192833_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_KK_Per_20260314T192829_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_KT_Per_20260314T192552_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_KZ_Gem_20260314T193123_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_LN_UMa_20260314T192846_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_LS_And_20260314T192837_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_NSVS_12572573_20260314T192543_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_NSV_544_20260314T192614_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_NSV_693_20260314T193224_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_N_Cas_2020_20260314T192754_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_N_Cas_2021_20260314T193409_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_RR_Lyn_20260314T192653_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_RS_Per_20260314T193132_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_RU_Cyg_20260314T193303_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_RY_Dra_20260314T192728_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_R_And_20260314T193039_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_R_Ari_20260314T193220_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_R_Aur_20260314T192745_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_R_Cam_20260314T193215_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_R_Dra_20260314T192904_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_R_Gem_20260314T193316_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_R_LMi_20260314T192644_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_R_UMa_20260314T193404_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_SDSS_J080846.19+313106.0_20260314T192609_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_SS_Cep_20260314T193009_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_SS_Mon_20260314T192627_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_SS_UMi_20260314T192649_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_SU_Per_20260314T193127_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_SU_UMa_20260314T192758_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_SW_And_20260314T192908_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_SW_Cep_20260314T192939_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_SW_UMa_20260314T192912_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_S_Aur_20260314T193048_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_S_Cas_20260314T193334_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_S_Cep_20260314T193114_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_S_Per_20260314T193136_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_S_UMi_20260314T193246_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_TY_Cas_20260314T192921_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_TZ_Aur_20260314T193254_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_TZ_Per_20260314T192934_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_T_Cam_20260314T192601_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_T_Cas_20260314T193228_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_T_Cep_20260314T193000_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_T_Per_20260314T193022_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_T_UMi_20260314T193105_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_UU_Aur_20260314T192723_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_UV_Per_20260314T192824_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_U_Cam_20260314T192820_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_U_LMi_20260314T192807_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_U_Lac_20260314T193250_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_U_Per_20260314T193241_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_U_UMi_20260314T192618_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_V0381_Cep_20260314T192811_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_V0386_Cep_20260314T192816_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_V0411_Per_20260314T192657_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_V0476_Cyg_20260314T193149_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_V0542_Cyg_20260314T192917_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_V0550_Per_20260314T192943_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_V0594_Cas_20260314T193013_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_V0641_Cas_20260314T192732_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_V0704_Cas_20260314T192548_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_V0774_Cas_20260314T192741_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_V0778_Cas_20260314T193158_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_V1028_Cyg_20260314T193207_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_V1143_Cyg_20260314T193426_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_V1405_Cas_20260314T193413_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_V416_Dra_20260314T193342_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_V713_Cep_20260314T192623_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_VW_UMa_20260314T193400_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_VX_Cep_20260314T193233_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_VY_UMa_20260314T193417_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_V_Cas_20260314T193145_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_WZ_Cas_20260314T192706_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_W_And_20260314T193031_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_W_Cas_20260314T193312_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_W_Cep_20260314T192750_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_W_Dra_20260314T192842_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_XX_Per_20260314T193430_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_XZ_Cyg_20260314T193101_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_XZ_Dra_20260314T192640_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_X_Cam_20260314T192719_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_YZ_Cnc_20260314T192636_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_Y_Per_20260314T192803_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_Z_Cam_20260314T192952_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_Z_UMa_20260314T193044_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_eps_Aur_20260314T192737_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_miu_Cep_20260314T193321_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_mu._Cep_20260314T193325_Raw.fits | N/A | No objective defined. |
| data/local_buffer/SIM_psi_1_Aur_20260314T192539_Raw.fits | N/A | No objective defined. |
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
