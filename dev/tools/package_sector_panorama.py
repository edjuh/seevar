#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/package_sector_panorama.py
Objective: Package a pre-stitched panorama sector plus a SeeVar horizon mask into
the conservative Stellarium spherical landscape zip format.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

import sys
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.preflight.horizon_stellarium_export import _horizon_txt, _load_location, _readme_txt, _slugify


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Package a stitched panorama sector for Stellarium.")
    parser.add_argument("--panorama", required=True, help="Input panorama image (PNG or JPEG)")
    parser.add_argument("--mask", required=True, help="SeeVar horizon_mask.json")
    parser.add_argument("--output", required=True, help="Output zip path")
    parser.add_argument("--name", required=True, help="Landscape name")
    parser.add_argument("--left-az", type=float, required=True, help="True azimuth at the left edge of the sector")
    parser.add_argument("--right-az", type=float, required=True, help="True azimuth at the right edge of the sector")
    parser.add_argument("--width", type=int, default=4096)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--top-alt", type=float, default=45.0)
    parser.add_argument("--bottom-alt", type=float, default=-15.0)
    parser.add_argument("--fill-west-silhouette", action="store_true", help="Fill manual west obstruction sectors with a dark silhouette")
    parser.add_argument("--lat", type=float, default=None, help="Override latitude for landscape.ini")
    parser.add_argument("--lon", type=float, default=None, help="Override longitude for landscape.ini")
    parser.add_argument("--elevation", type=float, default=None, help="Override elevation (m) for landscape.ini")
    parser.add_argument("--maidenhead", type=str, default=None, help="Override site maidenhead in the description")
    return parser.parse_args()


def _next_power_of_two(value: int) -> int:
    value = max(1, int(value))
    return 1 << (value - 1).bit_length()


def _png_bytes(image: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(image).save(buf, format="PNG")
    return buf.getvalue()


def _landscape_ini(name: str, description: str, location: dict, top_alt: float, bottom_alt: float) -> str:
    return (
        "[landscape]\r\n"
        f"name = {name}\r\n"
        "type = spherical\r\n"
        "author = SeeVar\r\n"
        f"description = {description}\r\n"
        "maptex = panorama.png\r\n"
        f"maptex_top = {top_alt:.2f}\r\n"
        f"maptex_bottom = {bottom_alt:.2f}\r\n"
        "bottom_cap_color = 0.03,0.03,0.03\r\n"
        "angle_rotatez = 0.00\r\n"
        "polygonal_horizon_list = horizon.txt\r\n"
        "polygonal_horizon_list_mode = azDeg_altDeg\r\n"
        "polygonal_angle_rotatez = 0\r\n"
        f"minimal_altitude = {math.floor(bottom_alt):d}\r\n"
        "\r\n"
        "[location]\r\n"
        "planet = Earth\r\n"
        f"name = {name}\r\n"
        f"latitude = {location['lat']:.6f}\r\n"
        f"longitude = {location['lon']:.6f}\r\n"
        f"altitude = {int(round(location['elevation']))}\r\n"
    )


def _resolve_location(args: argparse.Namespace) -> dict:
    if args.lat is not None and args.lon is not None:
        return {
            "lat": float(args.lat),
            "lon": float(args.lon),
            "elevation": float(args.elevation if args.elevation is not None else 0.0),
            "maidenhead": str(args.maidenhead or "UNKNOWN"),
        }
    location = _load_location()
    if args.lat is not None:
        location["lat"] = float(args.lat)
    if args.lon is not None:
        location["lon"] = float(args.lon)
    if args.elevation is not None:
        location["elevation"] = float(args.elevation)
    if args.maidenhead is not None:
        location["maidenhead"] = str(args.maidenhead)
    return location


def _crop_nonblack(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    arr = np.asarray(rgba)
    mask = arr[:, :, 3] > 0
    if not mask.any():
        rgb = arr[:, :, :3]
        mask = (rgb.sum(axis=2) > 20)
    if not mask.any():
        return rgba
    ys, xs = np.where(mask)
    return rgba.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))


