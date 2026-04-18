#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/panorama_calibration.py
Version: 1.0.0
Objective: Shared compass calibration helpers for panorama capture and
Stellarium panorama layout.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import sys
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.env_loader import DATA_DIR


PANORAMA_CALIBRATION = DATA_DIR / "panorama_compass_calibration.json"

_CARDINAL_TRUE_AZ = {
    "n": 0.0,
    "north": 0.0,
    "e": 90.0,
    "east": 90.0,
    "s": 180.0,
    "south": 180.0,
    "w": 270.0,
    "west": 270.0,
}


def normalize_azimuth(value: float) -> float:
    return float(value) % 360.0


def shortest_delta_deg(src_deg: float, dst_deg: float) -> float:
    return ((float(dst_deg) - float(src_deg) + 180.0) % 360.0) - 180.0


def parse_true_azimuth(token: str) -> float:
    text = str(token).strip().lower()
    if text in _CARDINAL_TRUE_AZ:
        return _CARDINAL_TRUE_AZ[text]
    return normalize_azimuth(float(text))


def parse_reference_point(spec: str) -> dict:
    text = str(spec).strip()
    if "->" in text:
        lhs, rhs = text.split("->", 1)
    elif "=" in text:
        lhs, rhs = text.split("=", 1)
    else:
        raise ValueError(f"Invalid reference '{spec}'. Use observed=true, e.g. 210=180 or 210=south")

    observed = normalize_azimuth(float(lhs.strip()))
    true_az = parse_true_azimuth(rhs.strip())
    return {
        "observed_az_deg": observed,
        "true_az_deg": true_az,
        "delta_deg": shortest_delta_deg(observed, true_az),
    }


def load_calibration_points(path: Path | None = None) -> list[dict]:
    file_path = Path(path or PANORAMA_CALIBRATION)
    if not file_path.exists():
        return []
    try:
        payload = json.loads(file_path.read_text())
    except Exception:
        return []

    points = payload.get("points", [])
    if not isinstance(points, list):
        return []

    cleaned: list[dict] = []
    for point in points:
        if not isinstance(point, dict):
            continue
        try:
            observed = normalize_azimuth(float(point["observed_az_deg"]))
            true_az = normalize_azimuth(float(point["true_az_deg"]))
        except Exception:
            continue
        cleaned.append({
            "observed_az_deg": observed,
            "true_az_deg": true_az,
            "delta_deg": shortest_delta_deg(observed, true_az),
        })
    return cleaned


def merge_calibration_points(existing: list[dict], additions: list[dict]) -> list[dict]:
    merged: dict[float, dict] = {}
    for point in existing + additions:
        observed = round(normalize_azimuth(point["observed_az_deg"]), 3)
        true_az = normalize_azimuth(point["true_az_deg"])
        merged[observed] = {
            "observed_az_deg": observed,
            "true_az_deg": true_az,
            "delta_deg": shortest_delta_deg(observed, true_az),
        }
    return [merged[key] for key in sorted(merged)]


def save_calibration_points(points: list[dict], path: Path | None = None) -> Path:
    file_path = Path(path or PANORAMA_CALIBRATION)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "points": [
            {
                "observed_az_deg": round(float(point["observed_az_deg"]), 3),
                "true_az_deg": round(float(point["true_az_deg"]), 3),
            }
            for point in merge_calibration_points([], points)
        ],
    }
    file_path.write_text(json.dumps(payload, indent=2) + "\n")
    return file_path


def apply_calibration(azimuth_deg: float, points: list[dict] | None = None, fallback_offset_deg: float = 0.0) -> float:
    observed = normalize_azimuth(azimuth_deg)
    refs = sorted(points or [], key=lambda item: float(item["observed_az_deg"]))
    if not refs:
        return normalize_azimuth(observed + float(fallback_offset_deg))
    if len(refs) == 1:
        return normalize_azimuth(observed + float(refs[0]["delta_deg"]))

    observed_positions = [float(point["observed_az_deg"]) for point in refs]
    deltas = [float(point["delta_deg"]) for point in refs]
    cycle_positions = observed_positions + [observed_positions[0] + 360.0]
    cycle_deltas = deltas + [deltas[0]]

    lookup_az = observed
    if lookup_az < observed_positions[0]:
        lookup_az += 360.0

    for idx in range(len(refs)):
        start = cycle_positions[idx]
        end = cycle_positions[idx + 1]
        if start <= lookup_az <= end:
            span = max(end - start, 1e-6)
            weight = (lookup_az - start) / span
            interp_delta = cycle_deltas[idx] * (1.0 - weight) + cycle_deltas[idx + 1] * weight
            return normalize_azimuth(observed + interp_delta)

    return normalize_azimuth(observed + deltas[0])
