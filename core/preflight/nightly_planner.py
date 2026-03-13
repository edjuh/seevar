#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/nightly_planner.py
Version: 2.6.1
Objective: Filters the audited Federation Catalog by Cadence, Horizon, and Altitude (Unified Config).
"""

import json, sys
from pathlib import Path
from datetime import datetime, timezone
from astropy.coordinates import SkyCoord, AltAz, EarthLocation
from astropy.time import Time
import astropy.units as u

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))

# FIX: Drop the broken gps_location and use unified env_loader
from core.utils.env_loader import load_config
from core.preflight.horizon import is_obstructed

DATA_DIR = PROJECT_ROOT / "data"
CATALOG_DIR = PROJECT_ROOT / "catalogs"
FEDERATION_CATALOG = CATALOG_DIR / "federation_catalog.json"
OUTPUT_PLAN = DATA_DIR / "tonights_plan.json"

def run_funnel():
    print(f"--- 🌌 INITIATING NIGHTLY TRIAGE ---")
    
    if not FEDERATION_CATALOG.exists():
        print(f"❌ Error: {FEDERATION_CATALOG.name} missing. Run Librarian first.")
        return

    # Pull dynamic horizon and coordinates from config
    cfg = load_config()
    min_alt = cfg.get("location", {}).get("horizon_limit", 30.0)
    lat = cfg.get("location", {}).get("lat", 0.0)
    lon = cfg.get("location", {}).get("lon", 0.0)
    elev = cfg.get("location", {}).get("elevation", 0.0)
        
    with open(FEDERATION_CATALOG, 'r') as f:
        data = json.load(f)
        targets = data.get("data", data.get("targets", [])) if isinstance(data, dict) else data
    
    loc = EarthLocation(lat=lat*u.deg, lon=lon*u.deg, height=elev*u.m)
    now = Time(datetime.now(timezone.utc))
    altaz_frame = AltAz(obstime=now, location=loc)
    
    tonight = []
    skipped_cadence = 0
    
    for t in targets:
        if t.get('cadence_skip', False):
            skipped_cadence += 1
            continue

        coord = SkyCoord(ra=t.get('ra', 0.0)*u.deg, dec=t.get('dec', 0.0)*u.deg, frame='icrs')
        altaz = coord.transform_to(altaz_frame)
        
        alt = float(altaz.alt.deg)
        az = float(altaz.az.deg)
        
        if alt < min_alt: continue
        if is_obstructed(az, alt): continue
        
        t['current_alt'] = round(alt, 2)
        tonight.append(t)
    
    print(f"[+] Total targets evaluated: {len(targets)}")
    print(f"[-] Deferred by Cadence Auditor: {skipped_cadence}")
    print(f"[=] Targets above {min_alt}° clear of obstructions: {len(tonight)}")

    plan_out = {
        "#objective": "Final nightly flight plan filtered by cadence, physical horizon, and altitude.",
        "metadata": {
            "generated": datetime.now().isoformat(),
            "schema_version": "2026.1",
            "target_count": len(tonight)
        },
        "targets": tonight
    }
    
    with open(OUTPUT_PLAN, 'w') as f:
        json.dump(plan_out, f, indent=4)
    print(f"✅ Flight Plan secured: {OUTPUT_PLAN.name}")

if __name__ == "__main__":
    run_funnel()
