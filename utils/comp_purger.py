#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: utils/comp_purger.py
Version: 1.2.0 (Pee Pastinakel)
Objective: Scans comparison charts and deletes any file that is empty, malformed, or missing coordinate data.
"""

import os
import json

COMP_DIR = os.path.expanduser("~/seestar_organizer/data/comp_stars")

def execute_purge():
    files = [f for f in os.listdir(COMP_DIR) if f.endswith('.json')]
    print(f"🔍 Scanning {len(files)} files for corruption or empty data...")

    killed = 0
    survived = 0

    for f in files:
        path = os.path.join(COMP_DIR, f)
        keep = False
        try:
            with open(path, 'r') as file:
                data = json.load(file)
            if isinstance(data, list) and len(data) > 0:
                if isinstance(data, dict) and 'ra' in data and 'dec' in data:
                    keep = True
        except Exception:
            pass

        if not keep:
            os.remove(path)
            killed += 1
        else:
            survived += 1

    print("-" * 40)
    print(f"🔥 Burned     : {killed} useless files.")
    print(f"🛡️  Survived   : {survived} valid charts.")

if __name__ == "__main__":
    execute_purge()
