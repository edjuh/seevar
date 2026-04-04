#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/postflight/bayer_photometry.py
Version: 2.2.0
Objective: Bayer-channel aperture photometry engine for the IMX585 using real solved WCS
products for source placement, with sigma-clipped comparison-star ensembles.
"""

import logging
import math
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

logger = logging.getLogger("seevar.bayer_photometry")

BAYER_PATTERN = "GRBG"

R_AP_DEFAULT = 8
R_SKY_IN_DEFAULT = 12
R_SKY_OUT_DEFAULT = 18
SEARCH_RADIUS = 10

SATURATION_CEILING = 60000
MIN_COMP_SNR = 5.0
MIN_CLIPPED_COMPS = 3
CLIP_SIGMA = 2.5
CLIP_MAX_ITERS = 2
PSF_MODEL = "moffat"


def aperture_flux(
    image: np.ndarray,
    cx: int,
    cy: int,
    r_ap: int = R_AP_DEFAULT,
    r_sky_in: int = R_SKY_IN_DEFAULT,
    r_sky_out: int = R_SKY_OUT_DEFAULT,
    bayer_channel: str = "ALL",
) -> Tuple[float, float, float]:
    """
    Circular aperture photometry with strict Bayer-matrix channel slicing.

    Returns (net_flux, sky_median, snr).
    """
    y_idx, x_idx = np.ogrid[-cy:image.shape[0] - cy, -cx:image.shape[1] - cx]
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

    r2 = (x_idx ** 2 + y_idx ** 2).astype(np.float64)
    ap_mask = (r2 <= r_ap ** 2) & b_mask
    sky_mask = (r2 >= r_sky_in ** 2) & (r2 <= r_sky_out ** 2) & b_mask

    sky_vals = image[sky_mask].astype(np.float64)
    sky_median = float(np.median(sky_vals)) if len(sky_vals) > 0 else 0.0
    sky_std = float(sky_vals.std()) if len(sky_vals) > 0 else 1.0

    ap_sum = float(image[ap_mask].astype(np.float64).sum())
    n_ap = int(ap_mask.sum())
    net_flux = ap_sum - sky_median * n_ap
    snr = net_flux / (sky_std * math.sqrt(n_ap)) if sky_std > 0 and n_ap > 0 else 0.0

    return net_flux, sky_median, snr


class BayerFITS:
    """
    FITS reader backed by astropy for data access and solved WCS use.
    """

    def __init__(self, fits_path: Path):
        self.path = Path(fits_path)
        self.header: dict = {}
        self.array: Optional[np.ndarray] = None
        self._wcs: Optional[WCS] = None

    @property
    def has_wcs(self) -> bool:
        return self._wcs is not None

    def load(self, wcs_path: Optional[Path] = None) -> bool:
        try:
            with fits.open(self.path) as hdul:
                hdr = hdul[0].header.copy()
                data = hdul[0].data
        except OSError as e:
            logger.error("Cannot open %s: %s", self.path, e)
            return False
        except Exception as e:
            logger.error("Failed to read FITS %s: %s", self.path, e)
            return False

        if data is None:
            logger.error("No image data in %s", self.path)
            return False

        arr = np.array(data, dtype=np.float64)
        if arr.ndim != 2:
            logger.error("Expected 2D image, got shape %s in %s", arr.shape, self.path)
            return False

        self.header = dict(hdr)
        self.array = arr
        self._wcs = None

        solve_path = Path(wcs_path) if wcs_path else self.path.with_suffix(".wcs")
        if solve_path.exists():
            try:
                self._wcs = WCS(str(solve_path))
            except Exception as e:
                logger.error("Failed to load WCS %s: %s", solve_path, e)

        return True

    def world_to_pixel(self, ra_deg: float, dec_deg: float) -> Tuple[float, float]:
        if not self._wcs:
            raise RuntimeError("No solved WCS loaded")
        x, y = self._wcs.world_to_pixel_values(ra_deg, dec_deg)
        return float(x), float(y)

    def measure_star(self, ra_deg: float, dec_deg: float, r_ap: Optional[int] = None) -> dict:
        if self.array is None:
            return {"error": "image_not_loaded"}
        if not self._wcs:
            return {"error": "no_wcs"}

        try:
            x, y = self.world_to_pixel(ra_deg, dec_deg)
        except Exception as e:
            return {"error": f"world_to_pixel_failed: {e}"}

        h, w = self.array.shape
        if x < SEARCH_RADIUS or y < SEARCH_RADIUS or x >= (w - SEARCH_RADIUS) or y >= (h - SEARCH_RADIUS):
            return {"error": "out_of_frame"}

        cx = int(round(x))
        cy = int(round(y))
        r_ap_eff = int(r_ap if r_ap is not None else R_AP_DEFAULT)

        peak = float(np.max(self.array[max(0, cy - 2):min(h, cy + 3), max(0, cx - 2):min(w, cx + 3)]))
        saturated = peak >= SATURATION_CEILING

        flux_g, sky_g, snr_g = aperture_flux(self.array, cx, cy, r_ap=r_ap_eff, bayer_channel="G")
        flux_r, sky_r, snr_r = aperture_flux(self.array, cx, cy, r_ap=r_ap_eff, bayer_channel="R")
        flux_b, sky_b, snr_b = aperture_flux(self.array, cx, cy, r_ap=r_ap_eff, bayer_channel="B")

        return {
            "x": x,
            "y": y,
            "r_ap": r_ap_eff,
            "peak": peak,
            "saturated": saturated,
            "flux_G": flux_g,
            "flux_R": flux_r,
            "flux_B": flux_b,
            "sky_G": sky_g,
            "sky_R": sky_r,
            "sky_B": sky_b,
            "snr_G": snr_g,
            "snr_R": snr_r,
            "snr_B": snr_b,
        }


def _robust_sigma(values: np.ndarray) -> float:
    if len(values) < 2:
        return 0.0
    med = float(np.median(values))
    mad = float(np.median(np.abs(values - med)))
    if mad > 0:
        return 1.4826 * mad
    return float(np.std(values))


def _sigma_clip_comps(comp_rows: list) -> tuple[list, int]:
    survivors = list(comp_rows)
    rejected_total = 0

    for _ in range(CLIP_MAX_ITERS):
        if len(survivors) < MIN_CLIPPED_COMPS:
            break

        zp_arr = np.array([row["zp"] for row in survivors], dtype=np.float64)
        med = float(np.median(zp_arr))
        sigma = _robust_sigma(zp_arr)

        if sigma <= 0:
            break

        next_survivors = [row for row in survivors if abs(row["zp"] - med) <= CLIP_SIGMA * sigma]
        newly_rejected = len(survivors) - len(next_survivors)

        if newly_rejected <= 0:
            break

        if len(next_survivors) < MIN_CLIPPED_COMPS:
            break

        rejected_total += newly_rejected
        survivors = next_survivors

    return survivors, rejected_total


def differential_magnitude(
    fits_file: BayerFITS,
    target_ra: float,
    target_dec: float,
    comp_stars: list,
    channel: str = "G",
) -> dict:
    """
    Compute differential magnitude for target against a sigma-clipped comparison ensemble.
    """
    flux_key = f"flux_{channel}"
    snr_key = f"snr_{channel}"

    t = fits_file.measure_star(target_ra, target_dec, r_ap=None)
    if "error" in t:
        return {"status": "fail", "error": t["error"]}
    if t.get("saturated"):
        return {"status": "fail", "error": "target_saturated", "peak_adu": t.get("peak")}
    if t[flux_key] <= 0:
        return {"status": "fail", "error": "target_flux_zero_or_negative"}

    target_flux = t[flux_key]
    target_snr = t[snr_key]
    target_r_ap = t["r_ap"]

    comp_rows = []

    for comp in comp_stars:
        v_mag = next((b["mag"] for b in comp.get("bands", []) if b["band"] == "V"), None)
        if v_mag is None:
            continue
        if getattr(v_mag, "mask", False):
            continue
        try:
            v_mag = float(v_mag)
        except (TypeError, ValueError):
            continue

        comp_ra = comp.get("ra")
        comp_dec = comp.get("dec")
        if comp_ra is None or comp_dec is None:
            continue

        m = fits_file.measure_star(comp_ra, comp_dec, r_ap=target_r_ap)
        if "error" in m or m.get("saturated"):
            continue
        if m[flux_key] <= 0:
            continue

        comp_snr = m[snr_key]
        if comp_snr < MIN_COMP_SNR:
            continue

        zp = v_mag + 2.5 * math.log10(m[flux_key])
        comp_rows.append({
            "zp": float(zp),
            "weight": float(comp_snr ** 2),
            "snr": float(comp_snr),
            "source_id": comp.get("source_id", "GAIA"),
            "v_mag": float(v_mag),
        })

    if not comp_rows:
        return {"status": "fail", "error": "no_valid_comp_stars"}

    n_comps_raw = len(comp_rows)
    clipped_rows, n_rejected = _sigma_clip_comps(comp_rows)

    if len(clipped_rows) < MIN_CLIPPED_COMPS:
        return {
            "status": "fail",
            "error": f"insufficient_valid_comps_after_clip: {len(clipped_rows)}",
            "n_comps_raw": n_comps_raw,
            "n_comps_rejected": n_rejected,
        }

    zp_arr = np.array([row["zp"] for row in clipped_rows], dtype=np.float64)
    w_arr = np.array([row["weight"] for row in clipped_rows], dtype=np.float64)
    w_sum = w_arr.sum()

    avg_zp = float(np.sum(w_arr * zp_arr) / w_sum)
    zp_std = float(np.sqrt(np.sum(w_arr * (zp_arr - avg_zp) ** 2) / w_sum))
    magnitude = avg_zp - 2.5 * math.log10(target_flux)

    snr_err = 1.0857 / target_snr if target_snr > 0 else 9.99
    total_err = round(math.sqrt(zp_std ** 2 + snr_err ** 2), 3)

    brightest = min(clipped_rows, key=lambda row: row["v_mag"])

    return {
        "status": "ok",
        "mag": round(magnitude, 3),
        "err": total_err,
        "n_comps": len(clipped_rows),
        "n_comps_raw": n_comps_raw,
        "n_comps_rejected": n_rejected,
        "zero_point": round(avg_zp, 4),
        "zp_std": round(zp_std, 4),
        "channel": channel,
        "target_snr": round(target_snr, 1),
        "peak_adu": round(t.get("peak", 0), 1),
        "r_ap_used": target_r_ap,
        "comp_label": brightest["source_id"],
    }
