#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/stellarium_panorama_capture.py
Version: 1.0.0
Objective: Capture a real visual panorama from the Seestar wide-camera RTSP
stream while slewing around the horizon, then optionally build a Stellarium
spherical landscape zip from the captured JPEGs.
"""

import argparse
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from alpaca.camera import Camera
from alpaca.telescope import Telescope

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import core.preflight.horizon_scanner_v2 as hv2
from core.preflight.stellarium_panorama_from_media import build_panorama_zip
from core.preflight.horizon_stellarium_export import HORIZON_MASK, STELLARIUM_DIR, _slugify
from core.utils.env_loader import DATA_DIR, load_config

PANORAMA_DIR = DATA_DIR / "panorama_media"
RTSP_WIDE_PORT = 4555


def _primary_scope_ip() -> str:
    cfg = load_config()
    scopes = cfg.get("seestars", [])
    if scopes:
        ip = scopes[0].get("ip")
        if ip and ip != "TBD":
            return str(ip)
    return "192.168.8.11"


def _capture_rtsp_jpeg(ip: str, out_path: Path, timeout: float = 10.0) -> None:
    url = f"rtsp://{ip}:{RTSP_WIDE_PORT}/stream"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-rtsp_transport", "tcp",
        "-i", url,
        "-frames:v", "1",
        "-q:v", "2",
        "-y",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, timeout=timeout)


def _capture_rtsp_mp4(ip: str, out_path: Path, seconds: float, timeout: float | None = None) -> None:
    url = f"rtsp://{ip}:{RTSP_WIDE_PORT}/stream"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-rtsp_transport", "tcp",
        "-i", url,
        "-t", f"{seconds:.2f}",
        "-an",
        "-y",
        "-c:v", "copy",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, timeout=timeout or max(10.0, seconds + 8.0))


def _build_output_dir(base_dir: Path | None) -> Path:
    if base_dir is not None:
        out = Path(base_dir)
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = PANORAMA_DIR / f"capture_{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _capture_positions(step_deg: float) -> list[float]:
    values = np.arange(0.0, 360.0, float(step_deg)).tolist()
    if not values:
        values = [0.0]
    return [round(v, 1) for v in values]


def capture_visual_panorama(
    ip: str,
    port: int,
    telescope_num: int,
    camera_num: int,
    client_id: int,
    altitude_deg: float,
    az_step_deg: float,
    output_dir: Path,
    video_seconds: float,
    build_zip: bool,
    zip_path: Path | None,
    landscape_name: str | None,
    top_alt: float,
    bottom_alt: float,
    sun_visible: bool,
) -> tuple[list[Path], Path | None]:
    output_dir = _build_output_dir(output_dir)
    positions = _capture_positions(az_step_deg)

    location, lat, lon, elev = hv2.get_location()
    sun_alt, sun_az = hv2.get_sun_altaz(lat, lon, elev)

    addr = f"{ip}:{port}"
    telescope = Telescope(addr, telescope_num)
    camera = Camera(addr, camera_num)

    hv2.ALPACA_CAMERA_BASE = f"http://{ip}:{port}/api/v1/camera/{camera_num}"

    telescope.Connected = True
    camera.Connected = True
    hv2.configure_camera(camera)
    try:
        telescope.Unpark()
    except Exception:
        pass

    if not hv2.probe_wide_camera(camera, client_id):
        hv2.disconnect_safely(camera, telescope)
        raise RuntimeError("Wide camera probe failed before panorama capture")

    captured: list[Path] = []
    try:
        for idx, az in enumerate(positions, start=1):
            if sun_visible and hv2.az_distance(az, sun_az) < hv2.SUN_EXCLUSION_DEG:
                hv2.log.warning("[%02d/%02d] Skip Az=%.1f° — sun exclusion", idx, len(positions), az)
                continue

            hv2.log.info("[%02d/%02d] Panorama slew Az=%.1f° Alt=%.1f°", idx, len(positions), az, altitude_deg)
            if not hv2.slew_with_recovery(telescope, camera, location, az, altitude_deg, client_id):
                hv2.log.warning("Skipping panorama stop at Az=%.1f°", az)
                continue

            try:
                actual_az = float(telescope.Azimuth)
            except Exception:
                actual_az = az
            tag = f"{actual_az:05.1f}".replace(".", "_")

            jpg_path = output_dir / f"panorama_az{tag}.jpg"
            _capture_rtsp_jpeg(ip, jpg_path)
            captured.append(jpg_path)

            if video_seconds > 0:
                mp4_path = output_dir / f"panorama_az{tag}.mp4"
                try:
                    _capture_rtsp_mp4(ip, mp4_path, seconds=video_seconds)
                except Exception as exc:
                    hv2.log.warning("Short video capture failed at Az=%.1f°: %s", az, exc)

        zip_out = None
        if build_zip and captured:
            if zip_path is None:
                STELLARIUM_DIR.mkdir(parents=True, exist_ok=True)
                zip_name = _slugify(landscape_name or "SeeVar Panorama")
                zip_out = STELLARIUM_DIR / f"{zip_name}.zip"
            else:
                zip_out = Path(zip_path)
            build_panorama_zip(
                media_paths=captured,
                output_zip=zip_out,
                name=landscape_name or "SeeVar Panorama",
                pano_width=4096,
                pano_height=1024,
                top_alt=top_alt,
                bottom_alt=bottom_alt,
                mask_path=HORIZON_MASK if HORIZON_MASK.exists() else None,
            )
        return captured, zip_out
    finally:
        hv2.disconnect_safely(camera, telescope)


def main():
    parser = argparse.ArgumentParser(description="Capture a real visual panorama from the Seestar wide-camera RTSP stream.")
    parser.add_argument("--ip", type=str, default=None)
    parser.add_argument("--port", type=int, default=32323)
    parser.add_argument("--camera-num", type=int, default=hv2.WIDE_CAMERA_NUM_DEFAULT)
    parser.add_argument("--telescope-num", type=int, default=hv2.TELESCOPE_NUM_DEFAULT)
    parser.add_argument("--client-id", type=int, default=hv2.CLIENT_ID_DEFAULT)
    parser.add_argument("--alt", type=float, default=20.0)
    parser.add_argument("--az-step", type=float, default=30.0)
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument("--video-seconds", type=float, default=0.0, help="Optional short MP4 duration per azimuth stop")
    parser.add_argument("--no-zip", action="store_true")
    parser.add_argument("--zip-output", type=str, default=None)
    parser.add_argument("--name", type=str, default="SeeVar Visual Panorama")
    parser.add_argument("--top-alt", type=float, default=45.0)
    parser.add_argument("--bottom-alt", type=float, default=-15.0)
    parser.add_argument("--sun-visible", dest="sun_visible", action="store_true")
    parser.add_argument("--sun-blocked", dest="sun_visible", action="store_false")
    parser.set_defaults(sun_visible=None)
    args = parser.parse_args()

    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg is required for RTSP panorama capture")

    ip = args.ip or _primary_scope_ip()
    if args.sun_visible is None:
        answer = input("Can the sun be seen by the Seestar from this site right now? [y/N]: ").strip().lower()
        sun_visible = answer.startswith("y")
    else:
        sun_visible = bool(args.sun_visible)

    captured, zip_out = capture_visual_panorama(
        ip=ip,
        port=args.port,
        telescope_num=args.telescope_num,
        camera_num=args.camera_num,
        client_id=args.client_id,
        altitude_deg=args.alt,
        az_step_deg=args.az_step,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        video_seconds=float(args.video_seconds),
        build_zip=not args.no_zip,
        zip_path=Path(args.zip_output) if args.zip_output else None,
        landscape_name=args.name,
        top_alt=float(args.top_alt),
        bottom_alt=float(args.bottom_alt),
        sun_visible=sun_visible,
    )

    print(f"Captured JPEGs : {len(captured)}")
    if captured:
        print(f"Media dir      : {captured[0].parent}")
    if zip_out:
        print(f"Stellarium zip : {zip_out}")


if __name__ == "__main__":
    main()
