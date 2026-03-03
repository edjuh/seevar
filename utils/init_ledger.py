#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: utils/init_ledger.py
Version: 1.5.1 (Resilient Ledger)
Objective: Initializes the persistent Register (ledger.json) from the master target list.
"""

import json
from pathlib import Path
from datetime import datetime

def initialize():
    root = Path(__file__).resolve().parents[1]
    targets_path = root / "data/targets.json"
    ledger_path = root / "data/ledger.json"

    if not targets_path.exists():
        print(f"❌ Master list missing: {targets_path}")
        return

    with open(targets_path, 'r') as f:
        master_data = json.load(f)
    
    # Logic: Handle both Wrapped Dict and Raw List formats
    if isinstance(master_data, dict):
        targets = master_data.get("targets", [])
    elif isinstance(master_data, list):
        targets = master_data
    else:
        print("❌ Unknown data format in targets.json")
        return
    
    # Define the Scientific Grade Register
    ledger = {
        "header": {
            "objective": "Master Observational Register and Status Ledger",
            "federation_version": "1.5.0",
            "initialized_at": datetime.now().isoformat(),
            "target_count": len(targets)
        },
        "entries": {}
    }

    # Populate the entries with the 'Bookmark' state
    for t in targets:
        # Use star_name (AAVSO) or name (Generic)
        name = t.get('star_name') or t.get('name', 'Unknown')
        ledger["entries"][name] = {
            "status": "PENDING",
            "last_success": None,
            "attempts": 0,
            "priority": "NORMAL"
        }

    with open(ledger_path, 'w') as f:
        json.dump(ledger, f, indent=4)
    
    print(f"✅ Ledger created at {ledger_path}")
    print(f"✅ Registered {len(ledger['entries'])} targets.")

if __name__ == "__main__":
    initialize()
