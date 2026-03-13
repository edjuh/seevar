#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/postflight/master_analyst.py
Version: 2.0.0
Objective: High-level plate-solving coordinator executing astrometry.net's solve-field.
"""

import subprocess
import logging
import warnings
from pathlib import Path
from astropy.io import fits
from astropy.wcs import WCS
from astropy.utils.exceptions import AstropyWarning

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [ANALYST] - %(message)s')
logger = logging.getLogger("MasterAnalyst")

# Silence the standard FITS WCS axis mismatch warnings
warnings.filterwarnings('ignore', category=AstropyWarning, append=True)

class MasterAnalyst:
    def __init__(self):
        # Verify solve-field is actually installed on the Pi
        try:
            subprocess.run(['solve-field', '--version'], capture_output=True, check=True)
        except FileNotFoundError:
            logger.error("❌ astrometry.net (solve-field) is not installed or not in PATH.")

    def solve_and_locate(self, fits_path_str):
        fits_file = Path(fits_path_str)
        wcs_file = fits_file.with_suffix('.wcs')

        if not fits_file.exists():
            logger.error(f"❌ File not found: {fits_file}")
            return None, None

        # 1. Extract the hints from our healed header
        try:
            with fits.open(fits_file) as hdul:
                hdr = hdul[0].header
                target_name = hdr.get('OBJECT', 'Unknown')
                ra_deg = hdr.get('RA')
                dec_deg = hdr.get('DEC')
        except Exception as e:
            logger.error(f"❌ Failed to read header for {fits_file.name}: {e}")
            return None, None

        if ra_deg is None or dec_deg is None:
            logger.error("❌ FITS header missing RA/DEC. Run Header Medic first.")
            return None, None

        # 2. Plate Solve (if WCS map doesn't already exist)
        if not wcs_file.exists():
            logger.info(f"🌌 Initiating Plate Solve for {fits_file.name} ({target_name})...")
            
            # Using the RA/Dec hints forces astrometry to solve locally in seconds instead of minutes
            cmd = [
                'solve-field',
                str(fits_file),
                '--ra', str(ra_deg),
                '--dec', str(dec_deg),
                '--radius', '2',          # Search within a 2-degree radius of the hint
                '--downsample', '2',      # Speeds up solving for large 1080p frames
                '--no-plots',             # Do not generate visual overlay images (saves time)
                '--overwrite',
                '--tweak-order', '1'      # Simple distortion polynomial
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)

            if not wcs_file.exists():
                logger.error("❌ Plate Solving failed! Check if astrometry index files are installed.")
                logger.debug(result.stderr)
                return None, None
                
            logger.info("✅ Plate Solve successful. WCS map generated.")
        else:
            logger.info(f"♻️ WCS map already exists for {fits_file.name}. Skipping solve.")

        # 3. Map the target's celestial coordinates to physical image pixels
        try:
            w = WCS(str(wcs_file))
            # origin=0 for standard numpy 0-indexed arrays
            px, py = w.all_world2pix(ra_deg, dec_deg, 0)
            logger.info(f"📍 Target {target_name} precisely located at Pixel X: {px:.2f}, Y: {py:.2f}")
            return float(px), float(py)
        except Exception as e:
            logger.error(f"❌ Failed to calculate pixel coordinates: {e}")
            return None, None

if __name__ == "__main__":
    analyst = MasterAnalyst()
    
    # Let's fire it at RR Lyrae to test the pipeline
    test_file = Path(__file__).resolve().parents[2] / "tests" / "fits" / "rr_lyrae.fits"
    analyst.solve_and_locate(test_file)
