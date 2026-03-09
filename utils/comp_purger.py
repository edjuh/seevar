#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: utils/comp_purger.py
Version: 1.0.0
Objective: Prunes orphaned or corrupted comparison star charts to ensure a clean Librarian sync.
"""

import os
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger("Janitor")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REF_DIR = PROJECT_ROOT / "catalogs" / "reference_stars"

def purge_fluff():
    if not REF_DIR.exists():
        logger.info("📂 Reference directory not found. Nothing to purge.")
        return

    files = list(REF_DIR.glob("*.json"))
    purged = 0
    for f in files:
        # Example purge logic: remove files under 100 bytes (corrupted/empty)
        if f.stat().st_size < 100:
            f.unlink()
            purged += 1
    
    logger.info(f"🧹 Janitor: Cleaned {purged} corrupted chart files.")

if __name__ == "__main__":
    purge_fluff()
