#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/field_rotation.py
Version: 1.0.0
Objective: Calculate Alt/Az field rotation limits and derive maximum safe exposure times before rotation blur becomes unacceptable.
           alt-az mounted telescopes (ZWO S30-Pro, S30, S50).
           Field rotation smears the PSF into a streak, degrading photometry.
           Maximum safe exposure is fed to exposure_planner.py as a hard cap.

Theory:
    In alt-az mode the field rotates around the optical axis as the telescope
    tracks. Rotation rate (degrees/second):
        dPA/dt = cos(lat) * sin(az) / cos(alt)

    Maximum rotation occurs near the meridian at high altitude.
    Near the zenith (alt → 90°) cos(alt) → 0: the keyhole singularity.
    Hard limit of 5s applies within 2° of zenith.

Reference: Astronomical Algorithms, Meeus (1991), Chapter 14.
"""

import math
from dataclasses import dataclass

SIDEREAL_DEG_PER_SEC = 360.0 / 86164.0905

# Tolerance: maximum acceptable PSF smear in pixels before quality degrades
DEFAULT_TOLERANCE_PX = 2.0   # practical blur budget for solvable alt-az science frames
MAX_SAFE_EXP_S       = 120.0  # absolute cap regardless of rotation
KEYHOLE_ALT_DEG      = 88.0   # within 2° of zenith — apply hard limit
KEYHOLE_EXP_S        = 5.0    # hard limit near zenith


@dataclass
class RotationResult:
    az_deg:          float
    alt_deg:         float
    lat_deg:         float
    rot_rate_deg_s:  float   # field rotation rate in degrees/second
    rot_rate_px_s:   float   # rotation rate in pixels/second at sensor
    max_exp_s:       float   # maximum safe exposure in seconds
    keyhole:         bool    # True if within keyhole zone
    note:            str


def field_rotation_rate(az_deg: float, alt_deg: float,
                        lat_deg: float) -> float:
    """
    Return field rotation rate in degrees/second for an alt-az telescope.
    Positive = clockwise rotation as seen in eyepiece.
    Returns 0.0 if cos(alt) is effectively zero (keyhole).
    """
    az_r  = math.radians(az_deg)
    alt_r = math.radians(alt_deg)
    lat_r = math.radians(lat_deg)

    cos_alt = math.cos(alt_r)
    if abs(cos_alt) < 1e-4:
        return 0.0  # keyhole — handled separately

    return abs(math.cos(lat_r) * math.sin(az_r) / cos_alt) * SIDEREAL_DEG_PER_SEC


def max_exposure_s(
    az_deg:         float,
    alt_deg:        float,
    lat_deg:        float,
    pixscale_arcsec: float,
    tolerance_px:   float = DEFAULT_TOLERANCE_PX,
) -> RotationResult:
    """
    Calculate maximum safe exposure before field rotation exceeds
    tolerance_px pixels of PSF smear.

    Args:
        az_deg:          Target azimuth in degrees
        alt_deg:         Target altitude in degrees
        lat_deg:         Observer latitude in degrees
        pixscale_arcsec: Sensor pixel scale in arcsec/pixel
        tolerance_px:    Max acceptable smear in pixels (default 0.5)

    Returns:
        RotationResult with max_exp_s and diagnostic fields
    """
    # Keyhole check
    if alt_deg >= KEYHOLE_ALT_DEG:
        return RotationResult(
            az_deg=az_deg, alt_deg=alt_deg, lat_deg=lat_deg,
            rot_rate_deg_s=0.0, rot_rate_px_s=0.0,
            max_exp_s=KEYHOLE_EXP_S, keyhole=True,
            note=f"KEYHOLE — alt {alt_deg:.1f}° > {KEYHOLE_ALT_DEG}°. "
                 f"Hard limit {KEYHOLE_EXP_S}s."
        )

    # Rotation rate in degrees/second
    rot_deg_s = field_rotation_rate(az_deg, alt_deg, lat_deg)

    # Convert to arcsec/second → pixels/second
    rot_arcsec_s = rot_deg_s * 3600.0
    rot_px_s     = rot_arcsec_s / pixscale_arcsec

    if rot_px_s < 1e-6:
        # Effectively no rotation (target near N/S pole, or on meridian N/S)
        return RotationResult(
            az_deg=az_deg, alt_deg=alt_deg, lat_deg=lat_deg,
            rot_rate_deg_s=rot_deg_s, rot_rate_px_s=rot_px_s,
            max_exp_s=MAX_SAFE_EXP_S, keyhole=False,
            note=f"Negligible rotation ({rot_px_s*60:.3f} px/min). "
                 f"Max cap {MAX_SAFE_EXP_S}s."
        )

    # Maximum safe exposure
    max_exp = min(tolerance_px / rot_px_s, MAX_SAFE_EXP_S)
    max_exp = max(max_exp, 5.0)  # practical floor for solvable alt-az frames

    severity = "LOW" if max_exp > 60 else ("MEDIUM" if max_exp > 20 else "HIGH")
    note = (
        f"Rotation {rot_deg_s*3600:.3f}\"/s ({rot_px_s:.3f} px/s) — "
        f"max safe {max_exp:.1f}s [{severity}]"
    )

    return RotationResult(
        az_deg=az_deg, alt_deg=alt_deg, lat_deg=lat_deg,
        rot_rate_deg_s=rot_deg_s, rot_rate_px_s=rot_px_s,
        max_exp_s=round(max_exp, 1), keyhole=False,
        note=note
    )


if __name__ == "__main__":
    # Demonstration table for Haarlem (52.38°N)
    # S30-Pro pixel scale: 3.74 arcsec/pixel
    LAT       = 52.38
    PIXSCALE  = 3.74

    print("Field Rotation Table — Haarlem 52.38°N, S30-Pro (3.74\"/px)")
    print("=" * 70)
    print(f"{'Az':>6} {'Alt':>6} {'Rate arcsec/s':>13} {'Rate px/s':>10} {'Max exp':>9}  Note")
    print("-" * 70)

    test_cases = [
        (0,   30), (0,   60), (0,   80),   # North at various altitudes
        (90,  30), (90,  45), (90,  60),   # East
        (180, 30), (180, 60), (180, 75),   # South (near meridian)
        (270, 30), (270, 45), (270, 60),   # West
        (180, 89),                          # Near zenith
    ]

    for az, alt in test_cases:
        r = max_exposure_s(az, alt, LAT, PIXSCALE)
        print(f"{r.az_deg:>6.0f} {r.alt_deg:>6.0f} "
              f"{r.rot_rate_deg_s*3600:>9.3f} "
              f"{r.rot_rate_px_s:>10.4f} "
              f"{r.max_exp_s:>8.1f}s  "
              f"{r.note[:35]}")
