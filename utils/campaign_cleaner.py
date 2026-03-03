#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: utils/campaign_cleaner.py
Version: 1.2.0 (Pee Pastinakel)
Objective: Deduplicates root campaign targets and securely links them via robust coordinate parsing.
"""

import os
import json
from astropy.coordinates import SkyCoord
import astropy.units as u

CAMPAIGN_PATH = os.path.expanduser("~/seestar_organizer/data/campaign_targets.json")
COMP_DIR = os.path.expanduser("~/seestar_organizer/data/comp_stars")

def clean_and_link():
    with open(CAMPAIGN_PATH, 'r') as f:
        campaign_data = json.load(f)
    
    raw_targets = campaign_data.get('targets', [])
    unique_targets = {t.get('star_name'): t for t in raw_targets if t.get('star_name')}
    target_list = list(unique_targets.values())

    comp_files = [f for f in os.listdir(COMP_DIR) if f.endswith('.json')]
    comp_locations = []
    
    for cf in comp_files:
        try:
            with open(os.path.join(COMP_DIR, cf), 'r') as f:
                cdata = json.load(f)
                first_star = cdata if isinstance(cdata, list) else cdata.get('comp_stars', [None])
                if first_star:
                    cra, cdec = str(first_star['ra']), str(first_star['dec'])
                    if ':' in cra:
                        if not cdec.startswith(('+', '-')): cdec = '+' + cdec
                        coord = SkyCoord(cra, cdec, unit=(u.hourangle, u.deg))
                    else:
                        coord = SkyCoord(float(cra), float(cdec), unit=(u.deg, u.deg))
                    comp_locations.append({'file': cf, 'coord': coord})
        except Exception: pass
    
    matched = 0
    for t in target_list:
        ra, dec = t.get('ra'), t.get('dec')
        if ra is None or dec is None: continue
        try:
            t_coord = SkyCoord(ra, dec, unit=(u.deg, u.deg))
            for cl in comp_locations:
                if t_coord.separation(cl['coord']).degree < 1.5:
                    t['comp_file'] = cl['file']
                    matched += 1
                    break
        except Exception: pass

    campaign_data['targets'] = target_list
    with open(CAMPAIGN_PATH, 'w') as f:
        json.dump(campaign_data, f, indent=4)
    print(f"✅ Science-Ready (Linked) : {matched}")

if __name__ == "__main__":
    clean_and_link()
