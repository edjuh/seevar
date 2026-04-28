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

from core.postflight.aavso_reporter import AAVSOReporter, BAAModifiedExtendedReporter

TEST_OBSERVATIONS = [
    {
        "target":  "SS CYG",
        "jd":      2461115.54321,
        "mag":     12.043,
        "err":     0.021,
        "filter":  "CV",
        "comp":    "000-BCF-527",
        "cmag":    11.190,
        "kname":   "000-BCF-528",
        "kmag":    12.400,
        "amass":   1.234,
        "chart":   "X12345T",
        "notes":   "SeeVar_pipeline_test",
    },
    {
        "target":  "SS CYG",
        "jd":      2461115.58765,
        "mag":     12.071,
        "err":     0.019,
        "filter":  "CV",
        "comp":    "000-BCF-527",
        "cmag":    11.190,
        "kname":   "000-BCF-528",
        "kmag":    12.400,
        "amass":   1.301,
        "chart":   "X12345T",
        "notes":   "SeeVar_pipeline_test",
    },
]

def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "aavso").strip().lower()
    print("[SeeVar] AAVSO Reporter test driver")
    print("=" * 50)
    if mode == "baa":
        rep = BAAModifiedExtendedReporter(observer_code="TEST")
    else:
        rep = AAVSOReporter(observer_code="TEST")
    print(f"Observer code : {rep.obs_code}")
    print(f"Report dir    : {rep.report_dir}")
    print(f"Mode          : {mode}")
    print()
    path = rep.finalize_report(TEST_OBSERVATIONS)
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
    if mode == "baa":
        print("  2. Send the file to the BAA VSS contact for parser verification")
    else:
        print("  2. Go to https://www.aavso.org/webobs")
        print("  3. Upload the file — review the light-curve preview")
        print("  4. CANCEL — do not submit synthetic data to the AID")
    print(f"\nReport path: {path}")

if __name__ == "__main__":
    main()
