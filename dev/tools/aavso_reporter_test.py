#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/aavso_reporter_test.py
Version: 1.0.0
Objective: Generate a small dummy AAVSO Extended Format report for WebObs
           preview testing, or the BAA-modified AAVSO Extended variant for
           VSSDB testing. Uses SS Cyg with plausible synthetic values.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))

from core.postflight.aavso_reporter import AAVSOReporter, BAAModifiedExtendedReporter, BAACCDReporter

TEST_OBSERVATIONS = [
    {
        "target":  "SS CYG",
        "jd":      2461115.54321,
        "mag":     12.043,
        "err":     0.021,
        "filter":  "TG",
        "comp":    "000-BCF-527",
        "cmag":    11.190,
        "kname":   "000-BCF-528",
        "kmag":    12.400,
        "amass":   1.234,
        "chart":   "X12345T",
        "notes":   "SeeVar_pipeline_test",
        "peak_adu": 42112.0,
    },
    {
        "target":  "SS CYG",
        "jd":      2461115.58765,
        "mag":     12.071,
        "err":     0.019,
        "filter":  "TG",
        "comp":    "000-BCF-527",
        "cmag":    11.190,
        "kname":   "000-BCF-528",
        "kmag":    12.400,
        "amass":   1.301,
        "chart":   "X12345T",
        "notes":   "SeeVar_pipeline_test",
        "peak_adu": 43851.0,
    },
]

TEST_BAA_CCD_OBSERVATIONS = [
    {
        "target": "SS CYG",
        "jd": 2461115.54321,
        "mag": 12.043,
        "err": 0.021,
        "filter": "TG",
        "chart": "X12345T",
        "target_inst_mag": 17.221,
        "target_inst_err": 0.021,
        "exp_len": 10,
        "file_name": "SS_CYG_20260428T221500_Raw_cal.fits",
        "comp_rows": [
            {"source_id": "000-BCF-527", "v_mag": 11.190, "v_mag_err": 0.010, "inst_mag": 16.367, "inst_err": 0.017},
            {"source_id": "000-BCF-528", "v_mag": 12.400, "v_mag_err": 0.012, "inst_mag": 17.579, "inst_err": 0.021},
            {"source_id": "000-BCF-530", "v_mag": 12.980, "v_mag_err": 0.015, "inst_mag": 18.161, "inst_err": 0.024},
        ],
        "peak_adu": 42112.0,
    },
    {
        "target": "SS CYG",
        "jd": 2461115.58765,
        "mag": 12.071,
        "err": 0.019,
        "filter": "TG",
        "chart": "X12345T",
        "target_inst_mag": 17.244,
        "target_inst_err": 0.019,
        "exp_len": 10,
        "file_name": "SS_CYG_20260428T222100_Raw_cal.fits",
        "comp_rows": [
            {"source_id": "000-BCF-527", "v_mag": 11.190, "v_mag_err": 0.010, "inst_mag": 16.341, "inst_err": 0.017},
            {"source_id": "000-BCF-528", "v_mag": 12.400, "v_mag_err": 0.012, "inst_mag": 17.604, "inst_err": 0.022},
            {"source_id": "000-BCF-530", "v_mag": 12.980, "v_mag_err": 0.015, "inst_mag": 18.186, "inst_err": 0.024},
        ],
        "peak_adu": 43851.0,
    },
]

def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "aavso").strip().lower()
    print("[SeeVar] AAVSO Reporter test driver")
    print("=" * 50)
    if mode == "baa":
        rep = BAAModifiedExtendedReporter(observer_code="TEST")
        observations = TEST_OBSERVATIONS
    elif mode == "baa-full":
        rep = BAACCDReporter(observer_code="TEST")
        observations = TEST_BAA_CCD_OBSERVATIONS
    else:
        rep = AAVSOReporter(observer_code="TEST")
        observations = TEST_OBSERVATIONS
    print(f"Observer code : {rep.obs_code}")
    print(f"Report dir    : {rep.report_dir}")
    print(f"Mode          : {mode}")
    print()
    path = rep.finalize_report(observations)
    print(f"[OK] Report written: {path}")
    print()
    print("Contents:")
    print("-" * 50)
    with open(path) as f:
        print(f.read())
    print("-" * 50)
    print()
    print("Next steps:")
    print("  1. Review the file above — check format looks correct")
    if mode in {"baa", "baa-full"}:
        print("  2. Send the file to the BAA VSS contact for parser verification")
    else:
        print("  2. Go to https://www.aavso.org/webobs")
        print("  3. Upload the file — review the light-curve preview")
        print("  4. CANCEL — do not submit synthetic data to the AID")
    print(f"\nReport path: {path}")

if __name__ == "__main__":
    main()
