#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/catalogs/build_messier_catalog.py
Objective: Normalize simple Messier JSON source data into SeeVar secondary-target schema.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = Path.home() / "Downloads" / "messier_data.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "catalogs" / "messier.json"


def parse_name(raw: str) -> tuple[str, str]:
    """Split source names like 'M1, Crab Nebula.' into object id and alias."""
    text = raw.strip().rstrip(".")
    if "," not in text:
        return text, ""
    ident, alias = text.split(",", 1)
    return ident.strip(), alias.strip()


def parse_coordinates(raw: str) -> tuple[float, float]:
    """Parse 'RA 05h 34.5m, LD. +22º 01’' into decimal RA/Dec degrees."""
    text = (
        raw.replace("–", "-")
        .replace("−", "-")
        .replace("º", "d")
        .replace("°", "d")
        .replace("’", "'")
        .replace(";", ",")
    )
    match = re.search(
        r"RA\s*(\d+(?:\.\d+)?)h\s*(\d+(?:\.\d+)?)m.*?([+-]?\d+(?:\.\d+)?)d\s*(\d+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r"RA\s*(\d+(?:\.\d+)?):\s*(\d+(?:\.\d+)?).*?([+-]?\d+(?:\.\d+)?):\s*(\d+(?:\.\d+)?)",
            text,
            re.IGNORECASE,
        )
    if not match:
        raise ValueError(f"cannot parse coordinates: {raw!r}")

    ra_h = float(match.group(1))
    ra_m = float(match.group(2))
    dec_d = float(match.group(3))
    dec_m = float(match.group(4))
    sign = -1.0 if dec_d < 0 else 1.0
    ra_deg = (ra_h + ra_m / 60.0) * 15.0
    dec_deg = dec_d + sign * dec_m / 60.0
    return round(ra_deg, 6), round(dec_deg, 6)


def normalize(source: list[dict]) -> list[dict]:
    """Convert source rows into planner-compatible secondary imaging targets."""
    targets = []
    for row in source:
        ident, alias = parse_name(str(row["name"]))
        ra_deg, dec_deg = parse_coordinates(str(row["coordinates"]))
        mag = row.get("magnitude")
        targets.append(
            {
                "name": ident,
                "common_name": alias,
                "ra": ra_deg,
                "dec": dec_deg,
                "type": "MESSIER",
                "catalog": "messier",
                "science_mode": "imaging",
                "max_mag": float(mag) if mag is not None else None,
                "priority": -5,
                "duration": 900,
            }
        )
    return targets


def main() -> None:
    parser = argparse.ArgumentParser(description="Build catalogs/messier.json.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    source = json.loads(args.input.read_text(encoding="utf-8"))
    targets = normalize(source)
    payload = {
        "#objective": "Secondary Messier imaging catalog for optional filler targets after primary science.",
        "source": str(args.input),
        "schema": "seevar-secondary-catalog-v1",
        "target_count": len(targets),
        "targets": targets,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(targets)} targets to {args.output}")


if __name__ == "__main__":
    main()