def _resample_profile(profile: dict) -> dict[str, float]:
    out = {}
    for az in range(360):
        out[str(az)] = float(profile.get(str(az), profile.get(az, 15.0)))
    return out


def _make_canvas(
    panorama: Image.Image,
    profile: dict[str, float],
    left_az: float,
    right_az: float,
    width: int,
    height: int,
    top_alt: float,
    bottom_alt: float,
    fill_west_silhouette: bool,
) -> np.ndarray:
    src = _crop_nonblack(panorama).convert("RGBA")
    sector_width = max(1, int(round(width * (((right_az - left_az) % 360 or 360.0) / 360.0))))
    src = src.resize(
        (sector_width, height),
        Image.Resampling.LANCZOS,
    )
    src_arr = np.asarray(src, dtype=np.uint8)
    canvas = np.zeros((height, width, 4), dtype=np.uint8)

    sector_span = (right_az - left_az) % 360.0
    if sector_span == 0:
        sector_span = 360.0
    left_x = int(round((left_az % 360.0) / 360.0 * width))
    for dx in range(src_arr.shape[1]):
        az = (left_az + (dx / max(1, src_arr.shape[1] - 1)) * sector_span) % 360.0
        x = int(round((az / 360.0) * (width - 1)))
        column = src_arr[:, dx, :].copy()
        alt0 = float(profile[str(int(math.floor(az)) % 360)])
        alt1 = float(profile[str((int(math.floor(az)) + 1) % 360)])
        frac = az - math.floor(az)
        horizon_alt = alt0 * (1.0 - frac) + alt1 * frac
        horizon_y = int(round(((top_alt - horizon_alt) / max(top_alt - bottom_alt, 1e-6)) * (height - 1)))
        horizon_y = max(0, min(height - 1, horizon_y))
        if horizon_y > 0:
            column[:horizon_y, 3] = 0
        canvas[:, x, :] = np.maximum(canvas[:, x, :], column)

    if fill_west_silhouette:
        for az in range(360):
            src_kind = str(profile.get(f"source:{az}", ""))
            if 245 <= az <= 324:
                x = int(round((az / 360.0) * (width - 1)))
                h_alt = float(profile[str(az)])
                horizon_y = int(round(((top_alt - h_alt) / max(top_alt - bottom_alt, 1e-6)) * (height - 1)))
                horizon_y = max(0, min(height - 1, horizon_y))
                canvas[horizon_y:, x, :3] = (36, 32, 30)
                canvas[horizon_y:, x, 3] = 255

    return canvas


def main() -> int:
    args = parse_args()
    panorama = Image.open(args.panorama)
    payload = json.loads(Path(args.mask).read_text())
    profile = _resample_profile(payload["profile"])
    width = _next_power_of_two(args.width)
    height = _next_power_of_two(args.height)
    canvas = _make_canvas(
        panorama=panorama,
        profile=profile,
        left_az=float(args.left_az),
        right_az=float(args.right_az),
        width=width,
        height=height,
        top_alt=float(args.top_alt),
        bottom_alt=float(args.bottom_alt),
        fill_west_silhouette=bool(args.fill_west_silhouette),
    )

    location = _resolve_location(args)
    name = args.name
    folder = _slugify(name)
    description = (
        f"SeeVar stitched sector panorama for {location['maidenhead']} "
        f"(lat={location['lat']:.5f}, lon={location['lon']:.5f}, elev={location['elevation']:.1f}m)"
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{folder}/panorama.png", _png_bytes(canvas))
        zf.writestr(
            f"{folder}/landscape.ini",
            _landscape_ini(name, description, location, float(args.top_alt), float(args.bottom_alt)),
        )
        zf.writestr(f"{folder}/readme.txt", _readme_txt(name, description, location, Path(args.mask)))
        zf.writestr(f"{folder}/horizon.txt", _horizon_txt(profile))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
