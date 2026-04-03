#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/horizon_scanner_v2.py
Version: 2.0.0
Objective: Simpler daytime horizon scanner using burst-median wide-camera frames and robust skyline detection, intended to replace the spike-prone gradient-max approach.

Design:
- Uses the wide camera through Alpaca as an engineering vision sensor
- Captures a short burst at each azimuth stop (video-like behavior)
- Uses temporal median to suppress transient noise
- Ignores outer edge columns and bottom frame clutter
- Uses per-degree median aggregation, never max
- Treats horizon scanning as a skyline detection problem, not a photometry problem
"""

import argparse
import json
import logging
import math
import struct
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests
from alpaca.camera import Camera
from alpaca.telescope import Telescope

from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_sun
from astropy.time import Time
import astropy.units as u

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.env_loader import DATA_DIR, load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("horizon_scanner_v2")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WIDE_CAMERA_NUM = 1
TELESCOPE_NUM = 0

PLATE_SCALE_WIDE = 55.0
SENSOR_W = 2160
SENSOR_H = 3840
FOV_H_DEG = SENSOR_W * PLATE_SCALE_WIDE / 3600.0
FOV_V_DEG = SENSOR_H * PLATE_SCALE_WIDE / 3600.0

AZ_STEP_DEG = round(FOV_H_DEG * 0.7, 1)
ALT_CENTER_DEG = 20.0
SETTLE_SEC = 4.0

BURST_FRAMES = 5
BURST_GAP_SEC = 0.15

EXPOSE_INITIAL_SEC = 0.002
EXPOSE_MIN_SEC = 0.0001
EXPOSE_MAX_SEC = 0.05
TARGET_MEAN_ADU = 28000
ADU_FLOOR = 200.0

GAIN_WIDE = 0

MIN_HORIZON_ALT = -5.0
MAX_HORIZON_ALT = 50.0
OPEN_SKY_DEFAULT = 15.0

SIDE_CROP_FRAC = 0.15
BOTTOM_CROP_FRAC = 0.18
ROW_WINDOW = 16
CONTRAST_ABS_MIN = 18.0
CONTRAST_SIGMA = 2.5
MIN_COLS_PER_DEG = 3
SMOOTH_WINDOW = 7

SUN_MIN_ALT_DEG = 10.0
SUN_EXCLUSION_DEG = FOV_H_DEG / 2 + 15.0
SITE_ELEV_M = 5.0

CLIENT_ID = 42
ALPACA_CAMERA_BASE = None

HORIZON_FILE = DATA_DIR / "horizon_mask.json"
FRAME_DIR = DATA_DIR / "horizon_frames"

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def az_distance(a, b):
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)

def get_location():
    cfg = load_config()
    loc = cfg.get("location", {})
    lat = float(loc.get("lat", 52.38))
    lon = float(loc.get("lon", 4.65))
    elev = float(loc.get("elevation", SITE_ELEV_M))
    return EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=elev * u.m), lat, lon, elev

def get_sun_altaz(lat_deg, lon_deg, elev_m=SITE_ELEV_M):
    loc = EarthLocation(lat=lat_deg * u.deg, lon=lon_deg * u.deg, height=elev_m * u.m)
    now = Time.now()
    frame = AltAz(obstime=now, location=loc)
    sun = get_sun(now).transform_to(frame)
    return float(sun.alt.deg), float(sun.az.deg)

def altaz_to_radec(az_deg, alt_deg, location):
    now = Time.now()
    altaz = SkyCoord(az=az_deg * u.deg, alt=alt_deg * u.deg, frame=AltAz(obstime=now, location=location))
    icrs = altaz.icrs
    return float(icrs.ra.hour), float(icrs.dec.deg)

def wait_for_slew(telescope, timeout=60.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if not telescope.Slewing:
                return True
        except Exception as e:
            log.warning("Slew poll error: %s", e)
        time.sleep(0.5)
    try:
        telescope.AbortSlew()
    except Exception:
        pass
    return False

def _next_txid(camera):
    tx = getattr(camera, "_hv2_txid", 0) + 1
    camera._hv2_txid = tx
    return tx

def _parse_imagebytes(raw):
    if len(raw) < 32:
        raise RuntimeError(f"ImageBytes too short: {len(raw)} bytes")

    error_num = struct.unpack_from("<i", raw, 4)[0]
    data_start = struct.unpack_from("<i", raw, 8)[0]
    img_element = struct.unpack_from("<i", raw, 12)[0]
    rank = struct.unpack_from("<i", raw, 20)[0]
    dim1 = struct.unpack_from("<i", raw, 24)[0]
    dim2 = struct.unpack_from("<i", raw, 28)[0]

    if error_num != 0:
        raise RuntimeError(f"ImageBytes error: {error_num}")
    if rank != 2:
        raise RuntimeError(f"Unsupported ImageBytes rank: {rank}")

    dtype_map = {
        1: np.int16,
        2: np.int32,
        3: np.float64,
        6: np.uint16,
        8: np.uint32,
    }
    dtype = dtype_map.get(img_element, np.int32)
    pixel_data = raw[data_start:]
    arr = np.frombuffer(pixel_data, dtype=dtype).reshape((dim2, dim1))
    return arr.astype(np.int32, copy=False)

def download_image(camera, timeout=20):
    if not ALPACA_CAMERA_BASE:
        raise RuntimeError("Camera REST base URL unavailable")

    params = {
        "ClientID": CLIENT_ID,
        "ClientTransactionID": _next_txid(camera),
    }

    try:
        r = requests.get(
            f"{ALPACA_CAMERA_BASE}/imagearrayvariant",
            params=params,
            timeout=timeout,
            headers={"Accept": "application/imagebytes"},
        )
        ctype = r.headers.get("Content-Type", "")
        if r.status_code == 200 and "imagebytes" in ctype.lower():
            return _parse_imagebytes(r.content)
    except Exception:
        pass

    r = requests.get(
        f"{ALPACA_CAMERA_BASE}/imagearray",
        params=params,
        timeout=max(timeout, 60),
    )
    data = r.json()
    err = data.get("ErrorNumber", 0)
    if err:
        raise RuntimeError(f"imagearray: error {err} — {data.get('ErrorMessage', '')}")

    value = data.get("Value")
    if value is None:
        raise RuntimeError("imagearray returned no Value")

    return np.array(value, dtype=np.int32)

def capture_image(camera, expose_sec, timeout=20, download_timeout=20):
    camera.StartExposure(expose_sec, True)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if bool(camera.ImageReady):
                break
        except Exception:
            pass
        time.sleep(0.25)
    else:
        try:
            camera.AbortExposure()
        except Exception:
            pass
        raise RuntimeError(f"Image not ready after {timeout:.1f}s")

    return download_image(camera, timeout=download_timeout)

def disconnect_safely(camera, telescope):
    for dev in (camera, telescope):
        if dev is None:
            continue
        try:
            dev.Connected = False
        except Exception:
            pass

def auto_expose(camera, current_sec):
    try:
        img = capture_image(camera, current_sec, timeout=20, download_timeout=30)
        mean_adu = max(float(img.mean()), ADU_FLOOR)
        new_sec = current_sec * (TARGET_MEAN_ADU / mean_adu) ** 0.5
        new_sec = max(EXPOSE_MIN_SEC, min(EXPOSE_MAX_SEC, new_sec))
        log.info("Auto exposure: mean=%.0f ADU, %.4fs -> %.4fs", mean_adu, current_sec, new_sec)
        return new_sec
    except Exception as e:
        log.warning("Auto exposure failed: %s", e)
        return current_sec

# ---------------------------------------------------------------------------
# Vision pipeline
# ---------------------------------------------------------------------------

def to_luma(img):
    if img.ndim == 3:
        return img[:, :, 1].astype(np.float64)
    return img.astype(np.float64)

def capture_burst(camera, expose_sec, n_frames=BURST_FRAMES):
    frames = []
    for idx in range(n_frames):
        img = capture_image(camera, expose_sec, timeout=20, download_timeout=30)
        frames.append(to_luma(img))
        if idx < n_frames - 1:
            time.sleep(BURST_GAP_SEC)
    stack = np.stack(frames, axis=0)
    return np.median(stack, axis=0)

def smooth_1d(arr, kernel=9):
    if kernel <= 1 or len(arr) < kernel:
        return arr
    return np.convolve(arr, np.ones(kernel) / kernel, mode="same")

def column_horizon_row(column, min_row, max_row):
    """
    Find the skyline row using signed contrast, not max absolute gradient.
    We want bright sky above, darker ground below.
    """
    best_row = None
    best_score = -1e9

    usable = column[min_row:max_row]
    if len(usable) < 2 * ROW_WINDOW + 1:
        return None, 0.0

    noise = float(np.std(usable))
    threshold = max(CONTRAST_ABS_MIN, CONTRAST_SIGMA * noise)

    for row in range(min_row + ROW_WINDOW, max_row - ROW_WINDOW):
        above = float(np.mean(column[row - ROW_WINDOW:row]))
        below = float(np.mean(column[row:row + ROW_WINDOW]))
        contrast = above - below  # skyline should be brighter above than below

        if contrast > best_score:
            best_score = contrast
            best_row = row

    if best_row is None or best_score < threshold:
        return None, best_score

    return best_row, best_score

def detect_horizon_in_frame(img, az_center, alt_center):
    """
    Robust skyline detector:
    - median burst input
    - ignore side edges and bottom clutter
    - map many column detections into per-degree medians
    """
    img_f = to_luma(img)
    h, w = img_f.shape

    left = int(round(w * SIDE_CROP_FRAC))
    right = int(round(w * (1.0 - SIDE_CROP_FRAC)))
    bottom_limit = int(round(h * (1.0 - BOTTOM_CROP_FRAC)))

    alt_per_pixel = FOV_V_DEG / h
    az_per_pixel = FOV_H_DEG / w

    min_row = int(max(0, h / 2 - (alt_center - MIN_HORIZON_ALT) / alt_per_pixel))
    max_row = int(min(bottom_limit, h / 2 + (MAX_HORIZON_ALT - alt_center) / alt_per_pixel))

    per_degree = defaultdict(list)
    confident_cols = 0

    for col in range(left, right):
        column = smooth_1d(img_f[:, col], kernel=11)
        row, score = column_horizon_row(column, min_row, max_row)
        if row is None:
            continue

        confident_cols += 1

        az_offset = (col - w / 2) * az_per_pixel
        az = (az_center + az_offset) % 360.0
        az_int = int(round(az)) % 360

        alt_offset = (h / 2 - row) * alt_per_pixel
        alt = alt_center + alt_offset
        alt = max(MIN_HORIZON_ALT, min(MAX_HORIZON_ALT, alt))

        per_degree[az_int].append(float(alt))

    result = {}
    stats = {}

    for az_int, samples in per_degree.items():
        if len(samples) < MIN_COLS_PER_DEG:
            continue
        med = float(np.median(samples))
        mad = float(np.median(np.abs(np.array(samples) - med))) if len(samples) > 1 else 0.0
        result[az_int] = round(med, 1)
        stats[az_int] = {
            "median": round(med, 2),
            "mad": round(mad, 2),
            "n_cols": len(samples),
        }

    pct = confident_cols / max(1, (right - left)) * 100.0
    log.info(
        "Skyline confidence: %d/%d center columns (%.0f%%), %d az degrees accepted",
        confident_cols,
        max(1, (right - left)),
        pct,
        len(result),
    )
    return result, stats

def accum_update(accum, az_deg, alt_deg):
    accum[int(round(az_deg)) % 360].append(float(alt_deg))

def median_smooth_profile(profile, window=SMOOTH_WINDOW):
    full = []
    for az in range(360):
        full.append(profile.get(az, np.nan))

    arr = np.array(full, dtype=np.float64)

    for _ in range(2):
        mask = np.isnan(arr)
        if not np.any(mask):
            break
        idx = np.where(~mask, np.arange(len(mask)), 0)
        np.maximum.accumulate(idx, out=idx)
        arr[mask] = arr[idx][mask]

    if np.all(np.isnan(arr)):
        return {az: OPEN_SKY_DEFAULT for az in range(360)}

    padded = np.concatenate([arr[-window:], arr, arr[:window]])
    out = np.copy(arr)

    for i in range(360):
        segment = padded[i:i + 2 * window + 1]
        segment = segment[np.isfinite(segment)]
        out[i] = np.median(segment) if len(segment) else OPEN_SKY_DEFAULT

    return {az: round(float(out[az]), 1) for az in range(360)}

def fill_gaps_from_accum(accum):
    profile = {}
    confidence = {}

    for az in range(360):
        samples = accum.get(az, [])
        if samples:
            med = float(np.median(samples))
            var = float(np.var(samples)) if len(samples) > 1 else 0.0
            profile[az] = round(med, 1)
            confidence[az] = {
                "mean": round(med, 1),
                "var": round(var, 2),
                "n": len(samples),
            }

    smoothed = median_smooth_profile(profile, window=SMOOTH_WINDOW)

    conf_out = {}
    for az in range(360):
        if az in confidence:
            conf_out[az] = confidence[az]
        else:
            conf_out[az] = {
                "mean": smoothed[az],
                "var": 0.0,
                "n": 0,
            }

    return smoothed, conf_out

# ---------------------------------------------------------------------------
# Scan runner
# ---------------------------------------------------------------------------

def run_scan(ip, port, dry_run=False, sun_visible=True):
    global ALPACA_CAMERA_BASE
    ALPACA_CAMERA_BASE = f"http://{ip}:{port}/api/v1/camera/{WIDE_CAMERA_NUM}"

    positions = np.arange(0, 360, AZ_STEP_DEG).tolist()
    location, lat, lon, elev = get_location()

    log.info("=" * 60)
    log.info("HORIZON SCANNER v2.0.0")
    log.info("Wide camera burst-median skyline mode")
    log.info("Az step %.1f° (70%% overlap)", AZ_STEP_DEG)
    log.info("Side crop %.0f%% each edge, bottom crop %.0f%%", SIDE_CROP_FRAC * 100, BOTTOM_CROP_FRAC * 100)
    log.info("Target: %s:%s", ip, port)
    log.info("=" * 60)

    FRAME_DIR.mkdir(parents=True, exist_ok=True)

    if dry_run:
        accum = defaultdict(list)
        for az in range(360):
            if 240 <= az <= 300:
                accum[az].append(25.0)
            elif 150 <= az <= 180:
                accum[az].append(18.0)
            else:
                accum[az].append(15.0)
        horizon, confidence = fill_gaps_from_accum(accum)
        return horizon, confidence, {}

    addr = f"{ip}:{port}"
    telescope = Telescope(addr, TELESCOPE_NUM)
    camera = Camera(addr, WIDE_CAMERA_NUM)

    try:
        telescope.Connected = True
        camera.Connected = True
    except Exception as e:
        log.error("Connection failed: %s", e)
        disconnect_safely(camera, telescope)
        return {}, {}, {}

    try:
        camera.Gain = GAIN_WIDE
    except Exception as e:
        log.warning("Gain set failed: %s", e)

    try:
        telescope.Unpark()
        time.sleep(4)
    except Exception as e:
        log.warning("Unpark warning: %s", e)

    sun_alt, sun_az = get_sun_altaz(lat, lon, elev)
    log.info("Sun: Alt=%.1f° Az=%.1f°", sun_alt, sun_az)

    if sun_visible:
        if sun_alt < SUN_MIN_ALT_DEG:
            log.error("Sun altitude %.1f° < %.1f° — refusing daytime scan", sun_alt, SUN_MIN_ALT_DEG)
            disconnect_safely(camera, telescope)
            return {}, {}, {}
        log.info("Sun exclusion zone: +/-%.0f° around Az %.0f°", SUN_EXCLUSION_DEG, sun_az)
    else:
        log.info("Sun visibility override: operator says sun is blocked from the Seestar")

    expose_sec = auto_expose(camera, EXPOSE_INITIAL_SEC)
    accum = defaultdict(list)
    skipped_sun = []
    frame_count = 0

    for idx, az in enumerate(positions, start=1):
        if sun_visible and az_distance(az, sun_az) < SUN_EXCLUSION_DEG:
            skipped_sun.append(float(az))
            log.warning("[%02d/%02d] Skip Az=%.1f° — sun exclusion", idx, len(positions), az)
            continue

        log.info("[%02d/%02d] Slew Az=%.1f° Alt=%.1f°", idx, len(positions), az, ALT_CENTER_DEG)

        try:
            ra_h, dec_d = altaz_to_radec(az, ALT_CENTER_DEG, location)
            telescope.SlewToCoordinatesAsync(ra_h, dec_d)
            if not wait_for_slew(telescope, timeout=45):
                log.warning("Slew timeout, skipping Az=%.1f°", az)
                continue
            time.sleep(SETTLE_SEC)
        except Exception as e:
            log.error("Slew failed at Az=%.1f°: %s", az, e)
            continue

        try:
            actual_alt = float(telescope.Altitude)
            actual_az = float(telescope.Azimuth)
        except Exception:
            actual_alt = ALT_CENTER_DEG
            actual_az = az

        try:
            burst = capture_burst(camera, expose_sec, n_frames=BURST_FRAMES)
            frame_count += BURST_FRAMES

            mean_adu = max(float(np.mean(burst)), ADU_FLOOR)
            expose_sec = expose_sec * (TARGET_MEAN_ADU / mean_adu) ** 0.5
            expose_sec = max(EXPOSE_MIN_SEC, min(EXPOSE_MAX_SEC, expose_sec))

            tag = f"{actual_az:05.1f}".replace(".", "_")
            np.save(FRAME_DIR / f"horizon_v2_az{tag}.npy", burst.astype(np.float32))
            log.info("Burst median frame saved, mean=%.0f ADU, next exposure=%.4fs", mean_adu, expose_sec)
        except Exception as e:
            log.error("Capture failed at Az=%.1f°: %s", az, e)
            continue

        try:
            frame_hz, frame_stats = detect_horizon_in_frame(burst, actual_az, actual_alt)
            for az_deg, alt_deg in frame_hz.items():
                accum_update(accum, az_deg, alt_deg)
            log.info("Accepted %d az degrees from this stop", len(frame_hz))
        except Exception as e:
            log.error("Detection failed at Az=%.1f°: %s", az, e)

    disconnect_safely(camera, telescope)

    horizon, confidence = fill_gaps_from_accum(accum)

    sun_info = {
        "visible_to_seestar": bool(sun_visible),
        "alt": round(sun_alt, 1),
        "az": round(sun_az, 1),
        "exclusion_deg": SUN_EXCLUSION_DEG,
        "skipped_azimuths": [round(a, 1) for a in skipped_sun],
    }

    log.info("Complete: %d burst frames, 360-degree profile produced", frame_count)
    return horizon, confidence, sun_info

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_horizon(horizon, confidence, output_path, sun_info):
    output_path.parent.mkdir(parents=True, exist_ok=True)

    profile = {str(az): round(horizon.get(az, OPEN_SKY_DEFAULT), 1) for az in range(360)}
    conf_out = {}

    for az in range(360):
        if az in confidence:
            conf_out[str(az)] = confidence[az]
        else:
            conf_out[str(az)] = {
                "mean": profile[str(az)],
                "var": 0.0,
                "n": 0,
            }

    payload = {
        "#objective": "Per-degree horizon profile from burst-median wide-camera skyline scan.",
        "source": "camera_scan_v2",
        "camera": "Camera #1 (IMX586, wide-angle)",
        "scanner_version": "2.0.0",
        "method": "burst_median_skyline",
        "az_step_deg": AZ_STEP_DEG,
        "burst_frames": BURST_FRAMES,
        "side_crop_frac": SIDE_CROP_FRAC,
        "bottom_crop_frac": BOTTOM_CROP_FRAC,
        "contrast_abs_min": CONTRAST_ABS_MIN,
        "contrast_sigma": CONTRAST_SIGMA,
        "open_sky_default": OPEN_SKY_DEFAULT,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_points": len(profile),
        "sun_info": sun_info,
        "profile": profile,
        "confidence": conf_out,
    }

    output_path.write_text(json.dumps(payload, indent=2))

    vals = [float(v) for v in profile.values()]
    log.info("Written: %s", output_path)
    log.info("Points: %d", len(profile))
    log.info("Min: %.1f  Max: %.1f  Mean: %.1f", min(vals), max(vals), sum(vals) / len(vals))

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Horizon Scanner v2 — burst-median skyline scan using the wide camera"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ip", type=str, default=None)
    parser.add_argument("--port", type=int, default=32323)
    parser.add_argument("--output", type=str, default=str(HORIZON_FILE))
    parser.add_argument(
        "--sun-visible",
        dest="sun_visible",
        action="store_true",
        help="Enable sun avoidance because the sun can be seen by the Seestar",
    )
    parser.add_argument(
        "--sun-blocked",
        dest="sun_visible",
        action="store_false",
        help="Disable sun avoidance because the sun is physically blocked",
    )
    parser.set_defaults(sun_visible=None)
    args = parser.parse_args()

    if args.ip:
        ip = args.ip
    else:
        cfg = load_config()
        seestars = cfg.get("seestars", [{}])
        ip = seestars[0].get("ip", "192.168.178.251")

    print("+" + "=" * 62 + "+")
    print("|                HORIZON SCANNER v2.0.0                |")
    print("|     Burst-median skyline detection, center-weighted   |")
    print("+" + "=" * 62 + "+")
    print(f"Target IP          : {ip}:{args.port}")
    print(f"Az step            : {AZ_STEP_DEG:.1f}°")
    print(f"Vertical FOV       : {FOV_V_DEG:.1f}°")
    print(f"Burst frames       : {BURST_FRAMES}")
    print(f"Side crop          : {SIDE_CROP_FRAC * 100:.0f}% each side")
    print(f"Bottom crop        : {BOTTOM_CROP_FRAC * 100:.0f}%")
    print(f"Output             : {args.output}")
    print("")

    if args.sun_visible is None and not args.dry_run:
        ans = input("Can the sun be seen by the Seestar from this site right now? [y/N]: ").strip().lower()
        sun_visible = ans in ("y", "yes")
    else:
        sun_visible = True if args.sun_visible is None else args.sun_visible

    horizon, confidence, sun_info = run_scan(
        ip=ip,
        port=args.port,
        dry_run=args.dry_run,
        sun_visible=sun_visible,
    )

    if not horizon:
        print("\nNo horizon produced.")
        raise SystemExit(1)

    write_horizon(horizon, confidence, Path(args.output), sun_info)

    print("\nDone.")
    print(f"Profile written to: {args.output}")
    print("Use this scanner on cloudy or bright daytime conditions for best skyline contrast.")

if __name__ == "__main__":
    main()
