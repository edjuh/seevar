#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#Objective: Enforces scientific cadence. Cross-references targets with ledger.json.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

def run_audit():
    project_root = Path(__file__).parent.parent.parent
    master_path = project_root / "data/targets.json"
    ledger_path = project_root / "data/ledger.json" # Historical record

    if not master_path.exists():
        print("[AUDIT] Master Catalog not found. Run Librarian first.")
        return

    # Create dummy ledger if missing to avoid failure
    if not ledger_path.exists():
        with open(ledger_path, 'w') as f:
            json.dump([], f)

    with open(master_path, 'r') as f:
        master = json.load(f)
    with open(ledger_path, 'r') as f:
        ledger = json.load(f)

    # CADENCE: Skip if observed in last 72 hours
    threshold = datetime.now() - timedelta(hours=72)
    
    # Track which targets have recent hits in the ledger
    recent_stars = {entry['name'] for entry in ledger 
                    if datetime.strptime(entry.get('date', '2000-01-01'), '%Y-%m-%d') > threshold}

    for target in master:
        name = target.get('name')
        target['cadence_skip'] = name in recent_stars

    with open(master_path, 'w') as f:
        json.dump(master, f, indent=4)

    print(f"✅ Audit: Cadence filters applied to {len(master)} targets.")

if __name__ == "__main__":
    run_audit()
