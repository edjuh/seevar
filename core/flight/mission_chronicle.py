#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/flight/mission_chronicle.py
Version: 4.1.1
Objective: Orchestrates the Sovereign funnel from Library Purge to Ledger Sync to Flight.
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
    # 1. Purge corruption from raw charts
    run_step("Janitor", "utils/comp_purger.py")

    # 2. Synchronize Library and Validate Charts
    run_step("Librarian", "core/preflight/librarian.py")

    # 3. Filter targets by Horizon/Visibility
    run_step("Planner", "core/preflight/nightly_planner.py")

    # 4. Filter by Ledger Cadence
    run_step("Ledger Sync", "core/preflight/ledger_manager.py")

    logger.info("🏁 Preflight sequence complete. Mission is ready for injection.")

if __name__ == "__main__":
    main()
