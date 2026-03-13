#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/postflight/psf_models.py
Version: 1.0.0
Objective: PSF fitting for stellar profiles on IMX585 Bayer frames.
           Provides FWHM estimation feeding dynamic aperture and SNR calculations.

Models implemented:
    - 2D Gaussian  : fast, adequate for synthetic/low-seeing frames
    - Moffat       : production model, correct power-law wings for real seeing
    - Airy disk    : reference only, not used in production pipeline

All models work on a 2D numpy cutout centred on the star.
Output: FWHMResult dataclass consumed by bayer_photometry and exposure_planner.
"""

import numpy as np
from dataclasses import dataclass
from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# IMX585 / S30-Pro physical constants
# ---------------------------------------------------------------------------
PIXEL_SCALE_ARCSEC = 3.75   # arcsec/pixel  (confirmed from pilot.py CDELT)
SENSOR_GAIN_E_ADU  = 1.0    # electrons per ADU (unity gain mode, IMX585 default)
READ_NOISE_E       = 1.6    # electrons RMS  (IMX585 datasheet, low-noise mode)
DARK_CURRENT_E_S   = 0.005  # electrons/pixel/second at ~20°C
FULL_WELL_E        = 50000  # electrons (conservative, well within 16-bit)
SATURATION_ADU     = 60000  # must match pastinakel_math.check_saturation ceiling


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------
@dataclass
class FWHMResult:
    fwhm_pixels: float          # FWHM in pixels
    fwhm_arcsec: float          # FWHM in arcsec
    model: str                  # 'gaussian' | 'moffat'
    amplitude: float            # peak ADU above sky background
    sky_background: float       # median sky ADU per pixel in annulus
    sky_noise: float            # stddev of sky in annulus (ADU)
    x_centre: float             # fitted centroid x (pixels, relative to cutout)
    y_centre: float             # fitted centroid y (pixels, relative to cutout)
    beta: Optional[float]       # Moffat beta parameter (None for Gaussian)
    converged: bool             # optimisation converged cleanly
    residual_rms: float         # RMS of fit residuals (ADU)


# ---------------------------------------------------------------------------
# Cutout helpers
# ---------------------------------------------------------------------------
def _extract_cutout(
    image: np.ndarray,
    cx: int,
    cy: int,
    half_size: int = 15
) -> Tuple[np.ndarray, int, int]:
    """
    Extract a square cutout centred on (cx, cy).
    Returns (cutout, actual_cx_in_cutout, actual_cy_in_cutout).
    Clips to image bounds gracefully.
    """
    rows, cols = image.shape
    x0 = max(0, cx - half_size)
    x1 = min(cols, cx + half_size + 1)
    y0 = max(0, cy - half_size)
    y1 = min(rows, cy + half_size + 1)
    cutout = image[y0:y1, x0:x1].astype(np.float64)
    return cutout, cx - x0, cy - y0


def _sky_background(cutout: np.ndarray, star_radius: int = 10) -> Tuple[float, float]:
    """
    Estimate sky background from an annulus outside star_radius.
    Returns (median_sky, sky_std).
    """
    h, w = cutout.shape
    cy, cx = h // 2, w // 2
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    annulus = cutout[r > star_radius]
    if len(annulus) < 10:
        return float(np.median(cutout)), float(np.std(cutout))
    return float(np.median(annulus)), float(np.std(annulus))


# ---------------------------------------------------------------------------
# 2D Gaussian model
# ---------------------------------------------------------------------------
def _gaussian_2d(coords, amplitude, x0, y0, sigma, sky):
    """Symmetric 2D Gaussian + sky pedestal, flattened for curve_fit."""
    x, y = coords
    return sky + amplitude * np.exp(
        -((x - x0) ** 2 + (y - y0) ** 2) / (2.0 * sigma ** 2)
    )


def fit_gaussian(image: np.ndarray, cx: int, cy: int) -> FWHMResult:
    """
    Fit a symmetric 2D Gaussian to a star centred at (cx, cy).
    FWHM = 2 * sqrt(2 * ln(2)) * sigma ~= 2.355 * sigma
    """
    from scipy.optimize import curve_fit

    cutout, lx, ly = _extract_cutout(image, cx, cy)
    sky_med, sky_std = _sky_background(cutout)
    h, w = cutout.shape
    yy, xx = np.mgrid[0:h, 0:w]

    peak = float(cutout[ly, lx]) - sky_med
    if peak <= 0:
        peak = float(cutout.max()) - sky_med

    p0 = [peak, lx, ly, 3.0, sky_med]
    bounds_lo = [0,    0,    0,    0.5, sky_med - 3 * sky_std]
    bounds_hi = [np.inf, w, h, 20.0, sky_med + 3 * sky_std]

    converged = True
    residual_rms = 0.0
    try:
        popt, _ = curve_fit(
            _gaussian_2d,
            (xx.ravel(), yy.ravel()),
            cutout.ravel(),
            p0=p0,
            bounds=(bounds_lo, bounds_hi),
            maxfev=5000,
        )
        amplitude, x0, y0, sigma, sky = popt
        fwhm_pix = 2.3548 * sigma
        fitted = _gaussian_2d((xx.ravel(), yy.ravel()), *popt).reshape(h, w)
        residual_rms = float(np.sqrt(np.mean((cutout - fitted) ** 2)))
        beta = None
    except Exception:
        converged = False
        data = cutout - sky_med
        data = np.clip(data, 0, None)
        total = data.sum()
        if total > 0:
            x0 = float((xx * data).sum() / total)
            y0 = float((yy * data).sum() / total)
            r2 = ((xx - x0) ** 2 + (yy - y0) ** 2) * data
            sigma = float(np.sqrt(r2.sum() / total))
        else:
            x0, y0, sigma = lx, ly, 3.0
        fwhm_pix = 2.3548 * sigma
        amplitude = peak
        sky = sky_med
        beta = None

    return FWHMResult(
        fwhm_pixels=round(fwhm_pix, 3),
        fwhm_arcsec=round(fwhm_pix * PIXEL_SCALE_ARCSEC, 3),
        model="gaussian",
        amplitude=round(amplitude, 1),
        sky_background=round(sky_med, 1),
        sky_noise=round(sky_std, 3),
        x_centre=round(x0, 2),
        y_centre=round(y0, 2),
        beta=None,
        converged=converged,
        residual_rms=round(residual_rms, 3),
    )


# ---------------------------------------------------------------------------
# Moffat profile  (production model)
# ---------------------------------------------------------------------------
def _moffat_2d(coords, amplitude, x0, y0, alpha, beta, sky):
    """
    Symmetric 2D Moffat + sky pedestal.
    PSF(r) = amplitude * (1 + (r/alpha)^2)^(-beta) + sky
    FWHM = 2 * alpha * sqrt(2^(1/beta) - 1)
    """
    x, y = coords
    r2 = (x - x0) ** 2 + (y - y0) ** 2
    return sky + amplitude * (1.0 + r2 / alpha ** 2) ** (-beta)


def fit_moffat(image: np.ndarray, cx: int, cy: int) -> FWHMResult:
    """
    Fit a symmetric 2D Moffat profile to a star centred at (cx, cy).
    beta ~ 2-4 for typical ground-based seeing.
    Falls back to Gaussian FWHM estimate on convergence failure.
    """
    from scipy.optimize import curve_fit

    cutout, lx, ly = _extract_cutout(image, cx, cy)
    sky_med, sky_std = _sky_background(cutout)
    h, w = cutout.shape
    yy, xx = np.mgrid[0:h, 0:w]

    peak = float(cutout[ly, lx]) - sky_med
    if peak <= 0:
        peak = float(cutout.max()) - sky_med

    p0    = [peak, lx, ly, 3.0, 2.5, sky_med]
    b_lo  = [0,    0,   0,  0.5, 1.0, sky_med - 3 * sky_std]
    b_hi  = [np.inf, w, h, 20.0, 8.0, sky_med + 3 * sky_std]

    converged = True
    residual_rms = 0.0
    try:
        popt, _ = curve_fit(
            _moffat_2d,
            (xx.ravel(), yy.ravel()),
            cutout.ravel(),
            p0=p0,
            bounds=(b_lo, b_hi),
            maxfev=8000,
        )
        amplitude, x0, y0, alpha, beta, sky = popt
        fwhm_pix = 2.0 * alpha * np.sqrt(2.0 ** (1.0 / beta) - 1.0)
        fitted = _moffat_2d((xx.ravel(), yy.ravel()), *popt).reshape(h, w)
        residual_rms = float(np.sqrt(np.mean((cutout - fitted) ** 2)))
    except Exception:
        converged = False
        gauss = fit_gaussian(image, cx, cy)
        fwhm_pix = gauss.fwhm_pixels
        x0, y0, amplitude, beta, sky = lx, ly, peak, None, sky_med

    return FWHMResult(
        fwhm_pixels=round(fwhm_pix, 3),
        fwhm_arcsec=round(fwhm_pix * PIXEL_SCALE_ARCSEC, 3),
        model="moffat",
        amplitude=round(amplitude, 1),
        sky_background=round(sky_med, 1),
        sky_noise=round(sky_std, 3),
        x_centre=round(x0, 2),
        y_centre=round(y0, 2),
        beta=round(beta, 3) if beta is not None else None,
        converged=converged,
        residual_rms=round(residual_rms, 3),
    )


# ---------------------------------------------------------------------------
# Convenience dispatcher
# ---------------------------------------------------------------------------
def fit_psf(
    image: np.ndarray,
    cx: int,
    cy: int,
    model: str = "moffat"
) -> FWHMResult:
    """
    Fit PSF to star at (cx, cy) in image.

    Args:
        image  : 2D numpy array, single Bayer channel (uint16 or float)
        cx, cy : pixel coordinates of star centre
        model  : 'moffat' (default, production) | 'gaussian' (faster)

    Returns:
        FWHMResult
    """
    if model == "gaussian":
        return fit_gaussian(image, cx, cy)
    return fit_moffat(image, cx, cy)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("psf_models.py self-test")
    print("-" * 40)

    size = 64
    yy, xx = np.mgrid[0:size, 0:size]
    cx, cy = 32, 32
    alpha_true, beta_true = 4.0, 2.8
    amp_true, sky_true = 20000.0, 1000.0

    r2 = (xx - cx) ** 2 + (yy - cy) ** 2
    star = sky_true + amp_true * (1.0 + r2 / alpha_true ** 2) ** (-beta_true)
    rng = np.random.default_rng(42)
    star += rng.normal(0, 30, star.shape)
    star = np.clip(star, 0, 65535).astype(np.uint16)

    fwhm_true = 2.0 * alpha_true * np.sqrt(2.0 ** (1.0 / beta_true) - 1.0)
    print(f"True FWHM : {fwhm_true:.3f} px  ({fwhm_true * PIXEL_SCALE_ARCSEC:.2f}\")")

    for model in ("gaussian", "moffat"):
        result = fit_psf(star, cx, cy, model=model)
        print(f"\n{model.upper()} fit:")
        print(f"  FWHM      : {result.fwhm_pixels:.3f} px  ({result.fwhm_arcsec:.2f}\")")
        print(f"  Amplitude : {result.amplitude:.1f} ADU")
        print(f"  Sky       : {result.sky_background:.1f} +/- {result.sky_noise:.1f} ADU")
        print(f"  Centroid  : ({result.x_centre:.2f}, {result.y_centre:.2f})")
        if result.beta:
            print(f"  Beta      : {result.beta:.3f}  (true: {beta_true})")
        print(f"  Converged : {result.converged}")
        print(f"  Residual  : {result.residual_rms:.2f} ADU RMS")
