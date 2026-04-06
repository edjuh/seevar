#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/postflight/dark_calibrator.py
Version: 1.1.0
Objective: Match and apply master dark calibration to science FITS frames before photometry.
"""

import logging
import shutil
from pathlib import Path

import numpy as np
from astropy.io import fits

import sys
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.flight.dark_library import DarkLibrary
from core.utils.env_loader import DATA_DIR

logger = logging.getLogger("seevar.dark_calibrator")

CALIBRATED_BUFFER = DATA_DIR / "calibrated_buffer"


def _header_float(header, key, default=None):
    try:
        value = header.get(key, default)
        if value in (None, "", "UNKNOWN"):
            return default
        return float(value)
    except Exception:
        return default


def _header_int(header, key, default=None):
    try:
        value = header.get(key, default)
        if value in (None, "", "UNKNOWN"):
            return default
        return int(round(float(value)))
    except Exception:
        return default


def _calibrated_output_path(science_fits: Path) -> Path:
    name = science_fits.name
    lower = name.lower()

    if lower.endswith(".fits"):
        stem = name[:-5]
        suffix = ".fits"
    elif lower.endswith(".fit"):
        stem = name[:-4]
        suffix = ".fit"
    else:
        stem = science_fits.stem
        suffix = science_fits.suffix or ".fits"

    if stem.endswith("_cal"):
        out_name = f"{stem}{suffix}"
    else:
        out_name = f"{stem}_cal{suffix}"

    return CALIBRATED_BUFFER / out_name


class DarkCalibrator:
    def __init__(self):
        self._library = DarkLibrary()

    def calibrate(self, science_fits: Path) -> dict:
        science_fits = Path(science_fits)
        CALIBRATED_BUFFER.mkdir(parents=True, exist_ok=True)

        try:
            with fits.open(science_fits) as hdul:
                sci_data = hdul[0].data.astype(np.float32)
                sci_header = hdul[0].header.copy()
        except Exception as e:
            return {"status": "fail", "error": f"science_load_failed: {e}"}

        exp_ms = _header_int(sci_header, "EXPMS")
        if exp_ms is None:
            exptime = _header_float(sci_header, "EXPTIME")
            if exptime is not None:
                exp_ms = int(round(exptime * 1000.0))

        gain = _header_int(sci_header, "GAIN")
        temp_c = _header_float(sci_header, "CCD-TEMP", 0.0)

        if exp_ms is None or gain is None:
            return {"status": "fail", "error": "missing_calibration_keys"}

        ok, entry, msg = self._library.best_dark(temp_c, exp_ms, gain)
        if not ok or not entry:
            return {"status": "fail", "error": "no_dark", "detail": msg}

        dark_path = Path(entry["master_path"])

        try:
            with fits.open(dark_path) as hdul:
                dark_data = hdul[0].data.astype(np.float32)
        except Exception as e:
            return {"status": "fail", "error": f"dark_load_failed: {e}"}

        if sci_data.shape != dark_data.shape:
            hint = ""
            if sci_data.shape == dark_data.shape[::-1]:
                hint = " (possible 90-degree rotation mismatch)"
            return {
                "status": "fail",
                "error": f"dark_shape_mismatch: science={sci_data.shape} dark={dark_data.shape}{hint}",
            }

        calibrated = sci_data.astype(np.float32) - dark_data.astype(np.float32)

        neg_frac = float(np.mean(calibrated < 0.0))
        if neg_frac > 0.001:
            logger.warning(
                "Dark subtraction yielded %.2f%% negative pixels for %s; dark may be too bright or mismatched",
                neg_frac * 100.0,
                science_fits.name,
            )

        calibrated = np.clip(calibrated, 0, 65535).astype(np.uint16)
        out_path = _calibrated_output_path(science_fits)

        sci_header["CALSTAT"] = "DARKSUB"
        sci_header["DARKKEY"] = Path(dark_path).stem[:68]
        sci_header["DARKEXP"] = int(exp_ms)
        sci_header["DARKGAIN"] = int(gain)

        fits.PrimaryHDU(data=calibrated, header=sci_header).writeto(out_path, overwrite=True)

        raw_wcs = science_fits.with_suffix(".wcs")
        cal_wcs = out_path.with_suffix(".wcs")
        if raw_wcs.exists():
            try:
                shutil.copy2(raw_wcs, cal_wcs)
            except Exception as e:
                logger.warning("Failed to copy WCS sidecar %s -> %s: %s", raw_wcs.name, cal_wcs.name, e)

        logger.info("Dark calibrated %s using %s -> %s", science_fits.name, dark_path.name, out_path.name)

        return {
            "status": "ok",
            "calibrated_path": str(out_path),
            "dark_path": str(dark_path),
            "dark_key": Path(dark_path).stem,
            "negative_pixel_fraction": round(neg_frac, 6),
        }


dark_calibrator = DarkCalibrator()


if __name__ == "__main__":
    pass
