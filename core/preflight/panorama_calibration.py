#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/panorama_calibration.py
Version: 1.1.0
Objective: Shared compass calibration helpers for panorama capture and
Stellarium panorama layout.
"""

from __future__ import annotations

import json
import re
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
    "ne": 45.0,
    "northeast": 45.0,
    "north-east": 45.0,
    "e": 90.0,
    "east": 90.0,
    "se": 135.0,
    "southeast": 135.0,
    "south-east": 135.0,
    "s": 180.0,
    "south": 180.0,
    "sw": 225.0,
    "southwest": 225.0,
    "south-west": 225.0,
    "w": 270.0,
    "west": 270.0,
    "nw": 315.0,
    "northwest": 315.0,
    "north-west": 315.0,
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


def extract_observed_azimuth_from_name(token: str) -> float | None:
    text = str(token).strip()
    match = re.search(r"obs(\d+(?:_\d+)?)", text.lower())
    if match:
        return normalize_azimuth(float(match.group(1).replace("_", ".")))
    legacy = re.search(r"(?<!true)(?<!cmd)az(\d+(?:_\d+)?)", text.lower())
    if legacy:
        return normalize_azimuth(float(legacy.group(1).replace("_", ".")))
    return None


def _kv_parse(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        fields[key.strip().lower()] = value.strip()
    return fields


def parse_reference_point(spec: str) -> dict:
    text = str(spec).strip()
    if "," in text and "=" in text:
        fields = _kv_parse(text)
        observed_token = fields.get("obs") or fields.get("observed")
        file_token = fields.get("file") or fields.get("image") or fields.get("path")
        true_token = fields.get("true") or fields.get("az") or fields.get("target")
        if not true_token:
            raise ValueError(f"Invalid reference '{spec}'. Missing true=...")
        if observed_token:
            observed = normalize_azimuth(float(observed_token))
        elif file_token:
            observed_from_file = extract_observed_azimuth_from_name(file_token)
            if observed_from_file is None:
                raise ValueError(f"Could not extract observed azimuth from '{file_token}'")
            observed = observed_from_file
        else:
            raise ValueError(f"Invalid reference '{spec}'. Use obs=... or file=...")

        true_az = parse_true_azimuth(true_token)
        point = {
            "observed_az_deg": observed,
            "true_az_deg": true_az,
            "delta_deg": shortest_delta_deg(observed, true_az),
        }
        if file_token:
            point["file"] = str(file_token)
        if "label" in fields:
            point["label"] = fields["label"]
        return point

    if "->" in text:
        lhs, rhs = text.split("->", 1)
    elif "=" in text:
        lhs, rhs = text.split("=", 1)
    else:
        raise ValueError(
            f"Invalid reference '{spec}'. Use observed=true, e.g. 210=180, "
            "210=south, or file=/path/panorama_obs210_3.jpg,true=180,label=south roofline"
        )

    observed_token = lhs.strip()
    observed = extract_observed_azimuth_from_name(observed_token)
    if observed is None:
        observed = normalize_azimuth(float(observed_token))
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
        if point.get("label"):
            cleaned[-1]["label"] = str(point["label"])
        if point.get("file"):
            cleaned[-1]["file"] = str(point["file"])
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
        if point.get("label"):
            merged[observed]["label"] = str(point["label"])
        if point.get("file"):
            merged[observed]["file"] = str(point["file"])
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
                **({"label": str(point["label"])} if point.get("label") else {}),
                **({"file": str(point["file"])} if point.get("file") else {}),
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
