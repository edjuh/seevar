#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: utils/coordinate_converter.py
Version: 1.2.0 (Pee Pastinakel)
Objective: Ensures data validity by converting sexagesimal AAVSO coordinates into decimal degrees for internal computational use and plate-solving.
"""

import os
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Librarian_Coords")

def hms_to_deg(hms):
    try:
        h, m, s = map(float, hms.split(':'))
        return (h + m/60 + s/3600) * 15
    except: return None

def dms_to_deg(dms):
    try:
        parts = dms.split(':')
        d = float(parts)
        m = float(parts)
        s = float(parts)
        sign = -1 if parts.strip().startswith('-') else 1
        return d + (sign * m/60) + (sign * s/3600)
    except: return None

def process_library():
    seq_dir = os.path.expanduser('~/seestar_organizer/data/comp_stars')
    if not os.path.exists(seq_dir): return
    
    files = [f for f in os.listdir(seq_dir) if f.endswith('.json')]
    updated_count = 0
    
    for filename in files:
        path = os.path.join(seq_dir, filename)
        with open(path, 'r+') as f:
            data = json.load(f)
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
                f.seek(0)
                json.dump(data, f, indent=4)
                f.truncate()
                updated_count += 1

    logger.info(f"✅ Librarian: Processed {len(files)} files. Updated {updated_count} with decimal coords.")

if __name__ == "__main__":
    process_library()
