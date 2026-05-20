#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/telescope/widefield_plate_solve.py
Version: 1.0.0
Objective: Capture a wide-camera frame from a Seestar, solve it with the known
           wide-camera plate scale, and report the true field center versus the
           mount's current pointing estimate.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image
from alpaca.camera import Camera
from alpaca.telescope import Telescope
from astropy.coordinates import SkyCoord
from astropy.io import fits
import astropy.units as u

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import core.preflight.horizon_scanner_v2 as hv2
from core.utils.env_loader import DATA_DIR, load_config, selected_scope, selected_scope_host, scope_file_tag


WIDE_CAMERA_SCALE_ARCSEC = 55.0
WIDE_SCALE_LOW = 35.0
WIDE_SCALE_HIGH = 80.0

BRIGHT_STARS = {
    "arcturus": ("Arcturus", 14.261021, 19.1825),
    "vega": ("Vega", 18.615649, 38.7837),
    "deneb": ("Deneb", 20.690532, 45.2803),
    "altair": ("Altair", 19.846389, 8.8683),
    "capella": ("Capella", 5.278155, 45.9980),
    "aldebaran": ("Aldebaran", 4.598677, 16.5093),
    "mizar": ("Mizar", 13.398750, 54.9254),
    "kochab": ("Kochab", 14.845109, 74.1555),
}


@dataclass(frozen=True)
class SolveHint:
    ra_hours: float
    dec_deg: float
    label: str


# Parse a focused command line for one wide-field capture/solve cycle.
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", default="", help="Override telescope IP; defaults to the selected scope.")
    parser.add_argument("--port", type=int, default=32323, help="Alpaca port.")
    parser.add_argument("--camera-num", type=int, default=1, help="Wide camera device number.")
    parser.add_argument("--telescope-num", type=int, default=0, help="Telescope device number.")
    parser.add_argument("--exposure-sec", type=float, default=2.0, help="Wide-frame exposure in seconds.")
    parser.add_argument("--gain", type=int, default=0, help="Wide-camera gain.")
    parser.add_argument("--radius-deg", type=float, default=25.0, help="Search radius around the hint coordinates.")
    parser.add_argument("--timeout-sec", type=int, default=90, help="Wall timeout for solve-field.")
    parser.add_argument("--cpulimit-sec", type=int, default=75, help="CPU limit for solve-field.")
    parser.add_argument("--downsample", type=int, default=2, help="Downsample factor passed to solve-field.")
    parser.add_argument("--settle-sec", type=float, default=5.0, help="Pause after an optional slew.")
    parser.add_argument("--output-dir", type=Path, default=DATA_DIR / "verify_buffer" / "widefield", help="Directory for FITS, preview, and WCS files.")
    parser.add_argument("--hint-ra-hours", type=float, default=None, help="Explicit RA hint in hours.")
    parser.add_argument("--hint-dec-deg", type=float, default=None, help="Explicit Dec hint in degrees.")
    parser.add_argument("--target-star", default="", help="Optional bright star name to slew to before capture.")
    parser.add_argument("--capture-only", action="store_true", help="Capture FITS and preview only; skip solve-field.")
    return parser.parse_args()


# Resolve the active scope metadata used for file naming and default host selection.
def resolve_scope(ip_override: str) -> tuple[dict, str]:
    cfg = load_config()
    if ip_override.strip():
        for idx, scope in enumerate(cfg.get("seestars", [])):
            if str(scope.get("ip", "")).strip() == ip_override.strip():
                resolved = dict(scope)
                resolved["scope_id"] = f"scope{idx + 1:02d}"
                return resolved, ip_override.strip()
        return selected_scope(cfg), ip_override.strip()
    return selected_scope(cfg), selected_scope_host(cfg)


# Stretch a raw wide-field frame into a quick-look grayscale JPEG.
def stretch_u8(data: np.ndarray) -> np.ndarray:
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return np.zeros(data.shape, dtype=np.uint8)
    lo, hi = np.percentile(finite, [1.0, 99.7])
    if hi <= lo:
        hi = lo + 1.0
    scaled = np.clip((data - lo) / (hi - lo), 0.0, 1.0)
    return (scaled * 255.0).astype(np.uint8)


