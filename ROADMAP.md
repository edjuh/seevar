# 🗺️ S30-PRO Development Roadmap: The Rommeldam Epic

> **Objective:** Tracks the architectural journey and future versioning milestones of the Seestar Federation, mapped to the characters of Marten Toonder's universe.
> **Version:** 3.0.0 (Snotolf)

This document outlines the architectural journey of the S30-PRO autonomous observatory, structurally mapped to the characters of Marten Toonder's universe.

## ✅ Past Milestones (The Foundation)
* **v0.0 Beunhaas:** Environment Validation.
* **v0.1 Brigadier Snuf:** The State Engine.
* **v0.2 Zedekia Zwederkoorn:** The Alpaca Bridge Patch.
* **v0.3 Joris Goedbloed:** Target Acquisition.
* **v0.4 Zachtzalver:** Command Translation.
* **v0.5 Hiep Hieper:** The Orchestrator (The Golden Bridge).
* **v0.6 Insp. Priembickel:** Hardening and Git strictness.
* **v0.7 Argus:** The all-seeing autonomous observer.
* **v0.8 Lieven Brekel:** Mid-sequence weather aborts and WCS bridge hardening.
* **v0.9 Terpen Tijn:** "Het is prut!" Westward priority active. Sub-pixel centroiding, dynamic CFA debayering, and stable Alpaca handshake for AAVSO targets.
* **v1.0 Kwetal:** Converting the Orchestrator into a bulletproof `systemd` background daemon.
* **v1.1 Pee Pastinakel:** Dynamic aperture scaling (PSF fitting) and saturation detection.
* **v1.2 Garmt:** Unified PEP 257 standardization. "Standardization Reaper" and full-sentence objective integration.
* **v1.3 Monkel:** The Discovery Phase. Daemon interruption fixes and Ziggo-subnet home/field detection.
* **v1.4 Kriel:** gpsd integration, dynamic 6-char Maidenhead. Alpaca communication centralization. Sovereign TCP path established.
* **v1.5 Humpie:** Storage and wear strategy. OS on SD, app and data on RAID1 USB array, live state in RAM (/dev/shm), NAS failover via rsync.
* **v1.6 Jochem:** Giving the background workers a bigger role. Cadence filter, ledger_manager, fleet_mapper sovereign TCP, full simulation end-to-end confirmed S1–S7 and T1–T7.
* **v1.7 Oene:** **The Clean Slate Milestone (March 2026).** Full reinstallation verified on fresh Bookworm SD card.
  - bootstrap.sh v1.3.1 — user-level systemd, GPS service, clear-outside-apy, horizon mask seeded
  - config.toml.example v2.0.0 — all sections complete, [weather] thresholds, [knmi] section, cadence config
  - INSTALL.md — tester-facing installation guide
  - AAVSO Extended Format reporter v1.2.0 — full 15-field format, WebObs 2.0 preview tested
  - JD header added to sovereign_stamp in pilot.py
  - BRIDGE LED removed from dashboard (ALP retired)
  - Flat horizon mask (15° all-round) seeded at install — replaced at first light
  - horizon.py v2.0.0 — per-degree profile, linear interpolation, best_windows()
  - weather.py v1.7.0 — tri-source consensus: open-meteo + Clear Outside + KNMI EDR
  - Weather evaluates only within astronomical dark window (skyfield)
  - KNMI EDR API — measured cloud oktas, visibility, present weather from Schiphol
  - ledger_manager.py v2.2.1 — dynamic 1/20th cadence from config.toml
  - hardware_loader.py v1.1.0 — Alpaca UDP discovery + HTTP fingerprint (FIRST LIGHT REQUIRED)
  - dashboard.py — config path fixed (seestar_organizer fossil removed)
  - GPLv3 LICENSE added — cgobat's recommendation accepted
  - CONTRIBUTING.md — public facing, Asthonising Automated Variable Star Observatory tagline
  - GitHub topics, description, INSTALL one-liner
  - Testers: Arenda (tester #1), Boyce-Astro introduction, Metius presentation (March 2026, well received)

---

## 🌲 Epoch 1: Het Kleine Volkje (v1.x)
*The invisible, tireless workers in the background. Focuses on system resilience and background magic.*

* **v1.8 Snotolf:** **The Hardware Whisperer.** An authentic, slightly spicy underlying system change.
  - ✅ Weather veto wired into orchestrator _run_idle — RAIN/FOGGY/WINDY abort session
  - ✅ Weather logic redesigned — cloud cover is warning only, never abort (v1.8.0)
    - Hard abort: rain, snow, hail, fog (measured + forecast), thunderstorm, wind
    - Per-hour evaluation across dark window replaces window_max worst-case
    - Best contiguous imaging window reported as imaging_window_start/end
    - Orchestrator reads imaging_go: true/false — not status string
  - ✅ link_status wired from orchestrator telemetry into dashboard (WAITING → ONLINE at first light)
  - ✅ field_rotation.py v1.0.0 — Young's approximation, max safe exposure per az/alt/lat
  - ✅ exposure_planner.py v1.2.0 — three-way cap (SNR/saturation/field rotation), chunking, scintillation noise
  - ✅ bootstrap.sh v1.4.0 — full preflight pipeline runs on install (librarian → audit → planner → compiler)
  - ✅ kaspar_animation.py v2.0.0 — Manim 1080p60 pipeline animation, YouTube: https://youtu.be/qG439gE7UBo
  - ✅ PRESENTATION.md — speaker's guide + session notes, docs/PRESENTATION.md
  - ✅ pilot.py v1.7.0 — ID-matched ControlSocket, Event telemetry filtering
  - ✅ seetop.py v1.1.1 — ncurses live observatory dashboard
  - ✅ .github/workflows/basic-checks.yml — CI on every PR
  - ✅ CONTRIBUTING.md updated — Garmt header format, architecture rules explicit
  - ✅ **THE ALPACA BREAKTHROUGH (2026-03-30)**
    - ZWO's official Alpaca driver (v1.2.0-3) runs inside the S30-Pro firmware on port 32323
    - Full telescope control confirmed: slew, track, park, unpark, pulse guide
    - Full camera control confirmed: gain, exposure, 8.3MP image download (2160×3840)
    - Filter wheel, focuser, dew heater switch — all accessible
    - **No phone app required. No session master lock. No JSON-RPC encryption.**
    - Port 4700 lockout was a red herring — the official REST API was open the entire time
    - Confirmed working without any ZWO cooperation or special access
  - ✅ **pilot.py v3.0.0 — Full Alpaca REST rewrite**
    - Replaces TCP ControlSocket (port 4700) and ImageSocket (port 4801)
    - AlpacaTelescope, AlpacaCamera, AlpacaFilterWheel client classes
    - Same DiamondSequence interface — FSM and orchestrator need zero changes
    - Acquire sequence A1-A7: slew → settle → gain → expose → wait → download → FITS
    - 33s JSON image transfer for 8.3MP (LAN) — acceptable for science cadence
  - ✅ **Satellite files updated for Alpaca:**
    - camera_control.py v3.0.0 — Alpaca management API health check
    - hardware_audit.py v3.0.0 — Alpaca telescope/camera telemetry reads
    - dark_library.py v2.0.0 — FilterWheel Dark position + Camera expose
    - neutralizer.py v2.0.0 — Alpaca Park command
    - hardware_loader.py — port 4700 → 32323
    - fleet_mapper.py — alpaca_port added to schema
  - ✅ **Confirmed S30-Pro Alpaca device map (port 32323):**
    - Telescope #0: Seestar Wilhelmina Telescope
    - Camera #0: Seestar Wilhelmina Telephoto Camera (IMX585, 3840×2160, 2.9µm)
    - Camera #1: Seestar Wilhelmina Wide Angle Camera (IMX586, 3840×2160)
    - Focuser #0: Seestar Wilhelmina Telephoto Focuser
    - Focuser #1: Seestar Wilhelmina Wide Angle Focuser
    - FilterWheel #0: Seestar Wilhelmina Filter Wheel (Dark/IR/LP)
    - Switch #0: Seestar Wilhelmina Switch (dew heater)
  - ✅ **Optics confirmed:**
    - Telephoto: 160mm f/5.3, 30mm aperture, quadruplet APO with ED element
    - Wide angle: 6mm, ultra-wide context camera
    - Pixel scale: 3.74 arcsec/pixel (telephoto)
    - Bayer: GRBG, offset (1,0)
  - ✅ exposure_planner.py — FOCAL_LENGTH_MM corrected 150 → 160
  - Hardware auto-detection via Alpaca UDP + HTTP fingerprint — confirm FIRST LIGHT markers
  - Camera-based automatic horizon profiling at first light
  - Flat frames pipeline (currently darks only)
  - Dew heater control — now accessible via Alpaca Switch #0
  - Pi Zero 2W / CM5 inside Seestar — sovereign at silicon level (research phase)
  - All-sky camera — wide angle, one frame/min, cloud cover from brightness variance
  - INA219 power monitoring — current draw, motor stall detection
  - GPS on one Seestar, broadcast fix over LAN to all federation instances
  - Weather forced refresh at dusk — sentinel wakes 30min before dark window
  - **G1/G2 green channel balance diagnostic** — peer review (March 2026)
  - **WilhelminaMonitor (port 4700) retained for battery/charger telemetry**
    - Alpaca does not expose battery_pct or charger_status
    - Event stream listener continues to feed dashboard vitals
    - pilot.py TelemetryBlock.battery_pct populated from dashboard state, not Alpaca
  - `vsx_catalog.py` restart resilience — nohup job dies on reboot, no auto-restart

* **v1.9 Fliep:** **The Deployment Master — Global Edition.**
  - `config_wizard.py` — re-runnable interactive config tool using tomli_w
  - Kiosk display service (Pi 4 — Pi 3 too slow)
  - KNMI waarschuwingen-nederland-48h — weather warnings as hard abort trigger
  - `vsx_catalog.py` — add systemd service for restart resilience (currently nohup only)
  - **Bortle auto-resolve from GPS coordinates**
  - **Binary image transfer** — Alpaca v3 ImageBytes for faster downloads
    - Current: 33s JSON for 8.3MP
    - Target: <5s binary transfer
    - Requires Alpaca ImageBytes support in ZWO firmware (request via forum)

  **Southern Hemisphere Support:**
  - `hemisphere` flag in config.toml (`northern` / `southern`, auto-detected from lat)
  - Westward priority flips to Eastward in Southern hemisphere (targets transit North)
  - `catalog_localiser.py` — declination-band aware, pulls targets for observer's actual sky
  - Weather sources — regional selection based on location
  - Moon avoidance — Southern hemisphere awareness
  - Dashboard flight window — local time display correct globally via astimezone()

  **General Deployment Gaps:**
  - `clear-outside-apy` — coverage limited to Europe/N.America, fallback needed for other regions
  - bootstrap.sh — add hemisphere auto-detection from lat, warn if Southern
  - INSTALL.md — Southern hemisphere section
  - astrometry index files — FOV-matched, correct globally

---

## ☕ Epoch 2: The Women of Rommeldam (v2.x)
*The caretakers and organizers. Focuses on bringing order, analysis, and presentation to the raw data.*

* **v2.0 Anne Marie Doddel:** **The Hardened Observatory.** Real-time photometric analysis, hardware hardening, and beautiful AAVSO light-curves. First light with Wilhelmina (S30-Pro, April 2026).
  - Vignetting correction — flat-field pipeline fully operational, per-frame correction in `aperture_flux`
  - G1/G2 balance constant applied if diagnostic confirms imbalance > 1%
  - `numba @jit` benchmark on `aperture_flux` mask operations
  - **Comparison star reconciliation** — Gaia DR3 vs AAVSO VSP
  - **Alpaca plan upload** — tom-dd132's UploadSeestarPlan proposal (ZWO forum)
    - If ZWO implements custom Alpaca Actions, SeeVar can push plans natively
    - Current workaround: direct slew+expose per target (working)

* **v2.1 Anne-Miebetje:** The classic first sub-version refinement.
* **v2.2 Wobbe:** A highly stable, technical build.
* **v2.3 Wolle:** Dedicated to visual graph and plot updates.
* **v2.4 Irma:** *(Irma de vlieg)* That one tiny, annoying bug fix.
* **v2.5 Prettig:** A major UX and ease-of-use improvement.
* **v2.6 Zonnetje:** An optimistic feature-release.
* **v2.7 Agatha:** *(Vrouw Dickerdack)* A more "official" or business-grade build.
* **v2.8 Georgette:** *(Vrouw Grootgrut)* Heavy focus on new data integration. Anna (S30-Pro #2) joins the federation.
* **v2.9 Tante Pollewop:** The final loving polish.

---

## 🧠 Epoch 3: De Medici & Analisten (v3.x)
*Focuses on the "health," logic, and psychological stability of the code.*
* **v3.0 Zielknijper:** The basis for the psychological stability of the code.
* **v3.1 Galzalver:** Plasters for the small wounds (hotfixes).
* **v3.2 Dr. Plus:** Added value and positive data-processing results.
* **v3.3 Alexander Pieps:** Refined data analysis down to the square millimeter.
* **v3.4 Sickbock:** Boundary-pushing (and risky) experimental features.
* **v3.5 Okke Zielzoeker:** Deep-diving into user analytics.
* **v3.6 Dr. Baboen:** Solid medical support under the hood.

---

## 🏛️ Epoch 4: De Bureaucratie & Middenstand (v4.x)
*Focuses on rules, administration, and AAVSO compliance.*
* **v4.0 Ambtenaar Dorknoper:** *"Dat is buiten de voorschriften."* Strict AAVSO compliance, immutable audit logs, and official submissions.
* **v4.1 Bulle Bas:** Enforcement of security and protocols.
* **v4.2 Notaris Canteclaer:** The fine print and legally correct handling.
* **v4.3 Dickerdack:** The mayor keeping the entire pipeline running smoothly.
* **v4.4 Grootgrut:** Inventory management and database handling.
* **v4.5 Pastuiven Verkwansel:** The secretary keeping the file systems ordered.
* **v4.6 Ambtenaar Plof:** Heavy lifting for massive datasets.
* **v4.7 Referendaris Lapsnuut:** The administrative finishing touch.

---

## 🍷 Epoch 5: De Adel & De Kleine Club (v5.x)
*Focuses on high-society UI/UX and elite processing. "Een release voor luyden van stand."*
* **v5.0 Markies de Canteclaer:** The place of honor. A GUI so refined the rabble won't understand it.
* **v5.1 Graaf van Zandbergen:** A solid, noble UI foundation.
* **v5.2 Baron de l'Esprit:** Refined, intellectual algorithms.
* **v5.3 Jonker Wip:** A light-footed, snappy UI update.
* **v5.4 Oud-majoor Buitenzorg:** Background discipline and memory management.
* **v5.6 De heer Steinhacker:** Industrial-grade optimizations for heavy capital logic.
* **v5.8 Notaris Fijn van Draad:** The perfect aristocratic administrative closure.

---

## 🔮 Epoch 6: Het Magische Bos (v6.x)
*Focuses on complex, inexplicable, and esoteric software forces.*
* **v6.0 Hocus Pas:** Where the true magic happens (machine learning/AI integration).
* **v6.1 Zwarte Zwadderneel:** Edge-cases and error handling. *Log requirement: System must state "Deze update is gedoemd te mislukken" on startup.*
* **v6.2 De Zwarte Raaf:** Mysterious, lightning-fast data transfer protocols.
* **v6.3 Oene de Reus:** Brute-forcing massive chunks of unstructured data.
* **v6.4 Argus de Draak:** Guarding the treasure room (advanced encryption/security).
* **v6.5 De Gnoom:** Deep, hidden underground scripts.
* **v6.6 De Heks van de Nevelvallei:** Advanced image filters peering through fog/clouds.
* **v6.7 Magister Morya:** Esoteric and highly abstract functions.

---

## 🔬 Epoch 7: De Wetenschappers & Fenomenologen (v7.x)
*Focuses on heavy mathematics, deep astrophysics, and phenomena.*
* **v7.0 Professor Prlwytzkofsky:** Phenomenological consistency of the night sky. *Log requirement: All fatal exceptions must be rendered in phonetic Polish ("Praw!").*
* **v7.4 Joachim Snerle:** Detecting "earthly" influences (atmospheric refraction compensation).

---

## 💰 Epoch 8: De Zware Jongens & De Handel (v8.x)
*Focuses on pure efficiency and data brokering. "Geld moet rollen!"*
* **v8.0 Bul Super:** The Boss. "Zaken zijn zaken." *Requirement: Bug reports only accepted if accompanied by a "commission."*
* **v8.1 Knol:** The muscle. Smashing through database bottlenecks.
* **v8.2 De Markelaar:** The broker. External API connections and data trading.
* **v8.3 De Lorreman:** Garbage collection and archiving. *Note: "Geen bug is te klein voor de handel."*
* **v8.5 O. Fanth Mzn:** The media magnate. Publishing and exporting final results to the web.
* **v8.6 Super-Hieper Transit:** Lightning-fast internal logistics and bus transfers.
* **v8.7 De Kassier:** The final financial and administrative wrap-up.
