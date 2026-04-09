#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/utils/platesolve_analyst.py
Version: 1.3.0
Objective: Diagnostic reporter for plate-solving success rates and pointing error,
           using astrometry.net with optional header hints and stale-output cleanup.
"""

import math
import os
import subprocess
from pathlib import Path

import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = PROJECT_ROOT / "tests" / "samples"
TEMP_DIR = SAMPLE_DIR / "solve_temp"

os.makedirs(TEMP_DIR, exist_ok=True)

SOLVE_TIMEOUT_SEC = 90
SOLVE_SCALE_FUZZ = 0.25


def _extract_hints(header) -> tuple[float | None, float | None]:
    ra_val = header.get("RA")
    dec_val = header.get("DEC")
    if ra_val is not None and dec_val is not None:
        try:
            return float(ra_val), float(dec_val)
        except Exception:
            pass

    ra_str = header.get("OBJCTRA")
    dec_str = header.get("OBJCTDEC")
    if ra_str and dec_str:
        try:
            coord = SkyCoord(f"{ra_str} {dec_str}", unit=(u.hourangle, u.deg))
            return float(coord.ra.deg), float(coord.dec.deg)
        except Exception:
            pass

    if header.get("CRVAL1") is not None and header.get("CRVAL2") is not None:
        try:
            return float(header["CRVAL1"]), float(header["CRVAL2"])
        except Exception:
            pass

    return None, None


def _extract_scale_arcsec_per_px(header) -> float | None:
    for key in ("PIXSCALE", "SCALE", "SECPIX"):
        value = header.get(key)
        if value not in (None, "", "UNKNOWN"):
            try:
                scale = float(value)
                if scale > 0:
                    return scale
            except Exception:
                pass

    for key in ("CDELT1", "CDELT2"):
        value = header.get(key)
        if value in (None, "", "UNKNOWN"):
            continue
        try:
            scale = abs(float(value)) * 3600.0
            if scale > 0:
                return scale
        except Exception:
            pass

    return None


def _cleanup_stale_products(filename: str):
    stem = Path(filename).stem
    suffixes = [".wcs", ".axy", ".corr", ".match", ".new", ".rdls", ".solved"]
    for suffix in suffixes:
        path = TEMP_DIR / f"{stem}{suffix}"
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass


def solve_and_compare(filepath: Path):
    try:
        header = fits.getheader(filepath, 0, ignore_missing_end=True)
        reported_ra, reported_dec = _extract_hints(header)
    except Exception as e:
        print(f"❌ Header Read Error on {filepath.name}: {e}")
        return

    print(f"\n🧩 Analyzing: {filepath.name}")
    if reported_ra is not None and reported_dec is not None:
        print(f"   📡 Header hint: RA {reported_ra:.5f} | Dec {reported_dec:.5f}")
    else:
        print("   📡 Header hint: unavailable")

    _cleanup_stale_products(filepath.name)

    cmd = [
        "solve-field", str(filepath),
        "--dir", str(TEMP_DIR),
        "--no-plots", "--overwrite",
        "--downsample", "2",
        "--cpulimit", "60",
    ]

    if reported_ra is not None and reported_dec is not None:
        cmd.extend([
            "--ra", str(reported_ra),
            "--dec", str(reported_dec),
            "--radius", "5.0",
        ])

    scale_arcsec = _extract_scale_arcsec_per_px(header)
    if scale_arcsec:
        low = max(0.1, scale_arcsec * (1.0 - SOLVE_SCALE_FUZZ))
        high = scale_arcsec * (1.0 + SOLVE_SCALE_FUZZ)
        cmd.extend([
            "--scale-units", "arcsecperpix",
            "--scale-low", f"{low:.3f}",
            "--scale-high", f"{high:.3f}",
        ])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SOLVE_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        print(f"   ❌ FAILED: solve-field timeout after {SOLVE_TIMEOUT_SEC}s")
        return
    except Exception as e:
        print(f"   ❌ EXECUTION ERROR: {e}")
        return

    wcs_file = TEMP_DIR / filepath.name.replace(".fits", ".wcs")
    if not wcs_file.exists():
        stderr_tail = (result.stderr or "").strip()[-300:]
        print(f"   ❌ FAILED: no WCS output (rc={result.returncode})")
        if stderr_tail:
            print(f"      stderr: {stderr_tail}")
        return

    try:
        w_hdr = fits.getheader(wcs_file, 0)
        true_ra = float(w_hdr.get("CRVAL1"))
        true_dec = float(w_hdr.get("CRVAL2"))
    except Exception as e:
        print(f"   ❌ WCS READ ERROR: {e}")
        return

    print(f"   🎯 SOLVED:   RA {true_ra:.5f} | Dec {true_dec:.5f}")

    if reported_ra is not None and reported_dec is not None:
        try:
            reported = SkyCoord(ra=reported_ra * u.deg, dec=reported_dec * u.deg, frame="icrs")
            solved = SkyCoord(ra=true_ra * u.deg, dec=true_dec * u.deg, frame="icrs")
            err_arcmin = float(reported.separation(solved).arcminute)
            print(f"   📏 ERROR:    {err_arcmin:.2f} arcmin")
        except Exception as e:
            print(f"   ⚠️  Could not compute error: {e}")


if __name__ == "__main__":
    if SAMPLE_DIR.exists():
        fits_files = sorted([f for f in SAMPLE_DIR.iterdir() if f.suffix.lower() == ".fits"])
        if not fits_files:
            print(f"No FITS files found in {SAMPLE_DIR}")
        for f in fits_files:
            solve_and_compare(f)
    else:
        print(f"Sample directory not found: {SAMPLE_DIR}")
