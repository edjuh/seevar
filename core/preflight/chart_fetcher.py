#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/chart_fetcher.py
Version: 1.4.2
Objective: Step 2 - Fetch AAVSO VSP comparison star sequences.
           FOV fixed at 180' (VSP maglimit 15 requires FOV <= 180').
           The S30-Pro sensor is ~270' but 180' delivers sufficient comparison stars.
"""
import json
import time
import requests
import sys
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger("AAVSO_Step2")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR  = PROJECT_ROOT / "catalogs"
MASTER_HAUL_FILE = CATALOG_DIR / "campaign_targets.json"
REF_DIR      = CATALOG_DIR / "reference_stars"

# Pi-Minute throttle — AAVSO VSP rate limit
POLL_DELAY_SECONDS = 31.4

def fetch_charts(target_list=None):
    REF_DIR.mkdir(parents=True, exist_ok=True)

    if target_list:
        logger.info(f"🎯 Targeted Fetch: {len(target_list)} stars requested.")
        process_list = target_list
    else:
        if not MASTER_HAUL_FILE.exists():
            logger.error(f"❌ Library not found: {MASTER_HAUL_FILE}")
            return
        with open(MASTER_HAUL_FILE, 'r') as f:
            data = json.load(f)
            targets = data.get("targets", []) if isinstance(data, dict) else data
        process_list = [t['name'] for t in targets if 'name' in t]
        logger.info(f"📡 Audit Mode: Checking {len(process_list)} targets...")

    api_hits = 0
    for star_name in process_list:
        clean_name = star_name.lower().replace(' ', '_').replace('-', '_')
        out_file = REF_DIR / f"{clean_name}.json"

        if out_file.exists():
            continue

        if api_hits > 0:
            logger.info(f"⏳ Throttling: Waiting {POLL_DELAY_SECONDS}s...")
            time.sleep(POLL_DELAY_SECONDS)

        logger.info(f"🔭 Fetching Chart for {star_name} (180' FOV, Mag 15)...")
        vsp_url    = "https://apps.aavso.org/vsp/api/chart/"
        vsp_params = {
            "format":   "json",
            "star":     star_name,
            "fov":      180,
            "maglimit": 15.0
        }

        try:
            res = requests.get(vsp_url, params=vsp_params, timeout=15)
            if res.status_code == 200:
                comps = res.json().get("photometry", [])
                output_data = {
                    "#objective":       f"AAVSO VSP Photometry sequence for {star_name}",
                    "target":           {"name": star_name},
                    "comparison_stars": comps
                }
                with open(out_file, "w") as f:
                    json.dump(output_data, f, indent=4)
                logger.info(f"✅ Cached {len(comps)} comparison stars.")
            else:
                # Log full response body to diagnose VSP rejections
                logger.warning(
                    f"⚠️ VSP Error {res.status_code} for {star_name}: {res.text[:300]}"
                )
        except Exception as e:
            logger.error(f"❌ Failed fetch for {star_name}: {e}")

        api_hits += 1

if __name__ == "__main__":
    manual_targets = sys.argv[1:]
    fetch_charts(manual_targets if manual_targets else None)
