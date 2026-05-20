#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/reports/lightcurve_plots.py
Objective: Build simple SeeVar light-curve PNGs from postflight summaries.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from astropy.time import Time

REPORT_DIR = PROJECT_ROOT / "data" / "reports"
DEFAULT_OUTPUT_DIR = REPORT_DIR / "lightcurves"


def parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).strip().rstrip("Z")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def jd_from_utc(value: Any) -> float | None:
    dt = parse_utc(value)
    if not dt:
        return None
    return float(Time(dt).jd)


def float_or_none(value: Any) -> float | None:
    try:
        if value in (None, "", "na"):
            return None
        result = float(value)
        if math.isnan(result):
            return None
        return result
    except Exception:
        return None


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value).strip("_")


def rows_from_summaries(report_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(report_dir.glob("postflight_summary_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for obs in payload.get("accepted_observations", []):
            name = str(obs.get("target_name") or "").strip()
            mag = float_or_none(obs.get("mag"))
            err = float_or_none(obs.get("err"))
            jd = jd_from_utc(obs.get("last_obs_utc") or obs.get("group_started_utc"))
            if not name or mag is None or jd is None:
                continue
            rows.append(
                {
                    "target": name,
                    "jd": jd,
                    "mag": mag,
                    "err": err,
                    "filter": obs.get("filter") or obs.get("photometric_system") or "TG",
                    "source": path.name,
                }
            )
    return rows


def rows_from_ledger(ledger_path: Path) -> list[dict[str, Any]]:
    if not ledger_path.exists():
        return []
    try:
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    entries = payload.get("entries", {}) if isinstance(payload, dict) else {}
    rows = []
    for name, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        mag = float_or_none(entry.get("last_mag"))
        err = float_or_none(entry.get("last_err"))
        jd = jd_from_utc(entry.get("last_obs_utc") or entry.get("last_success"))
        if mag is None or jd is None:
            continue
        rows.append(
            {
                "target": str(name),
                "jd": jd,
                "mag": mag,
                "err": err,
                "filter": entry.get("last_filter") or "TG",
                "source": ledger_path.name,
            }
        )
    return rows


def write_csv(rows: list[dict[str, Any]], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "lightcurve_points.csv"
    lines = ["target,jd,mag,err,filter,source"]
    for row in sorted(rows, key=lambda item: (item["target"], item["jd"])):
        err = "" if row["err"] is None else f"{row['err']:.3f}"
        lines.append(
            f"{row['target']},{row['jd']:.5f},{row['mag']:.3f},{err},{row['filter']},{row['source']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def plot_lightcurves(rows: list[dict[str, Any]], output_dir: Path, min_points: int) -> list[Path]:
    try:
        import matplotlib
    except ImportError as exc:
        raise SystemExit("matplotlib is required: pip install matplotlib") from exc

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["target"]].append(row)

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for target, points in sorted(grouped.items()):
        points = sorted(points, key=lambda item: item["jd"])
        if len(points) < min_points:
            continue
        x = [point["jd"] for point in points]
        y = [point["mag"] for point in points]
        yerr = [point["err"] or 0.0 for point in points]
        filt = sorted({str(point.get("filter") or "") for point in points if point.get("filter")})

        fig, ax = plt.subplots(figsize=(8, 4.5), dpi=140)
        ax.errorbar(x, y, yerr=yerr, fmt="o", color="#111111", ecolor="#777777", capsize=2)
        ax.invert_yaxis()
        ax.grid(True, alpha=0.25)
        ax.set_title(f"{target} light curve ({', '.join(filt) or 'TG'})")
        ax.set_xlabel("Julian Date")
        ax.set_ylabel("Magnitude")
        fig.tight_layout()

        path = output_dir / f"{safe_name(target)}.png"
        fig.savefig(path)
        plt.close(fig)
        paths.append(path)

    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate simple SeeVar light-curve plots.")
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--ledger", type=Path, default=PROJECT_ROOT / "data" / "ledger.json")
    parser.add_argument("--min-points", type=int, default=1)
    args = parser.parse_args()

    rows = rows_from_summaries(args.report_dir)
    if not rows:
        rows = rows_from_ledger(args.ledger)
    csv_path = write_csv(rows, args.output_dir)
    plots = plot_lightcurves(rows, args.output_dir, max(1, args.min_points))

    print(f"points: {len(rows)}")
    print(f"csv: {csv_path}")
    for path in plots:
        print(path)


if __name__ == "__main__":
    main()
