#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/horizon_audit.py
Version: 1.0.1
Objective: Audit tonights_plan.json against the real camera-scanned horizon
           mask. Shows how many targets are observable tonight and when.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body
from astropy.time import Time

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import core.preflight.horizon as horizon
from core.utils.env_loader import DATA_DIR, load_config

PLAN_FILE = DATA_DIR / "tonights_plan.json"


def load_plan():
    if not PLAN_FILE.exists():
        print(f"  No plan file: {PLAN_FILE}")
        return []
    data = json.loads(PLAN_FILE.read_text())
    return data if isinstance(data, list) else data.get("targets", [])


def get_dark_window(location):
    """Find tonight's astronomical dark window."""
    utc_now = datetime.now(timezone.utc)
    start = datetime(utc_now.year, utc_now.month, utc_now.day, 12, 0, tzinfo=timezone.utc)
    if utc_now.hour < 12:
        start -= timedelta(days=1)

    dusk = dawn = None
    is_night = False
    for m in range(0, 24 * 60, 5):
        t_dt = start + timedelta(minutes=m)
        t = Time(t_dt)
        frame = AltAz(obstime=t, location=location)
        sun_alt = float(get_body("sun", t).transform_to(frame).alt.deg)
        if sun_alt <= -18.0 and not is_night:
            is_night = True
            dusk = t_dt
            break

    if dusk is None:
        return None, None

    is_night = True
    for m in range(int((dusk - start).total_seconds() / 60), 24 * 60, 5):
        t_dt = start + timedelta(minutes=m)
        t = Time(t_dt)
        frame = AltAz(obstime=t, location=location)
        sun_alt = float(get_body("sun", t).transform_to(frame).alt.deg)
        if sun_alt > -18.0 and is_night:
            dawn = t_dt
            break

    return dusk, dawn


def audit_targets(targets, location, dusk, dawn):
    """For each target, find peak altitude and best observing time tonight."""
    results = []

    for t in targets:
        name = t.get("name", "?")
        ra_val = t.get("ra")
        dec_val = t.get("dec")

        if ra_val is None or dec_val is None:
            results.append({"name": name, "status": "NO_COORDS"})
            continue

        try:
            ra_deg = float(ra_val)
            dec_deg = float(dec_val)
        except (ValueError, TypeError):
            try:
                coord = SkyCoord(ra=ra_val, dec=dec_val, unit=(u.hourangle, u.deg))
                ra_deg = float(coord.ra.deg)
                dec_deg = float(coord.dec.deg)
            except Exception:
                results.append({"name": name, "status": "BAD_COORDS"})
                continue

        coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg)

        best_alt = -90.0
        best_az = 0.0
        best_time = None
        clear_minutes = 0

        check_time = dusk
        while check_time < dawn:
            t_astro = Time(check_time)
            frame = AltAz(obstime=t_astro, location=location)
            altaz = coord.transform_to(frame)
            alt = float(altaz.alt.deg)
            az = float(altaz.az.deg)

            if alt > best_alt:
                best_alt = alt
                best_az = az
                best_time = check_time

            if alt > 0 and not horizon.is_obstructed(az, alt):
                clear_minutes += 15

            check_time += timedelta(minutes=15)

        hz_at_peak = horizon.horizon_altitude(best_az)

        if best_alt < 15:
            status = "BELOW_FLOOR"
        elif best_alt < hz_at_peak:
            status = "BLOCKED"
        elif clear_minutes == 0:
            status = "ALWAYS_BLOCKED"
        elif clear_minutes < 30:
            status = "MARGINAL"
        else:
            status = "CLEAR"

        results.append({
            "name": name,
            "status": status,
            "peak_alt": round(best_alt, 1),
            "peak_az": round(best_az, 1),
            "horizon_at_peak": round(hz_at_peak, 1),
            "margin": round(best_alt - hz_at_peak, 1),
            "clear_min": clear_minutes,
            "best_time": best_time.strftime("%H:%M") if best_time else "--",
            "type": t.get("type", ""),
        })

    return results


