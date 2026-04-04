#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/test_tcrb_s30_s50_field.py
Version: 1.0.0
Objective: Rehearse postflight on T CrB-inspired synthetic S30 and S50 fields.

Design:
- Uses T CrB-centered synthetic scenes
- S30 variant approximates a wider B-chart-style field
- S50 variant approximates a tighter D-chart-style field
- Uses AAVSO-like comparison-star labels/magnitude ladder as scene anchors
- Builds matching master darks
- Runs accountant.process_buffer() with deterministic solve/photometry monkeypatches
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

TCRB_RA = 239.87566667
TCRB_DEC = 25.92016667


def reset_test_artifacts():
    for path in (LOCAL_BUFFER, ARCHIVE_DIR, DARK_DIR, CAL_DIR):
        path.mkdir(parents=True, exist_ok=True)

    for directory in (LOCAL_BUFFER, ARCHIVE_DIR, DARK_DIR, CAL_DIR):
        for p in directory.iterdir():
            if p.is_file():
                p.unlink()

    if LEDGER_FILE.exists():
        LEDGER_FILE.unlink()


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
    dy = (yy - y) / max(0.65, ellipticity)
    spot = amp * np.exp(-(dx * dx + dy * dy) / (2.0 * sigma * sigma))
    img[np.ix_(ys, xs)] += spot


def radial_vignetting(height, width, strength=0.10):
    yy, xx = np.indices((height, width), dtype=np.float32)
    cx = width / 2.0
    cy = height / 2.0
    rx = (xx - cx) / (width / 2.0)
    ry = (yy - cy) / (height / 2.0)
    r2 = np.clip(rx * rx + ry * ry, 0.0, 1.0)
    return 1.0 - strength * r2


def mag_to_amp(vmag, ref_mag=10.5, ref_amp=15000.0):
    return ref_amp * (10.0 ** (-0.4 * (vmag - ref_mag)))


def make_master_dark(tag, exp_ms=EXP_MS, gain=GAIN, temp_bin=TEMP_BIN):
    dark_key = f"dark_tb{temp_bin:+d}_e{exp_ms}_g{gain}"
    dark_path = DARK_DIR / f"{tag}_{dark_key}_master.fits"

    rng = np.random.default_rng(abs(hash(tag)) % (2**32))
    dark = rng.normal(135.0, 4.5, (HEIGHT, WIDTH)).astype(np.float32)

    yy, xx = np.indices((HEIGHT, WIDTH), dtype=np.float32)
    dark += 9.0 * np.exp(-(((xx - 1700.0) ** 2 + (yy - 3200.0) ** 2) / (2.0 * 280.0 ** 2)))

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
    return dark_path


def write_dark_index(entries):
    index = {}
    for entry in entries:
        index[entry["key"]] = {
            "temp_bin": entry["temp_bin"],
            "exp_ms": entry["exp_ms"],
            "gain": entry["gain"],
            "n_frames": 5,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "temp_c_actual": CCD_TEMP,
            "source": "synthetic_tcrb_test",
            "master_path": entry["master_path"],
        }
    (DARK_DIR / "index.json").write_text(json.dumps(index, indent=2))


def sky_background(rng, vign_strength=0.10):
    img = rng.normal(540.0, 16.0, (HEIGHT, WIDTH)).astype(np.float32)
    img += rng.normal(135.0, 4.0, (HEIGHT, WIDTH)).astype(np.float32)
    img *= radial_vignetting(HEIGHT, WIDTH, strength=vign_strength)

    yy, xx = np.indices((HEIGHT, WIDTH), dtype=np.float32)
    img += 16.0 * (yy / HEIGHT) + 8.0 * (xx / WIDTH)
    return img


