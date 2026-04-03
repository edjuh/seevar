#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/horizon.py
Version: 2.1.0
Objective: Veto and score targets based on local obstructions using Az/Alt mapping.
"""

import json
import tomllib
import logging
from pathlib import Path

logger = logging.getLogger("seevar.horizon")

PROJECT_ROOT  = Path(__file__).resolve().parents[2]
CONFIG_PATH   = PROJECT_ROOT / "config.toml"
MASK_PATH     = PROJECT_ROOT / "data" / "horizon_mask.json"

SCIENCE_FLOOR_DEG = 15.0

DEFAULT_OBSTRUCTIONS = [
    {"az_start": 150, "az_end": 210, "min_alt": 45},
    {"az_start": 300, "az_end": 350, "min_alt": 55},
]

_profile = {}
_use_profile = False


def _load_profile() -> bool:
    global _profile, _use_profile
    if _profile:
        return _use_profile

    if MASK_PATH.exists():
        try:
            with open(MASK_PATH) as f:
                data = json.load(f)
            _profile = {int(k): float(v) for k, v in data["profile"].items()}
            _use_profile = True
            logger.debug("Horizon profile loaded: %s (%d entries)", MASK_PATH, len(_profile))
            return True
        except Exception as e:
            logger.warning("Failed to load horizon_mask.json: %s — using box fallback", e)

    _use_profile = False
    return False


def _load_obstructions() -> list:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "rb") as f:
                config = tomllib.load(f)
            return config.get("site", {}).get("obstructions", DEFAULT_OBSTRUCTIONS)
        except Exception:
            pass
    return DEFAULT_OBSTRUCTIONS


def horizon_altitude(az: float) -> float:
    _load_profile()

    if _use_profile:
        az = az % 360.0
        az_int = int(az) % 360
        az_next = (az_int + 1) % 360
        h0 = _profile.get(az_int, SCIENCE_FLOOR_DEG)
        h1 = _profile.get(az_next, SCIENCE_FLOOR_DEG)
        frac = az - az_int
        alt = h0 + frac * (h1 - h0)
    else:
        obstructions = _load_obstructions()
        alt = SCIENCE_FLOOR_DEG
        for obs in obstructions:
            if obs["az_start"] <= (az % 360.0) <= obs["az_end"]:
                alt = max(alt, obs["min_alt"])

    return max(float(alt), SCIENCE_FLOOR_DEG)


def required_altitude(az: float, clearance_margin_deg: float = 0.0) -> float:
    return horizon_altitude(az) + max(0.0, float(clearance_margin_deg))


def clearance_margin(az: float, alt: float, clearance_margin_deg: float = 0.0) -> float:
    return float(alt) - required_altitude(az, clearance_margin_deg=clearance_margin_deg)


def is_obstructed(az: float, alt: float) -> bool:
    return alt < horizon_altitude(az)


def best_windows(step: int = 5) -> list:
    _load_profile()
    threshold = SCIENCE_FLOOR_DEG + 5

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

    return windows


if __name__ == "__main__":
    _load_profile()
    mode = "PROFILE" if _use_profile else "BOX MODEL FALLBACK"
    print(f"Horizon engine v2.1.0 — {mode}")
    print(f"Mask: {MASK_PATH}")
    print()
    print("Az    MinAlt  ReqAlt(+5)  Clear@25?")
    for az in range(0, 360, 10):
        h = horizon_altitude(az)
        r = required_altitude(az, clearance_margin_deg=5)
        status = "YES" if clearance_margin(az, 25.0, clearance_margin_deg=5) >= 0 else "NO"
        print(f"{az:3d}°  {h:6.1f}°   {r:6.1f}°      {status}")
