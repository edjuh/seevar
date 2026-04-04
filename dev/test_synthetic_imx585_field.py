#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/test_synthetic_imx585_field.py
Version: 1.0.0
Objective: End-to-end synthetic IMX585-style postflight rehearsal.

Creates:
- one synthetic science FITS with a 5-object scene
- one matching master dark
- one sidecar WCS
Then:
- monkeypatches solve/calibrate deterministically
- runs accountant.process_buffer()
- reports calibrated output + ledger result

This is a richer rehearsal than the basic dark smoke test:
- background pedestal
- read noise
- mild vignetting
- stars with different flux levels
- one faint near-edge source
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

WIDTH = 2160
HEIGHT = 3840

EXP_MS = 10000
GAIN = 80
CCD_TEMP = 20.8
TEMP_BIN = 20

TARGET_NAME = "IMX585_SYNTH"


def reset_test_artifacts():
    for path in (LOCAL_BUFFER, ARCHIVE_DIR, DARK_DIR, CAL_DIR):
        path.mkdir(parents=True, exist_ok=True)

    for directory in (LOCAL_BUFFER, ARCHIVE_DIR, DARK_DIR, CAL_DIR):
        for p in directory.iterdir():
            if p.is_file():
                p.unlink()

    if LEDGER_FILE.exists():
        LEDGER_FILE.unlink()


def radial_vignetting(height, width, strength=0.10):
    yy, xx = np.indices((height, width), dtype=np.float32)
    cx = width / 2.0
    cy = height / 2.0
    rx = (xx - cx) / (width / 2.0)
    ry = (yy - cy) / (height / 2.0)
    r2 = np.clip(rx * rx + ry * ry, 0.0, 1.0)
    return 1.0 - strength * r2


def draw_star(img, x, y, amp=12000.0, sigma=2.3, ellipticity=1.0):
    x0 = int(round(x))
    y0 = int(round(y))
    radius = max(7, int(round(5 * sigma)))

    xs = np.arange(max(0, x0 - radius), min(img.shape[1], x0 + radius + 1))
    ys = np.arange(max(0, y0 - radius), min(img.shape[0], y0 + radius + 1))
    if len(xs) == 0 or len(ys) == 0:
        return

    xx, yy = np.meshgrid(xs, ys)
    dx = xx - x
    dy = (yy - y) / max(0.6, ellipticity)
    spot = amp * np.exp(-(dx * dx + dy * dy) / (2.0 * sigma * sigma))
    img[np.ix_(ys, xs)] += spot


def make_master_dark(exp_ms=EXP_MS, gain=GAIN, temp_bin=TEMP_BIN):
    dark_key = f"dark_tb{temp_bin:+d}_e{exp_ms}_g{gain}"
    dark_path = DARK_DIR / f"{dark_key}_master.fits"

    rng = np.random.default_rng(585)
    dark = rng.normal(135.0, 4.5, (HEIGHT, WIDTH)).astype(np.float32)

    # Add a faint warm corner / structure so subtraction is not totally flat.
    yy, xx = np.indices((HEIGHT, WIDTH), dtype=np.float32)
    dark += 8.0 * np.exp(-(((xx - 1800.0) ** 2 + (yy - 3300.0) ** 2) / (2.0 * 260.0 ** 2)))

    hdr = fits.Header()
    hdr["IMAGETYP"] = "MASTER DARK"
    hdr["EXPTIME"] = exp_ms / 1000.0
    hdr["EXPMS"] = exp_ms
    hdr["GAIN"] = gain
    hdr["TEMPBIN"] = temp_bin
    hdr["TEMPCACT"] = CCD_TEMP
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
            "temp_c_actual": CCD_TEMP,
            "source": "synthetic_imx585_test",
            "master_path": str(dark_path),
        }
    }
    (DARK_DIR / "index.json").write_text(json.dumps(index, indent=2))
    return dark_path


