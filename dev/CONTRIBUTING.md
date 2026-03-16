# 🤝 Contributing to the Seestar Federation

> **Objective:** Defines the strict technical standards, workflow protocols, and "Garmt" purified header requirements for all project contributors (AI or Human).
> **Version:** 1.2.0 (Garmt)

Welcome to the Rommeldam architectural tradition. To maintain the stability of the S30-PRO observatory, all contributions must adhere to the following "Regelen van het Fatsoen" (Rules of Decorum).

## 🏰 1. The Purified Header Standard
Every Python file (`.py`) MUST begin with a PEP 257 docstring. No exceptions. This prevents "AI Tripping" and ensures functional clarity.
* **Filename:** The relative path from root.
* **Version:** Current Epoch (e.g., 1.2.0 Garmt).
* **Objective:** A single, unclipped sentence defining the file's primary responsibility.

## 🛰️ 2. Architectural Pillars
All new logic must be categorized into one of the three established pillars:
1.  **🛫 PREFLIGHT**: Data harvesting, vetting, and scheduling (Hardware remains OFF).
2.  **🚀 FLIGHT**: Hardware orchestration, slewing, and integration via sovereign TCP port 4700 (JSON-RPC). No Alpaca bridge. <!-- SeeVar-contrib-v1.6.0 -->
3.  **🧪 POSTFLIGHT**: Data syncing, photometry, and AAVSO reporting.

## 🏮 3. Core Logic Constraints
* **The Aperture Grip**: New selectors must respect the Westward Priority (Azimuth 180°-350°) to ensure science-grade photons are captured before targets set.
* **Throttling**: Any script hitting the AAVSO VSP API must implement the mandatory **188.4s (Pi-Minute)** sleep to prevent IP throttling. Pi IP was hard-blocked by AAVSO at 3.14s on 2026-03-13.
* **Path Integrity**: Never hardcode paths. Resolve all directories via `config.toml` to support the Lifeboat/RAID1 storage model.

## 🛠️ 4. The Pull Request (Git) Protocol
1.  Verify the **Logic Hub** links in `logic/README.md` are intact.
2.  Ensure `main.py` remains the only primary execution entry point for the daemon.
3.  Commit messages must reference the current Milestone (e.g., "Garmt: Added PSF fitting to Analyst").

"Wij handelen hier volgens de regelen van het fatsoen!"
