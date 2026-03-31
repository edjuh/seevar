#!/usr/bin/env python3
"""
test_camera_exposure.py — Test Alpaca Camera #0 on Wilhelmina (S30-Pro)
========================================================================
Confirmed 2026-03-30:
  - Alpaca v1.2.0-3 on port 32323
  - Telescope slew/track/park — WORKS
  - 7 devices exposed including Camera #0 (Telephoto, IMX585)

This script tests the full imaging chain:
  1. Connect to Camera #0 (Seestar Wilhelmina Telephoto Camera)
  2. Read sensor properties (size, pixel scale, gain range, etc.)
  3. Set gain (80 = HCG sweet spot per community consensus)
  4. Take a short test exposure (5s default)
  5. Poll for completion
  6. Download image array
  7. Save as FITS with proper headers

If this works, SeeVar has the complete autonomous chain:
  slew → expose → download → photometry → AAVSO

Usage:
  python3 test_camera_exposure.py              # 5s exposure, interactive
  python3 test_camera_exposure.py --exposure 10 # 10s exposure
  python3 test_camera_exposure.py --auto        # no prompts
  python3 test_camera_exposure.py --gain 120    # custom gain
"""

import sys
import os
import json
import time
import argparse
import struct
import requests
import numpy as np
from datetime import datetime, timezone

WILHELMINA_IP = "192.168.178.251"
ALPACA_PORT = 32323
CAMERA_NUM = 0  # Telephoto camera
CLIENT_ID = 42  # SeeVar client ID
OUTPUT_DIR = os.path.expanduser("~/seevar/data/test_frames")

# Alpaca camera states
CAMERA_STATES = {
    0: "Idle",
    1: "Waiting",
    2: "Exposing",
    3: "Reading",
    4: "Download",
    5: "Error",
}


