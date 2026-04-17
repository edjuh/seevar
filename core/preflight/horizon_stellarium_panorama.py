#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/horizon_stellarium_panorama.py
Version: 1.0.0
Objective: Build a spherical Stellarium landscape zip from horizon scanner v2
frame captures. This is a visual panorama package, distinct from the polygonal
horizon export used by SeeVar itself.
"""

import argparse
import io
import json
import math
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

import sys
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.preflight.horizon_stellarium_export import (
    HORIZON_MASK,
    STELLARIUM_DIR,
    _horizon_txt,
    _load_horizon_mask,
    _load_location,
    _readme_txt,
    _slugify,
)
from core.utils.env_loader import DATA_DIR

FRAME_DIR = DATA_DIR / "horizon_frames"


def _next_power_of_two(value: int) -> int:
    value = max(1, int(value))
    return 1 << (value - 1).bit_length()


def _parse_azimuth(path: Path) -> float:
    match = re.search(r"az(\d+)_([0-9])", path.stem)
    if not match:
        raise ValueError(f"Could not parse azimuth from {path.name}")
    return float(f"{match.group(1)}.{match.group(2)}")


def _load_image_frame(path: Path) -> np.ndarray:
    img = Image.open(path).convert("L")
    return np.asarray(img, dtype=np.uint8)


def _load_frame(path: Path) -> np.ndarray:
    arr = np.load(path)
    if arr.ndim == 3:
        arr = np.mean(arr, axis=0)
    arr = np.asarray(arr, dtype=np.float32)
    p1, p99 = np.percentile(arr, [1.0, 99.5])
    if not np.isfinite(p1) or not np.isfinite(p99) or p99 <= p1:
        scaled = np.zeros_like(arr, dtype=np.uint8)
    else:
        scaled = np.clip((arr - p1) * 255.0 / (p99 - p1), 0, 255).astype(np.uint8)
    return scaled


def _blend_panorama(frames: list[tuple[float, np.ndarray]], width: int, height: int, frame_width_px: int) -> np.ndarray:
    accum = np.zeros((height, width), dtype=np.float32)
    weights = np.zeros((height, width), dtype=np.float32)

    x = np.linspace(-1.0, 1.0, frame_width_px, dtype=np.float32)
    blend = np.clip(1.0 - np.abs(x), 0.05, 1.0)

    for az, frame in frames:
        resized = Image.fromarray(frame, mode="L").resize((frame_width_px, height), Image.Resampling.BICUBIC)
        img = np.asarray(resized, dtype=np.float32)
        center_x = (az % 360.0) / 360.0 * width
        start_x = int(round(center_x - frame_width_px / 2.0))
        for src_x in range(frame_width_px):
            dst_x = (start_x + src_x) % width
            w = blend[src_x]
            accum[:, dst_x] += img[:, src_x] * w
            weights[:, dst_x] += w

    missing = weights <= 1e-6
    if np.any(missing):
        col_weight = weights.mean(axis=0)
        col_value = accum.sum(axis=0)
        valid = np.where(col_weight > 1e-6)[0]
        if valid.size:
            for col in np.where(col_weight <= 1e-6)[0]:
                nearest = valid[np.argmin(np.abs(valid - col))]
                accum[:, col] = accum[:, nearest]
                weights[:, col] = np.maximum(weights[:, nearest], 1.0)

    pano = np.divide(accum, np.maximum(weights, 1e-6))
    return np.clip(pano, 0, 255).astype(np.uint8)


def _panorama_png_bytes(gray: np.ndarray) -> bytes:
    rgb = np.dstack([gray, gray, gray])
    image = Image.fromarray(rgb, mode="RGB")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
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
        "angle_rotatez = 0\r\n"
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


def export_stellarium_panorama_zip(
    mask_path: Path,
    frame_dir: Path,
    output_zip: Path | None = None,
    landscape_name: str | None = None,
    pano_width: int = 4096,
    pano_height: int | None = None,
    fov_h_deg: float = 33.0,
    fov_v_deg: float = 58.7,
    alt_center_deg: float = 20.0,
) -> Path:
    payload = _load_horizon_mask(mask_path)
    profile = payload["profile"]
    location = _load_location()

    frame_paths = sorted(frame_dir.glob("horizon_v2_az*.png"))
    frame_loader = _load_image_frame
    if not frame_paths:
        frame_paths = sorted(frame_dir.glob("horizon_v2_az*.npy"))
        frame_loader = _load_frame
    if not frame_paths:
        raise FileNotFoundError(f"No scanner frames found in {frame_dir}")

    if pano_height is None:
        ideal_height = int(round(pano_width * (fov_v_deg / 360.0)))
        pano_height = _next_power_of_two(ideal_height)
    pano_width = _next_power_of_two(pano_width)
    pano_height = _next_power_of_two(pano_height)

    top_alt = alt_center_deg + fov_v_deg / 2.0
    bottom_alt = alt_center_deg - fov_v_deg / 2.0
    frame_width_px = max(64, int(round(pano_width * (fov_h_deg / 360.0))))

    frames = [(_parse_azimuth(path), frame_loader(path)) for path in frame_paths]
    panorama = _blend_panorama(frames, pano_width, pano_height, frame_width_px)

    maidenhead = location["maidenhead"]
    name = landscape_name or f"SeeVar {maidenhead} Panorama"
    folder = _slugify(name)
    description = (
        f"SeeVar spherical panorama for {maidenhead} "
        f"(lat={location['lat']:.5f}, lon={location['lon']:.5f}, elev={location['elevation']:.1f}m)"
    )

    location_json = json.dumps({
        "name": name,
        "maidenhead": maidenhead,
        "lat": location["lat"],
        "lon": location["lon"],
        "elevation_m": location["elevation"],
        "location_source": location["source"],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "horizon_source": str(mask_path),
        "frames_source": str(frame_dir),
        "frame_count": len(frame_paths),
        "frame_format": frame_paths[0].suffix.lower(),
        "scanner_version": payload.get("scanner_version"),
        "panorama": {
            "width_px": pano_width,
            "height_px": pano_height,
            "top_alt_deg": round(top_alt, 3),
            "bottom_alt_deg": round(bottom_alt, 3),
            "frame_fov_h_deg": round(fov_h_deg, 3),
            "frame_fov_v_deg": round(fov_v_deg, 3),
        },
    }, indent=2) + "\n"

    if output_zip is None:
        STELLARIUM_DIR.mkdir(parents=True, exist_ok=True)
        output_zip = STELLARIUM_DIR / f"{folder}.zip"
    else:
        output_zip = Path(output_zip)
        output_zip.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{folder}/panorama.png", _panorama_png_bytes(panorama))
        zf.writestr(f"{folder}/horizon.txt", _horizon_txt(profile))
        zf.writestr(f"{folder}/landscape.ini", _landscape_ini(name, description, location, top_alt, bottom_alt))
        zf.writestr(f"{folder}/location.json", location_json)
        zf.writestr(f"{folder}/readme.txt", _readme_txt(name, description, location, mask_path))

    return output_zip


def main():
    parser = argparse.ArgumentParser(description="Build a spherical Stellarium panorama zip from horizon scanner v2 frames.")
    parser.add_argument("--input", default=str(HORIZON_MASK))
    parser.add_argument("--frames-dir", default=str(FRAME_DIR))
    parser.add_argument("--output", default=None)
    parser.add_argument("--name", default=None, help="Optional Stellarium landscape name")
    parser.add_argument("--width", type=int, default=4096)
    parser.add_argument("--height", type=int, default=None)
    parser.add_argument("--fov-h-deg", type=float, default=33.0)
    parser.add_argument("--fov-v-deg", type=float, default=58.7)
    parser.add_argument("--alt-center-deg", type=float, default=20.0)
    args = parser.parse_args()

    out = export_stellarium_panorama_zip(
        mask_path=Path(args.input),
        frame_dir=Path(args.frames_dir),
        output_zip=Path(args.output) if args.output else None,
        landscape_name=args.name,
        pano_width=args.width,
        pano_height=args.height,
        fov_h_deg=args.fov_h_deg,
        fov_v_deg=args.fov_v_deg,
        alt_center_deg=args.alt_center_deg,
    )
    print(out)


if __name__ == "__main__":
    main()
