#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/pointing_model.py
Version: 1.2.0
Objective: Store and apply short-lived pointing corrections measured from solved pre-alignment fields.

Coordinate convention
---------------------
RA is stored and returned in decimal hours [0, 24).
Dec is stored and returned in decimal degrees [-90, 90].
Internal degree arithmetic uses the half-open interval (-180, 180] via normalize_deg().

Model kinds
-----------
constant_prealignment  - single (RA, Dec) offset derived from 1-2 solved fields.
affine_prealignment    - 3x2 affine map from solved-sky to target-sky derived from >=3 fields.
    The affine model is trained as solved -> target. At apply-time the desired target RA/Dec
    is used as a first-order proxy for the solved position; this approximation is valid when
    residuals are small, typically < 30 arcmin for pre-alignment fields.
"""

from __future__ import annotations

import json
import logging
import re
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

import numpy as np

from core.utils.env_loader import DATA_DIR

__all__ = [
    "model_path",
    "normalize_ra_hours",
    "normalize_deg",
    "circular_median_deg",
    "apply_pointing_model",
    "build_constant_model",
    "build_affine_model",
    "build_pointing_model",
    "save_pointing_model",
    "load_pointing_model",
]

log = logging.getLogger(__name__)

# Only allow simple alphanumeric + hyphen/underscore scope tags to prevent
# path traversal, e.g. a tag of "../etc/passwd" escaping DATA_DIR.
_SAFE_TAG_RE = re.compile(r"[^\w\-]")


def model_path(scope_tag: str | None = None) -> Path:
    """Return the per-scope runtime JSON file used by the pilot."""
    raw = (scope_tag or "scope").strip() or "scope"
    tag = _SAFE_TAG_RE.sub("_", raw)
    if tag != raw:
        log.warning("scope_tag %r contained unsafe characters; sanitised to %r", raw, tag)
    return DATA_DIR / f"pointing_model.{tag}.json"


def _wrap_signed(value: float, half_period: float) -> float:
    """Wrap a value into the half-open interval (-half_period, half_period]."""
    period = half_period * 2.0
    return ((float(value) + half_period) % period) - half_period


def normalize_ra_hours(delta_hours: float) -> float:
    """Keep a right-ascension delta in the shortest signed interval (-12, 12]."""
    return _wrap_signed(delta_hours, 12.0)


def normalize_deg(delta_deg: float) -> float:
    """Keep an angular delta in the shortest signed interval (-180, 180]."""
    return _wrap_signed(delta_deg, 180.0)


def circular_median_deg(values: Sequence[float]) -> float:
    """Compute a wrap-safe median for a sequence of degree values."""
    if not values:
        return 0.0
    ref = float(values[0])
    deltas = [normalize_deg(float(value) - ref) for value in values]
    return (ref + statistics.median(deltas)) % 360.0


def apply_pointing_model(
    ra_hours: float,
    dec_deg: float,
    model: dict,
) -> tuple[float, float]:
    """Return corrected command coordinates for a target RA/Dec."""
    kind = model.get("kind")

    if kind == "affine_prealignment":
        ref_ra_deg = float(model["ref_ra_deg"])
        x = np.array(
            [normalize_deg(float(ra_hours) * 15.0 - ref_ra_deg), float(dec_deg), 1.0],
            dtype=float,
        )
        ra_coeff = np.array(model["command_ra_delta_coeff"], dtype=float)
        dec_coeff = np.array(model["command_dec_coeff"], dtype=float)
        command_ra_deg = (ref_ra_deg + float(ra_coeff @ x)) % 360.0
        command_dec = float(dec_coeff @ x)
        return command_ra_deg / 15.0, max(-90.0, min(90.0, command_dec))

    if kind == "constant_prealignment":
        corrected_ra = (float(ra_hours) + float(model.get("offset_ra_hours", 0.0))) % 24.0
        corrected_dec = float(dec_deg) + float(model.get("offset_dec_deg", 0.0))
        return corrected_ra, max(-90.0, min(90.0, corrected_dec))

    raise ValueError(
        f"apply_pointing_model: unrecognised model kind {kind!r}. "
        "Expected 'affine_prealignment' or 'constant_prealignment'."
    )


def _median_error(samples: Sequence[dict]) -> float | None:
    """Return the median error in arcmin, if samples include errors."""
    errors = [float(sample["error_arcmin"]) for sample in samples if "error_arcmin" in sample]
    return statistics.median(errors) if errors else None


def _model_header(
    kind: str,
    *,
    scope_tag: str,
    scope_name: str,
    max_age_hours: float,
    n_samples: int,
    now: datetime,
) -> dict:
    """Return fields common to every pointing model."""
    return {
        "version": 1,
        "kind": kind,
        "scope_tag": scope_tag,
        "scope_name": scope_name,
        "created_utc": now.isoformat(),
        "expires_utc": (now + timedelta(hours=float(max_age_hours))).isoformat(),
        "max_age_hours": float(max_age_hours),
        "n_samples": n_samples,
    }


def build_constant_model(
    samples: list[dict],
    *,
    scope_tag: str,
    scope_name: str = "",
    max_age_hours: float = 12.0,
) -> dict:
    """Build a robust constant-offset model from 1-2 solved calibration samples."""
    if not samples:
        raise ValueError("build_constant_model: at least one solved sample is required")

    ra_offsets_deg = [normalize_ra_hours(float(sample["offset_ra_hours"])) * 15.0 for sample in samples]
    median_ra_hours = normalize_ra_hours(circular_median_deg(ra_offsets_deg) / 15.0)
    dec_offsets = [float(sample["offset_dec_deg"]) for sample in samples]
    median_dec = statistics.median(dec_offsets)

    now = datetime.now(timezone.utc)
    return {
        **_model_header(
            "constant_prealignment",
            scope_tag=scope_tag,
            scope_name=scope_name,
            max_age_hours=max_age_hours,
            n_samples=len(samples),
            now=now,
        ),
        "offset_ra_hours": median_ra_hours,
        "offset_dec_deg": median_dec,
        "offset_ra_arcmin": median_ra_hours * 15.0 * 60.0,
        "offset_dec_arcmin": median_dec * 60.0,
        "median_error_arcmin": _median_error(samples),
        "samples": samples,
    }


def build_affine_model(
    samples: list[dict],
    *,
    scope_tag: str,
    scope_name: str = "",
    max_age_hours: float = 12.0,
) -> dict:
    """Build a least-squares affine model from 3 or more solved calibration samples."""
    if len(samples) < 3:
        raise ValueError(
            f"build_affine_model: at least 3 solved samples are required; got {len(samples)}"
        )

    actual_ra_deg = [float(sample["solved_ra_hours"]) * 15.0 for sample in samples]
    ref_ra_deg = circular_median_deg(actual_ra_deg)

    matrix: list[list[float]] = []
    out_ra: list[float] = []
    out_dec: list[float] = []
    for sample in samples:
        solved_ra_deg = float(sample["solved_ra_hours"]) * 15.0
        target_ra_deg = float(sample["target_ra_hours"]) * 15.0
        matrix.append(
            [normalize_deg(solved_ra_deg - ref_ra_deg), float(sample["solved_dec_deg"]), 1.0]
        )
        out_ra.append(normalize_deg(target_ra_deg - ref_ra_deg))
        out_dec.append(float(sample["target_dec_deg"]))

    x = np.array(matrix, dtype=float)
    ra_coeff, *_ = np.linalg.lstsq(x, np.array(out_ra, dtype=float), rcond=None)
    dec_coeff, *_ = np.linalg.lstsq(x, np.array(out_dec, dtype=float), rcond=None)

    now = datetime.now(timezone.utc)
    return {
        **_model_header(
            "affine_prealignment",
            scope_tag=scope_tag,
            scope_name=scope_name,
            max_age_hours=max_age_hours,
            n_samples=len(samples),
            now=now,
        ),
        "ref_ra_deg": ref_ra_deg,
        "command_ra_delta_coeff": [float(value) for value in ra_coeff],
        "command_dec_coeff": [float(value) for value in dec_coeff],
        "median_error_arcmin": _median_error(samples),
        "samples": samples,
    }


def build_pointing_model(
    samples: list[dict],
    *,
    scope_tag: str,
    scope_name: str = "",
    max_age_hours: float = 12.0,
) -> dict:
    """Choose and build the most appropriate model for the available samples."""
    builder = build_affine_model if len(samples) >= 3 else build_constant_model
    return builder(
        samples,
        scope_tag=scope_tag,
        scope_name=scope_name,
        max_age_hours=max_age_hours,
    )


def save_pointing_model(model: dict, scope_tag: str | None = None) -> Path:
    """Persist a model atomically enough for concurrent pilot reads."""
    path = model_path(scope_tag or model.get("scope_tag"))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(model, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    log.debug("Saved pointing model (%s) to %s", model.get("kind"), path)
    return path


def load_pointing_model(
    scope_tag: str | None = None,
    *,
    max_age_hours: float | None = None,
) -> dict | None:
    """Load a still-fresh pointing model; stale or malformed files are ignored.

    max_age_hours is accepted for older callers. The model's own expires_utc is
    authoritative, so callers cannot accidentally extend a model lifetime.
    """
    path = model_path(scope_tag)
    if not path.exists():
        return None

    try:
        model = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Failed to read pointing model from %s: %s", path, exc)
        return None

    try:
        expires_str = model["expires_utc"]
        expires = datetime.fromisoformat(str(expires_str))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
    except (KeyError, ValueError) as exc:
        log.warning("Pointing model at %s has invalid expires_utc (%s); discarding", path, exc)
        return None

    if datetime.now(timezone.utc) >= expires:
        log.debug("Pointing model at %s has expired (expires_utc=%s)", path, expires_str)
        return None

    return model
