#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/test_dark_postflight.py
Version: 1.0.1
Objective: Smoke-test the dark calibration + accountant closure path without hardware.

This version avoids early singleton initialization by:
- creating synthetic dark assets before importing accountant
- rebuilding accountant.dark_calibrator explicitly after the dark index exists
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from astropy.io import fits

import sys
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.env_loader import DATA_DIR


LOCAL_BUFFER = DATA_DIR / "local_buffer"
ARCHIVE_DIR = DATA_DIR / "archive"
DARK_DIR = DATA_DIR / "dark_library"
CAL_DIR = DATA_DIR / "calibrated_buffer"
LEDGER_FILE = DATA_DIR / "ledger.json"


def reset_test_artifacts():
    for path in (LOCAL_BUFFER, ARCHIVE_DIR, DARK_DIR, CAL_DIR):
        path.mkdir(parents=True, exist_ok=True)

    for directory in (LOCAL_BUFFER, ARCHIVE_DIR, DARK_DIR, CAL_DIR):
        for p in directory.iterdir():
            if p.is_file():
                p.unlink()

    if LEDGER_FILE.exists():
        LEDGER_FILE.unlink()


def make_master_dark(exp_ms=5000, gain=80, temp_bin=20):
    dark_key = f"dark_tb{temp_bin:+d}_e{exp_ms}_g{gain}"
    dark_path = DARK_DIR / f"{dark_key}_master.fits"

    dark = np.full((3840, 2160), 120.0, dtype=np.float32)

    hdr = fits.Header()
    hdr["IMAGETYP"] = "MASTER DARK"
    hdr["EXPTIME"] = exp_ms / 1000.0
    hdr["EXPMS"] = exp_ms
    hdr["GAIN"] = gain
    hdr["TEMPBIN"] = temp_bin
    hdr["TEMPCACT"] = 21.0
    hdr["NFRAMES"] = 5
    hdr["DATE"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    fits.PrimaryHDU(data=dark, header=hdr).writeto(dark_path, overwrite=True)

    index = {
        dark_key: {
            "temp_bin": temp_bin,
            "exp_ms": exp_ms,
            "gain": gain,
            "n_frames": 5,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "temp_c_actual": 21.0,
            "source": "smoke_test",
            "master_path": str(dark_path),
        }
    }
    (DARK_DIR / "index.json").write_text(json.dumps(index, indent=2))
    return dark_path


def draw_star(img, x, y, amp=8000.0, sigma=2.5):
    h, w = img.shape
    x0 = int(round(x))
    y0 = int(round(y))
    radius = max(6, int(round(4 * sigma)))
    xs = np.arange(max(0, x0 - radius), min(w, x0 + radius + 1))
    ys = np.arange(max(0, y0 - radius), min(h, y0 + radius + 1))
    if len(xs) == 0 or len(ys) == 0:
        return
    xx, yy = np.meshgrid(xs, ys)
    spot = amp * np.exp(-(((xx - x) ** 2 + (yy - y) ** 2) / (2.0 * sigma ** 2)))
    img[np.ix_(ys, xs)] += spot


def make_science_frame(name="TEST_VAR", exp_ms=5000, gain=80, ccd_temp=21.3):
    h, w = 3840, 2160
    img = np.random.normal(500.0, 18.0, (h, w)).astype(np.float32)
    img += 120.0

    stars = [
        (w / 2, h / 2, 14000.0),
        (w / 2 - 180, h / 2 + 120, 9000.0),
        (w / 2 + 240, h / 2 - 160, 8500.0),
        (w / 2 - 320, h / 2 - 260, 7000.0),
        (w / 2 + 300, h / 2 + 280, 6500.0),
    ]
    for x, y, amp in stars:
        draw_star(img, x, y, amp=amp, sigma=2.4)

    img = np.clip(img, 0, 65535).astype(np.uint16)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    fits_path = LOCAL_BUFFER / f"{name}_{timestamp}_Raw.fits"

    hdr = fits.Header()
    hdr["OBJECT"] = name
    hdr["DATE-OBS"] = datetime.now(timezone.utc).isoformat()
    hdr["EXPTIME"] = exp_ms / 1000.0
    hdr["EXPMS"] = exp_ms
    hdr["GAIN"] = gain
    hdr["CCD-TEMP"] = ccd_temp
    hdr["RA"] = 180.0
    hdr["DEC"] = 25.0
    hdr["CRVAL1"] = 180.0
    hdr["CRVAL2"] = 25.0
    hdr["CRPIX1"] = w / 2
    hdr["CRPIX2"] = h / 2
    hdr["CDELT1"] = -0.000305
    hdr["CDELT2"] = 0.000305
    hdr["CTYPE1"] = "RA---TAN"
    hdr["CTYPE2"] = "DEC--TAN"

    fits.PrimaryHDU(data=img, header=hdr).writeto(fits_path, overwrite=True)
    fits.PrimaryHDU(data=np.zeros((2, 2), dtype=np.uint16), header=hdr).writeto(
        fits_path.with_suffix(".wcs"),
        overwrite=True,
    )

    return fits_path


def inspect_results():
    ledger_ok = False
    cal_files = sorted(CAL_DIR.glob("*_cal.fit")) + sorted(CAL_DIR.glob("*_cal.fits"))
    archived = sorted(ARCHIVE_DIR.glob("*.fit")) + sorted(ARCHIVE_DIR.glob("*.fits"))

    if LEDGER_FILE.exists():
        data = json.loads(LEDGER_FILE.read_text())
        entries = data.get("entries", {})
        if entries.get("TEST_VAR", {}).get("status") == "OBSERVED":
            ledger_ok = True

    print("")
    print("Smoke test results")
    print(f"  Ledger stamped : {'YES' if ledger_ok else 'NO'}")
    print(f"  Calibrated FITS: {len(cal_files)}")
    print(f"  Archived raw   : {len(archived)}")

    if cal_files:
        print(f"  Cal file       : {cal_files[0]}")
    if archived:
        print(f"  Archived file  : {archived[0]}")

    if not ledger_ok or not cal_files or not archived:
        raise SystemExit(1)

    print("")
    print("PASS: dark calibration + accountant closure path exercised successfully.")


def main():
    print("Preparing dark-postflight smoke test...")
    reset_test_artifacts()
    make_master_dark()
    make_science_frame()

    import core.postflight.accountant as accountant
    from core.postflight.dark_calibrator import DarkCalibrator

    accountant.dark_calibrator = DarkCalibrator()

    def fake_solve_frame(path):
        p = Path(path)
        return {
            "ok": True,
            "wcs_path": str(p.with_suffix(".wcs")),
            "solved_ra_deg": 180.0,
            "solved_dec_deg": 25.0,
            "pixel_scale": 1.1,
            "fov_deg": 0.9,
        }

    def fake_calibrate(fits_path, ra_deg, dec_deg, target_name, target_mag=None, wcs_path=None, solve_result=None):
        return {
            "status": "ok",
            "mag": 12.345,
            "err": 0.031,
            "target_snr": 42.0,
            "n_comps": 4,
            "filter": "TG",
            "zero_point": 24.12,
            "zp_std": 0.07,
            "peak_adu": 14200,
            "solved_ra_deg": solve_result.get("solved_ra_deg", ra_deg) if solve_result else ra_deg,
            "solved_dec_deg": solve_result.get("solved_dec_deg", dec_deg) if solve_result else dec_deg,
        }

    accountant._analyst.solve_frame = fake_solve_frame
    accountant._engine.calibrate = fake_calibrate

    accountant.process_buffer()
    inspect_results()


if __name__ == "__main__":
    main()
