#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/horizon_scanner.py
Version: 1.4.2
Objective: Automated horizon profiling using the S30-Pro wide-angle camera
           (Camera #1, IMX586, 63° FOV) via Alpaca REST on port 32323.

v1.0.0: Initial implementation.
v1.0.1: Fixed hardware startup (unpark→slew→track), profile format.
v1.1.0: Code review fixes (abs gradient, auto-expose, overlap, retry, Welford).
v1.2.0: Gradient strength threshold — weak gradients (open sky) now correctly
         default to SCIENCE_FLOOR instead of MAX_HORIZON_ALT. Fixes the false
         50° wall over the back gardens at JO22hj.
v1.3.0: Sun avoidance — refuses to scan at night (sun < 10°), skips azimuth
         positions within the sun exclusion zone to prevent the Seestar's
         sun-protection from killing the session.
v1.4.0: Switched from raw requests to alpyca (official ASCOM Alpaca client).
         Gains automatic ImageBytes negotiation (~8× faster image transfer).
         Fixed: div-by-zero in auto-expose, imageready timeout handling,
         wait_for_slew logging + AbortSlew, NaN propagation in smoothing,
         second-pass wrap-around, azimuth stepping drift, unstable exposure
         adaptation, combined gradient threshold, cleanup on early returns.
v1.4.1: Image transfer hotfix — uses direct Alpaca REST for frame download
         after exposure ready, avoiding hangs in alpyca ImageArray access.
         Adds operator prompt/flags for whether the sun is actually visible
         to the Seestar from this site.
v1.4.2: Constructs camera REST base URL directly from ip/port/device number.
         Fixes "Camera REST base URL unavailable" on systems where alpyca does
         not expose the underlying endpoint.
"""

import argparse
import json
import logging
import math
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests
from alpaca.camera import Camera
from alpaca.telescope import Telescope

from astropy.coordinates import AltAz, EarthLocation, get_sun
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
log = logging.getLogger("horizon_scanner")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WIDE_CAMERA_NUM    = 1
TELESCOPE_NUM      = 0

PLATE_SCALE_WIDE   = 55.0
SENSOR_W           = 2160
SENSOR_H           = 3840
FOV_H_DEG          = SENSOR_W * PLATE_SCALE_WIDE / 3600.0
FOV_V_DEG          = SENSOR_H * PLATE_SCALE_WIDE / 3600.0

AZ_STEP_DEG        = round(FOV_H_DEG * 0.7, 1)
ALT_CENTER_DEG     = 20.0
ALT_HIGH_DEG       = 40.0
SETTLE_SEC         = 5.0

EXPOSE_INITIAL_SEC = 0.001
EXPOSE_MIN_SEC     = 0.00003
EXPOSE_MAX_SEC     = 0.1
TARGET_MEAN_ADU    = 30000
ADU_FLOOR          = 100.0

GAIN_WIDE          = 0

GRADIENT_KERNEL    = 15
MIN_HORIZON_ALT    = -5.0
MAX_HORIZON_ALT    = 50.0
SMOOTH_WINDOW      = 5

GRADIENT_SNR       = 3.0
GRADIENT_ABS_MIN   = 50.0
OPEN_SKY_DEFAULT   = 15.0

SUN_MIN_ALT_DEG    = 10.0
SUN_EXCLUSION_DEG  = FOV_H_DEG / 2 + 15.0
SITE_LON_FALLBACK  = 4.60
SITE_ELEV_M        = 5.0

CLIENT_ID          = 42
ALPACA_TIMEOUT     = 30.0
ALPACA_CAMERA_BASE = None

HORIZON_FILE       = DATA_DIR / "horizon_mask.json"
FRAME_DIR          = DATA_DIR / "horizon_frames"

# ---------------------------------------------------------------------------
# Coordinate conversion
# ---------------------------------------------------------------------------

def altaz_to_radec(az_deg, alt_deg, lat_deg, lst_hours):
    az_rad  = math.radians(az_deg)
    alt_rad = math.radians(alt_deg)
    lat_rad = math.radians(lat_deg)

    sin_dec = (math.sin(alt_rad) * math.sin(lat_rad) +
               math.cos(alt_rad) * math.cos(lat_rad) * math.cos(az_rad))
    dec_rad = math.asin(max(-1, min(1, sin_dec)))
    dec_deg = math.degrees(dec_rad)

    cos_ha = ((math.sin(alt_rad) - math.sin(dec_rad) * math.sin(lat_rad)) /
              max(1e-10, math.cos(dec_rad) * math.cos(lat_rad)))
    cos_ha = max(-1, min(1, cos_ha))
    ha_rad = math.acos(cos_ha)
    if math.sin(az_rad) > 0:
        ha_rad = 2 * math.pi - ha_rad
    ha_hours = math.degrees(ha_rad) / 15.0

    ra_hours = (lst_hours - ha_hours) % 24.0
    return ra_hours, dec_deg

# ---------------------------------------------------------------------------
# Sun position
# ---------------------------------------------------------------------------

def get_sun_altaz(lat_deg, lon_deg, elev_m=SITE_ELEV_M):
    loc = EarthLocation(lat=lat_deg * u.deg, lon=lon_deg * u.deg,
                        height=elev_m * u.m)
    now = Time.now()
    frame = AltAz(obstime=now, location=loc)
    sun = get_sun(now).transform_to(frame)
    return float(sun.alt.deg), float(sun.az.deg)

def az_distance(a, b):
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)

# ---------------------------------------------------------------------------
# Hardware helpers
# ---------------------------------------------------------------------------

def wait_for_slew(telescope, timeout=60.0):
    deadline = time.monotonic() + timeout
    warned = False
    while time.monotonic() < deadline:
        try:
            if not telescope.Slewing:
                return True
        except Exception as e:
            if not warned:
                log.warning(f"  Slew poll error: {e}")
                warned = True
        time.sleep(1)
    try:
        telescope.AbortSlew()
        log.warning("  Slew timed out — AbortSlew sent")
    except Exception:
        pass
    return False

def _next_txid(camera):
    tx = getattr(camera, "_hv_txid", 0) + 1
    camera._hv_txid = tx
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
            log.info("  Download transport: ImageBytes")
            return _parse_imagebytes(r.content)
    except Exception as e:
        log.warning(f"  ImageBytes fetch failed; falling back to JSON ImageArray: {e}")

    log.info("  Download transport: JSON ImageArray")
    params = {
        "ClientID": CLIENT_ID,
        "ClientTransactionID": _next_txid(camera),
    }
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

def capture_image(camera, expose_sec, timeout=60, download_timeout=20):
    try:
        log.info(f"  Exposure start: {expose_sec:.4f}s")
        camera.StartExposure(expose_sec, True)
    except Exception as e:
        raise RuntimeError(f"StartExposure failed: {e}") from e

    deadline = time.monotonic() + timeout
    ready = False
    last_ready_error = None

    while time.monotonic() < deadline:
        try:
            ready = bool(camera.ImageReady)
            if ready:
                break
        except Exception as e:
            if last_ready_error is None or str(e) != str(last_ready_error):
                log.warning(f"  ImageReady poll error: {e}")
            last_ready_error = e
        time.sleep(0.5)

    if not ready:
        try:
            camera.AbortExposure()
            log.warning("  Exposure timed out — AbortExposure sent")
        except Exception:
            pass
        detail = f" (last ImageReady error: {last_ready_error})" if last_ready_error else ""
        raise RuntimeError(f"Image not ready after {timeout:.1f}s{detail}")

    log.info("  Image ready; downloading frame...")
    img = download_image(camera, timeout=download_timeout)
    log.info(f"  Download complete: shape={img.shape} dtype={img.dtype}")
    return img

def disconnect_safely(camera, telescope):
    for dev in (camera, telescope):
        if dev is None:
            continue
        try:
            dev.Connected = False
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Auto-exposure
# ---------------------------------------------------------------------------

def auto_expose(camera, current_sec):
    try:
        img = capture_image(camera, current_sec, timeout=30, download_timeout=30)
        mean_adu = max(float(img.mean()), ADU_FLOOR)
        new_sec = current_sec * (TARGET_MEAN_ADU / mean_adu) ** 0.5
        new_sec = max(EXPOSE_MIN_SEC, min(EXPOSE_MAX_SEC, new_sec))
        log.info(f"  Auto-exposure: mean={mean_adu:.0f} ADU, "
                 f"{current_sec:.4f}s -> {new_sec:.4f}s")
        return new_sec
    except Exception as e:
        log.warning(f"  Auto-exposure failed: {e}")
        return current_sec

# ---------------------------------------------------------------------------
# Image analysis
# ---------------------------------------------------------------------------

def detect_horizon_in_frame(img, az_center, alt_center):
    h, w = img.shape[:2]

    if img.ndim == 3:
        img = img[:, :, 1]

    img_f = img.astype(np.float64)

    grad = np.zeros_like(img_f)
    k = GRADIENT_KERNEL
    for col in range(w):
        column = img_f[:, col]
        if len(column) > k:
            smoothed = np.convolve(column, np.ones(k) / k, mode="same")
        else:
            smoothed = column
        grad[:, col] = np.abs(np.gradient(smoothed))

    horizon_rows = np.zeros(w, dtype=np.float64)
    is_confident = np.ones(w, dtype=bool)
    alt_per_pixel = FOV_V_DEG / h

    for col in range(w):
        g = grad[:, col]
        min_row = int(max(0, h / 2 - (alt_center - MIN_HORIZON_ALT) / alt_per_pixel))
        max_row = int(min(h, h / 2 + (MAX_HORIZON_ALT - alt_center) / alt_per_pixel))

        if min_row >= max_row:
            horizon_rows[col] = h / 2
            is_confident[col] = False
            continue

        search = g[min_row:max_row]
        if len(search) == 0:
            horizon_rows[col] = h / 2
            is_confident[col] = False
            continue

        peak_val = np.max(search)
        median_val = np.median(search)

        is_weak_relative = (median_val > 0 and peak_val < GRADIENT_SNR * median_val)
        is_weak_absolute = peak_val < GRADIENT_ABS_MIN

        if is_weak_relative and is_weak_absolute:
            is_confident[col] = False
            target_row = h / 2 - (OPEN_SKY_DEFAULT - alt_center) / alt_per_pixel
            horizon_rows[col] = max(0, min(h - 1, target_row))
        else:
            peak_idx = np.argmax(search) + min_row
            horizon_rows[col] = peak_idx
            is_confident[col] = True

    try:
        from scipy.ndimage import median_filter
        confident_rows = horizon_rows.copy()
        confident_rows[~is_confident] = np.nan

        if np.any(is_confident):
            mask = np.isnan(confident_rows)
            idx = np.where(~mask, np.arange(len(mask)), 0)
            np.maximum.accumulate(idx, out=idx)
            confident_rows = confident_rows[idx]
            horizon_rows_smooth = median_filter(confident_rows, size=SMOOTH_WINDOW)
        else:
            target_row = h / 2 - (OPEN_SKY_DEFAULT - alt_center) / alt_per_pixel
            horizon_rows_smooth = np.full(w, target_row)
    except ImportError:
        kernel = np.ones(SMOOTH_WINDOW) / SMOOTH_WINDOW
        horizon_rows_smooth = np.convolve(horizon_rows, kernel, mode="same")

    az_per_pixel = FOV_H_DEG / w
    result = {}
    conf_count = 0

    for col in range(w):
        az_offset = (col - w / 2) * az_per_pixel
        az = (az_center + az_offset) % 360.0
        az_int = int(round(az)) % 360

        row = horizon_rows_smooth[col]
        alt_offset = (h / 2 - row) * alt_per_pixel
        alt = alt_center + alt_offset
        alt = max(MIN_HORIZON_ALT, min(MAX_HORIZON_ALT, alt))

        if is_confident[col]:
            conf_count += 1

        if az_int not in result or alt > result[az_int]:
            result[az_int] = round(alt, 1)

    pct = conf_count / w * 100 if w > 0 else 0
    log.info(f"  Gradient confidence: {conf_count}/{w} columns ({pct:.0f}%) had real boundaries")
    return result

# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

def run_scan(ip, port, dry_run=False, sun_visible=True):
    global ALPACA_CAMERA_BASE
    ALPACA_CAMERA_BASE = f"http://{ip}:{port}/api/v1/camera/{WIDE_CAMERA_NUM}"

    positions = np.arange(0, 360, AZ_STEP_DEG).tolist()
    n_positions = len(positions)

    log.info("=" * 60)
    log.info("HORIZON SCANNER v1.4.2")
    log.info(f"Camera #1 (IMX586, 63° FOV) — Az step {AZ_STEP_DEG:.1f}°")
    log.info(f"Target: {ip}:{port}")
    log.info(f"Gradient SNR threshold: {GRADIENT_SNR}x (abs min: {GRADIENT_ABS_MIN})")
    log.info(f"Open sky default: {OPEN_SKY_DEFAULT}°")
    log.info("=" * 60)

    FRAME_DIR.mkdir(parents=True, exist_ok=True)

    if dry_run:
        log.info("DRY RUN — synthetic horizon")
        horizon = {}
        confidence = {}
        for az in range(360):
            if 240 <= az <= 300:
                alt = 25.0
            elif 150 <= az <= 210:
                alt = 18.0
            else:
                alt = 15.0
            horizon[az] = alt
            confidence[az] = {"mean": alt, "var": 0.0, "n": 1}
        return horizon, confidence, {}

    addr = f"{ip}:{port}"
    telescope = Telescope(addr, TELESCOPE_NUM)
    camera = Camera(addr, WIDE_CAMERA_NUM)

    try:
        telescope.Connected = True
        camera.Connected = True
    except Exception as e:
        log.error(f"Connection failed: {e}")
        disconnect_safely(camera, telescope)
        return {}, {}, {}

    try:
        camera.Gain = GAIN_WIDE
    except Exception as e:
        log.warning(f"Gain: {e}")

    try:
        telescope.Unpark()
        log.info("Unpark — arm opening...")
        time.sleep(5)
    except Exception as e:
        log.warning(f"Unpark: {e}")

    try:
        lat = telescope.SiteLatitude
        lst = telescope.SiderealTime
        log.info(f"Site: lat={lat:.2f}° LST={lst:.3f}h")
    except Exception as e:
        log.error(f"Site params: {e}")
        disconnect_safely(camera, telescope)
        return {}, {}, {}

    try:
        lon = telescope.SiteLongitude
    except Exception:
        lon = SITE_LON_FALLBACK
        log.warning(f"Could not read SiteLongitude, using fallback {lon}")

    sun_alt, sun_az = get_sun_altaz(lat, lon)
    log.info(f"Sun: Alt={sun_alt:.1f}° Az={sun_az:.1f}°")

    if sun_visible:
        if sun_alt < SUN_MIN_ALT_DEG:
            log.error(f"Sun altitude {sun_alt:.1f}° < {SUN_MIN_ALT_DEG}° — too low for gradient detection. Refusing to scan.")
            log.error("Re-run during daytime with sun well above the horizon.")
            disconnect_safely(camera, telescope)
            return {}, {}, {}
        log.info(f"Sun exclusion zone: +/-{SUN_EXCLUSION_DEG:.0f}° around Az {sun_az:.0f}°")
    else:
        log.info("Sun visibility override: operator says the sun is blocked from the Seestar")
        log.info("Sun avoidance disabled for this scan")

    skipped_sun = []

    log.info("Slewing to safe position (Az=180° Alt=30°)...")
    try:
        ra, dec = altaz_to_radec(180.0, 30.0, lat, lst)
        telescope.SlewToCoordinatesAsync(ra, dec)
        wait_for_slew(telescope, timeout=30)
        time.sleep(3)
    except Exception as e:
        log.warning(f"Initial slew: {e}")

    try:
        telescope.Tracking = True
        log.info("Tracking enabled")
    except Exception as e:
        log.warning(f"Tracking: {e}")

    log.info("Calibrating exposure...")
    expose_sec = auto_expose(camera, EXPOSE_INITIAL_SEC)

    accum = {}

    def accum_update(az_int, alt):
        if az_int not in accum:
            accum[az_int] = {"n": 0, "mean": 0.0, "m2": 0.0}
        a = accum[az_int]
        a["n"] += 1
        delta = alt - a["mean"]
        a["mean"] += delta / a["n"]
        delta2 = alt - a["mean"]
        a["m2"] += delta * delta2

    frame_count = 0

    for i, az in enumerate(positions):
        alt = ALT_CENTER_DEG

        log.info(f"\n--- Position {i+1}/{n_positions}: Az={az:.1f}° Alt={alt:.0f}° ---")

        if sun_visible and az_distance(az, sun_az) < SUN_EXCLUSION_DEG:
            log.warning(f"  SKIP — Az {az:.0f}° within sun exclusion zone (sun at Az {sun_az:.0f}°)")
            skipped_sun.append(az)
            continue

        try:
            lst = telescope.SiderealTime
        except Exception:
            pass

        try:
            ra_h, dec_d = altaz_to_radec(az, alt, lat, lst)
        except Exception as e:
            log.error(f"  Coord: {e}")
            continue

        try:
            telescope.SlewToCoordinatesAsync(ra_h, dec_d)
            if not wait_for_slew(telescope):
                log.warning("  Slew timeout — skipping position")
                continue
            time.sleep(SETTLE_SEC)
        except Exception as e:
            log.error(f"  Slew: {e}")
            continue

        try:
            actual_alt = telescope.Altitude
            actual_az = telescope.Azimuth
            log.info(f"  Actual: Az={actual_az:.1f}° Alt={actual_alt:.1f}°")
        except Exception:
            actual_az, actual_alt = az, alt

        try:
            img = capture_image(camera, expose_sec)
            log.info(f"  Image {img.shape} mean={img.mean():.0f}")

            mean_adu = max(float(img.mean()), ADU_FLOOR)
            expose_sec = expose_sec * (TARGET_MEAN_ADU / mean_adu) ** 0.5
            expose_sec = max(EXPOSE_MIN_SEC, min(EXPOSE_MAX_SEC, expose_sec))
        except Exception as e:
            log.error(f"  Expose/download: {e}")
            continue

        try:
            tag = f"{actual_az:05.1f}".replace(".", "_")
            np.save(FRAME_DIR / f"horizon_az{tag}.npy", img)
            frame_count += 1
        except Exception:
            pass

        try:
            frame_hz = detect_horizon_in_frame(img, actual_az, actual_alt)
            log.info(f"  Horizon: {len(frame_hz)} degrees")
            for az_deg, alt_deg in frame_hz.items():
                accum_update(az_deg, alt_deg)
        except Exception as e:
            log.error(f"  Detection: {e}")

    tall_sectors = [az for az, a in accum.items() if a["mean"] > ALT_CENTER_DEG + 10]
    if tall_sectors:
        tall_azimuths = sorted(set(
            round(az_int / AZ_STEP_DEG) * AZ_STEP_DEG % 360
            for az_int in tall_sectors
        ))
        log.info(f"\nSecond pass: {len(tall_azimuths)} tall-obstruction positions at {ALT_HIGH_DEG}° center")

        for az in tall_azimuths:
            if sun_visible and az_distance(az, sun_az) < SUN_EXCLUSION_DEG:
                log.warning(f"  High pass SKIP Az={az:.0f}° — sun exclusion zone")
                continue
            try:
                lst = telescope.SiderealTime
                ra_h, dec_d = altaz_to_radec(az, ALT_HIGH_DEG, lat, lst)
                telescope.SlewToCoordinatesAsync(ra_h, dec_d)
                if not wait_for_slew(telescope):
                    log.warning(f"  High pass slew timeout Az={az:.0f}° — skipping")
                    continue
                time.sleep(SETTLE_SEC)
                actual_alt = telescope.Altitude
                actual_az = telescope.Azimuth
                img = capture_image(camera, expose_sec)
                frame_hz = detect_horizon_in_frame(img, actual_az, actual_alt)
                for az_deg, alt_deg in frame_hz.items():
                    accum_update(az_deg, alt_deg)
                log.info(f"  High pass Az={actual_az:.0f}°: {len(frame_hz)} deg")
            except Exception as e:
                log.warning(f"  High pass Az={az:.0f}°: {e}")

    horizon = {}
    confidence = {}
    for az_int, a in accum.items():
        horizon[az_int] = round(a["mean"], 1)
        var = a["m2"] / a["n"] if a["n"] > 1 else 0.0
        confidence[az_int] = {
            "mean": round(a["mean"], 1),
            "var": round(var, 2),
            "n": a["n"],
        }

    disconnect_safely(camera, telescope)

    sun_info = {
        "visible_to_seestar": bool(sun_visible),
        "alt": round(sun_alt, 1),
        "az": round(sun_az, 1),
        "exclusion_deg": SUN_EXCLUSION_DEG,
        "skipped_azimuths": [round(a, 1) for a in skipped_sun],
    }

    log.info(f"\nComplete: {frame_count} frames, {len(horizon)} degrees")
    if skipped_sun:
        log.info(f"  Sun-skipped positions: {len(skipped_sun)} (Az {min(skipped_sun):.0f}°-{max(skipped_sun):.0f}°, will be interpolated by fill_gaps)")
    return horizon, confidence, sun_info

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def fill_gaps(horizon):
    full = {}
    known = sorted(horizon.keys())
    if not known:
        return {az: OPEN_SKY_DEFAULT for az in range(360)}

    for az in range(360):
        if az in horizon:
            full[az] = horizon[az]
        else:
            below = [k for k in known if k <= az]
            above = [k for k in known if k > az]
            if not above and known:
                above = [known[0] + 360]
            if not below and known:
                below = [known[-1] - 360]
            if below and above:
                k_lo, k_hi = below[-1], above[0]
                k_lo_r = k_lo % 360 if k_lo < 0 else k_lo
                k_hi_r = k_hi % 360 if k_hi >= 360 else k_hi
                span = k_hi - k_lo
                if span > 0:
                    frac = (az - k_lo) / span
                    full[az] = round(
                        horizon.get(k_lo_r, OPEN_SKY_DEFAULT) * (1 - frac) +
                        horizon.get(k_hi_r, OPEN_SKY_DEFAULT) * frac,
                        1,
                    )
                else:
                    full[az] = horizon.get(k_lo_r, OPEN_SKY_DEFAULT)
            else:
                full[az] = OPEN_SKY_DEFAULT
    return full

def write_horizon(horizon, confidence, output_path, sun_info):
    output_path.parent.mkdir(parents=True, exist_ok=True)

    profile = {str(az): round(horizon.get(az, OPEN_SKY_DEFAULT), 1) for az in range(360)}
    conf_out = {}
    for az in range(360):
        if az in confidence:
            conf_out[str(az)] = confidence[az]
        else:
            conf_out[str(az)] = {
                "mean": horizon.get(az, OPEN_SKY_DEFAULT),
                "var": 0.0,
                "n": 0,
            }

    payload = {
        "#objective": "Per-degree horizon profile from wide-angle camera scan.",
        "source": "camera_scan",
        "camera": "Camera #1 (IMX586, 63 FOV)",
        "scanner_version": "1.4.2",
        "gradient_snr_threshold": GRADIENT_SNR,
        "gradient_abs_min": GRADIENT_ABS_MIN,
        "open_sky_default": OPEN_SKY_DEFAULT,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_points": len(profile),
        "sun_info": sun_info,
        "profile": profile,
        "confidence": conf_out,
    }

    output_path.write_text(json.dumps(payload, indent=2))
    vals = [float(v) for v in profile.values()]
    log.info(f"Written: {output_path}")
    log.info(f"  Points: {len(profile)}")
    log.info(f"  Min: {min(vals):.1f}  Max: {max(vals):.1f}  Mean: {sum(vals) / len(vals):.1f}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Horizon Scanner v1.4.2 — direct Alpaca download + sun visibility prompt"
    )
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ip", type=str, default=None)
    parser.add_argument("--port", type=int, default=32323)
    parser.add_argument("--output", type=str, default=str(HORIZON_FILE))
    parser.add_argument("--sun-visible", dest="sun_visible", action="store_true",
                        help="Enable sun avoidance because the sun can be seen by the Seestar")
    parser.add_argument("--sun-blocked", dest="sun_visible", action="store_false",
                        help="Disable sun avoidance because the sun is physically blocked")
    parser.set_defaults(sun_visible=None)
    args = parser.parse_args()

    if args.ip:
        ip = args.ip
    else:
        cfg = load_config()
        seestars = cfg.get("seestars", [{}])
        ip = seestars[0].get("ip", "192.168.178.251")

    n_pos = int(math.ceil(360 / AZ_STEP_DEG))

    print("+" + "=" * 58 + "+")
    print("|  SeeVar Horizon Scanner v1.4.2                         |")
    print("|  Direct Alpaca download + sun visibility prompt        |")
    print(f"|  Target: {ip}:{args.port}".ljust(59) + "|")
    print("+" + "=" * 58 + "+")
    print()
    print(f"  Az step: {AZ_STEP_DEG:.1f}° (70% FOV overlap)")
    print(f"  Positions: {n_pos}")
    print(f"  Gradient SNR: {GRADIENT_SNR}x")
    print(f"  Open sky default: {OPEN_SKY_DEFAULT}°")
    print()

    if args.sun_visible is None:
        if args.auto or args.dry_run:
            sun_visible = True
        else:
            ans = input("  Will the sun be visible to the Seestar during this scan? [y/N] ").strip().lower()
            sun_visible = ans in ("y", "yes")
    else:
        sun_visible = args.sun_visible

    print(f"  Sun visible to Seestar: {'yes' if sun_visible else 'no, blocked'}")
    print()

    if not args.auto and not args.dry_run:
        ans = input("  Start scan? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("  Cancelled.")
            return

    horizon_raw, confidence, sun_info = run_scan(
        ip,
        args.port,
        dry_run=args.dry_run,
        sun_visible=sun_visible,
    )
    if not horizon_raw:
        print("\n  No data. Check errors above.")
        return

    horizon_full = fill_gaps(horizon_raw)
    write_horizon(horizon_full, confidence, Path(args.output), sun_info)
    print(f"\n  Done. Output: {args.output}")
    print("  horizon.py will use this on next flight.")

if __name__ == "__main__":
    main()
