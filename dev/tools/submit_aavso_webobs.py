#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/submit_aavso_webobs.py
Objective: Probe or submit the newest staged AAVSO report through the
           authenticated apps.aavso.org WebObs photometry form.
"""

from __future__ import annotations

import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = PROJECT_ROOT / "data" / "reports"

import sys
sys.path.insert(0, str(PROJECT_ROOT))

from core.postflight.aavso_submitter import AAVSOWebObsSubmitter


# Pick the newest staged AAVSO extended report by default.
def _latest_aavso_report() -> Path:
    candidates = sorted(REPORT_DIR.glob("AAVSO_*.txt"))
    if not candidates:
        raise FileNotFoundError(f"No staged AAVSO report found in {REPORT_DIR}")
    return candidates[-1]


# Parse command-line flags for safe probe-vs-submit operation.
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe or submit a staged AAVSO report to WebObs.")
    parser.add_argument(
        "--report",
        type=Path,
        help="Explicit AAVSO report file. Defaults to the newest AAVSO_*.txt in data/reports.",
    )
    parser.add_argument(
        "--cookie",
        help="Override the configured AAVSO WebObs session cookie for this run.",
    )
    parser.add_argument(
        "--probe-only",
        action="store_true",
        help="Check authentication and parse the upload form without submitting.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds.",
    )
    return parser.parse_args()


# Render a compact CLI summary from the structured submit/probe result.
def _print_result(result: dict) -> None:
    for key in (
        "checked_utc",
        "submitted_utc",
        "submit_url",
        "final_url",
        "status_code",
        "authenticated",
        "accepted",
        "file_field",
        "result_json",
        "result_html",
        "error",
    ):
        if key in result:
            print(f"{key}: {result[key]}")

    for label in ("success_lines", "warning_lines", "out_of_limit_lines", "error_lines"):
        values = result.get(label) or []
        if values:
            print(f"{label}:")
            for value in values:
                print(f"  - {value}")


# Run the explicit probe or live submit operation.
def main() -> None:
    args = parse_args()
    client = AAVSOWebObsSubmitter(cookie_override=args.cookie, timeout=args.timeout)

    if args.probe_only:
        _print_result(client.probe())
        return

    report_path = args.report.expanduser().resolve() if args.report else _latest_aavso_report()
    _print_result(client.submit(report_path))


if __name__ == "__main__":
    main()
