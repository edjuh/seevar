#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seestar_organizer/core/preflight/audit.py
Version: 1.2.1
Objective: Enforces scientific cadence by cross-referencing the Federation catalog with ledger.json.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger("CadenceAudit")

def run_audit():
    # Structural path resolution
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    CATALOG_PATH = PROJECT_ROOT / "catalogs" / "federation_catalog.json"
    LEDGER_PATH = PROJECT_ROOT / "data" / "ledger.json"

    if not CATALOG_PATH.exists():
        logger.error(f"Federation Catalog missing at {CATALOG_PATH}. Run Librarian first.")
        return

    # Load Ledger (Historical Record)
    ledger = []
    if LEDGER_PATH.exists():
        try:
            with open(LEDGER_PATH, 'r') as f:
                data = json.load(f)
                # Handle standardized ledger structure with 'entries'
                ledger = data.get("entries", []) if isinstance(data, dict) else data
        except json.JSONDecodeError:
            logger.warning("Ledger corrupted. Starting fresh.")

    # Load Catalog
    with open(CATALOG_PATH, 'r') as f:
        catalog_data = json.load(f)
    
    targets = catalog_data.get("data", catalog_data.get("targets", [])) if isinstance(catalog_data, dict) else catalog_data
    now = datetime.now()

    # Define Cadence Windows
    priority_threshold = now - timedelta(hours=23)
    standard_threshold = now - timedelta(hours=71)

    # Build lookup of last observation dates from ledger
    last_obs_map = {}
    for entry in ledger:
        name = entry.get('name')
        try:
            obs_date = datetime.strptime(entry.get('date', '2000-01-01'), '%Y-%m-%d')
            if name not in last_obs_map or obs_date > last_obs_map[name]:
                last_obs_map[name] = obs_date
        except ValueError:
            continue

    updated_count = 0
    skipped_count = 0

    for target in targets:
        name = target.get('name')
        is_priority = target.get('priority', False)
        last_seen = last_obs_map.get(name)

        if not last_seen:
            target['cadence_skip'] = False
            continue

        limit = priority_threshold if is_priority else standard_threshold
        
        if last_seen > limit:
            target['cadence_skip'] = True
            skipped_count += 1
        else:
            target['cadence_skip'] = False
            updated_count += 1

    # Save standardized catalog back with Objective
    catalog_data["#objective"] = "Validated catalog updated with scientific cadence skip-logic."
    with open(CATALOG_PATH, 'w') as f:
        json.dump(catalog_data, f, indent=4)

    logger.info(f"✅ Cadence Audit Complete. Ready: {updated_count} | Skipped: {skipped_count}")

if __name__ == "__main__":
    run_audit()
