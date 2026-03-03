#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: utils/history_tracker.py
Version: 1.2.0 (Pee Pastinakel)
Objective: Scans the Seestar observation storage to update last_observed timestamps in the campaign database.
"""

import os
import json
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("History_Tracker")

def get_latest_obs_time(target_name, obs_root):
    """Finds the mtime of the newest FITS file for a given target."""
    target_path = os.path.join(obs_root, target_name)
    if not os.path.exists(target_path):
        return None
        
    latest_time = 0
    for root, dirs, files in os.walk(target_path):
        for f in files:
            if f.lower().endswith('.fit') or f.lower().endswith('.fits'):
                mtime = os.path.getmtime(os.path.join(root, f))
                if mtime > latest_time:
                    latest_time = mtime
                    
    return latest_time if latest_time > 0 else None

def sync_history():
    base_dir = os.path.expanduser("~/seestar_organizer")
    obs_root = os.path.join(base_dir, "data/observations")
    plan_path = os.path.join(base_dir, "data/campaign_targets.json")
    
    if not os.path.exists(plan_path):
        return

    with open(plan_path, 'r') as f:
        campaign = json.load(f)

    updates = 0
    for target in campaign['targets']:
        name = target.get('name')
        folder_name = name.replace(" ", "_")
        
        last_ts = get_latest_obs_time(name, obs_root) or get_latest_obs_time(folder_name, obs_root)
        
        if last_ts:
            last_date = datetime.fromtimestamp(last_ts).isoformat()
            if target.get('last_observed') != last_date:
                target['last_observed'] = last_date
                updates += 1

    with open(plan_path, 'w') as f:
        json.dump(campaign, f, indent=4)
        
    logger.info(f"✅ History Sync: Updated {updates} targets with new observation dates.")

if __name__ == "__main__":
    sync_history()
