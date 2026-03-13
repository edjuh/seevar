#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/mission_chronicle.py
Version: 4.2.0
Objective: Orchestrates the Preflight Funnel (Janitor -> Librarian -> Auditor -> Planner).
"""

import subprocess
import sys
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger("Chronicle")

PROJECT_ROOT = Path(__file__).resolve().parents[2]

def run_step(name, script_path):
    logger.info(f"🚀 Executing {name}...")
    full_path = PROJECT_ROOT / script_path
    result = subprocess.run([sys.executable, str(full_path)])
    if result.returncode != 0:
        logger.error(f"❌ {name} failed with exit code {result.returncode}")
        sys.exit(1)

def main():
    print("\n" + "="*50)
    print(" 📡 SEEVAR FEDERATION: PREFLIGHT FUNNEL")
    print("="*50 + "\n")

    # 1. Purge corruption from raw charts
    run_step("Janitor", "utils/comp_purger.py")

    # 2. Synchronize Library (Read AAVSO Haul -> Output Federation Catalog)
    run_step("Librarian", "core/preflight/librarian.py")

    # 3. Cross-reference Federation Catalog against ledger.json
    run_step("Cadence Auditor", "core/preflight/audit.py")

    # 4. Filter strictly by Horizon/Visibility/Cadence -> Output tonights_plan.json
    run_step("Nightly Planner", "core/preflight/nightly_planner.py")

    logger.info("🏁 Preflight sequence complete. The Flight Plan is locked.")

if __name__ == "__main__":
    main()