class AlpacaCamera:
    """Minimal Alpaca camera client for Wilhelmina."""

    def __init__(self, ip, port, device_number=0):
        self.base = f"http://{ip}:{port}/api/v1/camera/{device_number}"
        self.txid = 0

    def _next_tx(self):
        self.txid += 1
        return self.txid

    def _get(self, prop, **kwargs):
        params = {"ClientID": CLIENT_ID, "ClientTransactionID": self._next_tx()}
        params.update(kwargs)
        r = requests.get(f"{self.base}/{prop}", params=params, timeout=30)
        data = r.json()
        err = data.get("ErrorNumber", 0)
        if err:
            raise RuntimeError(f"{prop}: error {err} — {data.get('ErrorMessage','')}")
        return data.get("Value")

    def _put(self, method, **kwargs):
        payload = {"ClientID": CLIENT_ID, "ClientTransactionID": self._next_tx()}
        payload.update(kwargs)
        r = requests.put(f"{self.base}/{method}", data=payload, timeout=30)
        data = r.json()
        err = data.get("ErrorNumber", 0)
        if err:
            raise RuntimeError(f"{method}: error {err} — {data.get('ErrorMessage','')}")
        return data.get("Value")

    def _get_imagearray_binary(self):
        """
        Try to get image via ImageBytes (Alpaca v3+ binary transfer).
        Falls back to ImageArray JSON if not supported.
        Returns numpy array.
        """
        # First try ImageBytes (much faster for large sensors)
        try:
            params = {"ClientID": CLIENT_ID,
                      "ClientTransactionID": self._next_tx()}
            r = requests.get(f"{self.base}/imagearrayvariant",
                             params=params, timeout=120,
                             headers={"Accept": "application/imagebytes"})
            if r.status_code == 200 and "imagebytes" in r.headers.get("Content-Type", ""):
                print("  Using binary image transfer (fast)")
                return self._parse_imagebytes(r.content)
        except Exception as e:
            print(f"  Binary transfer not available: {e}")

        # Fall back to JSON ImageArray
        print("  Using JSON image transfer (may be slow for large sensor)...")
        params = {"ClientID": CLIENT_ID,
                  "ClientTransactionID": self._next_tx()}
        r = requests.get(f"{self.base}/imagearray",
                         params=params, timeout=300)
        data = r.json()
        err = data.get("ErrorNumber", 0)
        if err:
            raise RuntimeError(f"imagearray: error {err} — {data.get('ErrorMessage','')}")

        # The Value is Rank=2 array, Type depends on sensor
        rank = data.get("Rank", 2)
        img_type = data.get("Type", 2)  # 2=Int32
        value = data.get("Value")

        if value is None:
            raise RuntimeError("imagearray returned no Value")

        arr = np.array(value, dtype=np.int32)
        print(f"  Image array shape: {arr.shape}, dtype: {arr.dtype}")
        return arr

    def _parse_imagebytes(self, raw):
        """Parse Alpaca ImageBytes binary format."""
        # Header: metadata version (4), error (4), datastart (4),
        #         imageelement (4), transmission (4), rank (4),
        #         dim1 (4), dim2 (4), [dim3 (4)]
        # Then raw pixel data
        if len(raw) < 32:
            raise RuntimeError(f"ImageBytes too short: {len(raw)} bytes")

        meta_ver = struct.unpack_from('<i', raw, 0)[0]
        error_num = struct.unpack_from('<i', raw, 4)[0]
        data_start = struct.unpack_from('<i', raw, 8)[0]
        img_element = struct.unpack_from('<i', raw, 12)[0]
        transmission = struct.unpack_from('<i', raw, 16)[0]
        rank = struct.unpack_from('<i', raw, 20)[0]
        dim1 = struct.unpack_from('<i', raw, 24)[0]
        dim2 = struct.unpack_from('<i', raw, 28)[0]

        if error_num != 0:
            raise RuntimeError(f"ImageBytes error: {error_num}")

        # Element types: 1=Int16, 2=Int32, 3=Double, 6=UInt16, etc.
        dtype_map = {1: np.int16, 2: np.int32, 3: np.float64,
                     6: np.uint16, 8: np.uint32}
        dtype = dtype_map.get(img_element, np.int32)

        pixel_data = raw[data_start:]
        arr = np.frombuffer(pixel_data, dtype=dtype)
        arr = arr.reshape((dim2, dim1))  # row-major

        print(f"  ImageBytes: {dim1}x{dim2}, element type {img_element}, "
              f"{len(pixel_data)} bytes")
        return arr

    def connect(self):
        self._put("connected", Connected="true")

    def disconnect(self):
        self._put("connected", Connected="false")

    @property
    def connected(self):
        return self._get("connected")

    @property
    def name(self):
        return self._get("name")

    @property
    def description(self):
        return self._get("description")

    @property
    def sensor_name(self):
        try:
            return self._get("sensorname")
        except:
            return "unknown"

    @property
    def camera_xsize(self):
        return self._get("cameraxsize")

    @property
    def camera_ysize(self):
        return self._get("cameraysize")

    @property
    def pixel_size_x(self):
        return self._get("pixelsizex")

    @property
    def pixel_size_y(self):
        return self._get("pixelsizey")

    @property
    def max_adu(self):
        return self._get("maxadu")

    @property
    def sensor_type(self):
        # 0=Mono, 1=Color (RGGB), etc.
        return self._get("sensortype")

    @property
    def camera_state(self):
        return self._get("camerastate")

    @property
    def gain(self):
        return self._get("gain")

    @gain.setter
    def gain(self, value):
        self._put("gain", Gain=str(value))

    @property
    def gain_min(self):
        return self._get("gainmin")

    @property
    def gain_max(self):
        return self._get("gainmax")

    @property
    def gains(self):
        try:
            return self._get("gains")
        except:
            return None

    @property
    def exposure_min(self):
        return self._get("exposuremin")

    @property
    def exposure_max(self):
        return self._get("exposuremax")

    @property
    def image_ready(self):
        return self._get("imageready")

    @property
    def last_exposure_duration(self):
        return self._get("lastexposureduration")

    @property
    def last_exposure_start_time(self):
        return self._get("lastexposurestarttime")

    @property
    def can_abort(self):
        return self._get("canabortexposure")

    @property
    def can_stop(self):
        return self._get("canstopexposure")

    @property
    def can_get_cooler_power(self):
        try:
            return self._get("cancoolerpower")  # placeholder
        except:
            return False

    @property
    def ccd_temperature(self):
        try:
            return self._get("ccdtemperature")
        except:
            return None

    @property
    def bin_x(self):
        return self._get("binx")

    @property
    def bin_y(self):
        return self._get("biny")

    def start_exposure(self, duration, light=True):
        self._put("startexposure",
                   Duration=str(duration),
                   Light=str(light).lower())

    def abort_exposure(self):
        self._put("abortexposure")

    def get_image(self):
        return self._get_imagearray_binary()


