#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/pilot.py
Version: 4.0.3
Objective: Direct TCP control of ZWO S30-Pro for AAVSO-compliant Sovereign RAW acquisition with Dashboard Telemetry Callbacks.

pilot.py — SeeVar Sovereign Acquisition Pilot
v4.0.3 "Praw" — Zbigniew Prlwytzkofsky Edition

Wire protocol — reverse engineered from seestar_alp source:
  Port 4700  JSON-RPC control  (text, \r\n terminated)
  Port 4801  Binary frame stream (80-byte header + payload)

Header struct (big-endian, only first 20 bytes used):
  fmt = ">HHHIHHBBHH"
  _s1, _s2, _s3, size, _s5, _s6, code, frame_id, width, height

Frame IDs:
  21  Preview  — raw uint16 Bayer GRBG  <- science target
  23  Stack    — ZIP containing raw_data (not used here)

Sensor: IMX585, 2160x3840, uint16, GRBG Bayer
"""

import json
import logging
import socket
import struct
import time
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Constants — single source of truth
# ---------------------------------------------------------------------------

SEESTAR_HOST    = "192.168.178.55"
CTRL_PORT       = 4700          # JSON-RPC control
IMG_PORT        = 4801          # Binary frame stream (preview)

HEADER_SIZE     = 80            # Fixed header bytes per frame
HEADER_FMT      = ">HHHIHHBBHH" # big-endian; use first 20 bytes
FRAME_PREVIEW   = 21            # RAW uint16 Bayer single frame
FRAME_STACK     = 23            # ZIP stacked frame (not used)
MIN_PAYLOAD     = 1000          # Below this = heartbeat, skip

SENSOR_W        = 2160          # IMX585 full resolution
SENSOR_H        = 3840
BAYER_PATTERN   = "GRBG"
INSTRUMENT      = "IMX585"
TELESCOPE       = "ZWO S30-Pro"
FILTER_NAME     = "CV"          # Clear/V-proxy for AAVSO

# Acquisition parameters
SETTLE_SECONDS  = 8             # Post-slew settle time
FRAME_TIMEOUT   = 60            # Max wait for preview frame (seconds)
EXP_MS_DEFAULT  = 5000          # Default exposure ms

from core.utils.env_loader import DATA_DIR
LOCAL_BUFFER    = DATA_DIR / "local_buffer"

logger = logging.getLogger("seevar.pilot")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AcquisitionTarget:
    name:          str
    ra_hours:      float
    dec_deg:       float
    auid:          str          = ""
    exp_ms:        int          = EXP_MS_DEFAULT
    observer_code: str          = ""
    n_frames:      int          = 1


@dataclass
class FrameResult:
    success:    bool
    path:       Optional[Path]  = None
    width:      int             = 0
    height:     int             = 0
    elapsed_s:  float           = 0.0
    error:      str             = ""


# ---------------------------------------------------------------------------
# Low-level TCP helpers
# ---------------------------------------------------------------------------

def recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    """Read exactly n bytes using MSG_WAITALL (mirrors seestar_alp binary.py)."""
    try:
        data = sock.recv(n, socket.MSG_WAITALL)
    except socket.timeout:
        logger.warning("recv_exact: socket timeout")
        return None
    except socket.error as e:
        logger.error(f"recv_exact: socket error: {e}")
        return None
    if data is None or len(data) == 0:
        return None
    if len(data) != n:
        logger.warning(f"recv_exact: wanted {n}, got {len(data)}")
        return None
    return data


def parse_header(header: bytes) -> Tuple[int, int, int, int]:
    """
    Parse 80-byte frame header.
    Returns (size, frame_id, width, height).
    Only the first 20 bytes carry data; rest are padding.
    """
    if header is None or len(header) < 20:
        return 0, 0, 0, 0
    try:
        _s1, _s2, _s3, size, _s5, _s6, code, frame_id, width, height = \
            struct.unpack(HEADER_FMT, header[:20])
        return size, frame_id, width, height
    except struct.error as e:
        logger.error(f"parse_header: {e}")
        return 0, 0, 0, 0


# ---------------------------------------------------------------------------
# Control socket — JSON-RPC over port 4700
# ---------------------------------------------------------------------------

class ControlSocket:
    """Thin wrapper around the S30-Pro JSON-RPC control channel."""

    def __init__(self, host: str = SEESTAR_HOST, port: int = CTRL_PORT,
                 timeout: float = 15.0):
        self.host    = host
        self.port    = port
        self.timeout = timeout
        self._sock:  Optional[socket.socket] = None
        self._cmdid: int = 10000            # mirrors seestar_alp convention

    def connect(self) -> bool:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(self.timeout)
            s.connect((self.host, self.port))
            self._sock = s
            logger.info(f"ControlSocket connected to {self.host}:{self.port}")
            return True
        except socket.error as e:
            logger.error(f"ControlSocket connect failed: {e}")
            return False

    def disconnect(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def send(self, method: str, params=None) -> bool:
        if self._sock is None:
            logger.error("ControlSocket: not connected")
            return False
        msg = {"id": self._cmdid, "method": method}
        if params is not None:
            msg["params"] = params
        self._cmdid += 1
        wire = (json.dumps(msg) + "\r\n").encode("utf-8")
        try:
            self._sock.sendall(wire)
            logger.debug(f"-> {method} {params}")
            return True
        except socket.error as e:
            logger.error(f"ControlSocket send error: {e}")
            return False

    def recv_response(self) -> Optional[dict]:
        """Read one \r\n-terminated JSON response."""
        if self._sock is None:
            return None
        buf = b""
        try:
            while b"\r\n" not in buf:
                chunk = self._sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
            line = buf.split(b"\r\n")[0]
            return json.loads(line.decode("utf-8"))
        except (socket.error, json.JSONDecodeError) as e:
            logger.warning(f"recv_response: {e}")
            return None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()


# ---------------------------------------------------------------------------
# Image socket — binary frame stream on port 4801
# ---------------------------------------------------------------------------

class ImageSocket:
    """
    Connects to the S30-Pro binary image stream (port 4801).
    Waits for a single preview frame (frame_id == 21).
    Returns raw uint16 Bayer bytes + dimensions.
    """

    def __init__(self, host: str = SEESTAR_HOST, port: int = IMG_PORT,
                 timeout: float = FRAME_TIMEOUT):
        self.host    = host
        self.port    = port
        self.timeout = timeout

    def capture_one_preview(self) -> Tuple[Optional[bytes], int, int]:
        """
        Connect, receive frames until frame_id == 21, return (data, w, h).
        Disconnects after receiving one science frame.
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.host, self.port))
        except socket.error as e:
            logger.error(f"ImageSocket connect failed: {e}")
            return None, 0, 0

        logger.info(f"ImageSocket connected to {self.host}:{self.port}")
        deadline = time.monotonic() + self.timeout

        try:
            while time.monotonic() < deadline:
                header = recv_exact(sock, HEADER_SIZE)
                if header is None:
                    logger.warning("ImageSocket: no header received")
                    break

                size, frame_id, width, height = parse_header(header)
                logger.debug(f"frame_id={frame_id} size={size} {width}x{height}")

                if size < MIN_PAYLOAD:
                    # Heartbeat / keepalive packet — no payload to read
                    continue

                data = recv_exact(sock, size)
                if data is None:
                    logger.error("ImageSocket: failed to read payload")
                    break

                if frame_id == FRAME_PREVIEW:
                    expected = width * height * 2   # uint16 = 2 bytes/pixel
                    if len(data) != expected:
                        logger.error(
                            f"Preview payload size mismatch: "
                            f"got {len(data)}, expected {expected} "
                            f"({width}x{height}x2)"
                        )
                        continue
                    logger.info(
                        f"Preview frame received: {width}x{height}, "
                        f"{len(data):,} bytes"
                    )
                    return data, width, height

                elif frame_id == FRAME_STACK:
                    logger.debug("Stack frame received — skipping (preview mode)")
                    continue

        finally:
            sock.close()

        logger.error("ImageSocket: deadline exceeded without preview frame")
        return None, 0, 0


