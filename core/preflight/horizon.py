#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/horizon.py
Version: 2.1.1
Objective: Veto and score targets based on local obstructions using Az/Alt mapping.
"""

import json
import tomllib
import logging
from pathlib import Path

logger = logging.getLogger("seevar.horizon")

PROJECT_ROOT  = Path(__file__).resolve().parents[2]
CONFIG_PATH   = PROJECT_ROOT / "config.toml"
DEFAULT_MASK_PATH = PROJECT_ROOT / "data" / "horizon_mask.json"

DEFAULT_SCIENCE_FLOOR_DEG = 15.0

_profile = {}
_use_profile = False
_profile_source = None
_config = None
_obstructions = None


def _load_config() -> dict:
    global _config
    if _config is not None:
        return _config

    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "rb") as f:
                _config = tomllib.load(f)
                return _config
        except Exception as e:
            logger.warning("Failed to load config.toml for horizon model: %s", e)

    _config = {}
    return _config


def _science_floor_deg() -> float:
    cfg = _load_config()
    candidates = [
        cfg.get("location", {}).get("horizon_limit"),
        cfg.get("horizon", {}).get("floor_deg"),
        cfg.get("horizon", {}).get("safety_floor_deg"),
        DEFAULT_SCIENCE_FLOOR_DEG,
    ]
    values = []
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            values.append(float(candidate))
        except Exception:
            continue
    return max(values) if values else DEFAULT_SCIENCE_FLOOR_DEG


def _profile_enabled() -> bool:
    cfg = _load_config()
    value = cfg.get("horizon", {}).get("profile_enabled")
    if value is None:
        value = cfg.get("location", {}).get("horizon_profile_enabled")
    return bool(True if value is None else value)


def _profile_required() -> bool:
    cfg = _load_config()
    value = cfg.get("horizon", {}).get("profile_required")
    return bool(False if value is None else value)


def _profile_path() -> Path:
    cfg = _load_config()
    configured = cfg.get("horizon", {}).get("profile_path")
    if not configured:
        return DEFAULT_MASK_PATH

    path = Path(str(configured)).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _load_profile() -> bool:
    global _profile, _use_profile, _profile_source
    if _profile:
        return _use_profile

    mask_path = _profile_path()
    if mask_path.exists() and _profile_enabled():
        try:
            with open(mask_path) as f:
                data = json.load(f)
            _profile = {int(k): float(v) for k, v in data["profile"].items()}
            _use_profile = True
            _profile_source = mask_path
            logger.debug("Horizon profile loaded: %s (%d entries)", mask_path, len(_profile))
            return True
        except Exception as e:
            if _profile_required():
                raise RuntimeError(f"Required horizon profile failed to load: {mask_path}: {e}") from e
            logger.warning("Failed to load horizon profile %s: %s — using configured safety floors", mask_path, e)
    elif _profile_enabled() and _profile_required():
        raise FileNotFoundError(f"Required horizon profile does not exist: {mask_path}")

    _use_profile = False
    _profile_source = None
    return False


def _load_obstructions() -> list:
    global _obstructions
    if _obstructions is not None:
        return _obstructions

    config = _load_config()
    location_obstructions = config.get("location", {}).get("obstructions")
    if location_obstructions:
        _obstructions = location_obstructions
        return _obstructions

    site_obstructions = config.get("site", {}).get("obstructions")
    if site_obstructions:
        _obstructions = site_obstructions
        return _obstructions

    horizon_obstructions = config.get("horizon", {}).get("obstructions")
    if horizon_obstructions:
        _obstructions = horizon_obstructions
        return _obstructions

    _obstructions = []
    return _obstructions


def _az_in_sector(az: float, start: float, end: float) -> bool:
    az = az % 360.0
    start = start % 360.0
    end = end % 360.0
    if start <= end:
        return start <= az <= end
    return az >= start or az <= end


def _obstruction_altitude(az: float) -> float:
    alt = _science_floor_deg()
    for obs in _load_obstructions():
        try:
            start = float(obs["az_start"])
            end = float(obs["az_end"])
            min_alt = float(obs["min_alt"])
        except Exception:
            continue
        if _az_in_sector(az, start, end):
            alt = max(alt, min_alt)
    return alt


def horizon_altitude(az: float) -> float:
    _load_profile()
    floor = _science_floor_deg()

    if _use_profile:
        az = az % 360.0
        az_int = int(az) % 360
        az_next = (az_int + 1) % 360
        h0 = _profile.get(az_int, floor)
        h1 = _profile.get(az_next, floor)
        frac = az - az_int
        alt = h0 + frac * (h1 - h0)
    else:
        alt = floor

    # Manual boxes and the configured horizon_limit are safety floors. A bad or
    # stale scanned profile must never make a known blocked sector look clear.
    return max(float(alt), _obstruction_altitude(az), floor)


def required_altitude(az: float, clearance_margin_deg: float = 0.0) -> float:
    return horizon_altitude(az) + max(0.0, float(clearance_margin_deg))


def clearance_margin(az: float, alt: float, clearance_margin_deg: float = 0.0) -> float:
    return float(alt) - required_altitude(az, clearance_margin_deg=clearance_margin_deg)


def is_obstructed(az: float, alt: float) -> bool:
    return alt < horizon_altitude(az)


def horizon_summary() -> dict:
    _load_profile()
    obstructions = _load_obstructions()
    values = list(_profile.values()) if _use_profile else []
    return {
        "uses_profile": bool(_use_profile),
        "profile_path": str(_profile_source) if _use_profile else str(_profile_path()),
        "profile_required": _profile_required(),
        "profile_points": len(_profile) if _use_profile else 0,
        "profile_min_alt": round(min(values), 2) if values else None,
        "profile_max_alt": round(max(values), 2) if values else None,
        "science_floor_deg": round(_science_floor_deg(), 2),
        "obstruction_count": len(obstructions),
        "obstructions": [
            {
                "label": str(obs.get("label", f"obstruction_{idx + 1}")),
                "az_start": float(obs.get("az_start", 0.0)),
                "az_end": float(obs.get("az_end", 0.0)),
                "min_alt": float(obs.get("min_alt", 0.0)),
            }
            for idx, obs in enumerate(obstructions)
        ],
    }


def best_windows(step: int = 5) -> list:
    _load_profile()
    threshold = _science_floor_deg() + 5

    windows = []
    in_window = False
    w_start = 0
    w_min = 999.0

    for az in range(0, 361):
        alt = horizon_altitude(az % 360)
        if alt <= threshold:
            if not in_window:
                w_start = az
                w_min = alt
                in_window = True
            else:
                w_min = min(w_min, alt)
        else:
            if in_window:
                windows.append((w_start, az - 1, round(w_min, 1)))
                in_window = False
                w_min = 999.0

    if in_window:
        windows.append((w_start, 360, round(w_min, 1)))

    if len(windows) >= 2 and windows[0][0] == 0 and windows[-1][1] == 360:
        merged_start = windows[-1][0]
        merged_end = windows[0][1]
        merged_min = round(min(windows[-1][2], windows[0][2]), 1)
        windows = [(merged_start, merged_end, merged_min)] + windows[1:-1]

    return windows


if __name__ == "__main__":
    _load_profile()
    mode = "PROFILE + SAFETY BOXES" if _use_profile else "BOX MODEL FALLBACK"
    print(f"Horizon engine v2.1.1 — {mode}")
    summary = horizon_summary()
    print(f"Mask: {summary['profile_path']}")
    print(f"Profile points: {summary['profile_points']}")
    if summary["profile_min_alt"] is not None:
        print(f"Profile range: {summary['profile_min_alt']:.1f}° .. {summary['profile_max_alt']:.1f}°")
    print(f"Science floor: {_science_floor_deg():.1f}°")
    print(f"Manual obstructions: {len(_load_obstructions())}")
    for obs in summary["obstructions"]:
        print(
            f"  - {obs['label']}: az {obs['az_start']:.1f}°..{obs['az_end']:.1f}° "
            f"min_alt {obs['min_alt']:.1f}°"
        )
    print()
    print("Az    MinAlt  ReqAlt(+5)  Clear@25?")
    for az in range(0, 360, 10):
        h = horizon_altitude(az)
        r = required_altitude(az, clearance_margin_deg=5)
        status = "YES" if clearance_margin(az, 25.0, clearance_margin_deg=5) >= 0 else "NO"
        print(f"{az:3d}°  {h:6.1f}°   {r:6.1f}°      {status}")
