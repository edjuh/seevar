#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/test_calibration_assets.py
Version: 1.0.0
Objective: Smoke-test calibration asset requirement summaries without FITS dependencies.
"""

import json
from pathlib import Path

import sys
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.postflight.calibration_assets import MISSING_CALIBRATIONS_FILE, save_missing_calibrations


def main():
    sample_entries = {
        "TEST_VAR": {
            "status": "FAILED_NO_DARK",
            "required_dark_exp_ms": 10000,
            "required_dark_gain": 80,
            "required_dark_temp_c": 20.0,
            "required_bias_gain": 80,
            "required_flat_filter": "TG",
            "required_flat_scope_id": "scope01",
            "required_flat_scope_name": "Wilhelmina",
            "last_capture_path": "TEST_VAR_scope01_20260416T190000_Raw.fits",
            "last_capture_utc": "2026-04-16T19:00:00Z",
        },
        "TEST_VAR_2": {
            "status": "OBSERVED",
            "required_bias_gain": 80,
            "required_flat_filter": "TG",
            "required_flat_scope_id": "scope02",
            "required_flat_scope_name": "Anna",
            "last_capture_path": "TEST_VAR_2_scope02_20260416T191500_Raw.fits",
            "last_capture_utc": "2026-04-16T19:15:00Z",
        },
    }

    save_missing_calibrations(sample_entries)
    payload = json.loads(MISSING_CALIBRATIONS_FILE.read_text())
    reqs = payload.get("requirements", {})

    if len(reqs.get("darks", [])) != 1:
        raise SystemExit("expected 1 dark requirement")
    if len(reqs.get("biases", [])) != 1:
        raise SystemExit("expected 1 bias requirement")
    if len(reqs.get("flats", [])) != 2:
        raise SystemExit("expected 2 flat requirements")

    print("PASS: calibration asset requirement summary emitted correctly.")


if __name__ == "__main__":
    main()
