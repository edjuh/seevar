#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/schedule_compiler.py
Version: 1.0.2
Objective: Translates tonights_plan.json into a native SSC JSON payload using the 1x1 mosaic hack for dithering.
"""

import json
import uuid
import sys
import logging
from pathlib import Path

try:
    import tomllib
except ImportError:
    import toml as tomllib

from astropy.coordinates import SkyCoord
import astropy.units as u

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger("Compiler")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.toml"
DATA_DIR = PROJECT_ROOT / "data"
TONIGHTS_PLAN = DATA_DIR / "tonights_plan.json"
OUTPUT_PAYLOAD = DATA_DIR / "ssc_payload.json"

def convert_to_seestar_coords(ra_deg, dec_deg):
    """Converts decimal degrees to the strict HHhMMmSS.Ss format required by the SSC."""
    coord = SkyCoord(ra=ra_deg*u.deg, dec=dec_deg*u.deg, frame='icrs')
    
    # Let Astropy handle the formatting and sign logic safely
    ra_str = coord.ra.to_string(unit=u.hour, sep=('h', 'm', 's'), precision=1, pad=True)
    dec_str = coord.dec.to_string(sep=('d', 'm', 's'), precision=1, alwayssign=True, pad=True)
    
    return ra_str, dec_str

def compile_schedule():
    if not TONIGHTS_PLAN.exists():
        logger.error(f"❌ {TONIGHTS_PLAN.name} not found.")
        sys.exit(1)

    with open(CONFIG_PATH, "rb") as f:
        cfg = tomllib.load(f)
    
    planner_cfg = cfg.get("planner", {})
    mount_mode = planner_cfg.get("mount_mode", "ALT/AZ").upper()
    dithering = planner_cfg.get("dithering", False)
    
    logger.info(f"⚙️ Compiling for Intended State: {mount_mode} | Dithering: {dithering}")

    if mount_mode == "ALT/AZ":
        exp_time = 60
    elif mount_mode == "EQ" and not dithering:
        exp_time = 300
    elif mount_mode == "EQ" and dithering:
        exp_time = 60
    else:
        exp_time = 60 

    with open(TONIGHTS_PLAN, "r") as f:
        plan = json.load(f)
        targets = plan.get("targets", [])

    if not targets:
        logger.warning("⚠️ No targets in plan. Aborting compilation.")
        return

    payload = {
        "#objective": "Compiled native SSC JSON payload for Seestar execution.",
        "version": 1.0,
        "Event": "Scheduler",
        "schedule_id": str(uuid.uuid4()),
        "state": "stopped",
        "list": []
    }

    payload["list"].append({
        "action": "start_up_sequence",
        "params": {
            "auto_focus": True,
            "dark_frames": True,
            "3ppa": (mount_mode == "EQ")
        },
        "schedule_item_id": str(uuid.uuid4())
    })

    for t in targets:
        ra_str, dec_str = convert_to_seestar_coords(t["ra"], t["dec"])
        duration = t.get("duration", 600)
        
        payload["list"].append({
            "action": "start_mosaic",
            "params": {
                "target_name": t["name"],
                "is_j2000": True,
                "ra": ra_str,
                "dec": dec_str,
                "is_use_lp_filter": False,
                "panel_time_sec": duration,
                "ra_num": 1,
                "dec_num": 1,
                "panel_overlap_percent": 0,
                "selected_panels": "1",
                "gain": 80,
                "exp_time": exp_time,
                "is_use_autofocus": True,
                "num_tries": 3,
                "retry_wait_s": 15
            },
            "schedule_item_id": str(uuid.uuid4())
        })

    payload["list"].append({
        "action": "scope_park",
        "params": {},
        "schedule_item_id": str(uuid.uuid4())
    })
    payload["list"].append({
        "action": "shutdown",
        "params": {},
        "schedule_item_id": str(uuid.uuid4())
    })

    with open(OUTPUT_PAYLOAD, "w") as f:
        json.dump(payload, f, indent=4)
        
    logger.info(f"✅ Compilation Complete. Generated {len(targets)} targets into {OUTPUT_PAYLOAD.name}")

if __name__ == "__main__":
    compile_schedule()
