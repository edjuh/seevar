#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seestar_organizer/core/preflight/aavso_fetcher.py
Version: 12.1.0
Objective: Step 1 - Haul AAVSO targets and strictly filter by 30-degree horizon physics, with metadata injection.
"""

import json
import requests
import sys
import logging
from datetime import datetime
from pathlib import Path

try:
    import tomllib
except ImportError:
    import toml as tomllib

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger("AAVSO_Step1")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.toml"
CATALOG_DIR = PROJECT_ROOT / "catalogs"
MASTER_HAUL_FILE = CATALOG_DIR / "campaign_targets.json"

# PHYSICS CONSTRAINTS
MAG_LIMIT = 15.0
# To reach 30 degrees altitude at 52.38N latitude:
# 30 = 90 - 52.38 + Dec -> Dec must be >= -7.62
MIN_DEC = -7.62  

def get_aavso_key():
    try:
        with open(CONFIG_PATH, "rb") as f:
            cfg = tomllib.load(f)
        return cfg.get("aavso", {}).get("target_key")
    except Exception:
        logger.error("❌ Failed to read target_key from config.toml")
        sys.exit(1)

def haul_and_filter(api_key):
    logger.info("📡 STEP 1: Hauling Master Target List from AAVSO...")
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    
    url = "https://targettool.aavso.org/TargetTool/api/v1/targets"
    
    try:
        res = requests.get(url, auth=(api_key, "api_token"), params={"obs_section": "all"}, timeout=30)
        res.raise_for_status()
        raw_targets = res.json().get("targets", [])
        
        targets = []
        valid_types = ["M", "SR", "LPV"]
        
        for t in raw_targets:
            star_name = t.get("star_name", "").strip()
            if not star_name: continue
                
            star_type = t.get("var_type", "").upper()
            is_slow = any(vt in star_type for vt in valid_types)
            
            try: mag = float(t.get("max_mag", 99.0))
            except: mag = 99.0
            
            try: dec = float(t.get("dec", -90.0))
            except: dec = -90.0
                
            # The triple gate: Slow Variable + Brighter than Mag 15 + Crosses 30-degree horizon
            if is_slow and mag <= MAG_LIMIT and dec >= MIN_DEC:
                targets.append({
                    "name": star_name,
                    "ra": t.get("ra", 0.0),
                    "dec": dec,
                    "type": star_type,
                    "mag_max": mag,
                    "priority": 2, 
                    "duration": 600
                })
                
        # Inject Sovereign Metadata
        output_data = {
            "metadata": {
                "objective": "Master haul of AAVSO targets filtered by 30-degree horizon physics.",
                "generated": datetime.now().isoformat(),
                "schema_version": "2026.1",
                "target_count": len(targets)
            },
            "targets": targets
        }
                
        with open(MASTER_HAUL_FILE, "w") as f:
            json.dump(output_data, f, indent=4)
            
        logger.info(f"✅ Target Base Secured: {len(targets)} scientifically observable targets locked into {MASTER_HAUL_FILE.name}")

    except Exception as e:
        logger.error(f"❌ Failed to fetch or filter targets: {e}")
        sys.exit(1)

if __name__ == "__main__":
    auth_key = get_aavso_key()
    if auth_key:
        haul_and_filter(auth_key)