# ─── Step 1: Camera Properties ────────────────────────────────────────────

def show_camera_properties(cam):
    """Read and display all camera properties."""
    print("=" * 60)
    print("STEP 1: Camera #0 Properties (Telephoto)")
    print("=" * 60)

    print("\n  Connecting...")
    cam.connect()
    print(f"  ✓ Connected: {cam.connected}")

    props = [
        ("Name", lambda: cam.name),
        ("Description", lambda: cam.description),
        ("Sensor name", lambda: cam.sensor_name),
        ("Sensor size", lambda: f"{cam.camera_xsize} x {cam.camera_ysize} px"),
        ("Pixel size", lambda: f"{cam.pixel_size_x:.2f} x {cam.pixel_size_y:.2f} µm"),
        ("Max ADU", lambda: cam.max_adu),
        ("Sensor type", lambda: {0: "Mono", 1: "Color"}.get(cam.sensor_type, cam.sensor_type)),
        ("Gain", lambda: cam.gain),
        ("Gain range", lambda: f"{cam.gain_min} – {cam.gain_max}"),
        ("Gain presets", lambda: cam.gains),
        ("Exposure range", lambda: f"{cam.exposure_min}s – {cam.exposure_max}s"),
        ("Binning", lambda: f"{cam.bin_x} x {cam.bin_y}"),
        ("CCD temperature", lambda: cam.ccd_temperature),
        ("Can abort", lambda: cam.can_abort),
        ("Can stop", lambda: cam.can_stop),
        ("Camera state", lambda: CAMERA_STATES.get(cam.camera_state, "Unknown")),
    ]

    results = {}
    for label, getter in props:
        try:
            val = getter()
            print(f"  {label}: {val}")
            results[label] = val
        except Exception as e:
            print(f"  {label}: ERROR — {e}")

    return results


# ─── Step 2: Take Exposure ─────────────────────────────────────────────────

