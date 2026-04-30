#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/prealign_pointing.py
Version: 1.0.0
Objective: Build a quick SeeVar software pointing model from 2-3 bright
           plate-solved alignment stars before starting a science sequence.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import astropy.units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord
from astropy.time import Time

from core.flight.pilot import AcquisitionTarget, DiamondSequence
from core.flight.pointing_model import build_pointing_model, normalize_ra_hours, save_pointing_model
from core.preflight.horizon import required_altitude
from core.utils.env_loader import load_config, selected_scope, scope_file_tag


@dataclass(frozen=True)
class AlignStar:
    name: str
    ra_hours: float
    dec_deg: float
    mag: float


BRIGHT_STARS = [
    AlignStar("Arcturus", 14.261021, 19.1825, -0.05),
    AlignStar("Vega", 18.615649, 38.7837, 0.03),
    AlignStar("Deneb", 20.690532, 45.2803, 1.25),
    AlignStar("Altair", 19.846389, 8.8683, 0.76),
    AlignStar("Alphecca", 15.578128, 26.7147, 2.22),
    AlignStar("Eltanin", 17.943438, 51.4889, 2.24),
    AlignStar("Kochab", 14.845109, 74.1555, 2.07),
    AlignStar("Mizar", 13.398750, 54.9254, 2.23),
    AlignStar("Dubhe", 11.062130, 61.7510, 1.79),
    AlignStar("Regulus", 10.139531, 11.9672, 1.35),
    AlignStar("Spica", 13.419883, -11.1614, 0.98),
    AlignStar("Capella", 5.278155, 45.9980, 0.08),
    AlignStar("Aldebaran", 4.598677, 16.5093, 0.85),
]


# Parse the command line for a short, explicit pre-alignment run.
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", type=int, default=3, help="Number of successful alignment solves to collect.")
    parser.add_argument("--exposure-sec", type=float, default=5.0, help="Alignment frame exposure in seconds.")
    parser.add_argument("--min-alt", type=float, default=35.0, help="Minimum geometric altitude for alignment stars.")
    parser.add_argument("--max-alt", type=float, default=82.0, help="Avoid stars above this altitude where mount geometry can be unstable.")
    parser.add_argument("--clearance-margin", type=float, default=8.0, help="Extra degrees above the SeeVar horizon mask.")
    parser.add_argument("--min-az-separation", type=float, default=45.0, help="Prefer stars separated by at least this azimuth.")
    parser.add_argument("--max-stars", type=int, default=8, help="Maximum candidate stars to attempt.")
    parser.add_argument("--max-age-hours", type=float, default=12.0, help="How long the generated pointing model remains valid.")
    parser.add_argument("--allow-partial", action="store_true", help="Write a model even when fewer than --points solves succeeded.")
    parser.add_argument("--solve-radius-deg", type=float, default=20.0, help="Search radius for alignment solves.")
    parser.add_argument("--solve-timeout-sec", type=int, default=90, help="Timeout for each alignment solve.")
    parser.add_argument("--solve-downsample", type=int, default=2, help="Downsample factor for alignment solves.")
    parser.add_argument("--ip", default="", help="Override selected scope IP address.")
    parser.add_argument("--scope-tag", default="", help="Override output model scope tag, e.g. scope01 or scope02.")
    parser.add_argument("--dry-run", action="store_true", help="Only list selected candidates; do not move the telescope.")
    parser.add_argument("--park-after", action="store_true", help="Park the telescope after pre-alignment.")
    parser.add_argument("--output", type=Path, default=None, help="Override pointing model output path.")
    return parser.parse_args()


# Resolve the scope metadata used for naming the runtime pointing model.
def resolve_scope(args: argparse.Namespace) -> dict:
    cfg = load_config()
    ip = str(args.ip or "").strip()
    if ip:
        for idx, scope in enumerate(cfg.get("seestars", [])):
            if str(scope.get("ip", "")).strip() == ip:
                enriched = dict(scope)
                enriched["scope_id"] = f"scope{idx + 1:02d}"
                enriched["scope_name"] = enriched.get("name", enriched["scope_id"])
                return enriched
    return selected_scope(cfg)


