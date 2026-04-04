#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/horizon_scanner_v2.py
Version: 2.0.6
Objective: Rooftop-aware daytime horizon scanner using burst-median wide-camera frames
and vectorized skyline detection for balcony / urban sites.
"""

import argparse
import json
import math
import struct
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import logging
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

WIDE_CAMERA_NUM_DEFAULT = 1
TELESCOPE_NUM_DEFAULT = 0
CLIENT_ID_DEFAULT = 42

PLATE_SCALE_WIDE = 55.0
SENSOR_W = 2160
SENSOR_H = 3840
FOV_H_DEG = SENSOR_W * PLATE_SCALE_WIDE / 3600.0
FOV_V_DEG = SENSOR_H * PLATE_SCALE_WIDE / 3600.0

AZ_STEP_DEG = round(FOV_H_DEG * 0.7, 1)
ALT_CENTER_DEG = 20.0
SETTLE_SEC = 4.0
POST_RECOVERY_PAUSE_SEC = 4.0
SLEW_RETRY_LIMIT = 2

BURST_FRAMES = 5
BURST_GAP_SEC = 0.15

EXPOSE_INITIAL_SEC = 0.002
EXPOSE_MIN_SEC = 0.0001
EXPOSE_MAX_SEC = 0.05
TARGET_MEAN_ADU = 28000
ADU_FLOOR = 200.0

GAIN_WIDE = 0

MIN_HORIZON_ALT = -5.0
MAX_HORIZON_ALT = 75.0
OPEN_SKY_DEFAULT = 15.0

SIDE_CROP_FRAC_DEFAULT = 0.15
BOTTOM_CROP_FRAC_DEFAULT = 0.18

SIDE_CROP_FRAC_BALCONY = 0.12
BOTTOM_CROP_FRAC_BALCONY = 0.34

ROW_WINDOW = 16
CONTRAST_ABS_MIN_DEFAULT = 10.0
CONTRAST_SIGMA_DEFAULT = 2.0
CONTRAST_ABS_MIN_BALCONY = 8.0
CONTRAST_SIGMA_BALCONY = 1.8
MIN_COLS_PER_DEG_DEFAULT = 1
SMOOTH_WINDOW = 7

SUN_MIN_ALT_DEG = 10.0
SUN_EXCLUSION_DEG = FOV_H_DEG / 2 + 15.0
SITE_ELEV_M = 5.0

WEST_HOUSE_START_AZ = 240
WEST_HOUSE_END_AZ = 320
WEST_HOUSE_ALT_DEG = 70.0

ALPACA_CAMERA_BASE = None

HORIZON_FILE = DATA_DIR / "horizon_mask.json"
FRAME_DIR = DATA_DIR / "horizon_frames"


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


def download_image(camera, client_id, timeout=20):
    if not ALPACA_CAMERA_BASE:
        raise RuntimeError("Camera REST base URL unavailable")

    params = {
        "ClientID": client_id,
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


def capture_image(camera, client_id, expose_sec, timeout=20, download_timeout=20):
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

    return download_image(camera, client_id=client_id, timeout=download_timeout)


def disconnect_safely(camera, telescope):
    for dev in (camera, telescope):
        if dev is None:
            continue
        try:
            dev.Connected = False
        except Exception:
            pass


def auto_expose(camera, client_id, current_sec):
    try:
        img = capture_image(camera, client_id, current_sec, timeout=20, download_timeout=30)
        mean_adu = max(float(img.mean()), ADU_FLOOR)
        new_sec = current_sec * (TARGET_MEAN_ADU / mean_adu) ** 0.5
        new_sec = max(EXPOSE_MIN_SEC, min(EXPOSE_MAX_SEC, new_sec))
        log.info("Auto exposure: mean=%.0f ADU, %.4fs -> %.4fs", mean_adu, current_sec, new_sec)
        return new_sec
    except Exception as e:
        log.warning("Auto exposure failed: %s", e)
        return current_sec


def probe_wide_camera(camera, client_id):
    log.info("Probing wide camera availability...")
    try:
        img = capture_image(camera, client_id, EXPOSE_MIN_SEC, timeout=10, download_timeout=15)
        mean_adu = float(np.mean(img))
        log.info("Wide camera probe OK: shape=%s mean=%.0f ADU", img.shape, mean_adu)
        return True
    except Exception as e:
        msg = str(e)
        if "WIDE_ANGLE not connected" in msg or "0x4ff" in msg:
            log.error("Wide camera unavailable: %s", e)
        else:
            log.error("Wide camera probe failed: %s", e)
        return False


def configure_camera(camera):
    try:
        camera.Gain = GAIN_WIDE
    except Exception as e:
        log.warning("Gain set failed: %s", e)

    for attr, value in (("BinX", 1), ("BinY", 1)):
        try:
            setattr(camera, attr, value)
        except Exception:
            pass

    for attr, value in (("ReadoutMode", 0),):
        try:
            setattr(camera, attr, value)
        except Exception:
            pass


def is_0x4ff_error(exc):
    return "0x4ff" in str(exc)


def reconnect_devices(telescope, camera, client_id):
    log.warning("Attempting device reconnection...")
    try:
        telescope.Connected = False
    except Exception:
        pass
    try:
        camera.Connected = False
    except Exception:
        pass

    time.sleep(2.0)

    try:
        telescope.Connected = True
        camera.Connected = True
        configure_camera(camera)

        try:
            telescope.Unpark()
            time.sleep(2.0)
        except Exception:
            pass

        if not probe_wide_camera(camera, client_id):
            log.error("Reconnect failed: wide camera probe did not recover")
            return False

        log.info("Device reconnection succeeded")
        return True
    except Exception as e:
        log.error("Reconnect failed: %s", e)
        return False


def slew_with_recovery(telescope, camera, location, az, alt, client_id):
    ra_h, dec_d = altaz_to_radec(az, alt, location)

    for attempt in range(1, SLEW_RETRY_LIMIT + 1):
        try:
            telescope.SlewToCoordinatesAsync(ra_h, dec_d)
        except Exception as e:
            log.warning("Slew command failed at Az=%.1f° attempt %d/%d: %s", az, attempt, SLEW_RETRY_LIMIT, e)
            if attempt >= SLEW_RETRY_LIMIT:
                return False
            if not reconnect_devices(telescope, camera, client_id):
                return False
            time.sleep(POST_RECOVERY_PAUSE_SEC)
            continue

        if wait_for_slew(telescope, timeout=45):
            time.sleep(SETTLE_SEC)
            return True

        log.warning("Slew timeout at Az=%.1f° attempt %d/%d", az, attempt, SLEW_RETRY_LIMIT)
        if attempt >= SLEW_RETRY_LIMIT:
            return False

        try:
            telescope.AbortSlew()
        except Exception:
            pass

        if not reconnect_devices(telescope, camera, client_id):
            return False
        time.sleep(POST_RECOVERY_PAUSE_SEC)

    return False


def to_luma(img):
    if img.ndim == 3:
        return img[:, :, 1].astype(np.float64)
    return img.astype(np.float64)


def capture_burst(camera, client_id, expose_sec, n_frames=BURST_FRAMES, retries=2):
    frames = []
    for idx in range(n_frames):
        last_error = None
        for _ in range(retries + 1):
            try:
                img = capture_image(camera, client_id, expose_sec, timeout=20, download_timeout=30)
                frames.append(to_luma(img))
                last_error = None
                break
            except Exception as e:
                last_error = e
                time.sleep(0.5)
        if last_error is not None:
            raise last_error

        if idx < n_frames - 1:
            time.sleep(BURST_GAP_SEC)

    stack = np.stack(frames, axis=0)
    return np.median(stack, axis=0)


def _stretch_to_u8(img):
    p2 = float(np.percentile(img, 2))
    p98 = float(np.percentile(img, 98))
    if p98 <= p2:
        p2 = float(np.min(img))
        p98 = float(np.max(img))
    if p98 <= p2:
        return np.zeros_like(img, dtype=np.uint8)
    stretched = np.clip((img - p2) * 255.0 / (p98 - p2), 0, 255)
    return stretched.astype(np.uint8)


def write_debug_preview(img, debug, out_path):
    gray = _stretch_to_u8(img)
    rgb = np.stack([gray, gray, gray], axis=2)

    left = debug["left"]
    right = debug["right"]
    min_row = debug["min_row"]
    max_row = debug["max_row"]
    bottom_limit = debug["bottom_limit"]

    rgb[:, max(0, left - 1):min(rgb.shape[1], left + 1)] = [255, 255, 0]
    rgb[:, max(0, right - 1):min(rgb.shape[1], right + 1)] = [255, 255, 0]
    rgb[max(0, min_row - 1):min(rgb.shape[0], min_row + 1), :] = [0, 255, 255]
    rgb[max(0, max_row - 1):min(rgb.shape[0], max_row + 1), :] = [0, 255, 255]
    rgb[max(0, bottom_limit - 1):min(rgb.shape[0], bottom_limit + 1), :] = [255, 0, 255]

    for hit in debug["hits"]:
        col = hit["col"]
        row = hit["row"]
        if 0 <= row < rgb.shape[0] and 0 <= col < rgb.shape[1]:
            rgb[row, col] = [255, 0, 0]
            if row + 1 < rgb.shape[0]:
                rgb[row + 1, col] = [255, 0, 0]
            if row - 1 >= 0:
                rgb[row - 1, col] = [255, 0, 0]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(f"P6\n{rgb.shape[1]} {rgb.shape[0]}\n255\n".encode("ascii"))
        f.write(rgb.tobytes())


def detect_horizon_in_frame(
    img,
    az_center,
    alt_center,
    side_crop_frac,
    bottom_crop_frac,
    contrast_abs_min,
    contrast_sigma,
    min_cols_per_deg,
):
    img_f = to_luma(img)
    h, w = img_f.shape

    left = int(round(w * side_crop_frac))
    right = int(round(w * (1.0 - side_crop_frac)))
    bottom_limit = int(round(h * (1.0 - bottom_crop_frac)))

    alt_per_pixel = FOV_V_DEG / h
    az_per_pixel = FOV_H_DEG / w

    min_row = int(max(0, h / 2 - (alt_center - MIN_HORIZON_ALT) / alt_per_pixel))
    max_row = int(min(bottom_limit, h / 2 + (MAX_HORIZON_ALT - alt_center) / alt_per_pixel))

    crop = img_f[:, left:right]
    n_cols = crop.shape[1]

    if n_cols <= 0 or max_row - min_row < 2 * ROW_WINDOW + 1:
        debug = {
            "hits": [],
            "left": left,
            "right": right,
            "min_row": min_row,
            "max_row": max_row,
            "bottom_limit": bottom_limit,
            "confident_cols": 0,
        }
        return {}, {}, debug

    # Vertical smoothing for all columns at once.
    kernel = 11
    pad = kernel // 2
    padded = np.pad(crop, ((pad, pad), (0, 0)), mode="edge")
    cs_smooth = np.vstack([
        np.zeros((1, n_cols), dtype=np.float64),
        np.cumsum(padded, axis=0, dtype=np.float64),
    ])
    smoothed = (cs_smooth[kernel:, :] - cs_smooth[:-kernel, :]) / kernel
    smoothed = smoothed[:h, :]

    # Search range only.
    search = smoothed[min_row:max_row, :]
    n_rows = search.shape[0]
    if n_rows < 2 * ROW_WINDOW + 1:
        debug = {
            "hits": [],
            "left": left,
            "right": right,
            "min_row": min_row,
            "max_row": max_row,
            "bottom_limit": bottom_limit,
            "confident_cols": 0,
        }
        return {}, {}, debug

    # Sliding-window contrast across all rows/columns.
    cs = np.vstack([
        np.zeros((1, n_cols), dtype=np.float64),
        np.cumsum(search, axis=0, dtype=np.float64),
    ])

    r_start = ROW_WINDOW
    r_end = n_rows - ROW_WINDOW
    r_idx = np.arange(r_start, r_end)

    above = cs[r_idx, :] - cs[r_idx - ROW_WINDOW, :]
    below = cs[r_idx + ROW_WINDOW, :] - cs[r_idx, :]
    contrast = (above - below) / ROW_WINDOW

    best_local = np.argmax(contrast, axis=0)
    best_score = contrast[best_local, np.arange(n_cols)]
    best_row = best_local + r_start + min_row

    # Preserve per-column noise-aware thresholding.
    noise = np.std(search, axis=0)
    thresholds = np.maximum(float(contrast_abs_min), float(contrast_sigma) * noise)
    confident = best_score >= thresholds

    col_indices = np.arange(left, right)
    az_offset = (col_indices - w / 2) * az_per_pixel
    az_vals = (az_center + az_offset) % 360.0
    az_ints = np.round(az_vals).astype(int) % 360

    alt_offset = (h / 2 - best_row) * alt_per_pixel
    alt_vals = np.clip(alt_center + alt_offset, MIN_HORIZON_ALT, MAX_HORIZON_ALT)

    per_degree = defaultdict(list)
    hits = []
    confident_cols = 0

    for i in range(n_cols):
        if not confident[i]:
            continue
        confident_cols += 1
        az_int = int(az_ints[i])
        per_degree[az_int].append(float(alt_vals[i]))
        hits.append({
            "col": int(col_indices[i]),
            "row": int(best_row[i]),
            "score": round(float(best_score[i]), 2),
        })

    result = {}
    stats = {}

    for az_int, samples in per_degree.items():
        if len(samples) < min_cols_per_deg:
            continue
        med = float(np.median(samples))
        mad = float(np.median(np.abs(np.array(samples) - med))) if len(samples) > 1 else 0.0
        result[az_int] = round(med, 1)
        stats[az_int] = {
            "median": round(med, 2),
            "mad": round(mad, 2),
            "n_cols": len(samples),
        }

    pct = confident_cols / max(1, n_cols) * 100.0
    log.info(
        "Skyline confidence: %d/%d center columns (%.0f%%), %d az degrees accepted",
        confident_cols,
        n_cols,
        pct,
        len(result),
    )

    debug = {
        "hits": hits,
        "left": left,
        "right": right,
        "min_row": min_row,
        "max_row": max_row,
        "bottom_limit": bottom_limit,
        "confident_cols": confident_cols,
    }
    return result, stats, debug


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
                "source": "measured",
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
                "source": "interpolated",
            }

    return smoothed, conf_out


def az_in_sector(az, start, end):
    if start <= end:
        return start <= az <= end
    return az >= start or az <= end


def apply_manual_override(profile, confidence, start_az, end_az, altitude_deg, label):
    for az in range(360):
        if az_in_sector(az, start_az, end_az):
            profile[az] = round(float(altitude_deg), 1)
            confidence[az] = {
                "mean": round(float(altitude_deg), 1),
                "var": 0.0,
                "n": -1,
                "source": f"manual:{label}",
            }
    return profile, confidence


def write_csv(profile, confidence, output_path):
    csv_path = output_path.with_suffix(".csv")
    lines = ["azimuth_deg,altitude_deg,n,source"]
    for az in range(360):
        conf = confidence[str(az)]
        lines.append(f"{az},{profile[str(az)]},{conf['n']},{conf['source']}")
    csv_path.write_text("\n".join(lines) + "\n")
    return csv_path


def plot_horizon_profile(profile, confidence, sun_info, output_path):
    try:
        import matplotlib.pyplot as plt
    except Exception as e:
        log.warning("matplotlib not available, skipping plot: %s", e)
        return None

    az = np.arange(360, dtype=np.float64)
    alt = np.array([float(profile[str(int(a))]) for a in az], dtype=np.float64)

    measured_mask = np.array([confidence[str(int(a))]["source"] == "measured" for a in az], dtype=bool)
    manual_mask = np.array([str(confidence[str(int(a))]["source"]).startswith("manual:") for a in az], dtype=bool)
    interp_mask = ~(measured_mask | manual_mask)

    fig = plt.figure(figsize=(13, 6))

    ax_polar = fig.add_subplot(1, 2, 1, projection="polar")
    theta = np.deg2rad(az)
    ax_polar.plot(theta, alt, color="royalblue", linewidth=2, label="Profile")
    ax_polar.fill_between(theta, alt, 0, alpha=0.12, color="royalblue")

    if np.any(measured_mask):
        ax_polar.scatter(theta[measured_mask], alt[measured_mask], s=14, c="limegreen", label="Measured")
    if np.any(manual_mask):
        ax_polar.scatter(theta[manual_mask], alt[manual_mask], s=10, c="orange", label="Manual")

    if sun_info and sun_info.get("visible_to_seestar"):
        ax_polar.scatter(np.deg2rad(float(sun_info["az"])), float(sun_info["alt"]), s=50, c="red", label="Sun")

    ax_polar.set_theta_zero_location("N")
    ax_polar.set_theta_direction(-1)
    ax_polar.set_rmax(max(60, int(np.nanmax(alt)) + 5))
    ax_polar.set_title("Horizon Profile (Polar)")
    ax_polar.grid(True, alpha=0.3)
    ax_polar.legend(loc="upper right", fontsize=8)

    ax_cart = fig.add_subplot(1, 2, 2)
    ax_cart.plot(az, alt, color="royalblue", linewidth=2)
    ax_cart.fill_between(az, alt, 0, alpha=0.12, color="royalblue")

    if np.any(measured_mask):
        ax_cart.scatter(az[measured_mask], alt[measured_mask], s=20, c="limegreen", label="Measured")
    if np.any(manual_mask):
        ax_cart.scatter(az[manual_mask], alt[manual_mask], s=12, c="orange", label="Manual")
    if np.any(interp_mask):
        ax_cart.scatter(az[interp_mask], alt[interp_mask], s=6, c="gray", alpha=0.25, label="Interpolated")

    if sun_info and sun_info.get("visible_to_seestar"):
        ax_cart.axvline(float(sun_info["az"]), color="red", linestyle="--", alpha=0.6)
        ax_cart.scatter(float(sun_info["az"]), float(sun_info["alt"]), s=40, c="red")

    ax_cart.set_xlim(0, 360)
    ax_cart.set_ylim(-5, max(60, int(np.nanmax(alt)) + 5))
    ax_cart.set_xticks(np.arange(0, 361, 45))
    ax_cart.set_xlabel("Azimuth (deg)")
    ax_cart.set_ylabel("Altitude (deg)")
    ax_cart.set_title("Horizon Profile (Cartesian)")
    ax_cart.grid(True, alpha=0.3)
    ax_cart.legend(fontsize=8)

    plt.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    log.info("Plot written: %s", output_path)
    return output_path


def run_scan(
    ip,
    port,
    camera_num,
    telescope_num,
    client_id,
    dry_run=False,
    sun_visible=True,
    side_crop_frac=SIDE_CROP_FRAC_DEFAULT,
    bottom_crop_frac=BOTTOM_CROP_FRAC_DEFAULT,
    contrast_abs_min=CONTRAST_ABS_MIN_DEFAULT,
    contrast_sigma=CONTRAST_SIGMA_DEFAULT,
    min_cols_per_deg=MIN_COLS_PER_DEG_DEFAULT,
):
    global ALPACA_CAMERA_BASE
    ALPACA_CAMERA_BASE = f"http://{ip}:{port}/api/v1/camera/{camera_num}"

    positions = np.arange(0, 360, AZ_STEP_DEG).tolist()
    location, lat, lon, elev = get_location()

    log.info("=" * 60)
    log.info("HORIZON SCANNER v2.0.6")
    log.info("Wide camera rooftop skyline mode")
    log.info("Az step %.1f° (70%% overlap)", AZ_STEP_DEG)
    log.info("Side crop %.0f%% each edge, bottom crop %.0f%%", side_crop_frac * 100, bottom_crop_frac * 100)
    log.info("Thresholds: abs=%.1f sigma=%.1f min_cols_per_deg=%d", contrast_abs_min, contrast_sigma, min_cols_per_deg)
    log.info("Devices: telescope=%d camera=%d client_id=%d", telescope_num, camera_num, client_id)
    log.info("Target: %s:%s", ip, port)
    log.info("=" * 60)

    FRAME_DIR.mkdir(parents=True, exist_ok=True)

    if dry_run:
        accum = defaultdict(list)
        for az in range(360):
            if 240 <= az <= 320:
                accum[az].append(70.0)
            elif 150 <= az <= 180:
                accum[az].append(20.0)
            else:
                accum[az].append(15.0)
        horizon, confidence = fill_gaps_from_accum(accum)
        return horizon, confidence, {}

    addr = f"{ip}:{port}"
    telescope = Telescope(addr, telescope_num)
    camera = Camera(addr, camera_num)

    try:
        telescope.Connected = True
        camera.Connected = True
    except Exception as e:
        log.error("Connection failed: %s", e)
        disconnect_safely(camera, telescope)
        return {}, {}, {}

    configure_camera(camera)

    if not probe_wide_camera(camera, client_id):
        disconnect_safely(camera, telescope)
        return {}, {}, {}

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

    expose_sec = auto_expose(camera, client_id, EXPOSE_INITIAL_SEC)
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
            ok = slew_with_recovery(telescope, camera, location, az, ALT_CENTER_DEG, client_id)
            if not ok:
                log.warning("Skipping Az=%.1f° after recovery attempts exhausted", az)
                continue
        except Exception as e:
            log.error("Slew failed at Az=%.1f°: %s", az, e)
            if is_0x4ff_error(e):
                reconnect_devices(telescope, camera, client_id)
            continue

        try:
            actual_alt = float(telescope.Altitude)
            actual_az = float(telescope.Azimuth)
        except Exception:
            actual_alt = ALT_CENTER_DEG
            actual_az = az

        try:
            burst = capture_burst(camera, client_id, expose_sec, n_frames=BURST_FRAMES, retries=2)
            frame_count += BURST_FRAMES

            mean_adu = max(float(np.mean(burst)), ADU_FLOOR)
            expose_sec = expose_sec * (TARGET_MEAN_ADU / mean_adu) ** 0.5
            expose_sec = max(EXPOSE_MIN_SEC, min(EXPOSE_MAX_SEC, expose_sec))

            tag = f"{actual_az:05.1f}".replace(".", "_")
            np.save(FRAME_DIR / f"horizon_v2_az{tag}.npy", burst.astype(np.float32))
            log.info("Burst median frame saved, mean=%.0f ADU, next exposure=%.4fs", mean_adu, expose_sec)
        except Exception as e:
            log.error("Capture failed at Az=%.1f°: %s", az, e)
            if is_0x4ff_error(e):
                reconnect_devices(telescope, camera, client_id)
            continue

        try:
            frame_hz, frame_stats, debug = detect_horizon_in_frame(
                burst,
                actual_az,
                actual_alt,
                side_crop_frac=side_crop_frac,
                bottom_crop_frac=bottom_crop_frac,
                contrast_abs_min=contrast_abs_min,
                contrast_sigma=contrast_sigma,
                min_cols_per_deg=min_cols_per_deg,
            )
            for az_deg, alt_deg in frame_hz.items():
                accum_update(accum, az_deg, alt_deg)

            tag = f"{actual_az:05.1f}".replace(".", "_")
            preview_path = FRAME_DIR / f"horizon_v2_az{tag}.ppm"
            write_debug_preview(burst, debug, preview_path)

            log.info(
                "Accepted %d az degrees from this stop using %d columns; debug=%s",
                len(frame_hz),
                debug["confident_cols"],
                preview_path.name,
            )
        except Exception as e:
            log.error("Detection failed at Az=%.1f°: %s", az, e)

    disconnect_safely(camera, telescope)

    horizon, confidence = fill_gaps_from_accum(accum)

    measured = sum(1 for entry in confidence.values() if entry["n"] > 0)
    interpolated = sum(1 for entry in confidence.values() if entry["n"] == 0)

    sun_info = {
        "visible_to_seestar": bool(sun_visible),
        "alt": round(sun_alt, 1),
        "az": round(sun_az, 1),
        "exclusion_deg": SUN_EXCLUSION_DEG,
        "skipped_azimuths": [round(a, 1) for a in skipped_sun],
    }

    log.info("Complete: %d burst frames, 360-degree profile produced", frame_count)
    log.info("Measured azimuths: %d, interpolated azimuths: %d", measured, interpolated)
    return horizon, confidence, sun_info


def run_offline_frame(
    frame_path,
    az_center,
    alt_center,
    side_crop_frac,
    bottom_crop_frac,
    contrast_abs_min,
    contrast_sigma,
    min_cols_per_deg,
):
    frame_path = Path(frame_path)
    if not frame_path.exists():
        raise FileNotFoundError(frame_path)

    img = np.load(frame_path)
    log.info("Offline frame loaded: %s shape=%s", frame_path, img.shape)

    frame_hz, frame_stats, debug = detect_horizon_in_frame(
        img,
        az_center=az_center,
        alt_center=alt_center,
        side_crop_frac=side_crop_frac,
        bottom_crop_frac=bottom_crop_frac,
        contrast_abs_min=contrast_abs_min,
        contrast_sigma=contrast_sigma,
        min_cols_per_deg=min_cols_per_deg,
    )

    preview_path = frame_path.with_suffix(".ppm")
    write_debug_preview(img, debug, preview_path)

    accum = defaultdict(list)
    for az_deg, alt_deg in frame_hz.items():
        accum_update(accum, az_deg, alt_deg)

    horizon, confidence = fill_gaps_from_accum(accum)

    log.info(
        "Offline detection accepted %d az degrees using %d columns; debug=%s",
        len(frame_hz),
        debug["confident_cols"],
        preview_path.name,
    )
    return horizon, confidence, {"visible_to_seestar": False, "offline_frame": str(frame_path)}


def write_horizon(
    horizon,
    confidence,
    output_path,
    sun_info,
    side_crop_frac,
    bottom_crop_frac,
    contrast_abs_min,
    contrast_sigma,
    min_cols_per_deg,
    manual_overrides,
):
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
                "source": "interpolated",
            }

    for override in manual_overrides:
        profile_int = {int(k): v for k, v in profile.items()}
        confidence_int = {int(k): v for k, v in conf_out.items()}
        profile_int, confidence_int = apply_manual_override(
            profile_int,
            confidence_int,
            override["start_az"],
            override["end_az"],
            override["altitude_deg"],
            override["label"],
        )
        profile = {str(k): v for k, v in profile_int.items()}
        conf_out = {str(k): v for k, v in confidence_int.items()}

    measured = sum(1 for entry in conf_out.values() if entry["source"] == "measured")
    interpolated = sum(1 for entry in conf_out.values() if entry["source"] == "interpolated")
    manual = sum(1 for entry in conf_out.values() if str(entry["source"]).startswith("manual:"))

    payload = {
        "#objective": "Per-degree horizon profile from burst-median wide-camera skyline scan.",
        "source": "camera_scan_v2",
        "camera": "Camera #1 (IMX586, wide-angle)",
        "scanner_version": "2.0.6",
        "method": "burst_median_rooftop_skyline",
        "az_step_deg": AZ_STEP_DEG,
        "burst_frames": BURST_FRAMES,
        "side_crop_frac": side_crop_frac,
        "bottom_crop_frac": bottom_crop_frac,
        "contrast_abs_min": contrast_abs_min,
        "contrast_sigma": contrast_sigma,
        "min_cols_per_deg": min_cols_per_deg,
        "open_sky_default": OPEN_SKY_DEFAULT,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_points": len(profile),
        "measured_points": measured,
        "interpolated_points": interpolated,
        "manual_points": manual,
        "manual_overrides": manual_overrides,
        "sun_info": sun_info,
        "profile": profile,
        "confidence": conf_out,
    }

    output_path.write_text(json.dumps(payload, indent=2))
    csv_path = write_csv(profile, conf_out, output_path)
    plot_path = plot_horizon_profile(profile, conf_out, sun_info, output_path.with_suffix(".png"))

    vals = [float(v) for v in profile.values()]
    log.info("Written: %s", output_path)
    log.info("CSV    : %s", csv_path)
    if plot_path:
        log.info("Plot   : %s", plot_path)
    log.info("Measured: %d  Interpolated: %d  Manual: %d", measured, interpolated, manual)
    log.info("Min: %.1f  Max: %.1f  Mean: %.1f", min(vals), max(vals), sum(vals) / len(vals))


def main():
    parser = argparse.ArgumentParser(
        description="Horizon Scanner v2 — burst-median skyline scan using the wide camera"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ip", type=str, default=None)
    parser.add_argument("--port", type=int, default=32323)
    parser.add_argument("--camera-num", type=int, default=WIDE_CAMERA_NUM_DEFAULT)
    parser.add_argument("--telescope-num", type=int, default=TELESCOPE_NUM_DEFAULT)
    parser.add_argument("--client-id", type=int, default=CLIENT_ID_DEFAULT)
    parser.add_argument("--output", type=str, default=str(HORIZON_FILE))
    parser.add_argument("--balcony-site", action="store_true", help="Use stronger rooftop/balcony tuning")
    parser.add_argument("--west-house", action="store_true", help="Apply known west-side house obstruction override")
    parser.add_argument("--side-crop-frac", type=float, default=None)
    parser.add_argument("--bottom-crop-frac", type=float, default=None)
    parser.add_argument("--contrast-abs-min", type=float, default=None)
    parser.add_argument("--contrast-sigma", type=float, default=None)
    parser.add_argument("--min-cols-per-deg", type=int, default=MIN_COLS_PER_DEG_DEFAULT)
    parser.add_argument("--offline-frame", type=str, default=None, help="Run detection on a saved .npy burst frame")
    parser.add_argument("--offline-az", type=float, default=0.0, help="Center azimuth for offline frame mode")
    parser.add_argument("--offline-alt", type=float, default=ALT_CENTER_DEG, help="Center altitude for offline frame mode")
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

    if args.balcony_site:
        side_crop_frac = SIDE_CROP_FRAC_BALCONY
        bottom_crop_frac = BOTTOM_CROP_FRAC_BALCONY
        contrast_abs_min = CONTRAST_ABS_MIN_BALCONY
        contrast_sigma = CONTRAST_SIGMA_BALCONY
    else:
        side_crop_frac = SIDE_CROP_FRAC_DEFAULT
        bottom_crop_frac = BOTTOM_CROP_FRAC_DEFAULT
        contrast_abs_min = CONTRAST_ABS_MIN_DEFAULT
        contrast_sigma = CONTRAST_SIGMA_DEFAULT

    if args.side_crop_frac is not None:
        side_crop_frac = args.side_crop_frac
    if args.bottom_crop_frac is not None:
        bottom_crop_frac = args.bottom_crop_frac
    if args.contrast_abs_min is not None:
        contrast_abs_min = args.contrast_abs_min
    if args.contrast_sigma is not None:
        contrast_sigma = args.contrast_sigma

    manual_overrides = []
    if args.west_house:
        manual_overrides.append({
            "label": "west_house",
            "start_az": WEST_HOUSE_START_AZ,
            "end_az": WEST_HOUSE_END_AZ,
            "altitude_deg": WEST_HOUSE_ALT_DEG,
        })

    print("+" + "=" * 62 + "+")
    print("|                HORIZON SCANNER v2.0.6                |")
    print("|     Rooftop skyline mode with vectorized detector     |")
    print("+" + "=" * 62 + "+")
    print(f"Target IP          : {ip}:{args.port}")
    print(f"Telescope #        : {args.telescope_num}")
    print(f"Camera #           : {args.camera_num}")
    print(f"Client ID          : {args.client_id}")
    print(f"Az step            : {AZ_STEP_DEG:.1f}°")
    print(f"Vertical FOV       : {FOV_V_DEG:.1f}°")
    print(f"Burst frames       : {BURST_FRAMES}")
    print(f"Balcony tuning     : {args.balcony_site}")
    print(f"West house override: {args.west_house}")
    print(f"Offline frame      : {args.offline_frame or '-'}")
    print(f"Side crop          : {side_crop_frac * 100:.0f}% each side")
    print(f"Bottom crop        : {bottom_crop_frac * 100:.0f}%")
    print(f"Contrast abs min   : {contrast_abs_min:.1f}")
    print(f"Contrast sigma     : {contrast_sigma:.1f}")
    print(f"Min cols / degree  : {args.min_cols_per_deg}")
    print(f"Output             : {args.output}")
    print("")

    if args.sun_visible is None and not args.dry_run and not args.offline_frame:
        ans = input("Can the sun be seen by the Seestar from this site right now? [y/N]: ").strip().lower()
        sun_visible = ans in ("y", "yes")
    else:
        sun_visible = True if args.sun_visible is None else args.sun_visible

    if args.offline_frame:
        horizon, confidence, sun_info = run_offline_frame(
            frame_path=args.offline_frame,
            az_center=args.offline_az,
            alt_center=args.offline_alt,
            side_crop_frac=side_crop_frac,
            bottom_crop_frac=bottom_crop_frac,
            contrast_abs_min=contrast_abs_min,
            contrast_sigma=contrast_sigma,
            min_cols_per_deg=args.min_cols_per_deg,
        )
    else:
        horizon, confidence, sun_info = run_scan(
            ip=ip,
            port=args.port,
            camera_num=args.camera_num,
            telescope_num=args.telescope_num,
            client_id=args.client_id,
            dry_run=args.dry_run,
            sun_visible=sun_visible,
            side_crop_frac=side_crop_frac,
            bottom_crop_frac=bottom_crop_frac,
            contrast_abs_min=contrast_abs_min,
            contrast_sigma=contrast_sigma,
            min_cols_per_deg=args.min_cols_per_deg,
        )

    if not horizon:
        print("\nNo horizon produced.")
        raise SystemExit(1)

    write_horizon(
        horizon,
        confidence,
        Path(args.output),
        sun_info,
        side_crop_frac=side_crop_frac,
        bottom_crop_frac=bottom_crop_frac,
        contrast_abs_min=contrast_abs_min,
        contrast_sigma=contrast_sigma,
        min_cols_per_deg=args.min_cols_per_deg,
        manual_overrides=manual_overrides,
    )

    print("\nDone.")
    print(f"Profile written to: {args.output}")
    print(f"Debug previews in : {FRAME_DIR}")
    print("Use --balcony-site for railing/roofline sites.")
    print("Use --offline-frame on saved .npy bursts while debugging.")


if __name__ == "__main__":
    main()
