#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/telescope/prealign_pointing.py
Version: 1.0.0
Objective: Build a quick SeeVar software pointing model from 2-3 bright
           plate-solved alignment stars before starting a science sequence.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import astropy.units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord
from astropy.io import fits
from astropy.time import Time
from alpaca.camera import Camera

from core.flight.pilot import AcquisitionTarget, DiamondSequence
from core.flight.pointing_model import build_pointing_model, normalize_ra_hours, save_pointing_model
import core.preflight.horizon_scanner_v2 as hv2
from core.preflight.horizon import required_altitude
from core.utils.env_loader import load_config, selected_scope, scope_file_tag


WIDE_CAMERA_NUM = 1
WIDE_CAMERA_SCALE_LOW = 35.0
WIDE_CAMERA_SCALE_HIGH = 80.0


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
    parser.add_argument("--no-wide-fallback", action="store_true", help="Do not retry failed alignment solves with the wide camera.")
    parser.add_argument("--wide-camera-num", type=int, default=WIDE_CAMERA_NUM, help="Wide-camera Alpaca device number.")
    parser.add_argument("--wide-exposure-sec", type=float, default=5.0, help="Wide-camera fallback exposure in seconds.")
    parser.add_argument("--wide-gain", type=int, default=0, help="Wide-camera fallback gain.")
    parser.add_argument("--wide-solve-radius-deg", type=float, default=60.0, help="Wide-camera fallback solve radius.")
    parser.add_argument("--port", type=int, default=32323, help="Alpaca port.")
    parser.add_argument("--ip", default="", help="Override selected scope IP address.")
    parser.add_argument("--scope-tag", default="", help="Override output model scope tag, e.g. scope01 or scope02.")
    parser.add_argument("--state-file", type=Path, default=None, help="Scoped system_state JSON to update during manual alignment.")
    parser.add_argument("--when", default="", help="UTC ISO time for candidate planning only, e.g. 2026-05-09T22:00:00Z.")
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
    obstime = Time(args.when) if str(args.when or "").strip() else Time(datetime.now(timezone.utc))
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


# Write prealignment progress into the same state file the dashboard reads.
def write_state(
    args: argparse.Namespace,
    scope: dict,
    sub: str,
    msg: str,
    target: str | None = None,
    state: str = "PREFLIGHT",
) -> None:
    if args.state_file is None:
        return
    try:
        payload = json.loads(args.state_file.read_text(encoding="utf-8")) if args.state_file.exists() else {}
    except Exception:
        payload = {}
    now_utc = datetime.now(timezone.utc).isoformat()
    payload.update(
        {
            "state": state,
            "scope_name": scope.get("scope_name") or scope.get("name"),
            "scope_id": scope.get("scope_id"),
            "sub": sub,
            "substate": sub,
            "msg": msg,
            "message": msg,
            "updated": now_utc,
            "updated_utc": now_utc,
            "current_target": target,
        }
    )
    args.state_file.parent.mkdir(parents=True, exist_ok=True)
    args.state_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


# Store a wide-camera frame as FITS with the target coordinates as solve hints.
def write_wide_alignment_fits(data: np.ndarray, target: AcquisitionTarget, host: str, scope_tag: str) -> Path:
    VERIFY_DIR = PROJECT_ROOT / "data" / "verify_buffer"
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    utc_obs = datetime.now(timezone.utc)
    safe_name = target.name.replace(" ", "_").replace("/", "-")
    out_path = VERIFY_DIR / f"{safe_name}_{scope_tag}_{utc_obs.strftime('%Y%m%dT%H%M%S')}_WIDE_ALIGN.fits"

    header = fits.Header()
    header["DATE-OBS"] = utc_obs.isoformat()
    header["OBJECT"] = target.name[:68]
    header["INSTRUME"] = "Seestar S30-Pro WIDE"
    header["TELESCOP"] = f"Seestar {scope_tag}"
    header["FILTER"] = "WIDE"
    header["HOSTIP"] = host
    header["OBJCTRA"] = float(target.ra_hours * 15.0)
    header["OBJCTDEC"] = float(target.dec_deg)
    header["CRVAL1"] = float(target.ra_hours * 15.0)
    header["CRVAL2"] = float(target.dec_deg)
    header["SCALE"] = 55.0
    fits.PrimaryHDU(data=data.astype(np.int32), header=header).writeto(out_path, overwrite=True)
    return out_path


