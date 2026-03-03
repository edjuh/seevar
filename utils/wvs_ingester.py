#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: utils/wvs_ingester.py
Version: 1.2.0 (Pee Pastinakel)
Objective: Downloads and parses the KNVWS Werkgroep Veranderlijke Sterren program list to automate local campaign alignment.
"""

import os
import json
import urllib.request
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("WVS_Ingester")

WVS_URL = "https://www.veranderlijkesterren.info/images/Bestanden/programmas/PRG_STER.TXT"

def fetch_wvs_program():
    logger.info("📡 Fetching Dutch WVS Program list...")
    try:
        with urllib.request.urlopen(WVS_URL, timeout=20) as response:
            lines = response.read().decode('iso-8859-1').splitlines()
            
        targets = []
        for line in lines:
            if not line.strip() or line.startswith(';'): continue
            star_name = line[0:15].strip()
            if star_name:
                targets.append({
                    "name": star_name,
                    "source": "KNVWS-WVS",
                    "priority_boost": 20
                })
        return targets
    except Exception as e:
        logger.error(f"❌ Failed to reach WVS: {e}")
        return []

def merge_to_campaign(new_targets):
    plan_path = os.path.expanduser("~/seestar_organizer/data/campaign_targets.json")
    if os.path.exists(plan_path):
        with open(plan_path, 'r') as f:
            campaign = json.load(f)
    else:
        campaign = {"targets": []}

    existing_names = {t.get('name', '').lower() for t in campaign['targets']}
    added = 0
    
    for t in new_targets:
        if t['name'].lower() not in existing_names:
            campaign['targets'].append(t)
            added += 1
            
    with open(plan_path, 'w') as f:
        json.dump(campaign, f, indent=4)
    logger.info(f"✅ Merged {added} new Dutch program stars into campaign.")

if __name__ == "__main__":
    wvs_data = fetch_wvs_program()
    if wvs_data:
        merge_to_campaign(wvs_data)