def main():
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  SeeVar Horizon Audit — Real Camera-Scanned Profile    ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    horizon._load_profile()
    mode = "PROFILE" if horizon._use_profile else "BOX MODEL FALLBACK"
    print(f"  Horizon source: {mode}")

    cfg = load_config()
    loc = cfg.get("location", {})
    lat = float(loc.get("lat", 52.38))
    lon = float(loc.get("lon", 4.60))
    elev = float(loc.get("elevation", 5.0))
    location = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=elev * u.m)
    print(f"  Observer: {lat:.2f}°N {lon:.2f}°E, {elev:.0f}m")

    targets = load_plan()
    print(f"  Targets in plan: {len(targets)}")

    if not targets:
        print("  Nothing to audit.")
        return

    dusk, dawn = get_dark_window(location)
    if not dusk or not dawn:
        print("  No astronomical dark window found.")
        return

    dusk_local = dusk.astimezone().strftime("%H:%M")
    dawn_local = dawn.astimezone().strftime("%H:%M")
    hours = (dawn - dusk).total_seconds() / 3600
    print(f"  Dark window: {dusk_local} – {dawn_local} ({hours:.1f}h)")
    print()

    results = audit_targets(targets, location, dusk, dawn)

    clear = [r for r in results if r["status"] == "CLEAR"]
    marginal = [r for r in results if r["status"] == "MARGINAL"]
    blocked = [r for r in results if r["status"] in ("BLOCKED", "ALWAYS_BLOCKED")]
    below = [r for r in results if r["status"] == "BELOW_FLOOR"]
    bad = [r for r in results if r["status"] in ("NO_COORDS", "BAD_COORDS")]

    print("═══════════════════════════════════════════════════════════")
    print(f"  CLEAR:      {len(clear):3d}  (observable tonight)")
    print(f"  MARGINAL:   {len(marginal):3d}  (<30 min clear window)")
    print(f"  BLOCKED:    {len(blocked):3d}  (behind buildings/trees)")
    print(f"  BELOW 15°:  {len(below):3d}  (never rises high enough)")
    print(f"  BAD COORDS: {len(bad):3d}")
    print("═══════════════════════════════════════════════════════════")
    print()

    clear_sorted = sorted(clear, key=lambda r: r["clear_min"], reverse=True)
    print(f"  TOP OBSERVABLE TARGETS ({len(clear_sorted)} total)")
    print(f"  {'Name':<20} {'Type':<8} {'Peak':>5} {'Hz':>5} {'Margin':>6} {'Clear':>5} {'Best':>5}")
    print(f"  {'-'*20} {'-'*8} {'-'*5} {'-'*5} {'-'*6} {'-'*5} {'-'*5}")
    for r in clear_sorted[:30]:
        print(
            f"  {r['name']:<20} {r['type']:<8} {r['peak_alt']:>5.1f} "
            f"{r['horizon_at_peak']:>5.1f} {r['margin']:>+5.1f}° "
            f"{r['clear_min']:>4d}m {r['best_time']:>5}"
        )
    if len(clear_sorted) > 30:
        print(f"  ... and {len(clear_sorted) - 30} more")

    if blocked:
        print()
        print(f"  BLOCKED BY HORIZON ({len(blocked)} targets)")
        print(f"  {'Name':<20} {'Type':<8} {'Peak':>5} {'Hz':>5} {'Az':>5} {'Dir':<4}")
        print(f"  {'-'*20} {'-'*8} {'-'*5} {'-'*5} {'-'*5} {'-'*4}")
        compass = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                   "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        for r in sorted(blocked, key=lambda x: x.get("peak_az", 0))[:20]:
            az = r.get("peak_az", 0)
            d = compass[int(round(az / 22.5)) % 16]
            print(
                f"  {r['name']:<20} {r['type']:<8} {r.get('peak_alt', 0):>5.1f} "
                f"{r.get('horizon_at_peak', 0):>5.1f} {az:>5.1f} {d:<4}"
            )
        if len(blocked) > 20:
            print(f"  ... and {len(blocked) - 20} more")

    print()
    if clear:
        total_clear_min = sum(r["clear_min"] for r in clear)
        avg_margin = sum(r["margin"] for r in clear) / len(clear)
        print(f"  Science potential: {len(clear)} targets × avg {avg_margin:.0f}° margin above horizon")
        print(f"  Total clear observing: {total_clear_min // 60}h {total_clear_min % 60}m across all targets")
        types = {}
        for r in clear:
            tp = r["type"] or "?"
            types[tp] = types.get(tp, 0) + 1
        type_str = ", ".join(f"{v} {k}" for k, v in sorted(types.items(), key=lambda x: -x[1]))
        print(f"  Types: {type_str}")
    else:
        print("  No observable targets tonight from this location.")


if __name__ == "__main__":
    main()
