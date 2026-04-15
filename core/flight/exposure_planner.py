#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/exposure_planner.py
Version: 1.2.0
Objective: Estimate safe science exposure parameters for a target using brightness, sky quality, and flight constraints.
           its magnitude range, sky conditions, field rotation and SNR goal.
           Three-way exposure cap: SNR, saturation, field rotation.
           Chunking strategy: safe single-frame exposure x n_frames to reach
           total integration time needed for faint-state detection.
           Feeds orchestrator exp_ms and n_frames.

Peer review contributions (March 2026):
  - mag_bright / mag_faint range — variable star magnitude swing
  - Chunking: fast safe frames for bright state, stacked for faint state
  - Scintillation noise term (Young approximation) for small apertures
  - Field rotation cap per az/alt/lat (field_rotation.py)
"""

import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Ensure project root is on path when run standalone
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# IMX585 / S30-Pro sensor constants
# ---------------------------------------------------------------------------
GAIN_E_ADU        = 1.0
READ_NOISE_E      = 1.6
DARK_CURRENT_E_S  = 0.005
FULL_WELL_E       = 50000
SATURATION_ADU    = 60000
PIXEL_SCALE       = 3.75
APERTURE_MM       = 30.0
FOCAL_LENGTH_MM   = 160.0
FOCAL_RATIO       = FOCAL_LENGTH_MM / APERTURE_MM
APERTURE_M        = APERTURE_MM / 1000.0
COLLECTING_AREA   = math.pi * (APERTURE_M / 2.0) ** 2
ALTITUDE_M        = 0.0

SYSTEM_THROUGHPUT = 0.80 * 0.50 * 0.90
V0_FLUX           = 3.64e10 * 88.0

BORTLE_SKY_E_S = {
    1: 0.002, 2: 0.003, 3: 0.005, 4: 0.010, 5: 0.020,
    6: 0.050, 7: 0.120, 8: 0.300, 9: 0.700,
}
DEFAULT_BORTLE  = 7
MIN_EXP_SEC     = 1.0
MAX_EXP_SEC     = 300.0
MAX_FRAME_SEC   = 20.0
TARGET_SNR      = 50.0
MIN_SNR         = 10.0
MAX_TOTAL_SEC   = 300.0

TYPICAL_FWHM_PIX    = 4.0
APERTURE_RADIUS_PIX = 1.7 * TYPICAL_FWHM_PIX
N_PIX_APERTURE      = math.pi * APERTURE_RADIUS_PIX ** 2


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------
@dataclass
class ExposurePlan:
    target_mag:         float
    mag_bright:         float
    exp_sec:            float
    exp_ms:             int
    n_frames:           int
    total_sec:          float
    expected_snr:       float
    source_electrons_s: float
    sky_electrons_s:    float
    n_pix:              float
    saturates:          bool
    saturation_sec:     float
    scintillation_mag:  float
    bortle:             int
    note:               str


# ---------------------------------------------------------------------------
# CCD equation
# ---------------------------------------------------------------------------
def _source_rate(v_mag: float) -> float:
    return V0_FLUX * COLLECTING_AREA * SYSTEM_THROUGHPUT * 10.0**(-v_mag / 2.5)


def _snr(source_e_s, sky_e_pix_s, n_pix, t) -> float:
    signal   = source_e_s * t
    noise_sq = signal + n_pix * (sky_e_pix_s * t + DARK_CURRENT_E_S * t
                                  + READ_NOISE_E**2)
    return signal / math.sqrt(noise_sq) if noise_sq > 0 else 0.0


def _solve_exposure(source_e_s, sky_e_pix_s, n_pix, target_snr) -> float:
    S, N = source_e_s, n_pix
    B    = sky_e_pix_s + DARK_CURRENT_E_S
    R2   = READ_NOISE_E**2
    Q    = target_snr**2
    a    = S**2
    b    = -Q * (S + N * B)
    c    = -Q * N * R2
    disc = b**2 - 4*a*c
    if disc < 0:
        return MAX_EXP_SEC
    return max(MIN_EXP_SEC, (-b + math.sqrt(disc)) / (2*a))


def _saturation_time(source_e_s) -> float:
    peak_e_s = source_e_s * 0.10
    return FULL_WELL_E / peak_e_s if peak_e_s > 0 else MAX_EXP_SEC


# ---------------------------------------------------------------------------
# Scintillation noise (Young approximation)
# ---------------------------------------------------------------------------
def _scintillation_mmag(alt_deg: float, exp_sec: float,
                         aperture_mm: float = APERTURE_MM,
                         altitude_m: float = ALTITUDE_M) -> float:
    if alt_deg <= 0:
        return 999.0
    airmass = 1.0 / math.sin(math.radians(alt_deg))
    D_cm    = aperture_mm / 10.0
    sigma   = (0.09 * D_cm**(-2/3) * airmass**1.75
               * math.exp(-altitude_m / 8000.0)
               / math.sqrt(2.0 * max(exp_sec, 0.1)))
    return round(2.5 * math.log10(1.0 + sigma) * 1000.0, 2)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def plan_exposure(
    target_mag:      float,
    mag_bright:      Optional[float] = None,
    sky_bortle:      int   = DEFAULT_BORTLE,
    target_snr:      float = TARGET_SNR,
    fwhm_pix:        Optional[float] = None,
    az_deg:          Optional[float] = None,
    alt_deg:         Optional[float] = None,
    lat_deg:         Optional[float] = None,
    pixscale_arcsec: float = PIXEL_SCALE,
) -> ExposurePlan:
    if mag_bright is None:
        mag_bright = target_mag

    sky_e_s       = BORTLE_SKY_E_S.get(sky_bortle, BORTLE_SKY_E_S[DEFAULT_BORTLE])
    source_faint  = _source_rate(target_mag)
    source_bright = _source_rate(mag_bright)
    n_pix         = math.pi * (1.7 * fwhm_pix)**2 if fwhm_pix else N_PIX_APERTURE

    # Cap 1: SNR-optimal for faint state
    t_snr = _solve_exposure(source_faint, sky_e_s, n_pix, target_snr)

    # Cap 2: Saturation of bright state
    t_sat     = _saturation_time(source_bright)
    saturates = t_sat < t_snr
    t_frame   = min(t_snr, t_sat * 0.5 if saturates else t_snr)

    # Cap 3: Field rotation
    rotation_note = ""
    if az_deg is not None and alt_deg is not None and lat_deg is not None:
        try:
            from core.flight.field_rotation import max_exposure_s as _rot_max
            rot = _rot_max(az_deg, alt_deg, lat_deg, pixscale_arcsec)
            if rot.max_exp_integ_s < t_frame:
                t_frame = max(MIN_EXP_SEC, rot.max_exp_integ_s)
                rotation_note = f" | ROT {rot.max_exp_integ_s:.0f}s"
        except ImportError:
            pass

    t_frame = min(max(t_frame, MIN_EXP_SEC), MAX_FRAME_SEC)

    # Chunking
    bortle_penalty = 1.0 + max(0, (sky_bortle - 4) * 0.15)
    required_total = min(60.0 * (2.512 ** (target_mag - 12.0)) * bortle_penalty,
                         MAX_TOTAL_SEC)
    n_frames = max(1, math.ceil(required_total / t_frame))
    total_s  = round(t_frame * n_frames, 1)

    achieved_snr = _snr(source_faint, sky_e_s, n_pix, t_frame)
    scint_mmag   = _scintillation_mmag(alt_deg if alt_deg else 45.0, t_frame)

    if saturates:
        note = (f"BRIGHT STATE SATURATES at {t_sat:.1f}s — "
                f"frame {t_frame:.1f}s x {n_frames} = {total_s:.0f}s total"
                f"{rotation_note}")
    elif achieved_snr < MIN_SNR:
        note = (f"FAINT — SNR {achieved_snr:.1f} at {t_frame:.1f}s x "
                f"{n_frames} frames = {total_s:.0f}s{rotation_note}")
    else:
        note = (f"{t_frame:.1f}s x {n_frames} = {total_s:.0f}s | "
                f"SNR {achieved_snr:.0f} | scint {scint_mmag:.1f}mmag"
                f"{rotation_note}")

    return ExposurePlan(
        target_mag=target_mag, mag_bright=mag_bright,
        exp_sec=round(t_frame, 1), exp_ms=int(t_frame * 1000),
        n_frames=n_frames, total_sec=total_s,
        expected_snr=round(achieved_snr, 1),
        source_electrons_s=round(source_faint, 3),
        sky_electrons_s=round(sky_e_s, 6),
        n_pix=round(n_pix, 1), saturates=saturates,
        saturation_sec=round(t_sat, 1),
        scintillation_mag=scint_mmag, bortle=sky_bortle, note=note,
    )


def plan_exposure_table(mags, sky_bortle=DEFAULT_BORTLE,
                        target_snr=TARGET_SNR):
    return [plan_exposure(m, sky_bortle=sky_bortle,
                          target_snr=target_snr) for m in mags]


if __name__ == "__main__":
    print("SeeVar Exposure Planner v1.2.0 — Haarlem, Bortle 8, S30-Pro")
    print("=" * 75)
    print(f"{'Target':20} {'Bright':>7} {'Faint':>6} {'Frame':>7} "
          f"{'N':>5} {'Total':>7} {'SNR':>6} {'Scint':>8}")
    print("-" * 75)

    test_targets = [
        ("Constant V=10",    10.0, 10.0),
        ("Mira (6-13)",       6.0, 13.0),
        ("T CrB (2-10 NR)",   2.0, 10.0),
        ("SS Cyg (8-12 UG)",  8.0, 12.0),
        ("Faint CV (14-16)", 14.0, 16.0),
        ("RCrB (6-15)",       6.0, 15.0),
    ]

    for name, bright, faint in test_targets:
        p = plan_exposure(faint, mag_bright=bright, sky_bortle=8,
                          az_deg=180, alt_deg=45, lat_deg=52.38)
        print(f"{name:20} {bright:>7.1f} {faint:>6.1f} "
              f"{p.exp_sec:>6.1f}s {p.n_frames:>5d} "
              f"{p.total_sec:>6.0f}s {p.expected_snr:>6.1f} "
              f"{p.scintillation_mag:>7.1f}mm")
    print()
    print("Note: T CrB at maximum — 1s frames, saturation guard active!")