def scene_s30():
    """
    Wider, more populated B-chart-like scene.
    """
    return [
        {"label": "TCrB", "vmag": 10.2, "x": 1080, "y": 1880, "sigma": 2.4, "ell": 1.00},
        {"label": "98",   "vmag": 9.81, "x": 860,  "y": 1760, "sigma": 2.2, "ell": 1.05},
        {"label": "102",  "vmag": 10.17, "x": 760, "y": 1540, "sigma": 2.2, "ell": 0.95},
        {"label": "106",  "vmag": 10.55, "x": 1120, "y": 1500, "sigma": 2.1, "ell": 1.00},
        {"label": "112",  "vmag": 11.78, "x": 930, "y": 2010, "sigma": 2.0, "ell": 1.05},
        {"label": "124",  "vmag": 12.37, "x": 1210, "y": 2140, "sigma": 1.9, "ell": 1.00},
        {"label": "138",  "vmag": 13.79, "x": 1115, "y": 1925, "sigma": 1.8, "ell": 1.00},
        {"label": "143",  "vmag": 14.34, "x": 1060, "y": 1985, "sigma": 1.8, "ell": 1.00},
        {"label": "field1", "vmag": 11.4, "x": 620, "y": 980, "sigma": 2.0, "ell": 1.10},
        {"label": "field2", "vmag": 12.0, "x": 1440, "y": 1100, "sigma": 1.9, "ell": 0.95},
        {"label": "field3", "vmag": 12.8, "x": 1470, "y": 2530, "sigma": 1.9, "ell": 1.00},
        {"label": "faint_edge", "vmag": 14.6, "x": 1800, "y": 3140, "sigma": 1.7, "ell": 1.00},
    ]


def scene_s50():
    """
    Tighter D-chart-like scene centered on T CrB and closest useful comps.
    """
    return [
        {"label": "TCrB", "vmag": 10.2, "x": 1080, "y": 1900, "sigma": 2.5, "ell": 1.00},
        {"label": "98",   "vmag": 9.81, "x": 820,  "y": 1840, "sigma": 2.3, "ell": 1.00},
        {"label": "106",  "vmag": 10.55, "x": 1100, "y": 1590, "sigma": 2.2, "ell": 1.00},
        {"label": "112",  "vmag": 11.78, "x": 930, "y": 2110, "sigma": 2.0, "ell": 1.00},
        {"label": "124",  "vmag": 12.37, "x": 1260, "y": 2250, "sigma": 1.9, "ell": 1.00},
        {"label": "138",  "vmag": 13.79, "x": 1130, "y": 1980, "sigma": 1.8, "ell": 1.00},
        {"label": "143",  "vmag": 14.34, "x": 1050, "y": 2040, "sigma": 1.8, "ell": 1.00},
    ]


def make_science_frame(tag, target_name, scene, exp_ms=EXP_MS, gain=GAIN, ccd_temp=CCD_TEMP):
    rng = np.random.default_rng(abs(hash(tag)) % (2**32))
    img = sky_background(rng, vign_strength=0.08 if "s50" in tag.lower() else 0.11)

    for idx, obj in enumerate(scene):
        amp = mag_to_amp(obj["vmag"])
        draw_star(
            img,
            obj["x"],
            obj["y"],
            amp=amp,
            sigma=obj["sigma"],
            ellipticity=obj["ell"],
        )
        # Slightly brighten the central target to mimic T CrB prominence in the sample.
        if idx == 0:
            draw_star(img, obj["x"] + 1.0, obj["y"] - 0.5, amp=amp * 0.22, sigma=obj["sigma"] * 1.15, ellipticity=obj["ell"])

    img = np.clip(img, 0, 65535).astype(np.uint16)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    fits_path = LOCAL_BUFFER / f"{target_name}_{tag}_{timestamp}_Raw.fits"

    hdr = fits.Header()
    hdr["OBJECT"] = target_name
    hdr["DATE-OBS"] = datetime.now(timezone.utc).isoformat()
    hdr["EXPTIME"] = exp_ms / 1000.0
    hdr["EXPMS"] = exp_ms
    hdr["GAIN"] = gain
    hdr["CCD-TEMP"] = ccd_temp
    hdr["RA"] = TCRB_RA
    hdr["DEC"] = TCRB_DEC
    hdr["CRVAL1"] = TCRB_RA
    hdr["CRVAL2"] = TCRB_DEC
    hdr["CRPIX1"] = WIDTH / 2
    hdr["CRPIX2"] = HEIGHT / 2
    hdr["CDELT1"] = -0.000305
    hdr["CDELT2"] = 0.000305
    hdr["CTYPE1"] = "RA---TAN"
    hdr["CTYPE2"] = "DEC--TAN"
    hdr["INSTRUME"] = "TCRB-SYNTH"
    hdr["BAYERPAT"] = "RGGB"

    fits.PrimaryHDU(data=img, header=hdr).writeto(fits_path, overwrite=True)
    fits.PrimaryHDU(data=np.zeros((2, 2), dtype=np.uint16), header=hdr).writeto(
        fits_path.with_suffix(".wcs"),
        overwrite=True,
    )

    return fits_path


