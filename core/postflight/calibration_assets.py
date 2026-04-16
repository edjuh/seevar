#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/postflight/calibration_assets.py
Version: 1.0.0
Objective: Shared calibration asset registry and requirement summaries for dark,
bias, and flat frames.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import sys
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.env_loader import DATA_DIR


CALIBRATION_INDEX_FILE = DATA_DIR / "calibration_index.json"
MISSING_CALIBRATIONS_FILE = DATA_DIR / "missing_calibrations.json"

DARK_LIBRARY_DIR = DATA_DIR / "dark_library"
BIAS_LIBRARY_DIR = DATA_DIR / "bias_library"
FLAT_LIBRARY_DIR = DATA_DIR / "flat_library"

CALIBRATION_DIRS = {
    "dark": DARK_LIBRARY_DIR,
    "bias": BIAS_LIBRARY_DIR,
    "flat": FLAT_LIBRARY_DIR,
}


def ensure_calibration_dirs() -> None:
    for directory in CALIBRATION_DIRS.values():
        directory.mkdir(parents=True, exist_ok=True)


def _empty_index() -> dict:
    return {
        "metadata": {
            "updated_utc": datetime.now(timezone.utc).isoformat(),
            "schema_version": "2026.7",
        },
        "assets": {
            "dark": {},
            "bias": {},
            "flat": {},
        },
    }


def load_calibration_index() -> dict:
    if CALIBRATION_INDEX_FILE.exists():
        try:
            payload = json.loads(CALIBRATION_INDEX_FILE.read_text())
            assets = payload.get("assets", {})
            for kind in CALIBRATION_DIRS:
                assets.setdefault(kind, {})
            payload["assets"] = assets
            payload.setdefault("metadata", {})
            return payload
        except Exception:
            pass
    return _empty_index()


def save_calibration_index(payload: dict) -> None:
    ensure_calibration_dirs()
    payload = dict(payload or {})
    payload["metadata"] = dict(payload.get("metadata", {}))
    payload["metadata"]["updated_utc"] = datetime.now(timezone.utc).isoformat()
    payload["metadata"].setdefault("schema_version", "2026.7")
    CALIBRATION_INDEX_FILE.write_text(json.dumps(payload, indent=2))


def upsert_calibration_asset(kind: str, key: str, entry: dict) -> None:
    kind = str(kind).strip().lower()
    if kind not in CALIBRATION_DIRS:
        raise ValueError(f"Unsupported calibration asset kind: {kind}")

    payload = load_calibration_index()
    assets = payload.setdefault("assets", {})
    assets.setdefault(kind, {})

    normalized = dict(entry or {})
    normalized["kind"] = kind
    normalized["key"] = key
    normalized["updated_utc"] = datetime.now(timezone.utc).isoformat()
    assets[kind][key] = normalized
    save_calibration_index(payload)


def _dedupe_requirement(bucket_map: dict, key: str, seed: dict) -> dict:
    bucket = bucket_map.get(key)
    if bucket is None:
        bucket = dict(seed)
        bucket_map[key] = bucket
    return bucket


def save_missing_calibrations(entries: dict) -> None:
    darks = {}
    biases = {}
    flats = {}

    for target_name, entry in (entries or {}).items():
        if not isinstance(entry, dict):
            continue

        capture_path = entry.get("last_capture_path")
        capture_utc = entry.get("last_capture_utc")
        gain = entry.get("required_bias_gain")
        scope_id = entry.get("required_flat_scope_id")
        scope_name = entry.get("required_flat_scope_name")
        filter_name = entry.get("required_flat_filter")

        if entry.get("status") == "FAILED_NO_DARK":
            exp_ms = entry.get("required_dark_exp_ms")
            dark_gain = entry.get("required_dark_gain")
            temp_bin = entry.get("required_dark_temp_c")
            if exp_ms not in (None, "") and dark_gain not in (None, ""):
                req_key = f"e{int(exp_ms)}_g{int(dark_gain)}_tb{temp_bin if temp_bin is not None else 'na'}"
                bucket = _dedupe_requirement(
                    darks,
                    req_key,
                    {
                        "exp_ms": int(exp_ms),
                        "gain": int(dark_gain),
                        "temp_bin": temp_bin,
                        "targets": [],
                        "capture_paths": [],
                        "latest_capture_utc": None,
                    },
                )
                bucket["targets"].append(target_name)
                if capture_path:
                    bucket["capture_paths"].append(capture_path)
                if capture_utc and (bucket["latest_capture_utc"] is None or capture_utc > bucket["latest_capture_utc"]):
                    bucket["latest_capture_utc"] = capture_utc

        if gain not in (None, ""):
            req_key = f"g{int(gain)}"
            bucket = _dedupe_requirement(
                biases,
                req_key,
                {
                    "gain": int(gain),
                    "targets": [],
                    "capture_paths": [],
                    "latest_capture_utc": None,
                    "status": "recommended",
                },
            )
            bucket["targets"].append(target_name)
            if capture_path:
                bucket["capture_paths"].append(capture_path)
            if capture_utc and (bucket["latest_capture_utc"] is None or capture_utc > bucket["latest_capture_utc"]):
                bucket["latest_capture_utc"] = capture_utc

        if filter_name:
            flat_scope = str(scope_id or "unknown_scope")
            req_key = f"{flat_scope}:{filter_name}"
            bucket = _dedupe_requirement(
                flats,
                req_key,
                {
                    "scope_id": flat_scope,
                    "scope_name": scope_name or flat_scope,
                    "filter": filter_name,
                    "targets": [],
                    "capture_paths": [],
                    "latest_capture_utc": None,
                    "status": "recommended",
                },
            )
            bucket["targets"].append(target_name)
            if capture_path:
                bucket["capture_paths"].append(capture_path)
            if capture_utc and (bucket["latest_capture_utc"] is None or capture_utc > bucket["latest_capture_utc"]):
                bucket["latest_capture_utc"] = capture_utc

    payload = {
        "metadata": {
            "updated_utc": datetime.now(timezone.utc).isoformat(),
            "schema_version": "2026.7",
            "dark_count": len(darks),
            "bias_count": len(biases),
            "flat_count": len(flats),
        },
        "requirements": {
            "darks": sorted(darks.values(), key=lambda x: (x["exp_ms"], x["gain"], str(x["temp_bin"]))),
            "biases": sorted(biases.values(), key=lambda x: x["gain"]),
            "flats": sorted(flats.values(), key=lambda x: (x["scope_id"], x["filter"])),
        },
    }

    ensure_calibration_dirs()
    MISSING_CALIBRATIONS_FILE.write_text(json.dumps(payload, indent=2))
