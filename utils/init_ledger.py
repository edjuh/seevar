#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: utils/init_ledger.py
Version: 1.5.3 (Federation Standard)
Objective: Initializes the master Ledger with proper headers and PENDING status.
"""

import json
from pathlib import Path
from datetime import datetime

def initialize():
    root = Path(__file__).resolve().parents[1]
    targets_path = root / "data/targets.json"
    ledger_path = root / "data/ledger.json"

    # 1. Load the Master Cargo
    with open(targets_path, 'r') as f:
        data = json.load(f)
    
    # Handle both list and dict-wrapped targets
    targets = data if isinstance(data, list) else data.get("targets", [])

    # 2. Build the Dict-Based Ledger (The Register)
    ledger = {
        "header": {
            "objective": "Master Observational Register and Status Ledger",
            "federation_version": "1.5.0",
            "last_updated": datetime.now().isoformat(),
            "target_count": len(targets)
        },
        "entries": {}
    }

    # 3. Populate entries (The 'Bookmark' starts here)
    for t in targets:
        name = t.get('star_name') or t.get('name', 'Unknown')
        ledger["entries"][name] = {
            "status": "PENDING",
            "last_success": None,
            "attempts": 0,
            "priority": "NORMAL"
        }

    # 4. Save to RAID1
    with open(ledger_path, 'w') as f:
        json.dump(ledger, f, indent=4)
    
    print(f"✅ Ledger Initialized: {len(ledger['entries'])} targets registered.")

if __name__ == "__main__":
    initialize()
