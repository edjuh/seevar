#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/audit.py
Version: 1.4.0
Objective: Enforces scientific cadence (1/20th rule) by properly parsing ledger dictionaries.

Changes from v1.3.1:
  - Guard against targets with missing name field
  - Fixed dead-code fallback in ledger lookup (safe_name only, no raw name)
  - Guard against catalog JSON read failure
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger("CadenceAudit")

def run_audit():
    PROJECT_ROOT = Path("/home/ed/seevar")
    CATALOG_PATH = PROJECT_ROOT / "catalogs" / "federation_catalog.json"
    LEDGER_PATH = PROJECT_ROOT / "data" / "ledger.json"

    if not CATALOG_PATH.exists():
        logger.error(f"Federation Catalog missing at {CATALOG_PATH}. Run Librarian first.")
        return

    # Load ledger
    ledger = {}
    if LEDGER_PATH.exists():
        try:
            with open(LEDGER_PATH, 'r') as f:
                data = json.load(f)
                ledger = data.get("entries", {}) if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            logger.warning("Ledger corrupted. Starting fresh.")

    # Load catalog
    try:
        with open(CATALOG_PATH, 'r') as f:
            catalog_data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Failed to read catalog: {e}")
        return

    targets = catalog_data.get("data", catalog_data.get("targets", [])) if isinstance(catalog_data, dict) else catalog_data
    now = datetime.now()

    # Build last-observation map from ledger (keys are already safe_names)
    last_obs_map = {}
    for safe_name, entry_data in ledger.items():
        if not isinstance(entry_data, dict):
            continue
        last_success = entry_data.get('last_success')
        if not last_success:
            continue
        try:
            obs_date = datetime.fromisoformat(str(last_success).replace('Z', '+00:00')).replace(tzinfo=None)
            if safe_name not in last_obs_map or obs_date > last_obs_map[safe_name]:
                last_obs_map[safe_name] = obs_date
        except Exception:
            continue

    updated_count = 0
    skipped_count = 0
    bad_count = 0

    for target in targets:
        name = target.get('name')
        if not name:
            bad_count += 1
            continue

        # Ledger keys are stored as safe_names — match that format
        safe_name = name.replace(" ", "_").upper()
        last_seen = last_obs_map.get(safe_name)

        if not last_seen:
            target['cadence_skip'] = False
            updated_count += 1
            continue

        rec_days = target.get('recommended_cadence_days', 3)
        limit = now - timedelta(days=rec_days)

        if last_seen > limit:
            target['cadence_skip'] = True
            skipped_count += 1
        else:
            target['cadence_skip'] = False
            updated_count += 1

    catalog_data["#objective"] = "Validated catalog updated with scientific cadence skip-logic."
    with open(CATALOG_PATH, 'w') as f:
        json.dump(catalog_data, f, indent=4)

    logger.info(f"✅ Cadence Audit Complete. Ready: {updated_count} | Deferred: {skipped_count}" +
                (f" | Bad entries: {bad_count}" if bad_count else ""))

if __name__ == "__main__":
    run_audit()
