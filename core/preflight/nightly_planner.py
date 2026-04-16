#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/nightly_planner.py
Version: 2.7.7
Objective: Builds the canonical nightly plan in data/tonights_plan.json using astronomical dark, local horizon clearance, and Alt/Az-aware efficiency scoring based on required observing blocks.
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

from core.utils.env_loader import effective_fleet_mode, live_available_scopes, load_config
from core.ledger_manager import calculate_cadence, load_ledger
from core.flight.exposure_planner import plan_exposure, DEFAULT_BORTLE

try:
    from core.preflight.horizon import required_altitude, clearance_margin, horizon_altitude
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
FLEET_PLAN_DIR = DATA_DIR / "fleet_plans"

LOOKAHEAD_HOURS = 36
SAMPLE_MINUTES = 10
CLEARANCE_MARGIN_DEG = 5.0
DEFAULT_START_AZ = 220.0
DEFAULT_BLOCK_OVERHEAD_MIN = 5
ZENITH_SOFT_LIMIT_DEG = 75.0


def _parse_utc_dt(value):
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _ledger_entry_for_target(entries: dict, target_name: str) -> dict:
    if not isinstance(entries, dict):
        return {}

    if target_name in entries and isinstance(entries[target_name], dict):
        return entries[target_name]

    safe_name = str(target_name).replace(" ", "_").upper()
    if safe_name in entries and isinstance(entries[safe_name], dict):
        return entries[safe_name]

    return {}


def _target_due_from_ledger(target: dict, ledger_entries: dict, now_utc: datetime, planning_start_utc: datetime) -> tuple[bool, str]:
    name = str(target.get("name", "")).strip()
    if not name:
        return True, "missing_name"

    entry = _ledger_entry_for_target(ledger_entries, name)
    if not entry:
        return True, "new_target"

    last_success = _parse_utc_dt(entry.get("last_success"))
    if last_success is not None:
        cadence_days = float(calculate_cadence(target))
        if now_utc - last_success < timedelta(days=cadence_days):
            return False, "cadence_not_due"

    last_capture = _parse_utc_dt(entry.get("last_capture_utc"))
    status = str(entry.get("status", "")).strip().upper()
    if last_capture is not None and last_capture >= planning_start_utc and status in {"CAPTURED_RAW", "OBSERVED"}:
        return False, "already_captured_this_night"

    return True, "due"


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


def _science_exposure_hint(target, sky_bortle=DEFAULT_BORTLE):
    bright_mag = target.get("mag_max")
    faint_mag = target.get("min_mag")

    try:
        bright_mag = float(bright_mag) if bright_mag is not None else None
    except Exception:
        bright_mag = None
    try:
        faint_mag = float(faint_mag) if faint_mag is not None else None
    except Exception:
        faint_mag = None

    target_mag = faint_mag if faint_mag is not None else bright_mag
    if target_mag is None:
        target_mag = 12.5
    if bright_mag is None:
        bright_mag = target_mag

    try:
        return plan_exposure(target_mag=target_mag, mag_bright=bright_mag, sky_bortle=int(sky_bortle))
    except Exception:
        return None


def estimate_required_block_minutes(target, sky_bortle=DEFAULT_BORTLE):
    hint = _science_exposure_hint(target, sky_bortle=sky_bortle)
    if hint is not None:
        integration_min = math.ceil(float(hint.total_sec) / 60.0)
        settle_min = 1 if float(hint.exp_sec) <= 5.0 else 2
        return max(6, min(25, integration_min + DEFAULT_BLOCK_OVERHEAD_MIN + settle_min))

    duration_sec = int(target.get("duration", 600))
    imaging_min = math.ceil(duration_sec / 60.0)
    # exposure block + slew/settle/acquire overhead
    return max(8, min(20, imaging_min + DEFAULT_BLOCK_OVERHEAD_MIN))


def sector_name(az_deg):
    az = az_deg % 360.0
    if az >= 315 or az < 45:
        return "N"
    if az < 135:
        return "E"
    if az < 225:
        return "S"
    return "W"


def sky_region_bonus(best_az_deg):
    az = best_az_deg % 360.0
    if 180 <= az <= 270:
        return 40.0   # south/west first
    if 135 <= az < 180:
        return 25.0   # south-east
    if 270 < az <= 315:
        return 10.0   # west/north-west
    if 45 <= az < 135:
        return 5.0    # east can wait
    return -30.0      # north/circumpolar should not dominate


