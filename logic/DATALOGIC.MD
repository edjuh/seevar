# 🗄️ S30-PRO Federation: Data Logic Manifest

**Objective:** Defines the role, origin, and transformation logic for all JSON data structures within the RAID1 repository.

## 📊 The Six Pillars of Federation Data

| Filename | Creator Script | Role & Scientific Objective |
| :--- | :--- | :--- |
| `campaign_targets.json` | `harvester.py` | **The Raw Cargo.** Unfiltered harvest from AAVSO. Contains duplicates and lack Federation stamps. |
| `targets.json` | `librarian.py` | **The Research Catalog.** Deduplicated and objective-stamped master list of 409 unique stars. Immutable source of truth. |
| `observable_targets.json` | `librarian.py` | **The Menu.** Daily subset of the 409 stars physically above the horizon (>30°) during the Vampire Clock window. |
| `ledger.json` | `init_ledger.py` | **The Register.** Persistent record of `PENDING` vs `COMPLETED` status. Manages the 9-night backlog "Bookmark." |
| `tonights_plan.json` | `librarian.py` | **The Flight Contract.** Sliced subset (~45 stars) picked from the Menu for tactical execution during the dark period. |
| `system_state.json` | `orchestrator.py` | **Telemetry.** Volatile real-time state (Slewing, Integrating, Current Target) for the federation dashboard. |

## 🧬 Data Transformation Flow

1. **Harvesting:** Raw data arrives as `campaign_targets.json`.
2. **Curation:** `librarian.py` purifies the cargo into the 409-star `targets.json`.
3. **Reality Filter:** `librarian.py` checks astrophysical visibility to generate the `observable_targets.json` menu.
4. **Triage:** `librarian.py` consults the `ledger.json` (Register) to find the "Bookmark" and slices the next ~45 targets into `tonights_plan.json`.
5. **Execution:** `orchestrator.py` (Flight Master) integration begins.
6. **Reconciliation:** Morning reports update the Register, moving the backlog forward.

---
**Status:** Federation Standard 2026.03
