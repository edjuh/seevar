#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/postflight/bayer_photometry.py
Version: 1.0.0
Objective: Bayer-channel aperture photometry engine for the IMX585 (GRBG pattern).
           Extracted from pilot.py and elevated to a standalone science module.
           Provides single-star flux extraction and multi-star differential photometry.
           No debayering. No Siril. Direct pixel math on raw uint16 FITS.
"""

import logging
import math
import numpy as np
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("seevar.bayer_photometry")

# IMX585 Bayer pattern — GRBG
# Row Even: G, R, G, R  (col 0,1,2,3...)
# Row Odd:  B, G, B, G
BAYER_PATTERN = "GRBG"

# Default aperture geometry (pixels)
R_AP_DEFAULT      = 8
R_SKY_IN_DEFAULT  = 12
R_SKY_OUT_DEFAULT = 18
SEARCH_RADIUS     = 10

# Saturation ceiling — IMX585 16-bit, stay in linear range
SATURATION_CEILING = 60000


# ---------------------------------------------------------------------------
# Core aperture flux extractor — operates on raw Bayer array
# ---------------------------------------------------------------------------

def aperture_flux(
    image: np.ndarray,
    cx: int, cy: int,
    r_ap: int = R_AP_DEFAULT,
    r_sky_in: int = R_SKY_IN_DEFAULT,
    r_sky_out: int = R_SKY_OUT_DEFAULT,
    bayer_channel: str = "ALL"
) -> Tuple[float, float, float]:
    """
    Circular aperture photometry with strict Bayer-matrix channel slicing.

    Bayer masks for GRBG (IMX585):
      G — Even/Even or Odd/Odd positions
      R — Even row, Odd col
      B — Odd row, Even col
      ALL — Luminance, all pixels

    Returns (net_flux, sky_median, snr).
    """
    y_idx, x_idx = np.ogrid[-cy:image.shape[0]-cy, -cx:image.shape[1]-cx]
    abs_y = y_idx + cy
    abs_x = x_idx + cx

    if bayer_channel == "G":
        b_mask = (abs_y % 2) == (abs_x % 2)
    elif bayer_channel == "R":
        b_mask = (abs_y % 2 == 0) & (abs_x % 2 == 1)
    elif bayer_channel == "B":
        b_mask = (abs_y % 2 == 1) & (abs_x % 2 == 0)
    else:
        b_mask = np.ones_like(abs_y, dtype=bool)

    r2       = (x_idx**2 + y_idx**2).astype(np.float64)
    ap_mask  = (r2 <= r_ap ** 2) & b_mask
    sky_mask = (r2 >= r_sky_in ** 2) & (r2 <= r_sky_out ** 2) & b_mask

    sky_vals   = image[sky_mask].astype(np.float64)
    sky_median = float(np.median(sky_vals)) if len(sky_vals) > 0 else 0.0
    sky_std    = float(sky_vals.std())      if len(sky_vals) > 0 else 1.0

    ap_sum   = float(image[ap_mask].astype(np.float64).sum())
    n_ap     = int(ap_mask.sum())
    net_flux = ap_sum - sky_median * n_ap
    snr      = net_flux / (sky_std * math.sqrt(n_ap)) if sky_std > 0 and n_ap > 0 else 0.0

    return net_flux, sky_median, snr


# ---------------------------------------------------------------------------
# FITS loader — pure numpy, no astropy dependency
# ---------------------------------------------------------------------------

class BayerFITS:
    """
    Lightweight raw FITS reader. Parses header and pixel array.
    Validates Bayer pattern and saturation before science extraction.
    """

    def __init__(self, fits_path: Path):
        self.path    = Path(fits_path)
        self.header: dict               = {}
        self.array:  Optional[np.ndarray] = None
        self._wcs:   dict               = {}

    def load(self) -> bool:
        try:
            with open(self.path, "rb") as f:
                raw = f.read()
        except OSError as e:
            logger.error("Cannot open %s: %s", self.path, e)
            return False

        header = {}
        header_blocks = 0
        found_end = False

        for block_start in range(0, len(raw), 2880):
            block = raw[block_start: block_start + 2880]
            header_blocks += 1
            for i in range(0, 2880, 80):
                rec = block[i:i+80].decode("ascii", errors="replace")
                key = rec[:8].strip()
                if key == "END":
                    found_end = True
                    break
                if "=" in rec[:30]:
                    k, _, rest = rec.partition("=")
                    val_str = rest.split("/")[0].strip().strip("'").strip()
                    try:
                        if "." in val_str:
                            header[k.strip()] = float(val_str)
                        elif val_str in ("T", "F"):
                            header[k.strip()] = (val_str == "T")
                        else:
                            header[k.strip()] = int(val_str)
                    except ValueError:
                        header[k.strip()] = val_str
            if found_end:
                break

        self.header = header
        bitpix = int(header.get("BITPIX", -32))
        naxis1 = int(header.get("NAXIS1", 0))
        naxis2 = int(header.get("NAXIS2", 0))

        data_start = header_blocks * 2880
        n_bytes    = abs(bitpix) // 8 * naxis1 * naxis2
        dt = {8: ">u1", 16: ">u2", -16: ">u2", 32: ">i4", -32: ">f4", -64: ">f8"}.get(bitpix, ">f4")

        self.array = np.frombuffer(
            raw[data_start: data_start + n_bytes], dtype=dt
        ).reshape(naxis2, naxis1)

        self._wcs = {
            "crval1": float(header.get("CRVAL1", 0)),
            "crval2": float(header.get("CRVAL2", 0)),
            "crpix1": float(header.get("CRPIX1", naxis1 / 2)),
            "crpix2": float(header.get("CRPIX2", naxis2 / 2)),
            "cdelt1": float(header.get("CDELT1", -0.001042)),
            "cdelt2": float(header.get("CDELT2",  0.001042)),
        }
        return True

    def world_to_pixel(self, ra: float, dec: float) -> Tuple[int, int]:
        w  = self._wcs
        px = w["crpix1"] + (w["crval1"] - ra)  / abs(w["cdelt1"])
        py = w["crpix2"] + (dec - w["crval2"])  / abs(w["cdelt2"])
        return int(round(px)), int(round(py))

    def is_saturated(self, cx: int, cy: int, box: int = 5) -> Tuple[bool, float]:
        arr = self.array
        y0, y1 = max(0, cy - box), min(arr.shape[0], cy + box)
        x0, x1 = max(0, cx - box), min(arr.shape[1], cx + box)
        peak = float(arr[y0:y1, x0:x1].max())
        return peak >= SATURATION_CEILING, peak

    def measure_star(
        self,
        ra: float, dec: float,
        r_ap: int = R_AP_DEFAULT,
        r_sky_in: int = R_SKY_IN_DEFAULT,
        r_sky_out: int = R_SKY_OUT_DEFAULT,
    ) -> dict:
        """
        Measure all four Bayer channels (G, R, B, ALL) at the given RA/Dec.
        Centroids on luminance first for robust anchoring, then extracts per channel.
        Returns a dict with fluxes, SNRs, and saturation flag.
        """
        cx, cy = self.world_to_pixel(ra, dec)
        arr    = self.array.astype(np.float64)
        h, w   = arr.shape

        if not (r_sky_out < cx < w - r_sky_out and r_sky_out < cy < h - r_sky_out):
            return {"error": "out_of_frame", "cx": cx, "cy": cy}

        # Centroid refinement on full luminance
        x0, x1 = max(0, cx - SEARCH_RADIUS), min(w, cx + SEARCH_RADIUS)
        y0, y1 = max(0, cy - SEARCH_RADIUS), min(h, cy + SEARCH_RADIUS)
        patch  = arr[y0:y1, x0:x1]
        pk     = np.unravel_index(patch.argmax(), patch.shape)
        cx, cy = x0 + pk[1], y0 + pk[0]

        # Saturation guard
        saturated, peak = self.is_saturated(cx, cy)
        if saturated:
            logger.warning("Star at (%d,%d) saturated — peak ADU %.0f", cx, cy, peak)

        result = {"cx": cx, "cy": cy, "peak": peak, "saturated": saturated}

        for ch in ("G", "R", "B", "ALL"):
            flux, sky, snr = aperture_flux(arr, cx, cy, r_ap, r_sky_in, r_sky_out, ch)
            result[f"flux_{ch}"]  = round(flux, 2)
            result[f"sky_{ch}"]   = round(sky,  2)
            result[f"snr_{ch}"]   = round(snr,  2)

        return result


# ---------------------------------------------------------------------------
# Differential photometry — target vs comparison stars
# ---------------------------------------------------------------------------

def differential_magnitude(
    fits_file:    BayerFITS,
    target_ra:    float,
    target_dec:   float,
    comp_stars:   list,
    channel:      str = "G"
) -> dict:
    """
    Compute differential magnitude for target against a list of comparison stars.

    comp_stars: list of dicts from AAVSO VSP, each must have:
        ra, dec, and bands list with {"band": "V", "mag": float}

    Returns:
        mag        — differential magnitude in requested channel
        err        — standard deviation of zero-point ensemble
        n_comps    — number of valid comparison stars used
        zero_point — ensemble average zero-point
        channel    — Bayer channel used
    """
    flux_key = f"flux_{channel}"
    snr_key  = f"snr_{channel}"

    # Measure target
    t = fits_file.measure_star(target_ra, target_dec)
    if "error" in t:
        return {"error": t["error"]}
    if t.get("saturated"):
        return {"error": "target_saturated"}
    if t[flux_key] <= 0:
        return {"error": "target_flux_zero_or_negative"}

    target_flux = t[flux_key]
    target_snr  = t[snr_key]

    # Measure each comparison star and collect zero-points
    zero_points = []
    for comp in comp_stars:
        # Get V magnitude from bands list
        v_mag = next(
            (b["mag"] for b in comp.get("bands", []) if b["band"] == "V"),
            None
        )
        if v_mag is None:
            continue

        comp_ra  = comp.get("ra")
        comp_dec = comp.get("dec")
        if comp_ra is None or comp_dec is None:
            continue

        m = fits_file.measure_star(comp_ra, comp_dec)
        if "error" in m or m.get("saturated"):
            continue
        if m[flux_key] <= 0:
            continue
        if m[snr_key] < 5.0:
            continue  # Skip low-SNR comps

        zp = v_mag + 2.5 * math.log10(m[flux_key])
        zero_points.append(zp)

    if not zero_points:
        return {"error": "no_valid_comp_stars"}

    zp_array   = np.array(zero_points)
    avg_zp     = float(np.mean(zp_array))
    zp_std     = float(np.std(zp_array))
    magnitude  = avg_zp - 2.5 * math.log10(target_flux)

    # Photometric error: quadrature sum of ZP scatter and target SNR noise
    snr_err    = 1.0857 / target_snr if target_snr > 0 else 9.99
    total_err  = round(math.sqrt(zp_std**2 + snr_err**2), 3)

    return {
        "mag":        round(magnitude, 3),
        "err":        total_err,
        "n_comps":    len(zero_points),
        "zero_point": round(avg_zp, 4),
        "zp_std":     round(zp_std, 4),
        "channel":    channel,
        "target_snr": round(target_snr, 1),
    }