def inspect_results(expected_targets):
    cal_files = sorted(CAL_DIR.glob("*_cal.fit")) + sorted(CAL_DIR.glob("*_cal.fits"))
    archived = sorted(ARCHIVE_DIR.glob("*.fit")) + sorted(ARCHIVE_DIR.glob("*.fits"))

    ledger_entries = {}
    if LEDGER_FILE.exists():
        data = json.loads(LEDGER_FILE.read_text())
        ledger_entries = data.get("entries", {})

    print("")
    print("T CrB synthetic field results")
    for name in expected_targets:
        status = ledger_entries.get(name, {}).get("status", "MISSING")
        print(f"  {name:<16} : {status}")

    print(f"  Calibrated FITS : {len(cal_files)}")
    print(f"  Archived raw    : {len(archived)}")

    if cal_files:
        print(f"  First cal file  : {cal_files[0]}")
    if archived:
        print(f"  First archived  : {archived[0]}")

    all_ok = all(ledger_entries.get(name, {}).get("status") == "OBSERVED" for name in expected_targets)
    if not all_ok or len(cal_files) < len(expected_targets) or len(archived) < len(expected_targets):
        raise SystemExit(1)

    print("")
    print("PASS: T CrB-inspired S30 and S50 synthetic fields processed successfully.")


def main():
    print("Preparing T CrB-inspired S30/S50 synthetic test...")
    reset_test_artifacts()

    dark_entries = []
    for tag in ("s30", "s50"):
        dark_key = f"dark_tb{TEMP_BIN:+d}_e{EXP_MS}_g{GAIN}"
        dark_path = make_master_dark(tag)
        dark_entries.append({
            "key": dark_key,
            "temp_bin": TEMP_BIN,
            "exp_ms": EXP_MS,
            "gain": GAIN,
            "master_path": str(dark_path),
        })
    # Since both paths share the same calibration key, keep the last one as authoritative.
    write_dark_index([dark_entries[-1]])

    s30_path = make_science_frame("s30", "TCRB_S30", scene_s30())
    s50_path = make_science_frame("s50", "TCRB_S50", scene_s50())

    print(f"  Science FITS : {s30_path.name}")
    print(f"  Science FITS : {s50_path.name}")
    print(f"  Dark index   : {DARK_DIR / 'index.json'}")

    import core.postflight.accountant as accountant
    from core.postflight.dark_calibrator import DarkCalibrator

    accountant.dark_calibrator = DarkCalibrator()

    def fake_solve_frame(path):
        p = Path(path)
        return {
            "ok": True,
            "wcs_path": str(p.with_suffix(".wcs")),
            "solved_ra_deg": TCRB_RA,
            "solved_dec_deg": TCRB_DEC,
            "pixel_scale": 1.1,
            "fov_deg": 0.9,
        }

    def fake_calibrate(fits_path, ra_deg, dec_deg, target_name, target_mag=None, wcs_path=None, solve_result=None):
        if "S30" in target_name:
            return {
                "status": "ok",
                "mag": 10.186,
                "err": 0.029,
                "target_snr": 48.2,
                "n_comps": 4,
                "filter": "TG",
                "zero_point": 24.19,
                "zp_std": 0.06,
                "peak_adu": 16500,
                "solved_ra_deg": solve_result.get("solved_ra_deg", ra_deg),
                "solved_dec_deg": solve_result.get("solved_dec_deg", dec_deg),
            }
        return {
            "status": "ok",
            "mag": 10.173,
            "err": 0.021,
            "target_snr": 61.5,
            "n_comps": 5,
            "filter": "TG",
            "zero_point": 24.41,
            "zp_std": 0.05,
            "peak_adu": 18200,
            "solved_ra_deg": solve_result.get("solved_ra_deg", ra_deg),
            "solved_dec_deg": solve_result.get("solved_dec_deg", dec_deg),
        }

    accountant._analyst.solve_frame = fake_solve_frame
    accountant._engine.calibrate = fake_calibrate

    accountant.process_buffer()
    inspect_results(["TCRB_S30", "TCRB_S50"])


if __name__ == "__main__":
    main()
