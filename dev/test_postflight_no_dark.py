#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/test_postflight_no_dark.py
Version: 1.0.0
Objective: Verify postflight fails honestly when no matching master dark exists.
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

TARGET_NAME = "NO_DARK_SYNTH"
WIDTH = 2160
HEIGHT = 3840


def reset_test_artifacts():
    for path in (LOCAL_BUFFER, ARCHIVE_DIR, DARK_DIR, CAL_DIR):
        path.mkdir(parents=True, exist_ok=True)

    for directory in (LOCAL_BUFFER, ARCHIVE_DIR, DARK_DIR, CAL_DIR):
        for p in directory.iterdir():
            if p.is_file():
                p.unlink()

    if LEDGER_FILE.exists():
        LEDGER_FILE.unlink()


def draw_star(img, x, y, amp=12000.0, sigma=2.3):
    x0 = int(round(x))
    y0 = int(round(y))
    radius = max(7, int(round(5 * sigma)))

    xs = np.arange(max(0, x0 - radius), min(img.shape[1], x0 + radius + 1))
    ys = np.arange(max(0, y0 - radius), min(img.shape[0], y0 + radius + 1))
    if len(xs) == 0 or len(ys) == 0:
        return

    xx, yy = np.meshgrid(xs, ys)
    spot = amp * np.exp(-(((xx - x) ** 2 + (yy - y) ** 2) / (2.0 * sigma * sigma)))
    img[np.ix_(ys, xs)] += spot


def make_science_frame():
    rng = np.random.default_rng(404)
    img = rng.normal(520.0, 16.0, (HEIGHT, WIDTH)).astype(np.float32)
    img += 120.0

    draw_star(img, WIDTH / 2, HEIGHT / 2, amp=15000.0, sigma=2.4)
    draw_star(img, WIDTH / 2 - 220, HEIGHT / 2 + 180, amp=9000.0, sigma=2.2)
    draw_star(img, WIDTH / 2 + 260, HEIGHT / 2 - 140, amp=7000.0, sigma=2.0)

    img = np.clip(img, 0, 65535).astype(np.uint16)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    fits_path = LOCAL_BUFFER / f"{TARGET_NAME}_{timestamp}_Raw.fits"

    hdr = fits.Header()
    hdr["OBJECT"] = TARGET_NAME
    hdr["DATE-OBS"] = datetime.now(timezone.utc).isoformat()
    hdr["EXPTIME"] = 8.0
    hdr["EXPMS"] = 8000
    hdr["GAIN"] = 80
    hdr["CCD-TEMP"] = 21.0
    hdr["RA"] = 180.0
    hdr["DEC"] = 25.0
    hdr["CRVAL1"] = 180.0
    hdr["CRVAL2"] = 25.0
    hdr["CRPIX1"] = WIDTH / 2
    hdr["CRPIX2"] = HEIGHT / 2
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
    ledger_status = "MISSING"
    if LEDGER_FILE.exists():
        data = json.loads(LEDGER_FILE.read_text())
        ledger_status = data.get("entries", {}).get(TARGET_NAME, {}).get("status", "MISSING")

    cal_files = sorted(CAL_DIR.glob("*_cal.fit")) + sorted(CAL_DIR.glob("*_cal.fits"))
    archived = sorted(ARCHIVE_DIR.glob("*.fit")) + sorted(ARCHIVE_DIR.glob("*.fits"))

    print("")
    print("No-dark failure test results")
    print(f"  Ledger status   : {ledger_status}")
    print(f"  Calibrated FITS : {len(cal_files)}")
    print(f"  Archived raw    : {len(archived)}")

    if archived:
        print(f"  Archived file   : {archived[0]}")

    if ledger_status != "FAILED_NO_DARK":
        raise SystemExit(1)
    if cal_files:
        raise SystemExit(1)
    if not archived:
        raise SystemExit(1)

    print("")
    print("PASS: missing-dark path failed honestly.")


def main():
    print("Preparing no-dark postflight failure test...")
    reset_test_artifacts()
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

    accountant._analyst.solve_frame = fake_solve_frame
    accountant.process_buffer()
    inspect_results()


if __name__ == "__main__":
    main()
