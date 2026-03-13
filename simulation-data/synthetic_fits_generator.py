#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: synthetic_fits_generator.py
Version: 2.0.0
Objective: Generates a synthetic, scientifically accurate RAW FITS file for a
           requested target using Gaia DR3 catalog data.
           Produces a genuine GRBG Bayer mosaic — each pixel carries only its
           native channel value, matching what the IMX585 delivers off the wire.
"""

import os
import sys
import json
import argparse
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.coordinates import SkyCoord
import astropy.units as u
from astroquery.vizier import Vizier

# ---------------------------------------------------------------------------
# Sensor constants — IMX585 / Seestar S30-Pro
# ---------------------------------------------------------------------------
BAYER_PATTERN = "GRBG"   # FIXED: was incorrectly RGGB in v1.0.0

FOV_RA_DEG    = 1.28
FOV_DEC_DEG   = 0.72
IMG_WIDTH     = 1080     # X-axis pixels (portrait orientation)
IMG_HEIGHT    = 1920     # Y-axis pixels
NOISE_FLOOR   = 500
NOISE_STD     = 15
CDELT_VAL     = 0.00067  # degrees/pixel (~2.4 arcsec/pixel)


# ---------------------------------------------------------------------------
# GRBG Bayer channel masks
# Row Even: G, R, G, R  (col 0,1,2,3...)
# Row Odd:  B, G, B, G
# ---------------------------------------------------------------------------

def make_bayer_masks(height, width):
    rows = np.arange(height)[:, None]
    cols = np.arange(width)[None, :]
    mask_G = (rows % 2) == (cols % 2)          # Even/Even or Odd/Odd
    mask_R = (rows % 2 == 0) & (cols % 2 == 1) # Even row, Odd col
    mask_B = (rows % 2 == 1) & (cols % 2 == 0) # Odd row, Even col
    return mask_G, mask_R, mask_B


def render_star_bayer(canvas, x_idx, y_idx, flux_amplitude, mask_G, mask_R, mask_B):
    """
    Render a 2D Gaussian PSF (5×5 bounding box) onto the Bayer canvas.
    Each pixel only receives flux if it belongs to its native Bayer channel.
    G pixels get full green flux; R/B pixels get appropriately scaled flux.
    """
    for i in range(-2, 3):
        for j in range(-2, 3):
            xi, yj = x_idx + i, y_idx + j
            if not (0 <= xi < IMG_WIDTH and 0 <= yj < IMG_HEIGHT):
                continue
            dist_sq = i**2 + j**2
            psf_val = flux_amplitude * np.exp(-dist_sq / 1.5)

            if np.isnan(psf_val) or not np.isfinite(psf_val):
                continue

            if mask_G[yj, xi]:
                canvas[yj, xi] += psf_val          # G channel — full flux
            elif mask_R[yj, xi]:
                canvas[yj, xi] += psf_val * 0.7    # R channel — scaled by typical colour index
            elif mask_B[yj, xi]:
                canvas[yj, xi] += psf_val * 0.4    # B channel — cooler stars are dimmer in blue


def generate_synthetic_fits(target_name, plan_file):
    # 1. Load target from daily roster
    if not os.path.exists(plan_file):
        print(f"Error: Roster file '{plan_file}' not found.")
        sys.exit(1)

    with open(plan_file, "r") as f:
        plan = json.load(f)

    target_data = next(
        (t for t in plan.get("targets", []) if t["name"] == target_name), None
    )
    if not target_data:
        print(f"Error: Target '{target_name}' not found in {plan_file}.")
        sys.exit(1)

    ra_deg  = target_data["ra"]
    dec_deg = target_data["dec"]
    print(f"Target found: {target_name} at RA: {ra_deg}, DEC: {dec_deg}")

    # 2. Query Gaia DR3 for background stars
    print("Querying Gaia DR3 via VizieR...")
    v = Vizier(columns=["RA_ICRS", "DE_ICRS", "Gmag"])
    v.ROW_LIMIT = -1

    coord  = SkyCoord(ra=ra_deg, dec=dec_deg, unit=(u.deg, u.deg), frame="icrs")
    result = v.query_region(
        coord,
        width=FOV_RA_DEG   * u.deg,
        height=FOV_DEC_DEG * u.deg,
        catalog="I/355/gaiadr3"
    )

    if not result or len(result) == 0:
        print("Error: No stars found in catalog for this region.")
        sys.exit(1)

    stars = result[0]
    print(f"Found {len(stars)} stars in the FOV.")

    # 3. Canvas — noise floor, then Bayer masks
    canvas   = np.random.normal(NOISE_FLOOR, NOISE_STD, (IMG_HEIGHT, IMG_WIDTH))
    mask_G, mask_R, mask_B = make_bayer_masks(IMG_HEIGHT, IMG_WIDTH)

    # 4. WCS projection
    w = WCS(naxis=2)
    w.wcs.crpix = [IMG_WIDTH / 2, IMG_HEIGHT / 2]
    w.wcs.cdelt = np.array([-CDELT_VAL, CDELT_VAL])
    w.wcs.crval = [ra_deg, dec_deg]
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]

    # 5. Project and render each star onto proper Bayer channels
    print("Projecting WCS and rendering GRBG Bayer PSFs...")
    star_coords = SkyCoord(ra=stars["RA_ICRS"], dec=stars["DE_ICRS"], unit=(u.deg, u.deg))
    x_pix, y_pix = w.world_to_pixel(star_coords)
    mags = stars["Gmag"]

    for x, y, mag in zip(x_pix, y_pix, mags):
        # Reject masked elements before float() triggers numpy UserWarning
        if getattr(mag, 'mask', False) or getattr(x, 'mask', False) or getattr(y, 'mask', False):
            continue
        try:
            x_f, y_f, mag_f = float(x), float(y), float(mag)
        except (ValueError, TypeError):
            continue
        if not (np.isfinite(x_f) and np.isfinite(y_f) and np.isfinite(mag_f)):
            continue
        flux_amplitude = 10 ** ((15 - mag_f) / 2.5) * 150
        x_idx, y_idx = int(round(x_f)), int(round(y_f))
        if not (0 <= x_idx < IMG_WIDTH and 0 <= y_idx < IMG_HEIGHT):
            continue
        render_star_bayer(canvas, x_idx, y_idx, flux_amplitude, mask_G, mask_R, mask_B)

    # 6. Enforce 16-bit range
    canvas = np.clip(canvas, 0, 65535).astype(np.uint16)

    # 7. Build FITS with correct headers
    hdu    = fits.PrimaryHDU(canvas)
    header = hdu.header
    header.update(w.to_header())
    header["OBJECT"]   = target_name
    header["IMAGETYP"] = "Light Frame"
    header["EXPTIME"]  = 60.0
    header["FILTER"]   = "CV"
    header["BAYERPAT"] = BAYER_PATTERN   # GRBG — matches IMX585 and pilot.py
    header["INSTRUME"] = "IMX585"
    header["TELESCOP"] = "ZWO S30-Pro"
    header["BITPIX"]   = 16
    header["COMMENT"]  = "Synthetic GRBG Bayer frame - SeeVar test data v2.0.0"

    out_dir   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "local_buffer")
    os.makedirs(out_dir, exist_ok=True)
    safe_name = target_name.replace(" ", "_")
    out_path  = os.path.join(out_dir, f"{safe_name}_synthetic.fits")

    hdu.writeto(out_path, overwrite=True)
    print(f"✅ Synthetic GRBG capture complete → {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Deterministic Synthetic GRBG Sky Generator for Seestar pipeline."
    )
    parser.add_argument("--target", required=True,
                        help="Target name — exact match as listed in the JSON roster.")
    parser.add_argument("--plan", default="tonights_plan.json",
                        help="Path to the JSON flight roster.")
    args = parser.parse_args()
    generate_synthetic_fits(args.target, args.plan)