def zenith_penalty(max_alt_deg):
    if max_alt_deg <= ZENITH_SOFT_LIMIT_DEG:
        return 0.0
    return (max_alt_deg - ZENITH_SOFT_LIMIT_DEG) * 8.0


def score_window(start_idx, end_idx, times, alt_arr, az_arr, req_arr, block_minutes, priority_weight=0.0):
    idx = slice(start_idx, end_idx + 1)
    alts = alt_arr[idx]
    azs = az_arr[idx]
    clearances = alts - req_arr[idx]

    duration_min = (end_idx - start_idx + 1) * SAMPLE_MINUTES
    effective_minutes = min(duration_min, block_minutes)
    coverage_ratio = min(2.0, duration_min / max(block_minutes, 1))

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
        2.0  * effective_minutes +
        25.0 * coverage_ratio +
        8.0  * min_clear +
        3.0  * mean_clear +
        1.0  * max_alt +
        10.0 * priority_weight +
        7.0  * urgency +
        sky_region_bonus(best_az) -
        zenith_penalty(max_alt)
    )

    return {
        "window_start_dt": start_dt,
        "window_end_dt": end_dt,
        "window_minutes": int(duration_min),
        "required_block_minutes": int(block_minutes),
        "effective_minutes": int(effective_minutes),
        "coverage_ratio": round(coverage_ratio, 2),
        "min_clearance_deg": round(min_clear, 2),
        "mean_clearance_deg": round(mean_clear, 2),
        "max_alt_deg": round(max_alt, 2),
        "best_az_deg": round(best_az, 2),
        "sector": sector_name(best_az),
        "urgency_score": round(urgency, 2),
        "efficiency_score": round(score, 2),
    }


def analyze_target(target, times, altaz_frame, dark_mask, sky_bortle=DEFAULT_BORTLE):
    coord = SkyCoord(
        ra=float(target.get("ra", 0.0)) * u.deg,
        dec=float(target.get("dec", 0.0)) * u.deg,
        frame="icrs",
    )
    altaz = coord.transform_to(altaz_frame)

    alt_arr = np.array(altaz.alt.deg, dtype=float)
    az_arr = np.array(altaz.az.deg, dtype=float)
    horizon_arr = np.array([horizon_altitude(float(az)) for az in az_arr], dtype=float)
    req_arr = np.array(
        [required_altitude(float(az), clearance_margin_deg=CLEARANCE_MARGIN_DEG) for az in az_arr],
        dtype=float,
    )

    any_dark = bool(np.any(dark_mask))
    any_above_horizon = bool(np.any(dark_mask & (alt_arr >= horizon_arr)))
    any_above_margin = bool(np.any(dark_mask & (alt_arr >= req_arr)))

    block_minutes = estimate_required_block_minutes(target, sky_bortle=sky_bortle)
    min_samples = max(1, math.ceil(block_minutes / SAMPLE_MINUTES))

    usable = dark_mask & (alt_arr >= req_arr)
    windows = contiguous_windows(usable.tolist())
    valid = [(s, e) for s, e in windows if (e - s + 1) >= min_samples]
    survives_block = bool(valid)

    diagnostics = {
        "dark": any_dark,
        "horizon": any_above_horizon,
        "margin": any_above_margin,
        "block": survives_block,
        "block_minutes": block_minutes,
    }

    if not valid:
        return None, diagnostics

    priority_weight = float(target.get("priority", 0.0))
    scored = [
        score_window(s, e, times, alt_arr, az_arr, req_arr, block_minutes, priority_weight)
        for s, e in valid
    ]
    best = max(scored, key=lambda w: (w["efficiency_score"], w["coverage_ratio"], w["max_alt_deg"]))

    current_alt = float(alt_arr[0])
    current_az = float(az_arr[0])
    current_req = float(required_altitude(current_az, clearance_margin_deg=CLEARANCE_MARGIN_DEG))
    current_margin = float(clearance_margin(current_az, current_alt, clearance_margin_deg=CLEARANCE_MARGIN_DEG))

    out = dict(target)
    exposure_hint = _science_exposure_hint(target, sky_bortle=sky_bortle)

    out["current_alt"] = round(current_alt, 2)
    out["current_az"] = round(current_az, 2)
    out["current_required_alt"] = round(current_req, 2)
    out["current_clearance_margin_deg"] = round(current_margin, 2)
    out["currently_clear"] = bool(current_margin >= 0.0)
    out["best_start_utc"] = best["window_start_dt"].isoformat()
    out["best_end_utc"] = best["window_end_dt"].isoformat()
    out["window_minutes"] = best["window_minutes"]
    out["required_block_minutes"] = best["required_block_minutes"]
    out["effective_minutes"] = best["effective_minutes"]
    out["coverage_ratio"] = best["coverage_ratio"]
    out["min_clearance_deg"] = best["min_clearance_deg"]
    out["mean_clearance_deg"] = best["mean_clearance_deg"]
    out["max_alt_deg"] = best["max_alt_deg"]
    out["best_az_deg"] = best["best_az_deg"]
    out["sector"] = best["sector"]
    out["urgency_score"] = best["urgency_score"]
    out["efficiency_score"] = best["efficiency_score"]
    if exposure_hint is not None:
        out["exp_ms"] = int(exposure_hint.exp_ms)
        out["n_frames"] = int(exposure_hint.n_frames)
        out["integration_sec"] = float(exposure_hint.total_sec)
        out["planner_mag"] = float(exposure_hint.target_mag)
        out["planner_bright_mag"] = float(exposure_hint.mag_bright)
        out["exposure_note"] = exposure_hint.note
    out["_best_start_dt"] = best["window_start_dt"]
    out["_best_end_dt"] = best["window_end_dt"]
    return out, diagnostics