# Persist the wide-camera frame as a FITS file with enough metadata for solve-field.
def write_wide_fits(data: np.ndarray, out_path: Path, hint: SolveHint | None, host: str, scope_tag: str) -> None:
    header = fits.Header()
    header["DATE-OBS"] = datetime.now(timezone.utc).isoformat()
    header["INSTRUME"] = "Seestar S30-Pro WIDE"
    header["TELESCOP"] = f"Seestar {scope_tag}"
    header["FILTER"] = "WIDE"
    header["XPIXSZ"] = 2.9
    header["YPIXSZ"] = 2.9
    header["SCALE"] = WIDE_CAMERA_SCALE_ARCSEC
    header["HOSTIP"] = host
    if hint is not None:
        header["OBJECT"] = hint.label[:68]
        header["OBJCTRA"] = float(hint.ra_hours * 15.0)
        header["OBJCTDEC"] = float(hint.dec_deg)
        header["CRVAL1"] = float(hint.ra_hours * 15.0)
        header["CRVAL2"] = float(hint.dec_deg)
    fits.PrimaryHDU(data=data.astype(np.int32), header=header).writeto(out_path, overwrite=True)


# Save a small visual preview next to the FITS so the operator can sanity-check the field.
def write_preview(data: np.ndarray, out_path: Path) -> None:
    preview = Image.fromarray(stretch_u8(data))
    preview.save(out_path, format="JPEG", quality=88)


# Read the current telescope-reported sky position for use as a solve hint.
def current_mount_hint(telescope: Telescope) -> SolveHint | None:
    try:
        ra_hours = float(telescope.RightAscension)
        dec_deg = float(telescope.Declination)
        return SolveHint(ra_hours=ra_hours, dec_deg=dec_deg, label="mount_reported_center")
    except Exception:
        return None


# Convert a named bright star into a slew target and solve hint.
def bright_star_hint(name: str) -> SolveHint:
    key = name.strip().lower()
    if key not in BRIGHT_STARS:
        choices = ", ".join(sorted(star for star in BRIGHT_STARS))
        raise ValueError(f"Unknown bright star '{name}'. Choices: {choices}")
    label, ra_hours, dec_deg = BRIGHT_STARS[key]
    return SolveHint(ra_hours=ra_hours, dec_deg=dec_deg, label=label)


# Return the best available hint source, preferring explicit coordinates or a named star.
def select_hint(args: argparse.Namespace, telescope: Telescope) -> SolveHint | None:
    if args.target_star.strip():
        return bright_star_hint(args.target_star)
    if args.hint_ra_hours is not None and args.hint_dec_deg is not None:
        return SolveHint(
            ra_hours=float(args.hint_ra_hours),
            dec_deg=float(args.hint_dec_deg),
            label="explicit_hint",
        )
    return current_mount_hint(telescope)


# Optionally slew the mount toward a bright reference before capturing the wide frame.
def maybe_slew_to_hint(telescope: Telescope, hint: SolveHint | None, settle_sec: float) -> None:
    if hint is None or hint.label in {"explicit_hint", "mount_reported_center"}:
        return
    telescope.SlewToCoordinatesAsync(hint.ra_hours, hint.dec_deg)
    deadline = time.monotonic() + 90.0
    while time.monotonic() < deadline:
        if not bool(telescope.Slewing):
            time.sleep(settle_sec)
            return
        time.sleep(0.5)
    raise RuntimeError(f"Slew to {hint.label} did not finish within 90s")


# Open the telescope and wide camera once so the probe does not create duplicate sessions.
def connect_devices(host: str, port: int, camera_num: int, telescope_num: int, gain: int) -> tuple[Telescope, Camera]:
    addr = f"{host}:{port}"
    telescope = Telescope(addr, telescope_num)
    camera = Camera(addr, camera_num)

    telescope.Connected = True
    camera.Connected = True

    hv2.ALPACA_CAMERA_BASE = f"http://{host}:{port}/api/v1/camera/{camera_num}"
    hv2.GAIN_WIDE = gain
    hv2.configure_camera(camera)
    if not hv2.probe_wide_camera(camera, hv2.CLIENT_ID_DEFAULT):
        raise RuntimeError("Wide camera probe failed")
    return telescope, camera


# Capture one real wide-camera frame through the fast Alpaca imagebytes path.
def capture_wide_frame(camera: Camera, exposure_sec: float) -> np.ndarray:
    image = hv2.capture_image(
        camera,
        hv2.CLIENT_ID_DEFAULT,
        exposure_sec,
        timeout=max(20.0, exposure_sec + 10.0),
        download_timeout=max(20.0, exposure_sec + 10.0),
    )
    if image.ndim == 3:
        image = image[:, :, 1]
    return image.astype(np.float32, copy=False)


