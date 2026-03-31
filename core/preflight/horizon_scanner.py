#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/horizon_scanner.py
Version: 1.0.0
Objective: Automated horizon profiling using the S30-Pro wide-angle camera
           (Camera #1, IMX586, 63° FOV) via Alpaca REST on port 32323.
           Scans 360° in azimuth during daytime, detects the sky-ground
           boundary in each frame, and writes data/horizon_mask.json.

Usage:
    python3 core/preflight/horizon_scanner.py              # interactive
    python3 core/preflight/horizon_scanner.py --auto       # no prompts
    python3 core/preflight/horizon_scanner.py --dry-run    # simulate only

The scan takes ~12 minutes (15 positions × ~50s each).
Run during daytime with clear sky for best contrast.
The telescope must be level and the arm open.

Output:
    data/horizon_mask.json — per-degree azimuth profile (0°–359°)
    data/horizon_frames/   — raw wide-angle JPEG/FITS per position (diagnostic)
"""

import argparse
import json
import logging
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import requests

# Project setup
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

# Wide-angle camera specs (IMX586 in S30-Pro, binned to 3840×2160)
WIDE_CAMERA_NUM    = 1       # Alpaca Camera #1
WIDE_FOCUSER_NUM   = 1       # Alpaca Focuser #1
TELESCOPE_NUM      = 0

# FOV geometry (sensor mounted vertically)
# With 2×2 binning: effective 1.6µm pixels at 6mm FL
# Plate scale ≈ 55 arcsec/pixel
PLATE_SCALE_WIDE   = 55.0    # arcsec/pixel (approximate)
SENSOR_W           = 2160    # pixels (horizontal — short axis, mounted vertical)
SENSOR_H           = 3840    # pixels (vertical — long axis)
FOV_H_DEG          = SENSOR_W * PLATE_SCALE_WIDE / 3600.0  # ~33°
FOV_V_DEG          = SENSOR_H * PLATE_SCALE_WIDE / 3600.0  # ~59°

# Scan parameters
AZ_STEP_DEG        = 25.0    # azimuth step between frames
AZ_START           = 0.0     # start azimuth
AZ_END             = 360.0   # full circle
ALT_CENTER_DEG     = 20.0    # altitude to center frames on
SETTLE_SEC         = 5.0     # post-slew settle
EXPOSE_SEC         = 0.001   # very short daytime exposure (1ms)
GAIN_WIDE          = 0       # minimum gain for daytime

# Edge detection
GRADIENT_KERNEL    = 15      # Sobel-like vertical gradient kernel size
MIN_HORIZON_ALT    = -5.0    # degrees — nothing below this is physical
MAX_HORIZON_ALT    = 45.0    # degrees — nothing above this is a horizon
SMOOTH_WINDOW      = 5       # median filter width for per-column horizon

# Alpaca
CLIENT_ID          = 43      # Distinct from pilot's 42
ALPACA_TIMEOUT     = 10.0

# Output
HORIZON_FILE       = DATA_DIR / "horizon_mask.json"
FRAME_DIR          = DATA_DIR / "horizon_frames"


# ---------------------------------------------------------------------------
# Alpaca helpers (lightweight — no pilot.py dependency for standalone use)
# ---------------------------------------------------------------------------

class AlpacaDevice:
    """Minimal Alpaca REST client for horizon scanner."""
    def __init__(self, ip: str, port: int, device_type: str, device_num: int):
        self.base = f"http://{ip}:{port}/api/v1/{device_type}/{device_num}"
        self._tx = 0

    def get(self, prop: str, timeout: float = ALPACA_TIMEOUT):
        self._tx += 1
        r = requests.get(f"{self.base}/{prop}",
                         params={"ClientID": CLIENT_ID,
                                 "ClientTransactionID": self._tx},
                         timeout=timeout)
        d = r.json()
        if d.get("ErrorNumber", 0):
            raise RuntimeError(f"GET {prop}: {d.get('ErrorMessage','')}")
        return d.get("Value")

    def put(self, method: str, timeout: float = ALPACA_TIMEOUT, **kwargs):
        self._tx += 1
        payload = {"ClientID": CLIENT_ID, "ClientTransactionID": self._tx}
        payload.update(kwargs)
        r = requests.put(f"{self.base}/{method}", data=payload, timeout=timeout)
        d = r.json()
        if d.get("ErrorNumber", 0):
            raise RuntimeError(f"PUT {method}: {d.get('ErrorMessage','')}")
        return d.get("Value")

    def connect(self):
        self.put("connected", Connected="true")

    def disconnect(self):
        try: self.put("connected", Connected="false")
        except: pass


# ---------------------------------------------------------------------------
# Image analysis — sky-ground boundary detection
# ---------------------------------------------------------------------------

def detect_horizon_in_frame(img: np.ndarray, az_center: float,
                            alt_center: float) -> dict:
    """
    Detect the sky-ground boundary in a wide-angle frame.

    Args:
        img: 2D numpy array (height × width), grayscale or green channel
        az_center: azimuth at frame center (degrees)
        alt_center: altitude at frame center (degrees)

    Returns:
        dict mapping azimuth (int degrees) → horizon altitude (float degrees)
    """
    h, w = img.shape[:2]

    # If colour (3D), convert to grayscale using green channel
    if img.ndim == 3:
        img = img[:, :, 1]  # green channel

    # Convert to float
    img_f = img.astype(np.float64)

    # Vertical gradient — sky is typically brighter than ground in daytime
    # Compute column-wise vertical gradient
    # Positive gradient = transition from dark (ground) to bright (sky)
    grad = np.zeros_like(img_f)
    k = GRADIENT_KERNEL
    for col in range(w):
        column = img_f[:, col]
        # Smooth the column first
        if len(column) > k:
            smoothed = np.convolve(column, np.ones(k)/k, mode='same')
        else:
            smoothed = column
        # Gradient (positive = getting brighter going up = sky above)
        grad[:, col] = np.gradient(smoothed)

    # For each column, find the horizon row
    # The horizon is where the strongest positive gradient occurs
    # (transition from dark ground to bright sky)
    # We scan from bottom up looking for the steepest brightness jump
    horizon_rows = np.zeros(w, dtype=np.float64)

    for col in range(w):
        g = grad[:, col]
        # Only look in the plausible altitude range
        alt_per_pixel = FOV_V_DEG / h
        min_row = int(max(0, h/2 - (alt_center - MIN_HORIZON_ALT) / alt_per_pixel))
        max_row = int(min(h, h/2 + (MAX_HORIZON_ALT - alt_center) / alt_per_pixel))

        if min_row >= max_row:
            horizon_rows[col] = h / 2
            continue

        # Find the row with maximum gradient in the search range
        search = g[min_row:max_row]
        if len(search) == 0:
            horizon_rows[col] = h / 2
            continue

        peak_idx = np.argmax(search) + min_row
        horizon_rows[col] = peak_idx

    # Median filter to smooth out noise
    from scipy.ndimage import median_filter
    horizon_rows_smooth = median_filter(horizon_rows, size=SMOOTH_WINDOW)

    # Map pixel coordinates to az/alt
    # Column → azimuth offset from center
    # Row → altitude (top of image = high altitude, bottom = low)
    az_per_pixel = FOV_H_DEG / w
    alt_per_pixel = FOV_V_DEG / h

    result = {}
    for col in range(w):
        az_offset = (col - w/2) * az_per_pixel
        az = (az_center + az_offset) % 360.0
        az_int = int(round(az)) % 360

        # Row 0 = top = highest altitude, Row h = bottom = lowest
        row = horizon_rows_smooth[col]
        alt_offset = (h/2 - row) * alt_per_pixel
        alt = alt_center + alt_offset

        # Clamp
        alt = max(MIN_HORIZON_ALT, min(MAX_HORIZON_ALT, alt))

        # If multiple pixels map to same degree, keep the highest horizon
        if az_int not in result or alt > result[az_int]:
            result[az_int] = round(alt, 1)

    return result


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

def run_scan(ip: str, port: int, dry_run: bool = False) -> dict:
    """
    Execute full 360° horizon scan using wide-angle Camera #1.

    Returns dict: {0: alt, 1: alt, ..., 359: alt}
    """
    log.info("=" * 60)
    log.info("HORIZON SCANNER v1.0.0")
    log.info("Wide-angle Camera #1 (IMX586, 63° FOV)")
    log.info(f"Target: {ip}:{port}")
    log.info(f"Scan: {AZ_START}°–{AZ_END}° in {AZ_STEP_DEG}° steps")
    log.info(f"Center altitude: {ALT_CENTER_DEG}°")
    log.info(f"Exposure: {EXPOSE_SEC}s, gain {GAIN_WIDE}")
    log.info("=" * 60)

    n_positions = int(math.ceil((AZ_END - AZ_START) / AZ_STEP_DEG))
    log.info(f"Positions: {n_positions}")
    log.info(f"Estimated time: {n_positions * 50:.0f}s ({n_positions * 50 / 60:.1f} min)")

    FRAME_DIR.mkdir(parents=True, exist_ok=True)

    if dry_run:
        log.info("DRY RUN — generating synthetic horizon")
        horizon = {}
        for az in range(360):
            # Fake profile: buildings west, clear south
            if 240 <= az <= 300:
                horizon[az] = 25.0  # building
            elif 150 <= az <= 210:
                horizon[az] = 12.0  # low treeline south
            else:
                horizon[az] = 15.0  # default
        return horizon

    # Connect devices
    telescope = AlpacaDevice(ip, port, "telescope", TELESCOPE_NUM)
    camera    = AlpacaDevice(ip, port, "camera", WIDE_CAMERA_NUM)

    telescope.connect()
    camera.connect()

    # Set camera for daytime: minimum gain, short exposure
    try:
        camera.put("gain", Gain=str(GAIN_WIDE))
        log.info(f"Wide camera gain set to {GAIN_WIDE}")
    except Exception as e:
        log.warning(f"Gain set: {e}")

    # Unpark if needed
    try:
        if telescope.get("atpark"):
            telescope.put("unpark")
            time.sleep(3)
    except Exception as e:
        log.warning(f"Unpark: {e}")

    # Enable tracking (needed for slew)
    telescope.put("tracking", Tracking="true")

    # Build horizon from all frames
    all_horizon = {}
    frame_count = 0

    for i in range(n_positions):
        az = AZ_START + i * AZ_STEP_DEG
        alt = ALT_CENTER_DEG

        log.info(f"\n--- Position {i+1}/{n_positions}: Az={az:.0f}° Alt={alt:.0f}° ---")

        # Convert Az/Alt to RA/Dec for slew
        # We need the telescope's current sidereal time for this
        try:
            lst = telescope.get("siderealtime")  # hours
            lat = telescope.get("sitelatitude")   # degrees

            # Alt/Az → RA/Dec conversion
            az_rad = math.radians(az)
            alt_rad = math.radians(alt)
            lat_rad = math.radians(lat)

            sin_dec = (math.sin(alt_rad) * math.sin(lat_rad) +
                       math.cos(alt_rad) * math.cos(lat_rad) * math.cos(az_rad))
            dec_rad = math.asin(max(-1, min(1, sin_dec)))
            dec_deg = math.degrees(dec_rad)

            cos_ha = ((math.sin(alt_rad) - math.sin(dec_rad) * math.sin(lat_rad)) /
                      (math.cos(dec_rad) * math.cos(lat_rad)))
            cos_ha = max(-1, min(1, cos_ha))
            ha_rad = math.acos(cos_ha)
            if math.sin(az_rad) > 0:
                ha_rad = 2 * math.pi - ha_rad
            ha_hours = math.degrees(ha_rad) / 15.0

            ra_hours = (lst - ha_hours) % 24.0

            log.info(f"  Converted: RA={ra_hours:.3f}h Dec={dec_deg:.2f}°")

        except Exception as e:
            log.error(f"  Coordinate conversion failed: {e}")
            continue

        # Slew
        try:
            telescope.put("slewtocoordinatesasync",
                          RightAscension=str(ra_hours),
                          Declination=str(dec_deg))

            # Wait for slew
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if not telescope.get("slewing"):
                    break
                time.sleep(1)

            time.sleep(SETTLE_SEC)
            log.info(f"  Slew complete, settled")

        except Exception as e:
            log.error(f"  Slew failed: {e}")
            continue

        # Read actual position
        try:
            actual_alt = telescope.get("altitude")
            actual_az = telescope.get("azimuth")
            log.info(f"  Actual position: Az={actual_az:.1f}° Alt={actual_alt:.1f}°")
        except Exception:
            actual_az = az
            actual_alt = alt

        # Expose with wide camera
        try:
            camera.put("startexposure",
                        Duration=str(EXPOSE_SEC),
                        Light="true")

            # Wait for image
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    if camera.get("imageready"):
                        break
                except Exception:
                    pass
                time.sleep(0.5)

            # Download
            log.info(f"  Downloading wide-angle frame...")
            t0 = time.monotonic()
            params = {"ClientID": CLIENT_ID, "ClientTransactionID": 9999}
            r = requests.get(f"{camera.base}/imagearray",
                             params=params, timeout=300)
            data = r.json()
            if data.get("ErrorNumber", 0):
                log.error(f"  Download error: {data.get('ErrorMessage','')}")
                continue

            img = np.array(data["Value"], dtype=np.int32)
            dl_time = time.monotonic() - t0
            log.info(f"  Downloaded {img.shape} in {dl_time:.1f}s "
                     f"(min={img.min()} max={img.max()})")

        except Exception as e:
            log.error(f"  Exposure/download failed: {e}")
            continue

        # Save diagnostic frame
        try:
            safe_az = f"{actual_az:05.1f}".replace(".", "_")
            np.save(FRAME_DIR / f"horizon_az{safe_az}.npy", img)
            frame_count += 1
        except Exception:
            pass

        # Detect horizon in this frame
        try:
            frame_horizon = detect_horizon_in_frame(
                img, actual_az, actual_alt)
            log.info(f"  Detected horizon for {len(frame_horizon)} azimuth degrees")

            # Merge into master
            for az_deg, alt_deg in frame_horizon.items():
                if az_deg not in all_horizon:
                    all_horizon[az_deg] = alt_deg
                else:
                    # Average overlapping regions
                    all_horizon[az_deg] = (all_horizon[az_deg] + alt_deg) / 2.0

        except Exception as e:
            log.error(f"  Horizon detection failed: {e}")

    # Disconnect
    try:
        camera.disconnect()
        telescope.disconnect()
    except Exception:
        pass

    log.info(f"\nScan complete: {frame_count} frames, "
             f"{len(all_horizon)} azimuth degrees profiled")

    return all_horizon


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def fill_gaps(horizon: dict) -> dict:
    """Fill any missing azimuth degrees by interpolation."""
    full = {}
    known = sorted(horizon.keys())

    if not known:
        # No data — return flat default
        return {az: 15.0 for az in range(360)}

    for az in range(360):
        if az in horizon:
            full[az] = horizon[az]
        else:
            # Find nearest known values
            below = [k for k in known if k <= az]
            above = [k for k in known if k >= az]

            if below and above:
                k_lo = below[-1]
                k_hi = above[0]
                if k_lo == k_hi:
                    full[az] = horizon[k_lo]
                else:
                    # Linear interpolation
                    frac = (az - k_lo) / (k_hi - k_lo)
                    full[az] = round(
                        horizon[k_lo] * (1 - frac) + horizon[k_hi] * frac, 1)
            elif below:
                full[az] = horizon[below[-1]]
            elif above:
                full[az] = horizon[above[0]]
            else:
                full[az] = 15.0

    return full


def write_horizon(horizon: dict, output_path: Path):
    """Write horizon_mask.json in SeeVar standard format."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # SeeVar format: list of {az: int, min_alt: float} for each degree
    profile = []
    for az in range(360):
        alt = horizon.get(az, 15.0)
        profile.append({"az": az, "min_alt": round(alt, 1)})

    payload = {
        "#objective": "Per-degree horizon profile from wide-angle camera scan.",
        "source": "camera_scan",
        "camera": "Camera #1 (IMX586, 63° FOV)",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_points": len(profile),
        "profile": profile,
    }

    output_path.write_text(json.dumps(payload, indent=2))
    log.info(f"Written: {output_path}")
    log.info(f"  Points: {len(profile)}")
    log.info(f"  Min altitude: {min(p['min_alt'] for p in profile):.1f}°")
    log.info(f"  Max altitude: {max(p['min_alt'] for p in profile):.1f}°")
    log.info(f"  Mean altitude: {sum(p['min_alt'] for p in profile)/len(profile):.1f}°")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Horizon Scanner — wide-angle Camera #1 via Alpaca")
    parser.add_argument("--auto", action="store_true",
                        help="Skip confirmation prompts")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulate scan without hardware")
    parser.add_argument("--ip", type=str, default=None,
                        help="Telescope IP (default: from config.toml)")
    parser.add_argument("--port", type=int, default=32323,
                        help="Alpaca port (default: 32323)")
    parser.add_argument("--output", type=str, default=str(HORIZON_FILE),
                        help=f"Output file (default: {HORIZON_FILE})")
    args = parser.parse_args()

    # Resolve IP
    if args.ip:
        ip = args.ip
    else:
        cfg = load_config()
        seestars = cfg.get("seestars", [{}])
        ip = seestars[0].get("ip", "192.168.178.251")

    print("╔══════════════════════════════════════════════════════════╗")
    print("║  SeeVar Horizon Scanner v1.0.0                         ║")
    print("║  Wide-angle Camera #1 (IMX586, 63° FOV)                ║")
    print(f"║  Target: {ip}:{args.port}                       ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()
    print(f"  FOV per frame: {FOV_H_DEG:.0f}° × {FOV_V_DEG:.0f}°")
    print(f"  Azimuth step: {AZ_STEP_DEG}°")
    print(f"  Positions: {int(math.ceil(360/AZ_STEP_DEG))}")
    print(f"  Estimated time: ~12 minutes")
    print()
    print("  Requirements:")
    print("  - Daytime (clear sky for contrast)")
    print("  - Telescope level and arm open")
    print("  - scipy installed (pip install scipy)")
    print()

    if not args.auto and not args.dry_run:
        ans = input("  Start horizon scan? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("  Cancelled.")
            return

    # Run scan
    horizon_raw = run_scan(ip, args.port, dry_run=args.dry_run)

    # Fill gaps and smooth
    horizon_full = fill_gaps(horizon_raw)

    # Write output
    write_horizon(horizon_full, Path(args.output))

    print()
    print("  Horizon profile complete.")
    print(f"  Output: {args.output}")
    print(f"  horizon.py will use this automatically on next flight.")


if __name__ == "__main__":
    main()
