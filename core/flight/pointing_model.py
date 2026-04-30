#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/pointing_model.py
Version: 1.0.0
Objective: Store and apply a short-lived constant pointing correction measured from solved pre-alignment fields.
"""

import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.utils.env_loader import DATA_DIR


# Return the per-scope runtime JSON file used by the pilot.
def model_path(scope_tag: str | None = None) -> Path:
    tag = (scope_tag or "scope").strip() or "scope"
    return DATA_DIR / f"pointing_model.{tag}.json"


# Keep right-ascension deltas in the shortest signed interval.
def normalize_ra_hours(delta_hours: float) -> float:
    return ((float(delta_hours) + 12.0) % 24.0) - 12.0


# Apply a constant solved-field correction to the next commanded slew.
def apply_pointing_model(ra_hours: float, dec_deg: float, model: dict) -> tuple[float, float]:
    corrected_ra = (float(ra_hours) + float(model.get("offset_ra_hours", 0.0))) % 24.0
    corrected_dec = float(dec_deg) + float(model.get("offset_dec_deg", 0.0))
    corrected_dec = max(-90.0, min(90.0, corrected_dec))
    return corrected_ra, corrected_dec


# Build a robust constant model from solved calibration samples.
def build_constant_model(
    samples: list[dict],
    *,
    scope_tag: str,
    scope_name: str = "",
    max_age_hours: float = 12.0,
) -> dict:
    if not samples:
        raise ValueError("Cannot build pointing model without solved samples")

    ra_offsets = [normalize_ra_hours(float(sample["offset_ra_hours"])) for sample in samples]
    dec_offsets = [float(sample["offset_dec_deg"]) for sample in samples]
    errors = [float(sample.get("error_arcmin", 0.0)) for sample in samples]
    now = datetime.now(timezone.utc)

    return {
        "version": 1,
        "kind": "constant_prealignment",
        "scope_tag": scope_tag,
        "scope_name": scope_name,
        "created_utc": now.isoformat(),
        "expires_utc": (now + timedelta(hours=float(max_age_hours))).isoformat(),
        "max_age_hours": float(max_age_hours),
        "n_samples": len(samples),
        "offset_ra_hours": statistics.median(ra_offsets),
        "offset_dec_deg": statistics.median(dec_offsets),
        "offset_ra_arcmin": statistics.median(ra_offsets) * 15.0 * 60.0,
        "offset_dec_arcmin": statistics.median(dec_offsets) * 60.0,
        "median_error_arcmin": statistics.median(errors) if errors else None,
        "samples": samples,
    }


# Persist a pointing model atomically enough for the pilot to read later.
def save_pointing_model(model: dict, scope_tag: str | None = None) -> Path:
    path = model_path(scope_tag or model.get("scope_tag"))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(model, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    return path


# Load a still-fresh pointing model; stale or malformed files are ignored.
def load_pointing_model(scope_tag: str | None = None, *, max_age_hours: float = 12.0) -> dict | None:
    path = model_path(scope_tag)
    if not path.exists():
        return None

    try:
        model = json.loads(path.read_text(encoding="utf-8"))
        created = datetime.fromisoformat(str(model["created_utc"]))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - created > timedelta(hours=float(max_age_hours)):
            return None
        return model
    except Exception:
        return None