def take_exposure(cam, duration, gain=80):
    """Take a single exposure and download the image."""
    print(f"\n{'=' * 60}")
    print(f"STEP 2: Exposure ({duration}s, gain {gain})")
    print("=" * 60)

    # Set gain
    print(f"\n  Setting gain to {gain}...")
    try:
        cam.gain = gain
        actual = cam.gain
        print(f"  ✓ Gain set to {actual}")
    except Exception as e:
        print(f"  ⚠ Gain set failed: {e} (continuing with current gain)")

    # Verify camera is idle
    state = cam.camera_state
    state_name = CAMERA_STATES.get(state, "Unknown")
    print(f"  Camera state: {state_name} ({state})")
    if state != 0:
        print(f"  ⚠ Camera not idle — state is {state_name}")
        if state == 2:
            print("  Aborting current exposure...")
            cam.abort_exposure()
            time.sleep(2)

    # Start exposure
    print(f"\n  Starting {duration}s light frame...")
    t0 = time.time()
    try:
        cam.start_exposure(duration, light=True)
    except Exception as e:
        print(f"  ✗ StartExposure FAILED: {e}")
        return None

    print(f"  ✓ Exposure started at {datetime.now(timezone.utc).isoformat()}")

    # Poll for completion
    print(f"  Waiting for exposure + readout...")
    poll_interval = 1 if duration < 10 else 2
    max_wait = duration + 60  # generous timeout for readout
    elapsed = 0

    while elapsed < max_wait:
        time.sleep(poll_interval)
        elapsed = time.time() - t0

        state = cam.camera_state
        state_name = CAMERA_STATES.get(state, "Unknown")

        if state == 2:  # Exposing
            remaining = max(0, duration - elapsed)
            bar_len = 30
            progress = min(1.0, elapsed / duration)
            filled = int(bar_len * progress)
            bar = "█" * filled + "░" * (bar_len - filled)
            print(f"\r  [{bar}] {elapsed:.0f}s / {duration}s", end="", flush=True)
        elif state == 3:  # Reading
            print(f"\n  Reading out sensor...")
        elif state == 0:  # Idle — might be ready
            ready = cam.image_ready
            if ready:
                print(f"\n  ✓ Image ready after {elapsed:.1f}s")
                break
            else:
                print(f"\n  State idle but image not ready, waiting...")
        elif state == 5:  # Error
            print(f"\n  ✗ Camera error state!")
            return None
        else:
            print(f"\n  State: {state_name} ({state}), {elapsed:.0f}s elapsed")

        # Also check imageready directly
        try:
            if cam.image_ready:
                print(f"\n  ✓ Image ready after {elapsed:.1f}s")
                break
        except:
            pass
    else:
        print(f"\n  ✗ Timeout after {max_wait}s waiting for image")
        return None

    # Get exposure metadata
    try:
        exp_duration = cam.last_exposure_duration
        exp_start = cam.last_exposure_start_time
        print(f"  Exposure duration: {exp_duration}s")
        print(f"  Exposure start: {exp_start}")
    except Exception as e:
        print(f"  ⚠ Could not read exposure metadata: {e}")
        exp_duration = duration
        exp_start = "unknown"

    # Download image
    print(f"\n  Downloading image array...")
    t_dl = time.time()
    try:
        img = cam.get_image()
        dl_time = time.time() - t_dl
        print(f"  ✓ Downloaded in {dl_time:.1f}s")
        print(f"  Shape: {img.shape}")
        print(f"  Dtype: {img.dtype}")
        print(f"  Min/Max: {img.min()} / {img.max()}")
        print(f"  Mean: {img.mean():.1f}")
        print(f"  Median: {np.median(img):.1f}")
        print(f"  Std: {img.std():.1f}")
    except Exception as e:
        print(f"  ✗ Image download FAILED: {e}")
        import traceback
        traceback.print_exc()
        return None

    return img, {
        "duration": exp_duration,
        "start": exp_start,
        "gain": gain,
        "shape": img.shape,
    }


# ─── Step 3: Save as FITS ─────────────────────────────────────────────────

