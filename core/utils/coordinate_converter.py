#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/utils/coordinate_converter.py
Version: 1.2.1
Objective: Ensures data validity by converting sexagesimal AAVSO coordinates into decimal degrees, appending #objective to JSON writes.
"""

import os
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Librarian_Coords")

def hms_to_deg(hms):
    try:
        parts = hms.split(':')
        h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
        return (h + m/60 + s/3600) * 15
    except Exception: 
        return None

def dms_to_deg(dms):
    try:
        parts = dms.split(':')
        d = float(parts[0])
        m = float(parts[1])
        s = float(parts[2])
        sign = -1 if parts[0].strip().startswith('-') else 1
        return d + (sign * m/60) + (sign * s/3600)
    except Exception: 
        return None

def process_library():
    seq_dir = os.path.expanduser('~/seevar/data/comp_stars')
    if not os.path.exists(seq_dir): return
    
    files = [f for f in os.listdir(seq_dir) if f.endswith('.json')]
    updated_count = 0
    
    for filename in files:
        path = os.path.join(seq_dir, filename)
        with open(path, 'r+') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                continue
                
            modified = False
            
            t = data.get("target", {})
            if "ra_deg" not in t and t.get("ra_hms"):
                t["ra_deg"] = round(hms_to_deg(t["ra_hms"]), 6)
                t["dec_deg"] = round(dms_to_deg(t["dec_dms"]), 6)
                modified = True
            
            comps = data.get("comparison_stars", [])
            for comp in comps:
                if "ra_deg" not in comp:
                    comp["ra_deg"] = round(hms_to_deg(comp["ra"]), 6)
                    comp["dec_deg"] = round(dms_to_deg(comp["dec"]), 6)
                    modified = True
            
            if modified:
                # Inject the objective tag per requirements
                data["#objective"] = "Coordinate data enriched with decimal degrees for processing."
                f.seek(0)
                json.dump(data, f, indent=4)
                f.truncate()
                updated_count += 1

    logger.info(f"✅ Librarian: Processed {len(files)} files. Updated {updated_count} with decimal coords.")

if __name__ == "__main__":
    process_library()
