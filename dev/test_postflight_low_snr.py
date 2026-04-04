#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/test_postflight_low_snr.py
Version: 1.0.0
Objective: Verify postflight rejects a dark-calibrated frame when photometric SNR is too low.
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

TARGET_NAME = "LOW_SNR_SYNTH"
WIDTH = 2160
HEIGHT = 3840
EXP_MS = 10000
GAIN = 80
CCD_TEMP = 21.0
TEMP_BIN = 20


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


def make_master_dark():
    dark_key = f"dark_tb{TEMP_BIN:+d}_e{EXP_MS}_g{GAIN}"
    dark_path = DARK_DIR / f"{dark_key}_master.fits"

    rng = np.random.default_rng(777)
    dark = rng.normal(130.0, 4.5, (HEIGHT, WIDTH)).astype(np.float32)

    hdr = fits.Header()
    hdr["IMAGETYP"] = "MASTER DARK"
    hdr["EXPTIME"] = EXP_MS / 1000.0
    hdr["EXPMS"] = EXP_MS
    hdr["GAIN"] = GAIN
    hdr["TEMPBIN"] = TEMP_BIN
    hdr["TEMPCACT"] = CCD_TEMP
    hdr["NFRAMES"] = 5
    hdr["DATE"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    fits.PrimaryHDU(data=dark, header=hdr).writeto(dark_path, overwrite=True)

    index = {
        dark_key: {
            "temp_bin": TEMP_BIN,
            "exp_ms": EXP_MS,
            "gain": GAIN,
            "n_frames": 5,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "temp_c_actual": CCD_TEMP,
            "source": "low_snr_test",
            "master_path": str(dark_path),
        }
    }
    (DARK_DIR / "index.json").write_text(json.dumps(index, indent=2))


def make_science_frame():
    rng = np.random.default_rng(778)
    img = rng.normal(520.0, 22.0, (HEIGHT, WIDTH)).astype(np.float32)
    img += 130.0

    # Very faint target and comps relative to background noise.
    draw_star(img, WIDTH / 2, HEIGHT / 2, amp=900.0, sigma=2.2)
    draw_star(img, WIDTH / 2 - 210, HEIGHT / 2 + 170, amp=700.0, sigma=2.1)
    draw_star(img, WIDTH / 2 + 250, HEIGHT / 2 - 130, amp=650.0, sigma=2.0)

    img = np.clip(img, 0, 65535).astype(np.uint16)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    fits_path = LOCAL_BUFFER / f"{TARGET_NAME}_{timestamp}_Raw.fits"

    hdr = fits.Header()
    hdr["OBJECT"] = TARGET_NAME
    hdr["DATE-OBS"] = datetime.now(timezone.utc).isoformat()
    hdr["EXPTIME"] = EXP_MS / 1000.0
    hdr["EXPMS"] = EXP_MS
    hdr["GAIN"] = GAIN
    hdr["CCD-TEMP"] = CCD_TEMP
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
    print("Low-SNR failure test results")
    print(f"  Ledger status   : {ledger_status}")
    print(f"  Calibrated FITS : {len(cal_files)}")
    print(f"  Archived raw    : {len(archived)}")

    if cal_files:
        print(f"  Cal file        : {cal_files[0]}")
    if archived:
        print(f"  Archived file   : {archived[0]}")

    if ledger_status != "FAILED_QC_LOW_SNR":
        raise SystemExit(1)
    if not archived:
        raise SystemExit(1)

    print("")
    print("PASS: low-SNR path failed honestly.")


def main():
    print("Preparing low-SNR postflight failure test...")
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
            "mag": 13.800,
            "err": 0.450,
            "target_snr": 2.7,
            "n_comps": 3,
            "filter": "TG",
            "zero_point": 24.1,
            "zp_std": 0.18,
            "peak_adu": 980,
            "solved_ra_deg": solve_result.get("solved_ra_deg", ra_deg),
            "solved_dec_deg": solve_result.get("solved_dec_deg", dec_deg),
        }

    accountant._analyst.solve_frame = fake_solve_frame
    accountant._engine.calibrate = fake_calibrate

    accountant.process_buffer()
    inspect_results()


if __name__ == "__main__":
    main()
