#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: utils/test_coords.py
Objective: Verifies target acquisition readiness for existing decimal coordinates.
"""

import json
from pathlib import Path

def test():
    path = Path("~/seestar_organizer/data/targets.json").expanduser()
    with open(path, 'r') as f:
        data = json.load(f)
    
    targets = data.get("targets", [])[:5]
    print(f"📡 Testing Coordinate Integrity for {len(targets)} targets...")
    
    for t in targets:
        name = t.get("star_name") or t.get("name")
        ra = t.get("ra")
        dec = t.get("dec")
        
        status = "✅" if isinstance(ra, (int, float)) else "❌"
        # Format strings now handle floats correctly
        print(f"{status} {name:15} | RA: {ra:8.4f} | Dec: {dec:8.4f}")

if __name__ == "__main__":
    test()