# ---------------------------------------------------------------------------
# FITS construction — no astropy dependency
# ---------------------------------------------------------------------------

def sovereign_stamp(target: AcquisitionTarget,
                    utc_obs: datetime,
                    width: int,
                    height: int) -> dict:
    """
    Build AAVSO-compliant FITS header dict with strict WCS anchor points.
    """
    ra_deg = target.ra_hours * 15.0
    h = {
        "SIMPLE":   True,
        "BITPIX":   16,
        "NAXIS":    2,
        "NAXIS1":   width,
        "NAXIS2":   height,
        "OBJECT":   target.name,
        "OBJCTRA":  _hours_to_hms(target.ra_hours),
        "OBJCTDEC": _deg_to_dms(target.dec_deg),
        "CRVAL1":   ra_deg,
        "CRVAL2":   target.dec_deg,
        "CRPIX1":   width / 2.0,
        "CRPIX2":   height / 2.0,
        "CDELT1":   -0.001042,
        "CDELT2":   0.001042,
        "CTYPE1":   "RA---TAN",
        "CTYPE2":   "DEC--TAN",
        "DATE-OBS": utc_obs.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
        "EXPTIME":  target.exp_ms / 1000.0,
        "INSTRUME": INSTRUMENT,
        "TELESCOP": TELESCOPE,
        "FILTER":   FILTER_NAME,
        "BAYERPAT": BAYER_PATTERN,
        "OBSERVER": target.observer_code or "UNKNOWN",
    }
    if target.auid:
        h["AUID"] = target.auid
    return h


