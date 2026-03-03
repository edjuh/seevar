#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: utils/quick_phot.py
Version: 1.2.0 (Pee Pastinakel)
Objective: Lightweight instrumental photometry script for rapid magnitude estimation and zero-point offset calculation.
"""

import os
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from photutils.aperture import SkyCircularAperture, SkyCircularAnnulus, aperture_photometry

SAMPLE_DIR = os.path.expanduser("~/seestar_organizer/tests/samples")
TEMP_DIR = os.path.join(SAMPLE_DIR, "solve_temp")

def measure_target(fits_name, target_ra, target_dec, ref_mag):
    img_path = os.path.join(SAMPLE_DIR, fits_name)
    wcs_path = os.path.join(TEMP_DIR, fits_name.replace(".fits", ".wcs"))
    
    if not os.path.exists(wcs_path):
        print(f"❌ Missing WCS for {fits_name}. Solve it first!")
        return

    try:
        with fits.open(img_path) as hdul:
            data = hdul.data
        with fits.open(wcs_path) as hdul:
            w = WCS(hdul.header)

        pos = SkyCircularAperture([[target_ra, target_dec]], r=0.01)
        annulus = SkyCircularAnnulus([[target_ra, target_dec]], r_in=0.015, r_out=0.025)

        phot_table = aperture_photometry(data, pos, wcs=w)
        bkg_table = aperture_photometry(data, annulus, wcs=w)
        
        raw_flux = phot_table['aperture_sum']
        bkg_flux = bkg_table['aperture_sum'] * (pos.r / (annulus.r_out**2 - annulus.r_in**2)**0.5)**2
        net_flux = raw_flux - bkg_flux
        
        inst_mag = -2.5 * np.log10(net_flux) if net_flux > 0 else 99
        
        print(f"🌟 Target: {fits_name}")
        print(f"   Net Flux: {round(float(net_flux), 2)}")
        print(f"   Inst Mag: {round(float(inst_mag), 2)}")
        print(f"   Ref Mag (AAVSO): {ref_mag}")
        print(f"   Zero-Point Offset: {round(float(ref_mag - inst_mag), 2)}")

    except Exception as e:
        print(f"❌ Photometry Error: {e}")

if __name__ == "__main__":
    measure_target("rr_lyrae.fits", 290.63771, 42.78394, 7.1)
