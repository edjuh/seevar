#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/horizon.py
Version: 2.0.0
Objective: Veto targets based on local obstructions using Az/Alt mapping.

Changes from v1.1.0:
    - Per-degree horizon profile from data/horizon_mask.json
      replaces rectangular Az/Alt box model
    - Linear interpolation between mask entries for sub-degree accuracy
    - Falls back to config.toml [site].obstructions boxes if mask missing
    - is_obstructed() signature unchanged — drop-in replacement
    - Added: horizon_altitude(az) — returns minimum clear altitude at az
    - Added: best_windows() — prints clear Az ranges above science floor
"""

import json
import tomllib
import logging
from pathlib import Path

logger = logging.getLogger("seevar.horizon")

PROJECT_ROOT  = Path(__file__).resolve().parents[2]
CONFIG_PATH   = PROJECT_ROOT / "config.toml"
MASK_PATH     = PROJECT_ROOT / "data" / "horizon_mask.json"

# Global science floor — atmospheric extinction hard limit
SCIENCE_FLOOR_DEG = 15.0

# Default box-model fallback (used if horizon_mask.json missing)
DEFAULT_OBSTRUCTIONS = [
    {"az_start": 150, "az_end": 210, "min_alt": 45},  # Roof obstruction
    {"az_start": 300, "az_end": 350, "min_alt": 55},  # Tree in NW
]

# Module-level cache
_profile: dict = {}
_use_profile: bool = False


def _load_profile() -> bool:
    """Load horizon_mask.json into module cache. Returns True if loaded."""
    global _profile, _use_profile
    if _profile:
        return _use_profile

    if MASK_PATH.exists():
        try:
            with open(MASK_PATH) as f:
                data = json.load(f)
            # Keys are stored as strings in JSON — convert to int
            _profile = {int(k): float(v) for k, v in data["profile"].items()}
            _use_profile = True
            logger.debug("Horizon profile loaded: %s (%d entries)", MASK_PATH, len(_profile))
            return True
        except Exception as e:
            logger.warning("Failed to load horizon_mask.json: %s — using box fallback", e)

    _use_profile = False
    return False


def _load_obstructions() -> list:
    """Load box-model obstructions from config.toml or return defaults."""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "rb") as f:
                config = tomllib.load(f)
            return config.get("site", {}).get("obstructions", DEFAULT_OBSTRUCTIONS)
        except Exception:
            pass
    return DEFAULT_OBSTRUCTIONS


def horizon_altitude(az: float) -> float:
    """
    Return minimum clear altitude (degrees) at given azimuth.
    Uses profile if available, else box model.
    Always enforces SCIENCE_FLOOR_DEG as a floor.
    """
    _load_profile()

    if _use_profile:
        az_int = int(az) % 360
        az_next = (az_int + 1) % 360
        h0 = _profile.get(az_int, SCIENCE_FLOOR_DEG)
        h1 = _profile.get(az_next, SCIENCE_FLOOR_DEG)
        # Linear interpolation for fractional degrees
        frac = az - int(az)
        alt = h0 + frac * (h1 - h0)
    else:
        # Box model fallback
        obstructions = _load_obstructions()
        alt = SCIENCE_FLOOR_DEG
        for obs in obstructions:
            if obs["az_start"] <= (az % 360) <= obs["az_end"]:
                alt = max(alt, obs["min_alt"])

    return max(alt, SCIENCE_FLOOR_DEG)


def is_obstructed(az: float, alt: float) -> bool:
    """
    Returns True if az/alt is blocked by local terrain or below science floor.
    Drop-in replacement for v1.1.0 — signature unchanged.
    """
    return alt < horizon_altitude(az)


def best_windows(step: int = 5) -> list:
    """
    Return list of (az_start, az_end, min_alt_in_window) for clear sectors.
    A sector is 'clear' if min_alt <= SCIENCE_FLOOR_DEG + 5 (i.e. barely above floor).
    """
    _load_profile()
    threshold = SCIENCE_FLOOR_DEG + 5  # 20° — comfortably open

    windows = []
    in_window = False
    w_start = 0
    w_min = 999

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
                w_min = 999

    return windows


if __name__ == "__main__":
    import sys

    _load_profile()
    mode = "PROFILE" if _use_profile else "BOX MODEL FALLBACK"
    print(f"🔭 Horizon engine v2.0.0 — {mode}")
    print(f"   Mask: {MASK_PATH}")
    print()

    # Full 360 table at 10° steps
    print("  Az    MinAlt  Clear?")
    for az in range(0, 360, 10):
        alt = horizon_altitude(az)
        status = "✅" if alt <= 20 else ("⚠️ " if alt <= 35 else "🚫")
        print(f"  {az:3d}°   {alt:5.1f}°  {status}")

    print()
    print("  Best science windows (alt ≤ 20°):")
    for w in best_windows():
        print(f"    Az {w[0]:3d}°–{w[1]:3d}°  min_alt={w[2]}°")

    # Quick test
    print()
    print("  Spot checks:")
    tests = [(180, 15), (180, 10), (270, 20), (130, 13), (90, 25)]
    for az, alt in tests:
        obs = is_obstructed(az, alt)
        print(f"    Az={az:3d}° Alt={alt:2d}° -> {'BLOCKED' if obs else 'CLEAR  '}")
