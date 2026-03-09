#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/ledger_manager.py
Version: 2.1.1
Objective: The High-Authority Mission Brain. Manages target cadence and observation history.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger("Ledger")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEDGER_FILE = PROJECT_ROOT / "data" / "ledger.json"
FEDERATED_CATALOG = PROJECT_ROOT / "catalogs" / "federation_catalog.json"
TONIGHTS_PLAN = PROJECT_ROOT / "data" / "tonights_plan.json"

STANDARD_CADENCE_DAYS = 3

def load_json(path):
    if not path.exists(): return {}
    with open(path, 'r') as f:
        return json.load(f)

def save_json(path, data, objective):
    header = {
        "objective": objective,
        "last_updated": datetime.now().isoformat(),
        "schema_version": "2026.1"
    }
    output = {"metadata": header, "entries": data}
    with open(path, 'w') as f:
        json.dump(output, f, indent=4)

def execute_ledger_sync():
    # 1. Intake - Robust handling for list or dict
    catalog_raw = load_json(FEDERATED_CATALOG)
    if isinstance(catalog_raw, list):
        targets = catalog_raw
    else:
        targets = catalog_raw.get("data", [])
    
    # 2. Load Ledger
    ledger_raw = load_json(LEDGER_FILE)
    entries = ledger_raw.get("entries", {})
    
    now = datetime.now()
    due_names = []
    
    # 3. Sync and Cadence
    for t in targets:
        name = t['name'].replace(" ", "_").upper()
        if name not in entries:
            entries[name] = {
                "status": "PENDING",
                "last_success": None,
                "attempts": 0,
                "priority": "NORMAL"
            }
        
        last_success = entries[name].get("last_success")
        if not last_success:
            due_names.append(name)
        else:
            last_date = datetime.fromisoformat(last_success)
            if now - last_date > timedelta(days=STANDARD_CADENCE_DAYS):
                due_names.append(name)

    # 4. Apply to Tonight's Plan
    plan_data = load_json(TONIGHTS_PLAN)
    # Handle list vs dict for the plan as well
    visible_targets = plan_data if isinstance(plan_data, list) else plan_data.get("targets", [])
    
    due_plan = [t for t in visible_targets if t['name'].replace(" ", "_").upper() in due_names]
    
    # 5. Save
    save_json(LEDGER_FILE, entries, "Master Observational Register and Status Ledger")
    
    # Standardize the plan output to Dict format
    final_plan = {
        "metadata": {
            "objective": "Tactical flight plan filtered by Ledger Cadence.",
            "generated": now.isoformat(),
            "due_count": len(due_plan)
        },
        "targets": due_plan
    }
    
    with open(TONIGHTS_PLAN, 'w') as f:
        json.dump(final_plan, f, indent=4)

    logger.info(f"✅ Ledger Sync Complete: {len(due_plan)} targets marked as 'DUE'.")

if __name__ == "__main__":
    execute_ledger_sync()
