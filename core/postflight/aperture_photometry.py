#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/postflight/aperture_photometry.py
Version: 1.0.0
Objective: Reusable aperture-photometry helpers for SeeVar postflight QA and
           science measurement.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from astropy.stats import SigmaClip
from photutils.aperture import ApertureStats, CircularAnnulus, CircularAperture
from photutils.centroids import centroid_quadratic

DEFAULT_RADIUS = 6.0
DEFAULT_ANNULUS_GAP = 5.0
DEFAULT_ANNULUS_WIDTH = 8.0

DEFAULT_SATURATION_LIMIT = 60000.0
DEFAULT_SNR_CRITICAL = 10.0
DEFAULT_SNR_POOR = 15.0
DEFAULT_SKY_SIGMA_BAD = 35.0


@dataclass
class PhotometryStats:
    x: float
    y: float
    radius: float
    raw_flux: float
    net_flux: float
    sky_median: float
    sky_std: float
    peak: float
    snr: float
    aperture_area: float
    valid: bool = True
    flags: list[str] = field(default_factory=list)


def refine_centroid(
    image: np.ndarray,
    x_guess: float,
    y_guess: float,
    radius_px: float = DEFAULT_RADIUS,
    max_shift_px: float | None = None,
) -> tuple[float, float]:
    """
    Refine an approximate source position with a quadratic centroid fit.

    If the fitted centroid is non-finite or shifts farther than the allowed
    maximum, the original guess is returned unchanged.
    """
    if max_shift_px is None:
        max_shift_px = radius_px

    h, w = image.shape
    r = int(radius_px) + 1
    ix, iy = int(x_guess), int(y_guess)

    y_min = max(0, iy - r)
    y_max = min(h, iy + r + 1)
    x_min = max(0, ix - r)
    x_max = min(w, ix + r + 1)

    cutout = image[y_min:y_max, x_min:x_max]
    if cutout.size == 0:
        return x_guess, y_guess

    xc, yc = centroid_quadratic(cutout)
    if not np.isfinite(xc) or not np.isfinite(yc):
        return x_guess, y_guess

    x_refined = x_min + xc
    y_refined = y_min + yc
    shift = np.hypot(x_refined - x_guess, y_refined - y_guess)
    if shift > max_shift_px:
        return x_guess, y_guess

    return float(x_refined), float(y_refined)


def measure_star(
    image: np.ndarray,
    x: float,
    y: float,
    radius_px: float = DEFAULT_RADIUS,
    annulus_gap_px: float = DEFAULT_ANNULUS_GAP,
    annulus_width_px: float = DEFAULT_ANNULUS_WIDTH,
    sigma: float = 3.0,
    maxiters: int = 5,
) -> PhotometryStats:
    """
    Measure a star with a circular aperture and sigma-clipped annulus.

    The returned SNR uses a simple first-order noise estimate based on source
    and local background counts. This is suitable for QA and initial science
    processing, and can be expanded later with gain/read-noise terms.
    """
    r_int = int(radius_px) + 1
    if (
        int(y) - r_int < 0
        or int(y) + r_int >= image.shape[0]
        or int(x) - r_int < 0
        or int(x) + r_int >= image.shape[1]
    ):
        return PhotometryStats(
            x=float(x),
            y=float(y),
            radius=float(radius_px),
            raw_flux=0.0,
            net_flux=0.0,
            sky_median=0.0,
            sky_std=0.0,
            peak=0.0,
            snr=0.0,
            aperture_area=0.0,
            valid=False,
            flags=["EDGE"],
        )

    aper = CircularAperture((x, y), r=radius_px)
    ann = CircularAnnulus(
        (x, y),
        r_in=radius_px + annulus_gap_px,
        r_out=radius_px + annulus_gap_px + annulus_width_px,
    )
    sigclip = SigmaClip(sigma=sigma, maxiters=maxiters)

    cutout = image[int(y) - r_int:int(y) + r_int, int(x) - r_int:int(x) + r_int]
    peak = float(np.max(cutout)) if cutout.size else 0.0

    raw = float(ApertureStats(image, aper).sum)
    sky = ApertureStats(image, ann, sigma_clip=sigclip)

    sky_median = float(sky.median)
    sky_std = float(sky.std)
    area = float(aper.area)

    net_flux = raw - (sky_median * area)
    net_flux = max(net_flux, 1e-5)

    noise = np.sqrt(max(net_flux, 0.0) + (area * max(sky_median, 0.0)))
    snr = float(net_flux / noise) if noise > 0 else 0.0

    return PhotometryStats(
        x=float(x),
        y=float(y),
        radius=float(radius_px),
        raw_flux=raw,
        net_flux=float(net_flux),
        sky_median=sky_median,
        sky_std=sky_std,
        peak=peak,
        snr=snr,
        aperture_area=area,
    )


def classify_quality(
    stats: PhotometryStats,
    saturation_limit: float = DEFAULT_SATURATION_LIMIT,
    snr_critical: float = DEFAULT_SNR_CRITICAL,
    snr_poor: float = DEFAULT_SNR_POOR,
    sky_sigma_bad: float = DEFAULT_SKY_SIGMA_BAD,
) -> PhotometryStats:
    """
    Apply lightweight QA flags to a photometry measurement.
    """
    flags: list[str] = []

    if not stats.valid:
        flags.append("INVALID")
    if stats.peak > saturation_limit:
        flags.append("SATURATED")
    if stats.snr < snr_critical:
        flags.append("CRIT_NOISE")
    elif stats.snr < snr_poor:
        flags.append("POOR_SNR")
    if stats.sky_std > sky_sigma_bad:
        flags.append("BAD_SKY")

    stats.flags = flags
    return stats