def write_fits(array: np.ndarray, header_dict: dict, output_path: Path) -> bool:
    """
    Write a FITS file without astropy — pure struct + numpy.
    BITPIX=16, big-endian uint16, single primary HDU.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Ensure big-endian uint16
    array = array.astype(np.uint16)
    if array.dtype.byteorder not in (">",):
        # NumPy 2.0 compliant byte swap
        array = array.byteswap().view(array.dtype.newbyteorder(">"))

    def card(key: str, value, comment: str = "") -> str:
        key = key.upper()[:8].ljust(8)
        if isinstance(value, bool):
            val_str = f"{'T' if value else 'F':>20}"
        elif isinstance(value, int):
            val_str = f"{value:>20}"
        elif isinstance(value, float):
            val_str = f"{value:>20.10G}"
        elif isinstance(value, str):
            escaped = value.replace("'", "''")
            val_str = f"'{escaped:<8}'"
            val_str = f"{val_str:<20}"
        else:
            val_str = f"'{str(value):<8}'"
            val_str = f"{val_str:<20}"
        c = f" / {comment}" if comment else ""
        raw = f"{key}= {val_str}{c}"
        return raw[:80].ljust(80)

    records = []
    priority_keys = ["SIMPLE", "BITPIX", "NAXIS", "NAXIS1", "NAXIS2"]
    for k in priority_keys:
        if k in header_dict:
            records.append(card(k, header_dict[k]))
    for k, v in header_dict.items():
        if k not in priority_keys:
            records.append(card(k, v))

    records.append(
        "COMMENT   SeeVar v4.0.0 Praw -- github.com/edjuh/seevar".ljust(80)
    )
    records.append("END" + " " * 77)

    # Pad header to 2880-byte block boundary
    while (len(records) * 80) % 2880 != 0:
        records.append(" " * 80)

    header_bytes = "".join(records).encode("ascii")

    # Data: big-endian uint16, padded to 2880-byte block
    data_bytes = array.tobytes()
    remainder = len(data_bytes) % 2880
    if remainder:
        data_bytes += b"\x00" * (2880 - remainder)

    try:
        with open(output_path, "wb") as f:
            f.write(header_bytes)
            f.write(data_bytes)
        logger.info(f"FITS written: {output_path}  ({output_path.stat().st_size:,} bytes)")
        return True
    except OSError as e:
        logger.error(f"FITS write failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Aperture photometry
# ---------------------------------------------------------------------------

def aperture_flux(image: np.ndarray, cx: int, cy: int,
                  r_ap: int = 8,
                  r_sky_in: int = 12,
                  r_sky_out: int = 18) -> Tuple[float, float, float]:
    """
    Circular aperture photometry.
    Returns (net_flux, sky_median, snr).
    """
    y_idx, x_idx = np.ogrid[-cy:image.shape[0]-cy, -cx:image.shape[1]-cx]
    r2 = (x_idx**2 + y_idx**2).astype(np.float64)
    ap_mask  = r2 <= r_ap ** 2
    sky_mask = (r2 >= r_sky_in ** 2) & (r2 <= r_sky_out ** 2)

    sky_vals   = image[sky_mask].astype(np.float64)
    sky_median = float(np.median(sky_vals)) if len(sky_vals) > 0 else 0.0
    sky_std    = float(sky_vals.std())      if len(sky_vals) > 0 else 1.0

    ap_sum   = float(image[ap_mask].astype(np.float64).sum())
    n_ap     = int(ap_mask.sum())
    net_flux = ap_sum - sky_median * n_ap
    snr      = net_flux / (sky_std * np.sqrt(n_ap)) if sky_std > 0 else 0.0

    return net_flux, sky_median, snr


# ---------------------------------------------------------------------------
# Photometry pipeline — works offline against existing FITS files
# ---------------------------------------------------------------------------

class PhotometryPipeline:
    """
    Aperture photometry on a FITS file.
    Reads WCS from header, locates target + comp stars, computes
    differential magnitudes via ensemble zero-point.
    """

    def __init__(self, fits_path: Path):
        self.path    = fits_path
        self._array: Optional[np.ndarray] = None
        self._header: dict = {}
        self._wcs:   dict = {}

    def load(self) -> bool:
        try:
            with open(self.path, "rb") as f:
                raw = f.read()
        except OSError as e:
            logger.error(f"Cannot read {self.path}: {e}")
            return False

        header: dict = {}
        header_blocks = 0
        found_end = False

        for block_start in range(0, len(raw), 2880):
            block = raw[block_start: block_start + 2880]
            header_blocks += 1
            for i in range(0, 2880, 80):
                rec = block[i:i+80].decode("ascii", errors="replace")
                key = rec[:8].strip()
                if key == "END":
                    found_end = True
                    break
                if "=" in rec[:30]:
                    k, _, rest = rec.partition("=")
                    val_str = rest.split("/")[0].strip().strip("'").strip()
                    try:
                        if "." in val_str:
                            header[k.strip()] = float(val_str)
                        elif val_str in ("T", "F"):
                            header[k.strip()] = (val_str == "T")
                        else:
                            header[k.strip()] = int(val_str)
                    except ValueError:
                        header[k.strip()] = val_str
            if found_end:
                break

        self._header = header

        bitpix = int(header.get("BITPIX", -32))
        naxis1 = int(header.get("NAXIS1", 0))
        naxis2 = int(header.get("NAXIS2", 0))

        data_start = header_blocks * 2880
        n_bytes    = abs(bitpix) // 8 * naxis1 * naxis2
        raw_data   = raw[data_start: data_start + n_bytes]

        dtype_map = {
            8:   ">u1",
            16:  ">i2",
            -16: ">u2",
            32:  ">i4",
            -32: ">f4",
            -64: ">f8",
        }
        dt = dtype_map.get(bitpix, ">f4")
        self._array = np.frombuffer(raw_data, dtype=dt).reshape(naxis2, naxis1)

        self._wcs = {
            "crval1": float(header.get("CRVAL1", 0)),
            "crval2": float(header.get("CRVAL2", 0)),
            "crpix1": float(header.get("CRPIX1", naxis1 / 2)),
            "crpix2": float(header.get("CRPIX2", naxis2 / 2)),
            "cdelt1": float(header.get("CDELT1", -0.001042)),  # 3.74"/px in deg
            "cdelt2": float(header.get("CDELT2",  0.001042)),
        }
        return True

    def world_to_pixel(self, ra: float, dec: float) -> Tuple[int, int]:
        """Simple TAN projection (no distortion terms)."""
        w = self._wcs
        px = w["crpix1"] + (w["crval1"] - ra)  / abs(w["cdelt1"])
        py = w["crpix2"] + (dec - w["crval2"]) / abs(w["cdelt2"])
        return int(round(px)), int(round(py))

    def measure(self, ra: float, dec: float,
                r_ap: int = 8, r_sky_in: int = 12, r_sky_out: int = 18,
                search_radius: int = 10) -> dict:
        """
        Aperture photometry at (ra, dec) with centroid refinement.
        """
        cx, cy = self.world_to_pixel(ra, dec)
        arr = self._array.astype(np.float64)
        h, w = arr.shape

        if not (r_sky_out < cx < w - r_sky_out and r_sky_out < cy < h - r_sky_out):
            return {"error": "out of frame", "cx": cx, "cy": cy}

        # Centroid refinement — peak within search box
        x0, x1 = max(0, cx - search_radius), min(w, cx + search_radius)
        y0, y1 = max(0, cy - search_radius), min(h, cy + search_radius)
        patch = arr[y0:y1, x0:x1]
        pk    = np.unravel_index(patch.argmax(), patch.shape)
        cx    = x0 + pk[1]
        cy    = y0 + pk[0]

        net_flux, sky_median, snr = aperture_flux(arr, cx, cy, r_ap, r_sky_in, r_sky_out)
        return {
            "cx": cx, "cy": cy,
            "net_flux": net_flux,
            "sky_median": sky_median,
            "snr": snr,
            "peak": float(arr[cy, cx]),
        }

    @property
    def header(self) -> dict:
        return self._header

    @property
    def array(self) -> Optional[np.ndarray]:
        return self._array


# ---------------------------------------------------------------------------
# Diamond Sequence — sovereign live acquisition
# ---------------------------------------------------------------------------

class DiamondSequence:
    """
    Sovereign acquisition sequence for one target.

    Protocol:
      1. iscope_stop_view         — clear any active session
      2. scope_sync [ra, dec]     — point mount
      3. settle (SETTLE_SECONDS)
      4. iscope_start_view        — triggers ContinuousExposure stage
      5. port 4801: recv header (80 bytes) -> parse -> recv payload
      6. frame_id == 21: raw uint16 Bayer bytes
      7. reshape(height, width) -> np.uint16 array
      8. Sovereign Stamp -> write_fits()
      9. iscope_stop_view
    """

    def __init__(self, host: str = SEESTAR_HOST):
        self.host = host

    def acquire(self, target: AcquisitionTarget, status_cb=None) -> FrameResult:
        def notify(msg):
            logger.info(msg)
            if status_cb:
                status_cb(msg)

        t_start = time.monotonic()
        utc_obs = datetime.now(timezone.utc)

        notify(f"Initializing Coordinates: RA={target.ra_hours:.4f}h, DEC={target.dec_deg:.4f}°")

        ctrl = ControlSocket(host=self.host)
        if not ctrl.connect():
            return FrameResult(success=False, error="Control socket connect failed")

        try:
            notify("Clearing active views (iscope_stop_view)...")
            ctrl.send("iscope_stop_view")
            time.sleep(1.0)

            notify(f"Commanding Mount Slew to {target.name}...")
            ctrl.send("scope_sync", [target.ra_hours, target.dec_deg])
            
            notify(f"Mount Settling ({SETTLE_SECONDS}s rule)...")
            time.sleep(SETTLE_SECONDS)

            notify("Engaging Continuous Exposure (iscope_start_view)...")
            ctrl.send("iscope_start_view", {"mode": "star"})
            time.sleep(2.0)

        except Exception as e:
            ctrl.disconnect()
            return FrameResult(success=False, error=f"Control sequence error: {e}")

        notify("Streaming Raw Payload via Port 4801...")
        img_sock = ImageSocket(host=self.host, timeout=FRAME_TIMEOUT)
        raw_data, width, height = img_sock.capture_one_preview()

        try:
            notify("Closing shutter (iscope_stop_view)...")
            ctrl.send("iscope_stop_view")
        finally:
            ctrl.disconnect()

        if raw_data is None:
            return FrameResult(success=False, error="No preview frame received")

        notify(f"Generating Sovereign WCS Headers (AUID: {target.auid})...")
        array = np.frombuffer(raw_data, dtype=np.uint16).reshape(height, width)

        LOCAL_BUFFER.mkdir(parents=True, exist_ok=True)
        safe_name = target.name.replace(" ", "_").replace("/", "-")
        timestamp = utc_obs.strftime("%Y%m%dT%H%M%S")
        out_path  = LOCAL_BUFFER / f"{safe_name}_{timestamp}_Raw.fits"

        header = sovereign_stamp(target, utc_obs, width, height)
        notify("Writing 16-bit FITS to Local Buffer...")
        ok     = write_fits(array, header, out_path)
        elapsed = time.monotonic() - t_start

        if ok:
            notify(f"Acquired {target.name} -> {out_path.name} ({elapsed:.1f}s)")
            return FrameResult(
                success=True, path=out_path,
                width=width, height=height, elapsed_s=elapsed,
            )
        return FrameResult(success=False, error="FITS write failed", elapsed_s=elapsed)


# ---------------------------------------------------------------------------
# Test harness — offline photometry against ss_cyg.fits
# ---------------------------------------------------------------------------

def run_photometry_test(fits_path: Path):
    print(f"\n{'='*62}")
    print(f"  SeeVar v4.0.0 Praw — Photometry Test")
    print(f"  {fits_path.name}")
    print(f"{'='*62}")

    pipe = PhotometryPipeline(fits_path)
    if not pipe.load():
        print("ERROR: Could not load FITS file")
        return

    h = pipe.header
    print(f"\n  Target   : {h.get('OBJECT', 'unknown')}")
    print(f"  Survey   : {h.get('SURVEY', h.get('INSTRUME', 'unknown'))}")
    print(f"  Date-Obs : {h.get('DATE-OBS', 'unknown')}")
    print(f"  ExpTime  : {h.get('EXPTIME', '?')}s")
    print(f"  BITPIX   : {h.get('BITPIX', '?')}")
    print(f"  Size     : {h.get('NAXIS1','?')} x {h.get('NAXIS2','?')}")
    print(f"  Bayer    : {h.get('BAYERPAT', 'N/A')}")

    arr = pipe.array.astype(np.float64)
    print(f"\n  Image stats:")
    print(f"    min={arr.min():.0f}  max={arr.max():.0f}  "
          f"mean={arr.mean():.0f}  std={arr.std():.0f}")

    # AAVSO sequence for SS Cyg
    SS_CYG_RA  = 325.6783
    SS_CYG_DEC = 43.5861

    comp_stars = [
        # label   V_mag   RA_deg      Dec_deg
        ("C1",     8.8,   325.8975,   43.5419),
        ("C2",     9.9,   325.7758,   43.5761),
        ("C3",    11.1,   325.5858,   43.6256),
    ]

    print(f"\n  Aperture photometry  (r_ap=8px, sky annulus 12-18px)")
    print(f"  {'Star':<10} {'V_mag':>6} {'x':>5} {'y':>5} "
          f"{'net_flux':>10} {'sky':>8} {'SNR':>6} {'peak':>8}")
    print("  " + "-" * 58)

    ssc_m = pipe.measure(SS_CYG_RA, SS_CYG_DEC)
    if "error" not in ssc_m:
        print(f"  {'SS Cyg':<10} {'?':>6} {ssc_m['cx']:>5} {ssc_m['cy']:>5} "
              f"{ssc_m['net_flux']:>10.0f} {ssc_m['sky_median']:>8.0f} "
              f"{ssc_m['snr']:>6.1f} {ssc_m['peak']:>8.0f}")
    else:
        print(f"  SS Cyg: {ssc_m['error']}")

    comp_fluxes = []
    for label, vmag, ra, dec in comp_stars:
        m = pipe.measure(ra, dec)
        if "error" not in m and m["net_flux"] > 0:
            comp_fluxes.append((label, vmag, m["net_flux"]))
            print(f"  {label:<10} {vmag:>6.1f} {m['cx']:>5} {m['cy']:>5} "
                  f"{m['net_flux']:>10.0f} {m['sky_median']:>8.0f} "
                  f"{m['snr']:>6.1f} {m['peak']:>8.0f}")
        else:
            print(f"  {label:<10} {vmag:>6.1f}  -- {m.get('error','negative flux')}")

    # Differential photometry — ensemble zero-point
    if len(comp_fluxes) >= 2 and "error" not in ssc_m and ssc_m["net_flux"] > 0:
        print(f"\n  Differential photometry (ensemble zero-point):")
        ssc_inst  = -2.5 * math.log10(ssc_m["net_flux"])
        zp_values = []
        for label, vmag, flux in comp_fluxes:
            if flux > 0:
                inst = -2.5 * math.log10(flux)
                zp   = vmag - inst
                zp_values.append(zp)
                print(f"    {label}: V={vmag:.1f}  inst={inst:.3f}  ZP={zp:.3f}")

        zp  = sum(zp_values) / len(zp_values)
        mag = ssc_inst + zp
        print(f"\n    Zero-point (ensemble): {zp:.3f}")
        print(f"    SS Cyg inst mag:       {ssc_inst:.3f}")
        print(f"    SS Cyg estimated mag:  {mag:.2f}")
        print(f"\n    NOTE: DSS2 Blue != V band.")
        print(f"    With real IMX585 frames use CV or TG band calibration.")

    print(f"\n{'='*62}")
    print("  Pipeline functional. Ready for IMX585 frames.")
    print(f"{'='*62}\n")


# ---------------------------------------------------------------------------
# Coordinate utilities
# ---------------------------------------------------------------------------

def _hours_to_hms(hours: float) -> str:
    h = int(hours)
    m = int((hours - h) * 60)
    s = ((hours - h) * 60 - m) * 60
    return f"{h:02d}:{m:02d}:{s:05.2f}"


def _deg_to_dms(deg: float) -> str:
    sign = "+" if deg >= 0 else "-"
    deg  = abs(deg)
    d    = int(deg)
    m    = int((deg - d) * 60)
    s    = ((deg - d) * 60 - m) * 60
    return f"{sign}{d:02d}:{m:02d}:{s:04.1f}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)-20s  %(levelname)-8s  %(message)s",
    )

    import sys

    if "--test" in sys.argv:
        # Offline photometry test — no telescope required
        # Usage: python pilot.py --test [path/to/file.fits]
        idx = sys.argv.index("--test")
        fits_path = Path(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else Path("ss_cyg.fits")
        run_photometry_test(fits_path)

    else:
        # Live acquisition — requires S30-Pro on network
        target = AcquisitionTarget(
            name          = "SS Cyg",
            ra_hours      = 325.6783 / 15.0,   # 21h 42m 42.8s
            dec_deg       = 43.5861,
            auid          = "000-BCB-641",
            exp_ms        = 5000,
            observer_code = "EDXXX",            # replace with AAVSO observer code
        )

        diamond = DiamondSequence(host=SEESTAR_HOST)
        result  = diamond.acquire(target)

        if result.success:
            print(f"\nAcquired {target.name}")
            print(f"  File   : {result.path}")
            print(f"  Size   : {result.width}x{result.height}")
            print(f"  Elapsed: {result.elapsed_s:.1f}s")
            run_photometry_test(result.path)
        else:
            print(f"\nAcquisition failed: {result.error}")
            sys.exit(1)
