#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/stellarium_panorama_from_media.py
Version: 1.3.0
Objective: Build a spherical Stellarium panorama package from normal RGB photos
or a video capture. This is the visual path and is intentionally separate from
SeeVar's mathematical horizon scanner.
"""

import argparse
import io
import math
import re
import shutil
import subprocess
import tempfile
import zipfile
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
from core.preflight.panorama_calibration import (
    PANORAMA_CALIBRATION,
    apply_calibration,
    load_calibration_points,
    merge_calibration_points,
    parse_reference_point,
    save_calibration_points,
)


def _next_power_of_two(value: int) -> int:
    value = max(1, int(value))
    return 1 << (value - 1).bit_length()


def _load_rgb(path: Path) -> np.ndarray:
    image = Image.open(path).convert("RGB")
    return np.asarray(image, dtype=np.uint8)


def _parse_media_token(pattern: str, stem: str) -> float | None:
    match = re.search(pattern, stem.lower())
    if not match:
        return None
    token = match.group(1).replace("_", ".")
    try:
        return float(token) % 360.0
    except ValueError:
        return None


def _extract_media_azimuth(
    path: Path,
    calibration_points: list[dict] | None = None,
    fallback_offset_deg: float = 0.0,
) -> float | None:
    stem = path.stem
    true_az = _parse_media_token(r"trueaz(\d+(?:_\d+)?)", stem)
    if true_az is not None:
        return true_az
    observed_az = _parse_media_token(r"obs(\d+(?:_\d+)?)", stem)
    if observed_az is not None:
        return apply_calibration(observed_az, calibration_points, fallback_offset_deg=fallback_offset_deg)
    legacy_az = _parse_media_token(r"(?<!true)(?<!obs)az(\d+(?:_\d+)?)", stem)
    if legacy_az is not None:
        return legacy_az
    return None


def _order_media_paths(
    paths: list[Path],
    calibration_points: list[dict] | None = None,
    fallback_offset_deg: float = 0.0,
) -> list[Path]:
    decorated = [
        (_extract_media_azimuth(path, calibration_points, fallback_offset_deg=fallback_offset_deg), idx, path)
        for idx, path in enumerate(paths)
    ]
    if all(az is not None for az, _, _ in decorated):
        return [path for _, _, path in sorted(decorated, key=lambda item: (float(item[0]), item[1]))]
    return paths


def _try_opencv_stitch(frames: list[np.ndarray]) -> np.ndarray | None:
    try:
        import cv2  # type: ignore
    except Exception:
        return None

    if len(frames) < 2:
        return None

    bgr_images = [cv2.cvtColor(frame, cv2.COLOR_RGB2BGR) for frame in frames]
    stitcher = cv2.Stitcher_create(cv2.Stitcher_PANORAMA)
    status, pano = stitcher.stitch(bgr_images)
    if status != cv2.Stitcher_OK or pano is None:
        return None
    return cv2.cvtColor(pano, cv2.COLOR_BGR2RGB)


def _blend_rgb_panorama(
    frames: list[np.ndarray],
    width: int,
    height: int,
    azimuths: list[float] | None,
    slice_width_px: int,
    center_crop_ratio: float = 0.7,
) -> np.ndarray:
    accum = np.zeros((height, width, 3), dtype=np.float32)
    weights = np.zeros((height, width), dtype=np.float32)
    blend = np.clip(1.0 - np.abs(np.linspace(-1.0, 1.0, slice_width_px, dtype=np.float32)), 0.02, 1.0)

    n = len(frames)
    for idx, frame in enumerate(frames):
        w = frame.shape[1]
        crop_w = max(32, int(round(w * center_crop_ratio)))
        left = max(0, (w - crop_w) // 2)
        right = min(w, left + crop_w)
        cropped = frame[:, left:right, :]
        resized = Image.fromarray(cropped).resize((slice_width_px, height), Image.Resampling.LANCZOS)
        img = np.asarray(resized, dtype=np.float32)
        if azimuths and idx < len(azimuths):
            center_x = (azimuths[idx] % 360.0) / 360.0 * width
        else:
            center_x = idx * (width / n) + (width / n) / 2.0
        start_x = int(round(center_x - slice_width_px / 2.0))
        for src_x in range(slice_width_px):
            dst_x = (start_x + src_x) % width
            weight = blend[src_x]
            accum[:, dst_x, :] += img[:, src_x, :] * weight
            weights[:, dst_x] += weight

    if np.any(weights <= 1e-6):
        valid = np.where(weights.mean(axis=0) > 1e-6)[0]
        if valid.size:
            for col in np.where(weights.mean(axis=0) <= 1e-6)[0]:
                nearest = valid[np.argmin(np.abs(valid - col))]
                accum[:, col, :] = accum[:, nearest, :]
                weights[:, col] = np.maximum(weights[:, nearest], 1.0)

    out = accum / np.maximum(weights[:, :, None], 1e-6)
    return np.clip(out, 0, 255).astype(np.uint8)


def _png_bytes(rgb: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG")
    return buf.getvalue()


def _landscape_ini(
    name: str,
    description: str,
    location: dict,
    top_alt: float,
    bottom_alt: float,
    has_horizon: bool,
    angle_rotatez: float,
) -> str:
    text = (
        "[landscape]\r\n"
        f"name = {name}\r\n"
        "type = spherical\r\n"
        "author = SeeVar\r\n"
        f"description = {description}\r\n"
        "maptex = panorama.png\r\n"
        f"maptex_top = {top_alt:.2f}\r\n"
        f"maptex_bottom = {bottom_alt:.2f}\r\n"
        "bottom_cap_color = 0.03,0.03,0.03\r\n"
        f"angle_rotatez = {angle_rotatez:.2f}\r\n"
        f"minimal_altitude = {math.floor(bottom_alt):d}\r\n"
        "\r\n"
        "[location]\r\n"
        "planet = Earth\r\n"
        f"name = {name}\r\n"
        f"latitude = {location['lat']:.6f}\r\n"
        f"longitude = {location['lon']:.6f}\r\n"
        f"altitude = {int(round(location['elevation']))}\r\n"
    )
    if has_horizon:
        text = text.replace(
            f"minimal_altitude = {math.floor(bottom_alt):d}\r\n",
            "polygonal_horizon_list = horizon.txt\r\n"
            "polygonal_horizon_list_mode = azDeg_altDeg\r\n"
            "polygonal_angle_rotatez = 0\r\n"
            f"minimal_altitude = {math.floor(bottom_alt):d}\r\n",
        )
    return text


def _video_duration_seconds(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def _extract_video_frames(video_path: Path, out_dir: Path, count: int) -> list[Path]:
    duration = max(_video_duration_seconds(video_path), 1.0)
    fps = max(count / duration, 0.05)
    pattern = out_dir / "frame_%04d.jpg"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", str(video_path),
            "-vf", f"fps={fps:.6f}",
            "-frames:v", str(count),
            str(pattern),
        ],
        check=True,
    )
    return sorted(out_dir.glob("frame_*.jpg"))


def build_panorama_zip(
    media_paths: list[Path],
    output_zip: Path,
    name: str,
    pano_width: int = 4096,
    pano_height: int = 1024,
    top_alt: float = 45.0,
    bottom_alt: float = -15.0,
    mask_path: Path | None = None,
    azimuth_offset_deg: float = 0.0,
    calibration_points: list[dict] | None = None,
) -> Path:
    location = _load_location()
    folder = _slugify(name)
    description = (
        f"SeeVar spherical panorama for {location['maidenhead']} "
        f"(lat={location['lat']:.5f}, lon={location['lon']:.5f}, elev={location['elevation']:.1f}m)"
    )

    media_paths = _order_media_paths(media_paths, calibration_points, fallback_offset_deg=azimuth_offset_deg)
    pano_width = _next_power_of_two(pano_width)
    pano_height = _next_power_of_two(pano_height)
    azimuths = [
        _extract_media_azimuth(path, calibration_points, fallback_offset_deg=azimuth_offset_deg)
        for path in media_paths
    ]
    if not any(az is not None for az in azimuths):
        azimuths = []
    slice_width_px = max(96, int(round((pano_width / max(len(media_paths), 1)) * 1.35)))

    missing = [str(path) for path in media_paths if not Path(path).exists()]
    if missing:
        joined = "\n".join(missing)
        raise FileNotFoundError(f"Input media not found:\n{joined}")

    frames = [_load_rgb(path) for path in media_paths]
    if azimuths:
        panorama = _blend_rgb_panorama(frames, pano_width, pano_height, azimuths if azimuths else None, slice_width_px)
    else:
        panorama = _try_opencv_stitch(frames)
        if panorama is None:
            panorama = _blend_rgb_panorama(frames, pano_width, pano_height, None, slice_width_px)
        else:
            panorama = np.asarray(
                Image.fromarray(panorama).resize((pano_width, pano_height), Image.Resampling.LANCZOS),
                dtype=np.uint8,
            )

    mask_payload = None
    if mask_path and Path(mask_path).exists():
        mask_payload = _load_horizon_mask(Path(mask_path))

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{folder}/panorama.png", _png_bytes(panorama))
        zf.writestr(
            f"{folder}/landscape.ini",
            _landscape_ini(
                name,
                description,
                location,
                top_alt,
                bottom_alt,
                has_horizon=mask_payload is not None,
                angle_rotatez=0.0,
            ),
        )
        zf.writestr(
            f"{folder}/readme.txt",
            _readme_txt(name, description, location, mask_path or HORIZON_MASK),
        )
        if mask_payload is not None:
            zf.writestr(f"{folder}/horizon.txt", _horizon_txt(mask_payload["profile"]))
    return output_zip


def main():
    parser = argparse.ArgumentParser(description="Build a Stellarium panorama zip from normal photos or a video.")
    parser.add_argument("--video", type=str, default=None)
    parser.add_argument("--frames", type=int, default=16, help="Number of frames to sample from the video")
    parser.add_argument("--mask", type=str, default=str(HORIZON_MASK))
    parser.add_argument("--output", type=str, required=True)
    parser.add_argument("--name", type=str, required=True)
    parser.add_argument("--width", type=int, default=4096)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--top-alt", type=float, default=45.0)
    parser.add_argument("--bottom-alt", type=float, default=-15.0)
    parser.add_argument("--azimuth-offset-deg", type=float, default=0.0)
    parser.add_argument("--calibration-file", type=str, default=str(PANORAMA_CALIBRATION))
    parser.add_argument(
        "--reference",
        action="append",
        default=[],
        help=(
            "Compass anchor. Examples: 210=180, 210=south, "
            "obs=210,true=180,label=south roofline, "
            "file=/path/panorama_obs210_3.jpg,true=135,label=SE railing"
        ),
    )
    parser.add_argument("--save-calibration", action="store_true", help="Write merged reference points back to the calibration JSON")
    parser.add_argument("images", nargs="*")
    args = parser.parse_args()

    media_paths: list[Path] = [Path(p) for p in args.images]
    temp_dir = None
    try:
        calibration_points = load_calibration_points(Path(args.calibration_file)) if args.calibration_file else []
        if args.reference:
            calibration_points = merge_calibration_points(
                calibration_points,
                [parse_reference_point(spec) for spec in args.reference],
            )
            if args.save_calibration and args.calibration_file:
                save_calibration_points(calibration_points, Path(args.calibration_file))
        if args.video:
            temp_dir = Path(tempfile.mkdtemp(prefix="seevar_pano_"))
            media_paths = _extract_video_frames(Path(args.video), temp_dir, args.frames)
        if not media_paths:
            raise SystemExit("No input media supplied.")

        out = build_panorama_zip(
            media_paths=media_paths,
            output_zip=Path(args.output),
            name=args.name,
            pano_width=args.width,
            pano_height=args.height,
            top_alt=args.top_alt,
            bottom_alt=args.bottom_alt,
            mask_path=Path(args.mask) if args.mask else None,
            azimuth_offset_deg=float(args.azimuth_offset_deg),
            calibration_points=calibration_points,
        )
        print(out)
    finally:
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
