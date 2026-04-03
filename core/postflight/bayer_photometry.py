#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/postflight/bayer_photometry.py
Version: 2.1.0
Objective: Bayer-channel aperture photometry engine for the IMX585 using real solved WCS products for source placement.
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
                self._wcs = None

        return True

    def world_to_pixel(self, ra: float, dec: float) -> Tuple[int, int]:
        if self._wcs is None:
            raise RuntimeError("no_wcs")
        px, py = self._wcs.all_world2pix(ra, dec, 0)
        if not np.isfinite(px) or not np.isfinite(py):
            raise RuntimeError("no_wcs")
        return int(round(float(px))), int(round(float(py)))

    def is_saturated(self, cx: int, cy: int, box: int = 5) -> Tuple[bool, float]:
        arr = self.array
        y0, y1 = max(0, cy - box), min(arr.shape[0], cy + box)
        x0, x1 = max(0, cx - box), min(arr.shape[1], cx + box)
        peak = float(arr[y0:y1, x0:x1].max())
        return peak >= SATURATION_CEILING, peak

    def _fit_aperture(self, cx: int, cy: int) -> int:
        try:
            from core.postflight.psf_models import fit_psf
            from core.postflight.pastinakel_math import calculate_dynamic_aperture

            g_image = self.array.astype(np.float64).copy()
            yy, xx = np.mgrid[0:g_image.shape[0], 0:g_image.shape[1]]
            non_g = (yy % 2) != (xx % 2)
            g_image[non_g] = 0

            result = fit_psf(g_image, cx, cy, model=PSF_MODEL)
            if not result.converged:
                logger.debug("PSF fit did not converge at (%d,%d), using default aperture", cx, cy)
                return R_AP_DEFAULT

            r_ap = int(round(calculate_dynamic_aperture(result.fwhm_pixels)))
            r_ap = max(4, min(20, r_ap))

            logger.debug(
                "PSF FWHM=%.2fpx -> r_ap=%dpx (model=%s, beta=%s)",
                result.fwhm_pixels,
                r_ap,
                result.model,
                result.beta,
            )
            return r_ap
        except Exception as e:
            logger.debug("PSF fit failed: %s, using default aperture", e)
            return R_AP_DEFAULT

    def measure_star(
        self,
        ra: float,
        dec: float,
        r_ap: Optional[int] = None,
        r_sky_in: int = R_SKY_IN_DEFAULT,
        r_sky_out: int = R_SKY_OUT_DEFAULT,
    ) -> dict:
        try:
            cx, cy = self.world_to_pixel(ra, dec)
        except Exception:
            return {"error": "no_wcs"}

        arr = self.array.astype(np.float64)
        h, w = arr.shape

        if not (r_sky_out < cx < w - r_sky_out and r_sky_out < cy < h - r_sky_out):
            return {"error": "out_of_frame", "cx": cx, "cy": cy}

        x0, x1 = max(0, cx - SEARCH_RADIUS), min(w, cx + SEARCH_RADIUS)
        y0, y1 = max(0, cy - SEARCH_RADIUS), min(h, cy + SEARCH_RADIUS)
        patch = arr[y0:y1, x0:x1]
        pk = np.unravel_index(patch.argmax(), patch.shape)
        cx, cy = x0 + pk[1], y0 + pk[0]

        saturated, peak = self.is_saturated(cx, cy)
        if saturated:
            logger.warning("Star at (%d,%d) saturated, peak ADU %.0f", cx, cy, peak)

        if r_ap is None:
            r_ap = self._fit_aperture(cx, cy)

        r_sky_in_used = max(r_sky_in, r_ap + 4)
        r_sky_out_used = max(r_sky_out, r_ap + 10)

        result = {
            "cx": cx,
            "cy": cy,
            "peak": peak,
            "saturated": saturated,
            "r_ap": r_ap,
        }

        for ch in ("G", "R", "B", "ALL"):
            flux, sky, snr = aperture_flux(arr, cx, cy, r_ap, r_sky_in_used, r_sky_out_used, ch)
            result[f"flux_{ch}"] = round(flux, 2)
            result[f"sky_{ch}"] = round(sky, 2)
            result[f"snr_{ch}"] = round(snr, 2)

        return result


def differential_magnitude(
    fits_file: BayerFITS,
    target_ra: float,
    target_dec: float,
    comp_stars: list,
    channel: str = "G",
) -> dict:
    """
    Compute differential magnitude for target against a list of comparison stars.
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

    zero_points = []
    weights = []

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
        zero_points.append(zp)
        weights.append(comp_snr ** 2)

    if not zero_points:
        return {"status": "fail", "error": "no_valid_comp_stars"}

    zp_arr = np.array(zero_points, dtype=np.float64)
    w_arr = np.array(weights, dtype=np.float64)
    w_sum = w_arr.sum()

    avg_zp = float(np.sum(w_arr * zp_arr) / w_sum)
    zp_std = float(np.sqrt(np.sum(w_arr * (zp_arr - avg_zp) ** 2) / w_sum))
    magnitude = avg_zp - 2.5 * math.log10(target_flux)

    snr_err = 1.0857 / target_snr if target_snr > 0 else 9.99
    total_err = round(math.sqrt(zp_std ** 2 + snr_err ** 2), 3)

    return {
        "status": "ok",
        "mag": round(magnitude, 3),
        "err": total_err,
        "n_comps": len(zero_points),
        "zero_point": round(avg_zp, 4),
        "zp_std": round(zp_std, 4),
        "channel": channel,
        "target_snr": round(target_snr, 1),
        "peak_adu": round(t.get("peak", 0), 1),
        "r_ap_used": target_r_ap,
    }