def greedy_order(candidates, planning_start_utc, start_az=DEFAULT_START_AZ):
    remaining = list(candidates)
    ordered = []
    current_az = float(start_az)
    virtual_now = planning_start_utc
    sector_usage = {"N": 0, "E": 0, "S": 0, "W": 0}

    while remaining:
        viable = [t for t in remaining if t["_best_end_dt"] > virtual_now]
        if not viable:
            break

        best = None
        best_score = None
        for t in viable:
            slew_deg = az_distance(current_az, float(t["best_az_deg"]))
            wait_min = max(0.0, (t["_best_start_dt"] - virtual_now).total_seconds() / 60.0)
            sector_penalty = max(0, sector_usage.get(t["sector"], 0) - 2) * 12.0

            adjusted = float(t["efficiency_score"]) - 0.35 * slew_deg - 0.08 * wait_min - sector_penalty
            if t["_best_start_dt"] <= virtual_now <= t["_best_end_dt"]:
                adjusted += 12.0

            if best is None or adjusted > best_score:
                best = t
                best_score = adjusted
                best["_estimated_slew_cost_deg"] = round(slew_deg, 2)

        remaining.remove(best)
        ordered.append(best)
        sector_usage[best["sector"]] = sector_usage.get(best["sector"], 0) + 1

        block_min = int(best["required_block_minutes"])
        virtual_now = max(virtual_now, best["_best_start_dt"]) + timedelta(minutes=block_min)
        current_az = float(best["best_az_deg"])

    for idx, t in enumerate(ordered, start=1):
        t["recommended_order"] = idx
        t["estimated_slew_cost_deg"] = t.pop("_estimated_slew_cost_deg", 0.0)
        t.pop("_best_start_dt", None)
        t.pop("_best_end_dt", None)

    return ordered


def _active_scopes(cfg: dict) -> list[dict]:
    scopes = []
    for idx, scope in enumerate(live_available_scopes(cfg)):
        scopes.append({
            "index": idx,
            "name": scope["scope_name"],
            "ip": scope["ip"],
            "scope_id": scope["scope_id"],
        })
    return scopes


