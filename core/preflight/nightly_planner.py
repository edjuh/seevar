#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/nightly_planner.py
Version: 2.7.6
Objective: Builds the canonical nightly plan in data/tonights_plan.json using astronomical dark, local horizon clearance, and Alt/Az-aware efficiency scoring.
"""

import json
import math
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import numpy as np
from astropy.coordinates import SkyCoord, AltAz, EarthLocation, get_sun
from astropy.time import Time
import astropy.units as u

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))

from core.utils.env_loader import load_config

try:
    from core.preflight.horizon import required_altitude, clearance_margin
except ImportError:
    from core.preflight.horizon import horizon_altitude

    def required_altitude(az: float, clearance_margin_deg: float = 0.0) -> float:
        return horizon_altitude(az) + max(0.0, float(clearance_margin_deg))

    def clearance_margin(az: float, alt: float, clearance_margin_deg: float = 0.0) -> float:
        return float(alt) - required_altitude(az, clearance_margin_deg=clearance_margin_deg)

DATA_DIR = PROJECT_ROOT / "data"
CATALOG_DIR = PROJECT_ROOT / "catalogs"
FEDERATION_CATALOG = CATALOG_DIR / "federation_catalog.json"
TONIGHTS_PLAN = DATA_DIR / "tonights_plan.json"

LOOKAHEAD_HOURS = 36
SAMPLE_MINUTES = 10
CLEARANCE_MARGIN_DEG = 5.0
MIN_WINDOW_MINUTES = 20
DEFAULT_START_AZ = 220.0
DEFAULT_BLOCK_MINUTES = 30
ZENITH_SOFT_LIMIT_DEG = 75.0


def az_distance(a, b):
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def build_time_grid(now_utc):
    steps = int((LOOKAHEAD_HOURS * 60) / SAMPLE_MINUTES) + 1
    return [now_utc + timedelta(minutes=i * SAMPLE_MINUTES) for i in range(steps)]


def contiguous_windows(mask):
    windows = []
    start = None
    for i, ok in enumerate(mask):
        if ok and start is None:
            start = i
        elif not ok and start is not None:
            windows.append((start, i - 1))
            start = None
    if start is not None:
        windows.append((start, len(mask) - 1))
    return windows


def astronomical_dark_mask(times, location, sun_limit_deg):
    t = Time(times)
    frame = AltAz(obstime=t, location=location)
    sun_alt = get_sun(t).transform_to(frame).alt.deg
    return np.array(sun_alt <= sun_limit_deg, dtype=bool)


def sky_region_bonus(best_az_deg):
    az = best_az_deg % 360.0
    if 180 <= az <= 270:
        return 35.0
    if 135 <= az < 180:
        return 20.0
    if 270 < az <= 315:
        return 10.0
    if 45 <= az < 135:
        return 0.0
    return -15.0


def zenith_penalty(max_alt_deg):
    if max_alt_deg <= ZENITH_SOFT_LIMIT_DEG:
        return 0.0
    return (max_alt_deg - ZENITH_SOFT_LIMIT_DEG) * 6.0


def circumpolar_penalty(window_minutes):
    if window_minutes <= 180:
        return 0.0
    return min(60.0, (window_minutes - 180) * 0.20)


def score_window(start_idx, end_idx, times, alt_arr, az_arr, req_arr, priority_weight=0.0):
    idx = slice(start_idx, end_idx + 1)
    alts = alt_arr[idx]
    azs = az_arr[idx]
    clearances = alts - req_arr[idx]

    duration_min = (end_idx - start_idx + 1) * SAMPLE_MINUTES
    min_clear = float(np.min(clearances))
    mean_clear = float(np.mean(clearances))
    max_alt = float(np.max(alts))
    best_i = int(np.argmax(alts)) + start_idx
    best_az = float(az_arr[best_i])

    start_dt = times[start_idx]
    end_dt = times[end_idx]
    minutes_until_end = max(0.0, (end_dt - times[0]).total_seconds() / 60.0)
    urgency = max(0.0, ((times[-1] - times[0]).total_seconds() / 60.0 - minutes_until_end) / 60.0)

    score = (
        0.20 * min(duration_min, 180.0) +
        8.0  * min_clear +
        3.0  * mean_clear +
        1.2  * max_alt +
        10.0 * priority_weight +
        7.0  * urgency +
        sky_region_bonus(best_az) -
        zenith_penalty(max_alt) -
        circumpolar_penalty(duration_min)
    )

    return {
        "window_start_dt": start_dt,
        "window_end_dt": end_dt,
        "window_minutes": int(duration_min),
        "min_clearance_deg": round(min_clear, 2),
        "mean_clearance_deg": round(mean_clear, 2),
        "max_alt_deg": round(max_alt, 2),
        "best_az_deg": round(best_az, 2),
        "urgency_score": round(urgency, 2),
        "efficiency_score": round(score, 2),
    }


def analyze_target(target, times, altaz_frame, dark_mask):
    coord = SkyCoord(
        ra=float(target.get("ra", 0.0)) * u.deg,
        dec=float(target.get("dec", 0.0)) * u.deg,
        frame="icrs",
    )
    altaz = coord.transform_to(altaz_frame)

    alt_arr = np.array(altaz.alt.deg, dtype=float)
    az_arr = np.array(altaz.az.deg, dtype=float)
    req_arr = np.array(
        [required_altitude(float(az), clearance_margin_deg=CLEARANCE_MARGIN_DEG) for az in az_arr],
        dtype=float,
    )

    usable = dark_mask & (alt_arr >= req_arr)
    windows = contiguous_windows(usable.tolist())
    min_samples = max(1, math.ceil(MIN_WINDOW_MINUTES / SAMPLE_MINUTES))
    valid = [(s, e) for s, e in windows if (e - s + 1) >= min_samples]
    if not valid:
        return None

    priority_weight = float(target.get("priority", 0.0))
    scored = [score_window(s, e, times, alt_arr, az_arr, req_arr, priority_weight) for s, e in valid]
    best = max(scored, key=lambda w: (w["efficiency_score"], w["window_minutes"], w["max_alt_deg"]))

    current_alt = float(alt_arr[0])
    current_az = float(az_arr[0])
    current_req = float(required_altitude(current_az, clearance_margin_deg=CLEARANCE_MARGIN_DEG))
    current_margin = float(clearance_margin(current_az, current_alt, clearance_margin_deg=CLEARANCE_MARGIN_DEG))

    out = dict(target)
    out["current_alt"] = round(current_alt, 2)
    out["current_az"] = round(current_az, 2)
    out["current_required_alt"] = round(current_req, 2)
    out["current_clearance_margin_deg"] = round(current_margin, 2)
    out["currently_clear"] = bool(current_margin >= 0.0)
    out["best_start_utc"] = best["window_start_dt"].isoformat()
    out["best_end_utc"] = best["window_end_dt"].isoformat()
    out["window_minutes"] = best["window_minutes"]
    out["min_clearance_deg"] = best["min_clearance_deg"]
    out["mean_clearance_deg"] = best["mean_clearance_deg"]
    out["max_alt_deg"] = best["max_alt_deg"]
    out["best_az_deg"] = best["best_az_deg"]
    out["urgency_score"] = best["urgency_score"]
    out["efficiency_score"] = best["efficiency_score"]
    out["_best_start_dt"] = best["window_start_dt"]
    out["_best_end_dt"] = best["window_end_dt"]
    return out


def greedy_order(candidates, planning_start_utc, start_az=DEFAULT_START_AZ):
    remaining = list(candidates)
    ordered = []
    current_az = float(start_az)
    virtual_now = planning_start_utc

    while remaining:
        viable = [t for t in remaining if t["_best_end_dt"] > virtual_now]
        if not viable:
            break

        best = None
        best_score = None
        for t in viable:
            slew_deg = az_distance(current_az, float(t["best_az_deg"]))
            wait_min = max(0.0, (t["_best_start_dt"] - virtual_now).total_seconds() / 60.0)

            adjusted = float(t["efficiency_score"]) - 0.35 * slew_deg - 0.08 * wait_min
            if t["_best_start_dt"] <= virtual_now <= t["_best_end_dt"]:
                adjusted += 12.0

            if best is None or adjusted > best_score:
                best = t
                best_score = adjusted
                best["_estimated_slew_cost_deg"] = round(slew_deg, 2)

        remaining.remove(best)
        ordered.append(best)

        block_min = min(DEFAULT_BLOCK_MINUTES, int(best["window_minutes"]))
        virtual_now = max(virtual_now, best["_best_start_dt"]) + timedelta(minutes=block_min)
        current_az = float(best["best_az_deg"])

    for idx, t in enumerate(ordered, start=1):
        t["recommended_order"] = idx
        t["estimated_slew_cost_deg"] = t.pop("_estimated_slew_cost_deg", 0.0)
        t.pop("_best_start_dt", None)
        t.pop("_best_end_dt", None)

    return ordered


def run_funnel():
    print("--- INITIATING NIGHTLY TRIAGE ---")

    if not FEDERATION_CATALOG.exists():
        print(f"Error: {FEDERATION_CATALOG.name} missing. Run Librarian first.")
        return

    cfg = load_config()
    location_cfg = cfg.get("location", {})
    planner_cfg = cfg.get("planner", {})

    lat = float(location_cfg.get("lat", 0.0))
    lon = float(location_cfg.get("lon", 0.0))
    elev = float(location_cfg.get("elevation", 0.0))
    sun_limit = float(planner_cfg.get("sun_altitude_limit", -18.0))

    with open(FEDERATION_CATALOG, "r") as f:
        data = json.load(f)
        targets = data.get("data", data.get("targets", [])) if isinstance(data, dict) else data

    now_utc = datetime.now(timezone.utc)
    times = build_time_grid(now_utc)
    location = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=elev * u.m)

    dark_mask = astronomical_dark_mask(times, location, sun_limit)
    dark_windows = contiguous_windows(dark_mask.tolist())
    if not dark_windows:
        print("No astronomical dark found in the planning horizon.")
        return

    planning_start_idx, planning_end_idx = dark_windows[0]
    planning_start_utc = times[planning_start_idx]
    planning_end_utc = times[planning_end_idx]

    trimmed_times = times[planning_start_idx:planning_end_idx + 1]
    trimmed_dark_mask = dark_mask[planning_start_idx:planning_end_idx + 1]
    altaz_frame = AltAz(obstime=Time(trimmed_times), location=location)

    analyzed = []
    for t in targets:
        analyzed_target = analyze_target(t, trimmed_times, altaz_frame, trimmed_dark_mask)
        if analyzed_target is not None:
            analyzed.append(analyzed_target)

    ordered = greedy_order(analyzed, planning_start_utc, start_az=DEFAULT_START_AZ)

    print(f"[+] Total catalog targets evaluated: {len(targets)}")
    print(f"[=] Tonight-plan candidates with usable dark windows: {len(ordered)}")

    plan_out = {
        "#objective": "Canonical nightly plan filtered by astronomical dark, local horizon, and Alt/Az-aware efficiency scoring.",
        "metadata": {
            "generated": datetime.now(timezone.utc).isoformat(),
            "schema_version": "2026.2",
            "planner_version": "2.7.6",
            "planning_mode": "astronomical_dark",
            "planning_start_utc": planning_start_utc.isoformat(),
            "planning_end_utc": planning_end_utc.isoformat(),
            "sample_minutes": SAMPLE_MINUTES,
            "clearance_margin_deg": CLEARANCE_MARGIN_DEG,
            "minimum_window_minutes": MIN_WINDOW_MINUTES,
            "sun_altitude_threshold_deg": sun_limit,
            "catalog_target_count": len(targets),
            "visible_target_count": len(ordered),
            "planned_target_count": len(ordered),
        },
        "targets": ordered,
    }

    with open(TONIGHTS_PLAN, "w") as f:
        json.dump(plan_out, f, indent=4)

    print(f"Tonight plan secured: {TONIGHTS_PLAN.name}")

    if ordered:
        print("\nTop 10 tonight-plan targets:")
        for t in ordered[:10]:
            name = t.get("name", t.get("target_name", "unnamed"))
            print(
                f"  #{t['recommended_order']:02d} {name} | "
                f"az={t['best_az_deg']:.1f} | "
                f"window={t['window_minutes']}m | "
                f"max_alt={t['max_alt_deg']:.1f}° | "
                f"score={t['efficiency_score']:.1f}"
            )


if __name__ == "__main__":
    run_funnel()
