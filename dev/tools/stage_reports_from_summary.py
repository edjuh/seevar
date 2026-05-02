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
from datetime import datetime, timedelta, timezone

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


# Parse a stored UTC timestamp into an aware datetime for ledger fallback.
def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


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


# Pull the latest coherent set of accepted observations from ledger.json when a
# postflight summary is not yet available on the host.
def _accepted_from_ledger(ledger_path: Path) -> list[dict]:
    payload = json.loads(ledger_path.read_text())
    entries = payload.get("entries", payload) if isinstance(payload, dict) else {}

    observed = []
    for target_name, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("status")) != "OBSERVED":
            continue
        obs_dt = _parse_dt(entry.get("last_obs_utc"))
        if obs_dt is None:
            continue
        observed.append((obs_dt, str(target_name), entry))

    if not observed:
        raise ValueError(f"No OBSERVED ledger rows with last_obs_utc found in {ledger_path}")

    newest_dt = max(item[0] for item in observed)
    cutoff = newest_dt - timedelta(hours=12)
    rows = []
    for obs_dt, target_name, entry in sorted(observed):
        if obs_dt < cutoff:
            continue
        rows.append({
            "target_name": target_name,
            "last_obs_utc": obs_dt.isoformat().replace("+00:00", "Z"),
            "mag": entry.get("last_mag"),
            "err": entry.get("last_err"),
            "filter": entry.get("last_filter", "TG"),
            "calibration_state": entry.get("last_calibration_state", "UNKNOWN"),
            "n_comps": entry.get("last_comps", 0),
            "n_comps_raw": entry.get("last_comps_raw", entry.get("last_comps", 0)),
            "n_comps_rejected": entry.get("last_comps_rejected", 0),
            "peak_adu": entry.get("last_peak_adu"),
            "target_inst_mag": entry.get("last_target_inst_mag"),
            "target_inst_err": entry.get("last_target_inst_err"),
            "scope_name": entry.get("last_scope_name"),
            "capture_file": entry.get("last_capture_path"),
            "comp_rows": entry.get("last_comp_rows") or [],
            "photometric_system": entry.get("last_photometric_system", "TG"),
            "measurement_kind": entry.get("last_measurement_kind", "raw_bayer_green_untransformed"),
        })
    return rows


# Render the requested submission files from one accepted-observation list.
def stage_reports(
    summary_path: Path | None,
    include_baa_ccd: bool = True,
    observer_code: str | None = None,
) -> list[Path]:
    ledger_fallback = False
    if summary_path is not None:
        payload = json.loads(summary_path.read_text())
        accepted = payload.get("accepted_observations") or []
        if not accepted:
            raise ValueError(f"No accepted observations found in {summary_path.name}")
    else:
        accepted = _accepted_from_ledger(PROJECT_ROOT / "data" / "ledger.json")
        ledger_fallback = True

    observations = [_observation_from_summary(row) for row in accepted]
    aavso = AAVSOReporter(observer_code=observer_code)
    baa_ext = BAAModifiedExtendedReporter(observer_code=observer_code)
    outputs = [
        aavso.finalize_report(observations),
        baa_ext.finalize_report(observations),
    ]

    if include_baa_ccd and not ledger_fallback:
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
    summary_path = args.summary.expanduser().resolve() if args.summary else None
    if summary_path is None:
        try:
            summary_path = _latest_summary(report_dir)
        except FileNotFoundError:
            summary_path = None
    outputs = stage_reports(
        summary_path,
        include_baa_ccd=not args.no_baa_ccd,
        observer_code=args.observer_code,
    )
    if summary_path is not None:
        print(f"Summary: {summary_path}")
    else:
        print(f"Summary: ledger fallback ({PROJECT_ROOT / 'data' / 'ledger.json'})")
        if not args.no_baa_ccd:
            print("Note: BAA CCD/CMOS export skipped in ledger fallback mode (exp_len not retained in ledger).")
    for path in outputs:
        print(path)


if __name__ == "__main__":
    main()