def assign_targets_to_scopes(ordered, scopes, fleet_mode, start_az=DEFAULT_START_AZ):
    if fleet_mode != "split" or len(scopes) < 2:
        return ordered, {}

    scope_state = {
        scope["name"]: {
            "count": 0,
            "block_minutes": 0,
            "current_az": float(start_az),
        }
        for scope in scopes
    }
    scope_index = {scope["name"]: scope for scope in scopes}

    assigned = []
    for target in ordered:
        best_scope = None
        best_cost = None

        for scope in scopes:
            state = scope_state[scope["name"]]
            slew_deg = az_distance(state["current_az"], float(target["best_az_deg"]))
            block_minutes = int(target.get("required_block_minutes", 0))
            cost = (
                state["block_minutes"] + block_minutes,
                round(slew_deg, 2),
                state["count"],
                scope["index"],
            )
            if best_cost is None or cost < best_cost:
                best_scope = scope
                best_cost = cost

        enriched = dict(target)
        name = best_scope["name"]
        state = scope_state[name]
        state["count"] += 1
        state["block_minutes"] += int(target.get("required_block_minutes", 0))
        state["current_az"] = float(target["best_az_deg"])

        enriched["assigned_scope"] = name
        enriched["assigned_scope_ip"] = best_scope["ip"]
        enriched["assigned_scope_id"] = best_scope["scope_id"]
        enriched["assigned_scope_order"] = state["count"]
        assigned.append(enriched)

    summary = {
        name: {
            "target_count": state["count"],
            "block_minutes": state["block_minutes"],
            "ip": scope_index[name]["ip"],
            "scope_id": scope_index[name]["scope_id"],
        }
        for name, state in scope_state.items()
    }
    return assigned, summary


def write_scope_plans(plan_out: dict, scopes: list[dict], fleet_mode: str):
    FLEET_PLAN_DIR.mkdir(parents=True, exist_ok=True)
    for old in FLEET_PLAN_DIR.glob("*.json"):
        old.unlink()

    if fleet_mode != "split" or len(scopes) < 2:
        return

    targets = plan_out.get("targets", [])
    for scope in scopes:
        scoped_targets = [t for t in targets if t.get("assigned_scope") == scope["name"]]
        scoped_plan = {
            "#objective": f"Nightly split plan for {scope['name']}.",
            "metadata": {
                **plan_out.get("metadata", {}),
                "scope_name": scope["name"],
                "scope_ip": scope["ip"],
                "scope_id": scope["scope_id"],
                "scope_target_count": len(scoped_targets),
            },
            "targets": scoped_targets,
        }
        out_path = FLEET_PLAN_DIR / f"tonights_plan.{scope['scope_id']}.json"
        with open(out_path, "w") as f:
            json.dump(scoped_plan, f, indent=4)