def make_science_frame(name=TARGET_NAME, exp_ms=EXP_MS, gain=GAIN, ccd_temp=CCD_TEMP):
    rng = np.random.default_rng(1585)

    # Background pedestal plus read noise.
    img = rng.normal(540.0, 16.0, (HEIGHT, WIDTH)).astype(np.float32)

    # Add a dark-like pedestal component so subtraction has something real to remove.
    img += rng.normal(135.0, 4.0, (HEIGHT, WIDTH)).astype(np.float32)

    # Mild vignetting, IMX585-ish engineering feel rather than exact physics.
    vign = radial_vignetting(HEIGHT, WIDTH, strength=0.11)
    img *= vign

    # A tiny sky gradient.
    yy, xx = np.indices((HEIGHT, WIDTH), dtype=np.float32)
    img += 18.0 * (yy / HEIGHT) + 10.0 * (xx / WIDTH)

    # Five synthetic objects: target, 3 comps, 1 faint near edge.
    objects = [
        {"name": "target", "x": WIDTH / 2 + 10, "y": HEIGHT / 2 - 20, "amp": 18000.0, "sigma": 2.4, "ell": 1.00},
        {"name": "comp1",  "x": WIDTH / 2 - 260, "y": HEIGHT / 2 + 160, "amp": 12000.0, "sigma": 2.3, "ell": 1.10},
        {"name": "comp2",  "x": WIDTH / 2 + 320, "y": HEIGHT / 2 - 210, "amp": 9500.0,  "sigma": 2.2, "ell": 0.95},
        {"name": "comp3",  "x": WIDTH / 2 - 420, "y": HEIGHT / 2 - 330, "amp": 7200.0,  "sigma": 2.0, "ell": 1.05},
        {"name": "faint",  "x": WIDTH - 180,     "y": HEIGHT - 260,     "amp": 2400.0,  "sigma": 1.9, "ell": 1.00},
    ]
    for obj in objects:
        draw_star(img, obj["x"], obj["y"], amp=obj["amp"], sigma=obj["sigma"], ellipticity=obj["ell"])

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
    hdr["RA"] = 180.125
    hdr["DEC"] = 24.875
    hdr["CRVAL1"] = 180.125
    hdr["CRVAL2"] = 24.875
    hdr["CRPIX1"] = WIDTH / 2
    hdr["CRPIX2"] = HEIGHT / 2
    hdr["CDELT1"] = -0.000305
    hdr["CDELT2"] = 0.000305
    hdr["CTYPE1"] = "RA---TAN"
    hdr["CTYPE2"] = "DEC--TAN"
    hdr["INSTRUME"] = "IMX585-SYNTH"
    hdr["BAYERPAT"] = "RGGB"

    fits.PrimaryHDU(data=img, header=hdr).writeto(fits_path, overwrite=True)
    fits.PrimaryHDU(data=np.zeros((2, 2), dtype=np.uint16), header=hdr).writeto(
        fits_path.with_suffix(".wcs"),
        overwrite=True,
    )

    return fits_path, objects


def inspect_results(expected_name=TARGET_NAME):
    ledger_ok = False
    cal_files = sorted(CAL_DIR.glob("*_cal.fit")) + sorted(CAL_DIR.glob("*_cal.fits"))
    archived = sorted(ARCHIVE_DIR.glob("*.fit")) + sorted(ARCHIVE_DIR.glob("*.fits"))

    if LEDGER_FILE.exists():
        data = json.loads(LEDGER_FILE.read_text())
        entries = data.get("entries", {})
        if entries.get(expected_name, {}).get("status") == "OBSERVED":
            ledger_ok = True

    print("")
    print("Synthetic IMX585 test results")
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
    print("PASS: synthetic IMX585-style field processed successfully.")


def main():
    print("Preparing synthetic IMX585-style postflight test...")
    reset_test_artifacts()
    dark_path = make_master_dark()
    science_path, objects = make_science_frame()

    print(f"  Science FITS : {science_path}")
    print(f"  Master dark  : {dark_path}")
    print(f"  Objects      : {len(objects)} synthetic sources")

    import core.postflight.accountant as accountant
    from core.postflight.dark_calibrator import DarkCalibrator

    accountant.dark_calibrator = DarkCalibrator()

    def fake_solve_frame(path):
        p = Path(path)
        return {
            "ok": True,
            "wcs_path": str(p.with_suffix(".wcs")),
            "solved_ra_deg": 180.125,
            "solved_dec_deg": 24.875,
            "pixel_scale": 1.1,
            "fov_deg": 0.9,
        }

    def fake_calibrate(fits_path, ra_deg, dec_deg, target_name, target_mag=None, wcs_path=None, solve_result=None):
        # Deterministic "successful" photometry result so we test orchestration/wiring, not catalog IO.
        return {
            "status": "ok",
            "mag": 11.982,
            "err": 0.024,
            "target_snr": 57.3,
            "n_comps": 3,
            "filter": "TG",
            "zero_point": 24.38,
            "zp_std": 0.05,
            "peak_adu": 18200,
            "solved_ra_deg": solve_result.get("solved_ra_deg", ra_deg) if solve_result else ra_deg,
            "solved_dec_deg": solve_result.get("solved_dec_deg", dec_deg) if solve_result else dec_deg,
        }

    accountant._analyst.solve_frame = fake_solve_frame
    accountant._engine.calibrate = fake_calibrate

    accountant.process_buffer()
    inspect_results()


if __name__ == "__main__":
    main()