# Run solve-field with wide-camera scale constraints and return the solved center.
def solve_wide_frame(fits_path: Path, hint: SolveHint | None, args: argparse.Namespace) -> dict:
    cmd = [
        "solve-field",
        str(fits_path),
        "--dir", str(fits_path.parent),
        "--overwrite",
        "--no-plots",
        "--no-verify",
        "--resort",
        "--objs", "1000",
        "--downsample", str(max(1, int(args.downsample))),
        "--scale-units", "arcsecperpix",
        "--scale-low", str(WIDE_SCALE_LOW),
        "--scale-high", str(WIDE_SCALE_HIGH),
        "--tweak-order", "2",
        "--cpulimit", str(max(5, int(args.cpulimit_sec))),
    ]
    if hint is not None:
        cmd.extend([
            "--ra", str(hint.ra_hours * 15.0),
            "--dec", str(hint.dec_deg),
            "--radius", str(max(1.0, float(args.radius_deg))),
        ])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=max(10, int(args.timeout_sec)),
    )
    wcs_path = fits_path.with_suffix(".wcs")
    if not wcs_path.exists():
        return {
            "ok": False,
            "returncode": result.returncode,
            "stderr": (result.stderr or "").strip()[-500:],
        }

    solved = fits.getheader(wcs_path, 0)
    solved_ra_deg = float(solved["CRVAL1"])
    solved_dec_deg = float(solved["CRVAL2"])
    payload = {
        "ok": True,
        "wcs_path": str(wcs_path),
        "solved_ra_deg": solved_ra_deg,
        "solved_dec_deg": solved_dec_deg,
    }
    if hint is not None:
        expected = SkyCoord(ra=hint.ra_hours * 15.0 * u.deg, dec=hint.dec_deg * u.deg, frame="icrs")
        actual = SkyCoord(ra=solved_ra_deg * u.deg, dec=solved_dec_deg * u.deg, frame="icrs")
        payload["error_arcmin"] = float(expected.separation(actual).arcminute)
    return payload


# Disconnect hardware cleanly so the test does not leave the wide camera occupied.
def disconnect_safely(camera: Camera | None, telescope: Telescope | None) -> None:
    hv2.disconnect_safely(camera, telescope)


# Execute one end-to-end wide-field capture and optional solve.
def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")

    scope, host = resolve_scope(args.ip)
    scope_tag = scope_file_tag(scope)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    image = None
    telescope = None
    camera = None
    try:
        telescope, camera = connect_devices(
            host,
            args.port,
            args.camera_num,
            args.telescope_num,
            args.gain,
        )
        hint = select_hint(args, telescope)
        maybe_slew_to_hint(telescope, hint, args.settle_sec)
        image = capture_wide_frame(camera, args.exposure_sec)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        base = output_dir / f"widefield_{scope_tag}_{timestamp}"
        fits_path = base.with_suffix(".fits")
        preview_path = base.with_suffix(".jpg")

        write_wide_fits(image, fits_path, hint, host, scope_tag)
        write_preview(image, preview_path)

        print(f"Captured FITS : {fits_path}")
        print(f"Preview JPG   : {preview_path}")
        if hint is not None:
            print(f"Hint source   : {hint.label}")
            print(f"Hint center   : RA={hint.ra_hours:.5f}h Dec={hint.dec_deg:.5f}°")
        else:
            print("Hint source   : none")

        if args.capture_only:
            return 0

        solve = solve_wide_frame(fits_path, hint, args)
        if not solve.get("ok"):
            print(f"Solve failed  : rc={solve.get('returncode')} stderr={solve.get('stderr', '')}")
            return 2

        solved_ra_hours = float(solve["solved_ra_deg"]) / 15.0
        print(f"Solved center : RA={solved_ra_hours:.5f}h Dec={solve['solved_dec_deg']:.5f}°")
        print(f"WCS file      : {solve['wcs_path']}")
        if "error_arcmin" in solve:
            print(f"Center error  : {solve['error_arcmin']:.2f} arcmin")
        return 0
    finally:
        disconnect_safely(camera, telescope)


if __name__ == "__main__":
    raise SystemExit(main())
