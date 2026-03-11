#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/postflight/photometry_engine.py
Version: 1.5.0
Objective: Executes precision aperture photometry on specific X/Y pixel coordinates.
"""

import logging
import warnings
import numpy as np
from astropy.io import fits
from astropy.utils.exceptions import AstropyWarning

try:
    from photutils.aperture import CircularAperture, CircularAnnulus, aperture_photometry
except ImportError:
    print("❌ Error: photutils not installed. Run: pip install photutils")
    exit(1)

from core.postflight.pastinakel_math import check_saturation

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [PHOTOMETRY] - %(message)s')
logger = logging.getLogger("PhotEngine")
warnings.filterwarnings('ignore', category=AstropyWarning, append=True)

class PhotometryEngine:
    def __init__(self, aperture_radius=5.0, sky_inner=10.0, sky_outer=15.0):
        # We will dynamically scale this later using pastinakel_math, 
        # but 5.0 is a robust starting radius for Seestar sampling.
        self.r_aperture = aperture_radius
        self.r_sky_in = sky_inner
        self.r_sky_out = sky_outer

    def extract_flux(self, fits_path_str, x, y):
        """
        Measures the background-subtracted ADU flux at a specific pixel location.
        """
        # 1. Bounds Check (Assuming 1080x1920 standard Seestar resolution)
        if x < 0 or x > 1920 or y < 0 or y > 1080:
            logger.warning(f"⚠️ Target at ({x:.1f}, {y:.1f}) is OUT OF BOUNDS.")
            return None

        try:
            with fits.open(fits_path_str) as hdul:
                data = hdul[0].data
                
                # If image is 3D (e.g. RGB), take the first channel (mono)
                if data.ndim == 3:
                    data = data[0]

            # 2. Saturation Check using Pastinakel Math
            # We check a small 5x5 bounding box around the target pixel
            ix, iy = int(x), int(y)
            # Ensure slicing doesn't go off the edge
            box = data[max(0, iy-2):iy+3, max(0, ix-2):ix+3]
            
            is_sat, peak_val = check_saturation(box)
            if is_sat:
                logger.error(f"❌ Target saturated! Peak ADU: {peak_val}. Invalid for science.")
                return None

            # 3. Define the Apertures
            position = (x, y)
            aperture = CircularAperture(position, r=self.r_aperture)
            annulus = CircularAnnulus(position, r_in=self.r_sky_in, r_out=self.r_sky_out)

            # 4. Perform Photometry
            phot_table = aperture_photometry(data, aperture)
            bkg_table = aperture_photometry(data, annulus)

            # 5. Background Subtraction Math
            raw_flux = phot_table['aperture_sum'][0]
            bkg_flux_total = bkg_table['aperture_sum'][0]
            
            # Calculate average background per pixel, then multiply by star aperture area
            bkg_mean = bkg_flux_total / annulus.area
            bkg_subtracted_flux = raw_flux - (bkg_mean * aperture.area)

            logger.info(f"✨ Flux Extracted: {bkg_subtracted_flux:.2f} ADU (Peak: {peak_val})")
            
            return {
                "inst_flux": bkg_subtracted_flux,
                "peak_adu": peak_val,
                "x": x,
                "y": y
            }

        except Exception as e:
            logger.error(f"❌ Flux extraction failed: {e}")
            return None

phot_engine = PhotometryEngine()
