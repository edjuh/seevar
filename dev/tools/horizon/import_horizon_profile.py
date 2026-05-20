#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/horizon/import_horizon_profile.py
Objective: Convert external horizon profiles into SeeVar horizon_mask.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "horizon_mask.json"


def parse_args() -> argparse.Namespace:
    """Define the command line for horizon profile conversion."""
    parser = argparse.ArgumentParser(
        description="Import MIRA/NINA/Stellarium az-alt horizon data into SeeVar format."
    )
    parser.add_argument("source", help="Input horizon file")
    parser.add_argument("-o", "--output", default=str(DEFAULT_OUTPUT), help="Output horizon_mask.json")
    parser.add_argument("--source-name", default="", help="Short label stored in the output metadata")
    parser.add_argument("--floor", type=float, default=0.0, help="Minimum altitude clamp for imported points")
    parser.add_argument("--round", type=int, default=2, help="Decimal places for per-degree altitudes")
    return parser.parse_args()


def _clamp_alt(value: float, floor: float) -> float:
    """Keep horizon altitudes inside a sane telescope-planning range."""
    return max(float(floor), min(90.0, float(value)))


def _point_from_mapping(item: dict) -> tuple[float, float] | None:
    """Extract one azimuth/altitude pair from common mapping keys."""
    az = item.get("az", item.get("azimuth", item.get("Azimuth")))
    alt = item.get("alt", item.get("altitude", item.get("Altitude")))
    if az is None or alt is None:
        return None
    return float(az) % 360.0, float(alt)


def _load_json(path: Path) -> list[tuple[float, float]]:
    """Read SeeVar JSON, MIRA-like JSON, or generic point arrays."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("profile"), dict):
        return [(float(k) % 360.0, float(v)) for k, v in data["profile"].items()]
    raw = data.get("points") if isinstance(data, dict) else data
    points = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                point = _point_from_mapping(item)
                if point:
                    points.append(point)
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                points.append((float(item[0]) % 360.0, float(item[1])))
    return points


def _load_csv(path: Path) -> list[tuple[float, float]]:
    """Read CSV files with az/alt headers or first two numeric columns."""
    text = path.read_text(encoding="utf-8")
    sample = "\n".join(text.splitlines()[:5])
    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t ")
    rows = list(csv.reader(text.splitlines(), dialect))
    if not rows:
        return []

    header = [cell.strip().lower() for cell in rows[0]]
    has_header = any(name in {"az", "azimuth"} for name in header)
    points = []
    if has_header:
        az_idx = next(i for i, name in enumerate(header) if name in {"az", "azimuth"})
        alt_idx = next(i for i, name in enumerate(header) if name in {"alt", "altitude", "horizon"})
        data_rows = rows[1:]
    else:
        az_idx, alt_idx, data_rows = 0, 1, rows

    for row in data_rows:
        if len(row) <= max(az_idx, alt_idx):
            continue
        try:
            points.append((float(row[az_idx]) % 360.0, float(row[alt_idx])))
        except ValueError:
            continue
    return points


def _load_mira_yaml(path: Path) -> list[tuple[float, float]]:
    """Read MIRA's simple points: [{az: ..., alt: ...}] YAML profile."""
    points = []
    pattern = re.compile(r"az\s*:\s*([-+]?\d+(?:\.\d+)?)\s*,\s*alt\s*:\s*([-+]?\d+(?:\.\d+)?)")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0]
        match = pattern.search(line)
        if match:
            points.append((float(match.group(1)) % 360.0, float(match.group(2))))
    return points


def _load_plain_pairs(path: Path) -> list[tuple[float, float]]:
    """Read Stellarium/NINA-style plain azimuth altitude pairs."""
    points = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        numbers = re.findall(r"[-+]?\d+(?:\.\d+)?", line)
        if len(numbers) >= 2:
            points.append((float(numbers[0]) % 360.0, float(numbers[1])))
    return points


def load_points(path: Path) -> list[tuple[float, float]]:
    """Load horizon points from JSON, YAML, CSV, or plain text."""
    suffix = path.suffix.lower()
    if suffix == ".json":
        points = _load_json(path)
    elif suffix in {".yaml", ".yml"}:
        points = _load_mira_yaml(path)
    elif suffix == ".csv":
        points = _load_csv(path)
    else:
        points = _load_plain_pairs(path)

    if len(points) < 2:
        raise ValueError(f"{path} did not contain at least two azimuth/altitude points")
    return sorted(points, key=lambda p: p[0])


def interpolate_profile(points: Iterable[tuple[float, float]], floor: float, ndigits: int) -> dict[str, float]:
    """Interpolate sparse azimuth points to SeeVar's per-degree 0..359 profile."""
    src = sorted(((az % 360.0, _clamp_alt(alt, floor)) for az, alt in points), key=lambda p: p[0])
    profile: dict[str, float] = {}
    for az_i in range(360):
        az = float(az_i)
        upper_idx = next((idx for idx, (src_az, _) in enumerate(src) if src_az >= az), 0)
        lower = src[upper_idx - 1]
        upper = src[upper_idx]
        lower_az, lower_alt = lower
        upper_az, upper_alt = upper
        target_az = az
        if upper_az < lower_az:
            upper_az += 360.0
            if target_az < lower_az:
                target_az += 360.0
        span = upper_az - lower_az
        alt = upper_alt if span <= 0 else lower_alt + ((target_az - lower_az) / span) * (upper_alt - lower_alt)
        profile[str(az_i)] = round(_clamp_alt(alt, floor), ndigits)
    return profile


def build_payload(source: Path, points: list[tuple[float, float]], profile: dict[str, float], source_name: str) -> dict:
    """Build SeeVar horizon_mask.json payload with confidence metadata."""
    confidence = {
        str(az): {
            "mean": profile[str(az)],
            "var": 0.0,
            "n": 1,
            "source": f"import:{source_name or source.name}",
        }
        for az in range(360)
    }
    values = list(profile.values())
    return {
        "#objective": "Imported local horizon profile for SeeVar planning.",
        "source": source_name or str(source),
        "source_path": str(source),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "input_points": len(points),
        "n_points": 360,
        "min_alt": round(min(values), 2),
        "max_alt": round(max(values), 2),
        "profile": profile,
        "confidence": confidence,
    }


def main() -> int:
    """Convert the selected horizon source and write SeeVar JSON."""
    args = parse_args()
    source = Path(args.source).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    points = load_points(source)
    profile = interpolate_profile(points, args.floor, args.round)
    payload = build_payload(source, points, profile, args.source_name, )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {output} points=360 input={len(points)} "
        f"min={payload['min_alt']:.1f} max={payload['max_alt']:.1f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
