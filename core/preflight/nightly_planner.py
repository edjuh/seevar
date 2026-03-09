#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seestar_organizer/core/preflight/nightly_planner.py
Version: 2.5.3
Objective: Executes the 6-step filtering funnel using the Federated Catalog. Dynamically pulls horizon limits from config.
"""

import json, sys, tomllib
from pathlib import Path
from datetime import datetime, timezone
from astropy.coordinates import SkyCoord, AltAz
from astropy.time import Time
import astropy.units as u

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))

from core.preflight.gps import gps_location
from core.preflight.horizon import is_obstructed

# Path Configuration
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_PATH = PROJECT_ROOT / "config.toml"
CATALOG_DIR = PROJECT_ROOT / "catalogs"
FEDERATION_CATALOG = CATALOG_DIR / "federation_catalog.json"
OUTPUT_PLAN = DATA_DIR / "tonights_plan.json"

def run_funnel():
    print(f"--- 🌌 INITIATING NIGHTLY TRIAGE ---")
    
    if not FEDERATION_CATALOG.exists():
        print(f"❌ Error: {FEDERATION_CATALOG.name} missing. Run Librarian first.")
        return

    # Pull dynamic horizon limit from config
    try:
        with open(CONFIG_PATH, "rb") as f:
            cfg = tomllib.load(f)
            min_alt = cfg.get("location", {}).get("horizon_limit", 30.0)
    except Exception:
        min_alt = 30.0
        
    with open(FEDERATION_CATALOG, 'r') as f:
        data = json.load(f)
        targets = data.get("data", data.get("targets", [])) if isinstance(data, dict) else data
    
    print(f"[1-3] Validated targets from Librarian: {len(targets)}")

    loc = gps_location.get_earth_location()
    now = Time(datetime.now(timezone.utc))
    altaz_frame = AltAz(obstime=now, location=loc)
    
    tonight = []
    for t in targets:
        coord = SkyCoord(ra=t.get('ra', 0.0)*u.deg, dec=t.get('dec', 0.0)*u.deg, frame='icrs')
        altaz = coord.transform_to(altaz_frame)
        
        alt = altaz.alt.deg
        az = altaz.az.deg
        
        if alt < min_alt: continue
        if is_obstructed(az, alt): continue
        
        t['current_alt'] = round(alt, 2)
        tonight.append(t)
    
    print(f"[4/5] Targets above {min_alt}° and clear of obstructions: {len(tonight)}")

    plan_out = {
        "#objective": "Initial nightly flight plan filtered by physical horizon and altitude.",
        "metadata": {
            "generated": datetime.now().isoformat(),
            "schema_version": "2026.1",
            "target_count": len(tonight)
        },
        "targets": tonight
    }
    
    with open(OUTPUT_PLAN, 'w') as f:
        json.dump(plan_out, f, indent=4)
    print(f"[6] Flight Plan secured: {OUTPUT_PLAN}")

if __name__ == "__main__":
    run_funnel()
