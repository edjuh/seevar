#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/stage_reports_from_summary.py
Objective: Stage AAVSO/BAA submission files from the latest real-night
           postflight summary JSON written by accountant.py.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from astropy.time import Time

PROJECT_ROOT = Path(__file__).resolve().parents[2]

import sys
sys.path.insert(0, str(PROJECT_ROOT))

from core.postflight.aavso_reporter import (
    AAVSOReporter,
    BAACCDReporter,
    BAAModifiedExtendedReporter,
)


# Choose the newest postflight summary unless the caller pins one explicitly.
def _latest_summary(report_dir: Path) -> Path:
    candidates = sorted(report_dir.glob("postflight_summary_*.json"))
    if not candidates:
        raise FileNotFoundError(f"No postflight summary JSON found in {report_dir}")
    return candidates[-1]


# Convert a stamped UTC string into the JD format required by report exporters.
def _to_jd(obs_utc: str) -> float:
    return float(Time(obs_utc).jd)


# Pick the brightest retained comparison star so the stock AAVSO extended file
# has a concrete CNAME/CMAG pair instead of a blank placeholder.
def _primary_comp(comp_rows: list[dict]) -> tuple[str, float]:
    usable = [row for row in (comp_rows or []) if isinstance(row, dict) and row.get("source_id") and row.get("v_mag") is not None]
    if not usable:
        return "ENSEMBLE", 0.0
    best = min(usable, key=lambda row: float(row.get("v_mag", 99.0)))
    return str(best["source_id"]), float(best["v_mag"])


# Turn one accepted summary row into the normalized observation payload used by
# the AAVSO and BAA report formatters.
def _observation_from_summary(row: dict) -> dict:
    comp_name, comp_mag = _primary_comp(row.get("comp_rows") or [])
    notes = [
        f"MODE={row.get('calibration_state', 'UNKNOWN')}",
        f"COMPS={row.get('n_comps', 0)}/{row.get('n_comps_raw', row.get('n_comps', 0))}",
    ]
    rejected = int(row.get("n_comps_rejected", 0) or 0)
    if rejected:
        notes.append(f"REJ={rejected}")

    return {
        "target": row["target_name"],
        "jd": _to_jd(row["last_obs_utc"]),
        "mag": row["mag"],
        "err": row["err"],
        "filter": row.get("filter", "TG"),
        "trans": "NO",
        "mtype": "STD",
        "comp": comp_name,
        "cmag": comp_mag,
        "kname": "na",
        "kmag": "na",
        "amass": "na",
        "group": row.get("scope_name") or "na",
        "chart": "na",
        "notes": " ".join(notes),
        "peak_adu": row.get("peak_adu"),
        "saturation_checked": True,
        "saturated": False,
        "target_inst_mag": row.get("target_inst_mag"),
        "target_inst_err": row.get("target_inst_err"),
        "exp_len": (float(row["exp_ms"]) / 1000.0) if row.get("exp_ms") not in (None, "") else None,
        "file_name": row.get("capture_file") or f"{row['target_name'].replace(' ', '_')}.fits",
        "comp_rows": row.get("comp_rows") or [],
    }


# Render the requested submission files from one accepted-observation list.
def stage_reports(
    summary_path: Path,
    include_baa_ccd: bool = True,
    observer_code: str | None = None,
) -> list[Path]:
    payload = json.loads(summary_path.read_text())
    accepted = payload.get("accepted_observations") or []
    if not accepted:
        raise ValueError(f"No accepted observations found in {summary_path.name}")

    observations = [_observation_from_summary(row) for row in accepted]
    aavso = AAVSOReporter(observer_code=observer_code)
    baa_ext = BAAModifiedExtendedReporter(observer_code=observer_code)
    outputs = [
        aavso.finalize_report(observations),
        baa_ext.finalize_report(observations),
    ]

    if include_baa_ccd:
        for obs in observations:
            outputs.append(BAACCDReporter(observer_code=observer_code).finalize_report([obs]))

    return outputs


# Parse CLI arguments for a read-mostly staging command.
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage AAVSO/BAA reports from a postflight summary JSON.")
    parser.add_argument(
        "--summary",
        type=Path,
        help="Explicit postflight summary JSON. Defaults to the newest postflight_summary_*.json in data/reports.",
    )
    parser.add_argument(
        "--no-baa-ccd",
        action="store_true",
        help="Skip per-target BAA CCD/CMOS export files.",
    )
    parser.add_argument(
        "--observer-code",
        help="Override observer code when local config.toml is absent or incomplete.",
    )
    return parser.parse_args()


# Run the staging command and print every generated report path.
def main() -> None:
    args = parse_args()
    report_dir = PROJECT_ROOT / "data" / "reports"
    summary_path = args.summary.expanduser().resolve() if args.summary else _latest_summary(report_dir)
    outputs = stage_reports(
        summary_path,
        include_baa_ccd=not args.no_baa_ccd,
        observer_code=args.observer_code,
    )
    print(f"Summary: {summary_path}")
    for path in outputs:
        print(path)


if __name__ == "__main__":
    main()