# Capture a fallback frame through the Seestar wide camera.
def capture_wide_alignment_frame(target: AcquisitionTarget, args: argparse.Namespace, host: str, scope_tag: str) -> Path:
    camera = None
    try:
        camera = Camera(f"{host}:{args.port}", int(args.wide_camera_num))
        camera.Connected = True
        hv2.ALPACA_CAMERA_BASE = f"http://{host}:{args.port}/api/v1/camera/{int(args.wide_camera_num)}"
        hv2.GAIN_WIDE = int(args.wide_gain)
        hv2.configure_camera(camera)
        if not hv2.probe_wide_camera(camera, hv2.CLIENT_ID_DEFAULT):
            raise RuntimeError("wide camera probe failed")
        image = hv2.capture_image(
            camera,
            hv2.CLIENT_ID_DEFAULT,
            float(args.wide_exposure_sec),
            timeout=max(20.0, float(args.wide_exposure_sec) + 10.0),
            download_timeout=max(20.0, float(args.wide_exposure_sec) + 10.0),
        )
        if image.ndim == 3:
            image = image[:, :, 1]
        return write_wide_alignment_fits(image, target, host, scope_tag)
    finally:
        hv2.disconnect_safely(camera, None)


# Solve a wide-camera fallback frame using loose scale constraints.
def solve_wide_alignment_frame(fits_path: Path, target: AcquisitionTarget, args: argparse.Namespace) -> dict:
    ra_deg = float(target.ra_hours * 15.0)
    dec_deg = float(target.dec_deg)
    cmd = [
        "solve-field",
        str(fits_path),
        "--dir",
        str(fits_path.parent),
        "--overwrite",
        "--no-plots",
        "--no-verify",
        "--resort",
        "--objs",
        "1000",
        "--downsample",
        str(max(1, int(args.solve_downsample))),
        "--ra",
        str(ra_deg),
        "--dec",
        str(dec_deg),
        "--radius",
        str(max(1.0, float(args.wide_solve_radius_deg))),
        "--scale-units",
        "arcsecperpix",
        "--scale-low",
        str(WIDE_CAMERA_SCALE_LOW),
        "--scale-high",
        str(WIDE_CAMERA_SCALE_HIGH),
        "--tweak-order",
        "2",
        "--cpulimit",
        str(max(5, min(int(args.solve_timeout_sec), int(args.solve_timeout_sec) - 5))),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=max(10, int(args.solve_timeout_sec)))
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"wide solve-field timeout after {args.solve_timeout_sec}s"}

    wcs_path = fits_path.with_suffix(".wcs")
    if not wcs_path.exists():
        return {"ok": False, "error": f"wide solve-field failed ({result.returncode})"}

    hdr = fits.getheader(wcs_path, 0)
    solved_ra_deg = float(hdr.get("CRVAL1"))
    solved_dec_deg = float(hdr.get("CRVAL2"))
    target_coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")
    solved_coord = SkyCoord(ra=solved_ra_deg * u.deg, dec=solved_dec_deg * u.deg, frame="icrs")
    return {
        "ok": True,
        "wcs_path": str(wcs_path),
        "solved_ra_deg": solved_ra_deg,
        "solved_dec_deg": solved_dec_deg,
        "error_arcmin": float(target_coord.separation(solved_coord).arcminute),
    }