def save_fits(img, metadata, cam, output_dir):
    """Save image as FITS with proper headers for photometry."""
    print(f"\n{'=' * 60}")
    print("STEP 3: Save FITS")
    print("=" * 60)

    try:
        from astropy.io import fits
    except ImportError:
        print("  ✗ astropy not installed — saving as .npy instead")
        os.makedirs(output_dir, exist_ok=True)
        fname = os.path.join(output_dir,
                             f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.npy")
        np.save(fname, img)
        print(f"  Saved: {fname}")
        return fname

    os.makedirs(output_dir, exist_ok=True)

    # Read telescope position for FITS headers
    tel_base = f"http://{WILHELMINA_IP}:{ALPACA_PORT}/api/v1/telescope/0"
    try:
        ra = requests.get(f"{tel_base}/rightascension",
                          params={"ClientID": CLIENT_ID,
                                  "ClientTransactionID": 9999},
                          timeout=5).json().get("Value", 0)
        dec = requests.get(f"{tel_base}/declination",
                           params={"ClientID": CLIENT_ID,
                                   "ClientTransactionID": 9999},
                           timeout=5).json().get("Value", 0)
        target = requests.get(f"{tel_base}/name",
                              params={"ClientID": CLIENT_ID,
                                      "ClientTransactionID": 9999},
                              timeout=5).json().get("Value", "Unknown")
    except:
        ra, dec, target = 0, 0, "Unknown"

    # Build FITS
    hdu = fits.PrimaryHDU(img.astype(np.uint16) if img.max() < 65536 else img)
    hdr = hdu.header

    # Standard FITS keywords
    hdr["OBSERVER"] = "REDA"
    hdr["TELESCOP"] = "Wilhelmina (ZWO Seestar S30-Pro)"
    hdr["INSTRUME"] = "IMX585"
    hdr["FOCALLEN"] = (160, "Focal length in mm")
    hdr["APTDIA"]   = (40, "Aperture diameter in mm")
    hdr["FOCRATIO"] = (4.0, "Focal ratio f/D")
    hdr["FILTER"]   = "TG"
    hdr["EXPTIME"]  = (metadata.get("duration", 0), "Exposure time in seconds")
    hdr["GAIN"]     = (metadata.get("gain", 0), "Camera gain")
    hdr["DATE-OBS"] = metadata.get("start", datetime.now(timezone.utc).isoformat())
    hdr["RA"]       = (ra * 15.0, "RA in degrees (J2000)")
    hdr["DEC"]      = (dec, "Dec in degrees (J2000)")
    hdr["OBJNAME"]  = target
    hdr["SITELAT"]  = (52.3822, "Observatory latitude")
    hdr["SITELONG"] = (4.6017, "Observatory longitude")
    hdr["SITEELEV"] = (5, "Observatory elevation in meters")
    hdr["PROGRAM"]  = "SeeVar"
    hdr["SWCREATE"] = "SeeVar/Alpaca"
    hdr["ALPACAV"]  = ("1.2.0-3", "Alpaca driver version")
    hdr["IMAGETYP"] = "Light"

    # Pixel scale: IMX585 2.9µm pixels, 160mm FL
    # scale = 206.265 * pixel_size_um / focal_length_mm
    try:
        pix_um = cam.pixel_size_x
        hdr["PIXSIZE1"] = (pix_um, "Pixel size X in microns")
        hdr["PIXSIZE2"] = (cam.pixel_size_y, "Pixel size Y in microns")
        hdr["SCALE"]    = (206.265 * pix_um / 160.0, "Plate scale arcsec/pixel")
    except:
        hdr["SCALE"] = (3.74, "Plate scale arcsec/pixel (estimated)")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = os.path.join(output_dir, f"wilhelmina_test_{timestamp}.fits")
    hdu.writeto(fname, overwrite=True)
    print(f"  ✓ Saved: {fname}")
    print(f"  Size: {os.path.getsize(fname) / 1024 / 1024:.1f} MB")

    # Quick sanity check
    with fits.open(fname) as hdul:
        print(f"  Verification: {hdul[0].data.shape}, {hdul[0].data.dtype}")
        print(f"  Headers: {len(hdul[0].header)} keywords")

    return fname


# ─── Step 4: Quick Camera Capability Probe ─────────────────────────────────

def probe_camera_extras(cam):
    """Check for any bonus capabilities."""
    print(f"\n{'=' * 60}")
    print("STEP 4: Extra capability probe")
    print("=" * 60)

    # Check supported actions on camera
    try:
        r = requests.get(
            f"http://{WILHELMINA_IP}:{ALPACA_PORT}/api/v1/camera/{CAMERA_NUM}/supportedactions",
            params={"ClientID": CLIENT_ID, "ClientTransactionID": 9999},
            timeout=5)
        actions = r.json().get("Value", [])
        if actions:
            print("  Camera supported actions:")
            for a in actions:
                print(f"    - {a}")
        else:
            print("  Camera supported actions: (none)")
    except Exception as e:
        print(f"  Supported actions check failed: {e}")

    # Check if ROI/subframe is available
    try:
        sx = cam._get("startx")
        sy = cam._get("starty")
        nx = cam._get("numx")
        ny = cam._get("numy")
        print(f"  Subframe: start=({sx},{sy}), size=({nx},{ny})")
    except Exception as e:
        print(f"  Subframe: {e}")

    # Check readout modes
    try:
        modes = cam._get("readoutmodes")
        mode = cam._get("readoutmode")
        print(f"  Readout modes: {modes} (current: {mode})")
    except Exception as e:
        print(f"  Readout modes: not supported ({e})")

    # Bayerpattern
    try:
        bayer_x = cam._get("bayeroffsetx")
        bayer_y = cam._get("bayeroffsety")
        print(f"  Bayer offset: ({bayer_x}, {bayer_y})")
    except Exception as e:
        print(f"  Bayer offset: {e}")


# ─── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Test Alpaca Camera #0 on Wilhelmina")
    parser.add_argument("--exposure", type=float, default=5.0,
                        help="Exposure duration in seconds (default: 5)")
    parser.add_argument("--gain", type=int, default=80,
                        help="Camera gain (default: 80, HCG sweet spot)")
    parser.add_argument("--auto", action="store_true",
                        help="Skip confirmation prompts")
    parser.add_argument("--output", type=str, default=OUTPUT_DIR,
                        help=f"Output directory (default: {OUTPUT_DIR})")
    args = parser.parse_args()

    print("╔══════════════════════════════════════════════════════════╗")
    print("║  Wilhelmina Camera Test — Alpaca Telephoto Camera #0   ║")
    print("║  Target: 192.168.178.251:32323  (IMX585, S30-Pro)      ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    cam = AlpacaCamera(WILHELMINA_IP, ALPACA_PORT, CAMERA_NUM)

    # Step 1: Properties
    props = show_camera_properties(cam)
    if not props:
        print("\n✗ Could not read camera properties")
        sys.exit(1)

    # Step 4 (early): Extras
    probe_camera_extras(cam)

    # Confirm exposure
    if not args.auto:
        print(f"\n{'=' * 60}")
        print(f"READY TO EXPOSE")
        print(f"  Duration: {args.exposure}s")
        print(f"  Gain: {args.gain}")
        print(f"  Output: {args.output}")
        print(f"{'=' * 60}")
        ans = input("\n  Take test exposure? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("  Skipped.")
            cam.disconnect()
            return
    else:
        print(f"\n  Auto mode: taking {args.exposure}s exposure at gain {args.gain}")

    # Step 2: Expose
    result = take_exposure(cam, args.exposure, args.gain)

    if result is None:
        print("\n✗ Exposure failed")
        cam.disconnect()
        sys.exit(1)

    img, metadata = result

    # Step 3: Save FITS
    fname = save_fits(img, metadata, cam, args.output)

    # Summary
    print(f"\n{'=' * 60}")
    print("COMPLETE — CAMERA TEST RESULTS")
    print("=" * 60)
    print(f"  Camera: {props.get('Name', '?')}")
    print(f"  Sensor: {props.get('Sensor size', '?')}")
    print(f"  Exposure: {metadata.get('duration', '?')}s at gain {metadata.get('gain', '?')}")
    print(f"  Image: {img.shape[1]}x{img.shape[0]} pixels")
    print(f"  ADU range: {img.min()} – {img.max()}")
    print(f"  Saved: {fname}")
    print()
    print("  If you see real star data in the ADU values above,")
    print("  SeeVar has the complete autonomous imaging chain.")
    print("  Next: integrate AlpacaCamera into pilot.py v3.0")
    print()

    cam.disconnect()
    print("  Disconnected. Done.")


if __name__ == "__main__":
    main()
