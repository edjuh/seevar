#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/utils/platesolve_analyst.py
Version: 1.2.1
Objective: Quantitative reporter for plate-solving success rates, performing blind solves to compare header coordinates against reality.
"""

import os
import subprocess
from astropy.io import fits

SAMPLE_DIR = os.path.expanduser("~/seevar/tests/samples")
TEMP_DIR = os.path.join(SAMPLE_DIR, "solve_temp")
os.makedirs(TEMP_DIR, exist_ok=True)

def solve_and_compare(filename):
    filepath = os.path.join(SAMPLE_DIR, filename)
    
    try:
        header = fits.getheader(filepath, 0, ignore_missing_end=True)
        reported_ra = header.get('OBJCTRA') or header.get('RA') or "Unknown"
        reported_dec = header.get('OBJCTDEC') or header.get('DEC') or "Unknown"
    except Exception as e:
        print(f"❌ Header Read Error on {filename}: {e}")
        return

    print(f"\n🧩 Analyzing: {filename}")
    print(f"   📡 Header: {reported_ra} | {reported_dec}")

    cmd = [
        "solve-field", filepath, 
        "--dir", TEMP_DIR,
        "--no-plots", "--overwrite",
        "--downsample", "2",
        "--cpulimit", "60"
    ]
    
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wcs_file = os.path.join(TEMP_DIR, filename.replace(".fits", ".wcs"))
        if os.path.exists(wcs_file):
            w_hdr = fits.getheader(wcs_file, 0)
            true_ra = w_hdr.get('CRVAL1')
            true_dec = w_hdr.get('CRVAL2')
            print(f"   🎯 SOLVED:   RA {round(true_ra, 5)} | Dec {round(true_dec, 5)}")
        else:
            print("   ❌ FAILED: No match found.")
    except Exception as e:
        print(f"   ❌ EXECUTION ERROR: {e}")

if __name__ == "__main__":
    if os.path.exists(SAMPLE_DIR):
        fits_files = sorted([f for f in os.listdir(SAMPLE_DIR) if f.endswith(".fits")])
        for f in fits_files:
            solve_and_compare(f)