# Return the observing site from config.toml.
def site_location() -> EarthLocation:
    cfg = load_config()
    loc = cfg.get("location", {})
    return EarthLocation(
        lat=float(loc.get("lat", 0.0)) * u.deg,
        lon=float(loc.get("lon", 0.0)) * u.deg,
        height=float(loc.get("elevation", 0.0)) * u.m,
    )


# Compute current horizontal coordinates for an alignment star.
def star_altaz(star: AlignStar, location: EarthLocation, obstime: Time) -> tuple[float, float]:
    coord = SkyCoord(ra=star.ra_hours * 15.0 * u.deg, dec=star.dec_deg * u.deg, frame="icrs")
    altaz = coord.transform_to(AltAz(obstime=obstime, location=location))
    return float(altaz.alt.deg), float(altaz.az.deg)


# Return true when two azimuths are far enough apart for useful calibration diversity.
def azimuth_far_enough(az: float, existing: list[dict], min_sep: float) -> bool:
    for item in existing:
        delta = abs((float(az) - float(item["az_deg"]) + 180.0) % 360.0 - 180.0)
        if delta < min_sep:
            return False
    return True


# Pick bright, visible, horizon-clear alignment stars for the current site and time.
def choose_alignment_stars(args: argparse.Namespace) -> list[dict]:
    location = site_location()
    obstime = Time(datetime.now(timezone.utc))
    candidates = []

    for star in BRIGHT_STARS:
        alt_deg, az_deg = star_altaz(star, location, obstime)
        required = required_altitude(az_deg, clearance_margin_deg=args.clearance_margin)
        if alt_deg < max(args.min_alt, required):
            continue
        if alt_deg > args.max_alt:
            continue
        candidates.append(
            {
                "star": star,
                "alt_deg": round(alt_deg, 2),
                "az_deg": round(az_deg, 2),
                "required_alt_deg": round(required, 2),
            }
        )

    candidates.sort(key=lambda item: (-item["alt_deg"], item["star"].mag))
    selected = []
    for item in candidates:
        if len(selected) >= max(args.points, args.max_stars):
            break
        if len(selected) < args.points and not azimuth_far_enough(item["az_deg"], selected, args.min_az_separation):
            continue
        selected.append(item)

    if len(selected) < args.points:
        for item in candidates:
            if item in selected:
                continue
            selected.append(item)
            if len(selected) >= args.points:
                break

    return selected[: args.max_stars]


# Emit progress from the pilot without requiring the full orchestrator.
def notify(step: str, msg: str) -> None:
    print(f"[{step}] {msg}", flush=True)


