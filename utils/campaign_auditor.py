#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: utils/campaign_auditor.py
Version: 1.2.0 (Pee Pastinakel)
Objective: Unpacks the JSON envelope and cross-references campaign targets with available AAVSO comparison charts via coordinates.
"""

import os
import json
from astropy.coordinates import SkyCoord
import astropy.units as u

CAMPAIGN_PATH = os.path.expanduser("~/seestar_organizer/data/campaign_targets.json")
COMP_DIR = os.path.expanduser("~/seestar_organizer/data/comp_stars")

def audit_campaign():
    with open(CAMPAIGN_PATH, 'r') as f:
        campaign = json.load(f)

    target_list = []
    if isinstance(campaign, list):
        target_list = campaign
    elif isinstance(campaign, dict):
        for key, value in campaign.items():
            if isinstance(value, list):
                target_list = value
                break

    if not target_list:
        print("❌ Could not locate a list of targets inside the JSON envelope.")
        return

    comp_files = [f for f in os.listdir(COMP_DIR) if f.endswith('.json')]
    comp_locations = []
    for cf in comp_files:
        try:
            with open(os.path.join(COMP_DIR, cf), 'r') as f:
                data = json.load(f)
                if data and isinstance(data, list) and len(data) > 0 and 'ra' in data:
                    coord = SkyCoord(data['ra'], data['dec'], unit=(u.hourangle, u.deg))
                    comp_locations.append({'file': cf, 'coord': coord})
        except Exception:
            pass

    matched_count = 0
    missing_comps = []

    for target in target_list:
        if not isinstance(target, dict): continue
        name = target.get('star_name') or target.get('canonical_name') or target.get('name') or "Unknown"
        ra = target.get('ra') or target.get('ra_deg') or target.get('RA')
        dec = target.get('dec') or target.get('dec_deg') or target.get('DEC')
        
        if ra is None or dec is None: continue

        try:
            if isinstance(ra, str) and ':' in ra:
                t_coord = SkyCoord(ra, dec, unit=(u.hourangle, u.deg))
            else:
                t_coord = SkyCoord(ra, dec, unit=(u.deg, u.deg))
                
            found_match = False
            for cl in comp_locations:
                if t_coord.separation(cl['coord']).degree < 1.5:
                    target['comp_file'] = cl['file']
                    matched_count += 1
                    found_match = True
                    break
            if not found_match: missing_comps.append(name)
        except Exception as e:
            print(f"⚠️  Coordinate parse error for {name}: {e}")

    if matched_count > 0:
        with open(CAMPAIGN_PATH, 'w') as f:
            json.dump(campaign, f, indent=4)
        print(f"💾 Updated {CAMPAIGN_PATH} with direct links.")

if __name__ == "__main__":
    audit_campaign()