# Slew, capture, plate-solve, and return one alignment sample.
def solve_alignment_star(
    sequence: DiamondSequence,
    item: dict,
    args: argparse.Namespace,
    host: str,
    scope: dict,
    scope_tag: str,
) -> dict:
    star: AlignStar = item["star"]
    target = AcquisitionTarget(
        name=f"ALIGN_{star.name}",
        ra_hours=star.ra_hours,
        dec_deg=star.dec_deg,
        exp_ms=int(round(args.exposure_sec * 1000.0)),
        n_frames=1,
    )

    print(f"Aligning {star.name}: alt={item['alt_deg']:.1f} az={item['az_deg']:.1f}", flush=True)
    write_state(args, scope, "PREALIGN SLEW", f"Pre-align slewing to {star.name}", star.name)
    sequence._telescope.slew_to_coordinates_async(star.ra_hours, star.dec_deg)
    if not sequence._telescope.wait_for_slew():
        return {"ok": False, "name": star.name, "error": "slew_timeout"}

    time.sleep(3.0)
    write_state(args, scope, "PREALIGN SOLVE", f"Pre-align solving {star.name} with telephoto camera", star.name)
    camera_source = "tele"
    fits_path = sequence._capture_temp_frame(target, args.exposure_sec, "ALIGN")
    solve = sequence._solve_verify_frame(
        fits_path,
        target,
        radius_deg=args.solve_radius_deg,
        timeout_sec=args.solve_timeout_sec,
        cpulimit_sec=max(5, min(args.solve_timeout_sec, args.solve_timeout_sec - 5)),
        downsample=args.solve_downsample,
    )
    if not solve.get("ok") and not args.no_wide_fallback:
        print(f"  Telephoto solve failed for {star.name}; trying wide camera fallback.", flush=True)
        write_state(args, scope, "PREALIGN WIDE", f"Pre-align solving {star.name} with wide camera", star.name)
        camera_source = "wide"
        fits_path = capture_wide_alignment_frame(target, args, host, scope_tag)
        solve = solve_wide_alignment_frame(fits_path, target, args)

    sample = {
        "ok": bool(solve.get("ok")),
        "name": star.name,
        "target_ra_hours": round(star.ra_hours, 8),
        "target_dec_deg": round(star.dec_deg, 8),
        "alt_deg": item["alt_deg"],
        "az_deg": item["az_deg"],
        "camera": camera_source,
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
        sample = solve_alignment_star(sequence, item, args, sequence.host, scope, scope_tag)
        samples.append(sample)
        if sample.get("ok"):
            print(
                f"  OK {sample['name']} ({sample['camera']}): dra={sample['offset_ra_hours'] * 15.0 * 60.0:.2f}' "
                f"ddec={sample['offset_dec_deg'] * 60.0:.2f}' solve_err={sample['error_arcmin']:.2f}'",
                flush=True,
            )
        else:
            print(f"  FAIL {sample['name']}: {sample.get('error')}", flush=True)

    successes = [sample for sample in samples if sample.get("ok")]
    if not successes:
        write_state(
            args,
            scope,
            "ALIGNMENT FAILED",
            "No alignment solve succeeded; science run blocked.",
            state="ABORTED",
        )
        print("No alignment solve succeeded; no pointing model written.", file=sys.stderr)
        return 4
    if len(successes) < args.points and not args.allow_partial:
        write_state(
            args,
            scope,
            "ALIGNMENT FAILED",
            f"Only {len(successes)}/{args.points} alignment solves succeeded; science run blocked.",
            state="ABORTED",
        )
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
    if model.get("kind") == "affine_prealignment":
        print(f"  successes={len(successes)} kind=affine median_error={model['median_error_arcmin']:.2f}'")
    else:
        print(f"  successes={len(successes)} ra_offset={model['offset_ra_arcmin']:.2f}' dec_offset={model['offset_dec_arcmin']:.2f}'")
    if len(successes) < args.points:
        print(f"  warning: requested {args.points} points, got {len(successes)}")
    write_state(args, scope, "PREALIGN OK", f"Pointing model ready from {len(successes)} solve(s).")

    if args.park_after:
        sequence._telescope.park()
        sequence._telescope.set_tracking(False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