# Slew, capture, plate-solve, and return one alignment sample.
def solve_alignment_star(sequence: DiamondSequence, item: dict, args: argparse.Namespace) -> dict:
    star: AlignStar = item["star"]
    target = AcquisitionTarget(
        name=f"ALIGN_{star.name}",
        ra_hours=star.ra_hours,
        dec_deg=star.dec_deg,
        exp_ms=int(round(args.exposure_sec * 1000.0)),
        n_frames=1,
    )

    print(f"Aligning {star.name}: alt={item['alt_deg']:.1f} az={item['az_deg']:.1f}", flush=True)
    sequence._telescope.slew_to_coordinates_async(star.ra_hours, star.dec_deg)
    if not sequence._telescope.wait_for_slew():
        return {"ok": False, "name": star.name, "error": "slew_timeout"}

    time.sleep(3.0)
    fits_path = sequence._capture_temp_frame(target, args.exposure_sec, "ALIGN")
    solve = sequence._solve_verify_frame(
        fits_path,
        target,
        radius_deg=args.solve_radius_deg,
        timeout_sec=args.solve_timeout_sec,
        cpulimit_sec=max(5, min(args.solve_timeout_sec, args.solve_timeout_sec - 5)),
        downsample=args.solve_downsample,
    )

    sample = {
        "ok": bool(solve.get("ok")),
        "name": star.name,
        "target_ra_hours": round(star.ra_hours, 8),
        "target_dec_deg": round(star.dec_deg, 8),
        "alt_deg": item["alt_deg"],
        "az_deg": item["az_deg"],
        "fits_path": str(fits_path),
    }

    if not solve.get("ok"):
        sample["error"] = solve.get("error", "unknown_error")
        return sample

    solved_ra_hours = float(solve["solved_ra_deg"]) / 15.0
    solved_dec_deg = float(solve["solved_dec_deg"])
    sample.update(
        {
            "solved_ra_hours": round(solved_ra_hours, 8),
            "solved_dec_deg": round(solved_dec_deg, 8),
            "offset_ra_hours": round(normalize_ra_hours(star.ra_hours - solved_ra_hours), 8),
            "offset_dec_deg": round(star.dec_deg - solved_dec_deg, 8),
            "error_arcmin": round(float(solve.get("error_arcmin", math.nan)), 3),
        }
    )
    return sample


# Run the pre-alignment workflow and write the runtime pointing model.
def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")

    scope = resolve_scope(args)
    scope_tag = args.scope_tag.strip() or scope_file_tag(scope)
    candidates = choose_alignment_stars(args)

    if not candidates:
        print("No suitable alignment stars are currently clear enough.", file=sys.stderr)
        return 2

    print("Alignment candidates:")
    for item in candidates:
        star: AlignStar = item["star"]
        print(f"  {star.name:10} mag={star.mag:4.1f} alt={item['alt_deg']:5.1f} az={item['az_deg']:6.1f}")

    if args.dry_run:
        return 0

    sequence = DiamondSequence(host=args.ip or None)
    telemetry = sequence.init_session(level_ok=True)
    if telemetry.veto_reason():
        print(f"Pre-alignment blocked: {telemetry.veto_reason()}", file=sys.stderr)
        return 3

    samples = []
    for item in candidates:
        if sum(1 for sample in samples if sample.get("ok")) >= args.points:
            break
        sample = solve_alignment_star(sequence, item, args)
        samples.append(sample)
        if sample.get("ok"):
            print(
                f"  OK {sample['name']}: dra={sample['offset_ra_hours'] * 15.0 * 60.0:.2f}' "
                f"ddec={sample['offset_dec_deg'] * 60.0:.2f}' solve_err={sample['error_arcmin']:.2f}'",
                flush=True,
            )
        else:
            print(f"  FAIL {sample['name']}: {sample.get('error')}", flush=True)

    successes = [sample for sample in samples if sample.get("ok")]
    if not successes:
        print("No alignment solve succeeded; no pointing model written.", file=sys.stderr)
        return 4
    if len(successes) < args.points and not args.allow_partial:
        print(
            f"Only {len(successes)}/{args.points} alignment solves succeeded; no pointing model written.",
            file=sys.stderr,
        )
        return 5

    model = build_pointing_model(
        successes,
        scope_tag=scope_tag,
        scope_name=scope.get("scope_name"),
        max_age_hours=args.max_age_hours,
    )
    if args.output:
        out_path = args.output
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(model, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        out_path = save_pointing_model(model, scope_tag)

    print(f"Pointing model written: {out_path}")
    print(f"  successes={len(successes)} ra_offset={model['offset_ra_arcmin']:.2f}' dec_offset={model['offset_dec_arcmin']:.2f}'")
    if len(successes) < args.points:
        print(f"  warning: requested {args.points} points, got {len(successes)}")

    if args.park_after:
        sequence._telescope.park()
        sequence._telescope.set_tracking(False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