def run_funnel():
    print("--- INITIATING NIGHTLY TRIAGE ---")

    if not FEDERATION_CATALOG.exists():
        print(f"Error: {FEDERATION_CATALOG.name} missing. Run Librarian first.")
        return

    cfg = load_config()
    location_cfg = cfg.get("location", {})
    planner_cfg = cfg.get("planner", {})
    fleet_mode = effective_fleet_mode(cfg)
    active_scopes = _active_scopes(cfg)

    lat = float(location_cfg.get("lat", 0.0))
    lon = float(location_cfg.get("lon", 0.0))
    elev = float(location_cfg.get("elevation", 0.0))
    sun_limit = float(planner_cfg.get("sun_altitude_limit", -18.0))
    sky_bortle = int(planner_cfg.get("sky_bortle", location_cfg.get("bortle", DEFAULT_BORTLE)))

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

    gate_counts = {
        "catalog_total": len(targets),
        "cadence_skipped": 0,
        "survive_dark": 0,
        "survive_horizon": 0,
        "survive_margin": 0,
        "survive_block": 0,
    }
    sector_counts = {"N": 0, "E": 0, "S": 0, "W": 0}

    analyzed = []
    for t in targets:
        if t.get("cadence_skip", False):
            gate_counts["cadence_skipped"] += 1
            continue

        analyzed_target, diag = analyze_target(t, trimmed_times, altaz_frame, trimmed_dark_mask, sky_bortle=sky_bortle)

        if diag["dark"]:
            gate_counts["survive_dark"] += 1
        if diag["horizon"]:
            gate_counts["survive_horizon"] += 1
        if diag["margin"]:
            gate_counts["survive_margin"] += 1
        if diag["block"]:
            gate_counts["survive_block"] += 1

        if analyzed_target is not None:
            sector_counts[analyzed_target["sector"]] += 1
            analyzed.append(analyzed_target)

    ordered = greedy_order(analyzed, planning_start_utc, start_az=DEFAULT_START_AZ)
    ledger_entries = load_ledger()
    ledger_skip_reasons = {
        "cadence_not_due": 0,
        "already_captured_this_night": 0,
    }
    due_ordered = []

    for target in ordered:
        due, reason = _target_due_from_ledger(target, ledger_entries, now_utc, planning_start_utc)
        if due:
            due_ordered.append(target)
            continue

        gate_counts["cadence_skipped"] += 1
        if reason in ledger_skip_reasons:
            ledger_skip_reasons[reason] += 1

    ordered = due_ordered
    ordered, scope_plan_summary = assign_targets_to_scopes(
        ordered,
        active_scopes,
        fleet_mode=fleet_mode,
        start_az=DEFAULT_START_AZ,
    )

    print(f"[+] Catalog total                : {gate_counts['catalog_total']}")
    print(f"[-] Deferred by cadence audit   : {gate_counts['cadence_skipped']}")
    print(f"[+] Survive dark                 : {gate_counts['survive_dark']}")
    print(f"[+] Survive local horizon        : {gate_counts['survive_horizon']}")
    print(f"[+] Survive +{CLEARANCE_MARGIN_DEG:.0f}° margin      : {gate_counts['survive_margin']}")
    print(f"[+] Survive required block       : {gate_counts['survive_block']}")
    print(f"[=] Final tonight-plan count    : {len(ordered)}")
    if gate_counts["cadence_skipped"]:
        print(
            "[=] Ledger deferred              : "
            f"{gate_counts['cadence_skipped']} "
            f"(cadence={ledger_skip_reasons['cadence_not_due']} "
            f"night-hold={ledger_skip_reasons['already_captured_this_night']})"
        )
    print(f"[=] Sector survivors            : N={sector_counts['N']} E={sector_counts['E']} S={sector_counts['S']} W={sector_counts['W']}")

    plan_out = {
        "#objective": "Canonical nightly plan filtered by astronomical dark, local horizon, and Alt/Az-aware efficiency scoring based on required observing blocks.",
        "metadata": {
            "generated": datetime.now(timezone.utc).isoformat(),
            "schema_version": "2026.2",
            "planner_version": "2.8.0",
            "planning_mode": "astronomical_dark",
            "fleet_mode": fleet_mode,
            "active_scope_count": len(active_scopes),
            "planning_start_utc": planning_start_utc.isoformat(),
            "planning_end_utc": planning_end_utc.isoformat(),
            "sample_minutes": SAMPLE_MINUTES,
            "clearance_margin_deg": CLEARANCE_MARGIN_DEG,
            "sun_altitude_threshold_deg": sun_limit,
            "sky_bortle": sky_bortle,
            "catalog_target_count": len(targets),
            "visible_target_count": len(ordered),
            "planned_target_count": len(ordered),
            "gate_counts": gate_counts,
            "ledger_skip_reasons": ledger_skip_reasons,
            "sector_counts": sector_counts,
            "scope_plan_summary": scope_plan_summary,
        },
        "targets": ordered,
    }

    with open(TONIGHTS_PLAN, "w") as f:
        json.dump(plan_out, f, indent=4)

    write_scope_plans(plan_out, active_scopes, fleet_mode)

    print(f"Tonight plan secured: {TONIGHTS_PLAN.name}")
    if fleet_mode == "split" and scope_plan_summary:
        print("Split mode assignments:")
        for scope_name, summary in scope_plan_summary.items():
            print(
                f"  {scope_name}: {summary['target_count']} target(s), "
                f"{summary['block_minutes']} planned block-minute(s)"
            )

    if ordered:
        print("\nTop 10 tonight-plan targets:")
        for t in ordered[:10]:
            name = t.get("name", t.get("target_name", "unnamed"))
            print(
                f"  #{t['recommended_order']:02d} {name} | "
                f"sector={t['sector']} | "
                f"block={t['required_block_minutes']}m | "
                f"avail={t['window_minutes']}m | "
                f"az={t['best_az_deg']:.1f} | "
                f"max_alt={t['max_alt_deg']:.1f}° | "
                f"score={t['efficiency_score']:.1f}"
            )


if __name__ == "__main__":
    run_funnel()
