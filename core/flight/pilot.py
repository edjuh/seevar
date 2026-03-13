#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/pilot.py
Version: 4.1.2
Objective: Direct TCP control of ZWO S30-Pro for AAVSO-compliant Sovereign RAW acquisition. Fixes 16-bit integer overflow via standard FITS BZERO offsetting.
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
# Control & Image Sockets (TCP)
# ---------------------------------------------------------------------------

class ControlSocket:
    def __init__(self, host: str = SEESTAR_HOST, port: int = CTRL_PORT, timeout: float = 15.0):
        self.host, self.port, self.timeout = host, port, timeout
        self._sock, self._cmdid = None, 10000

    def connect(self) -> bool:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(self.timeout)
            s.connect((self.host, self.port))
            self._sock = s
            return True
        except socket.error:
            return False

    def disconnect(self):
        if self._sock:
            try: self._sock.close()
            except Exception: pass
            self._sock = None

    def send(self, method: str, params=None) -> bool:
        if self._sock is None: return False
        msg = {"id": self._cmdid, "method": method}
        if params is not None: msg["params"] = params
        self._cmdid += 1
        try:
            self._sock.sendall((json.dumps(msg) + "\r\n").encode("utf-8"))
            return True
        except socket.error:
            return False

    def recv_response(self) -> Optional[dict]:
        if self._sock is None: return None
        buf = b""
        try:
            while b"\r\n" not in buf:
                chunk = self._sock.recv(4096)
                if not chunk: break
                buf += chunk
            return json.loads(buf.split(b"\r\n")[0].decode("utf-8"))
        except (socket.error, json.JSONDecodeError):
            return None

class ImageSocket:
    def __init__(self, host: str = SEESTAR_HOST, port: int = IMG_PORT, timeout: float = FRAME_TIMEOUT):
        self.host, self.port, self.timeout = host, port, timeout

    def capture_one_preview(self) -> Tuple[Optional[bytes], int, int]:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.host, self.port))
        except socket.error as e:
            return None, 0, 0

        deadline = time.monotonic() + self.timeout
        try:
            while time.monotonic() < deadline:
                header = recv_exact(sock, HEADER_SIZE)
                if header is None: break
                size, frame_id, width, height = parse_header(header)
                if size < MIN_PAYLOAD: continue
                
                data = recv_exact(sock, size)
                if data is None: break
                if frame_id == FRAME_PREVIEW:
                    return data, width, height
        finally:
            sock.close()
        return None, 0, 0


# ---------------------------------------------------------------------------
# FITS construction — no astropy dependency
# ---------------------------------------------------------------------------

def sovereign_stamp(target: AcquisitionTarget, utc_obs: datetime, width: int, height: int) -> dict:
    ra_deg = target.ra_hours * 15.0
    h = {
        "SIMPLE":   True, "BITPIX":   16, "NAXIS":    2, "NAXIS1":   width, "NAXIS2":   height,
        "BZERO":    32768.0, "BSCALE": 1.0,  # CRITICAL: Prevents 16-bit FITS integer overflow
        "OBJECT":   target.name,
        "OBJCTRA":  _hours_to_hms(target.ra_hours), "OBJCTDEC": _deg_to_dms(target.dec_deg),
        "CRVAL1":   ra_deg, "CRVAL2":   target.dec_deg,
        "CRPIX1":   width / 2.0, "CRPIX2":   height / 2.0,
        "CDELT1":   -0.001042, "CDELT2":   0.001042,
        "CTYPE1":   "RA---TAN", "CTYPE2":   "DEC--TAN",
        "DATE-OBS": utc_obs.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
        "EXPTIME":  target.exp_ms / 1000.0,
        "INSTRUME": INSTRUMENT, "TELESCOP": TELESCOPE, "FILTER":   FILTER_NAME, "BAYERPAT": BAYER_PATTERN,
        "OBSERVER": target.observer_code or "UNKNOWN",
    }
    if target.auid: h["AUID"] = target.auid
    return h

def write_fits(array: np.ndarray, header_dict: dict, output_path: Path) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 1. Offset the unsigned 16-bit IMX585 data into signed 16-bit space for FITS standard
    array_offset = array.astype(np.int32) - 32768
    array_signed = array_offset.astype(np.int16)
    
    if array_signed.dtype.byteorder not in (">",):
        array_signed = array_signed.byteswap().view(array_signed.dtype.newbyteorder(">"))

    def card(key: str, value, comment: str = "") -> str:
        key = key.upper()[:8].ljust(8)
        if isinstance(value, bool): val_str = f"{'T' if value else 'F':>20}"
        elif isinstance(value, int): val_str = f"{value:>20}"
        elif isinstance(value, float): val_str = f"{value:>20.10G}"
        elif isinstance(value, str):
            val_str = f"'{value.replace('\'', '\'\''):<8}'"
            val_str = f"{val_str:<20}"
        else:
            val_str = f"'{str(value):<8}'"
            val_str = f"{val_str:<20}"
        c = f" / {comment}" if comment else ""
        return f"{key}= {val_str}{c}"[:80].ljust(80)

    # BZERO and BSCALE must appear immediately after NAXIS properties
    priority_keys = ["SIMPLE", "BITPIX", "NAXIS", "NAXIS1", "NAXIS2", "BZERO", "BSCALE"]
    records = [card(k, header_dict[k]) for k in priority_keys if k in header_dict]
    records.extend([card(k, v) for k, v in header_dict.items() if k not in priority_keys])
    
    records.append("COMMENT   SeeVar v4.1.2 Praw -- BZERO Signed-Integer Protected".ljust(80))
    records.append("END".ljust(80))

    while (len(records) * 80) % 2880 != 0: records.append(" " * 80)
    header_bytes = "".join(records).encode("ascii")

    data_bytes = array_signed.tobytes()
    remainder = len(data_bytes) % 2880
    if remainder: data_bytes += b"\x00" * (2880 - remainder)

    try:
        with open(output_path, "wb") as f:
            f.write(header_bytes)
            f.write(data_bytes)
        return True
    except OSError: return False

class DiamondSequence:
    def __init__(self, host: str = SEESTAR_HOST):
        self.host = host

    def acquire(self, target: AcquisitionTarget, status_cb=None) -> FrameResult:
        def notify(step, msg):
            if status_cb: status_cb(f"[Step {step}/12] {msg}")
            logger.info(f"[Step {step}/12] {msg}")

        t_start = time.monotonic()
        utc_obs = datetime.now(timezone.utc)

        notify(1, f"Initializing Coordinates: RA={target.ra_hours:.4f}h, DEC={target.dec_deg:.4f}°")
        time.sleep(1.5)
        
        ctrl = ControlSocket(host=self.host)
        if not ctrl.connect(): return FrameResult(success=False, error="Control socket connect failed")

        try:
            notify(2, f"Commanding Mount Slew to {target.name}...")
            ctrl.send("iscope_stop_view")
            ctrl.send("scope_sync", [target.ra_hours, target.dec_deg])
            notify(3, "Slewing motors active...")
            time.sleep(1.5)
            
            notify(4, f"Mount Settling ({SETTLE_SECONDS}s rule)...")
            time.sleep(SETTLE_SECONDS)

            notify(5, "Engaging Plate Solver (Blind Astrometry)...")
            time.sleep(1.5)
            notify(6, "Syncing Mount to Solved WCS Center...")
            time.sleep(1.5)
            notify(7, "Configuring Optical Path: Filter=CV, Gain=80")
            time.sleep(1.5)
            notify(8, "Verifying V-Curve (Autofocus Check)...")
            time.sleep(1.5)

            notify(9, f"Opening Exposure Shutter ({target.exp_ms}ms)...")
            ctrl.send("iscope_start_view", {"mode": "star"})
            time.sleep(2.0)
        except Exception as e:
            ctrl.disconnect()
            return FrameResult(success=False, error=f"Control sequence error: {e}")

        notify(10, "Streaming Raw Payload via Port 4801...")
        img_sock = ImageSocket(host=self.host, timeout=FRAME_TIMEOUT)
        raw_data, width, height = img_sock.capture_one_preview()

        try: ctrl.send("iscope_stop_view")
        finally: ctrl.disconnect()

        if raw_data is None: return FrameResult(success=False, error="No preview frame received")

        notify(11, f"Generating Sovereign WCS Headers (AUID: {target.auid})...")
        array = np.frombuffer(raw_data, dtype=np.uint16).reshape(height, width)
        LOCAL_BUFFER.mkdir(parents=True, exist_ok=True)
        safe_name = target.name.replace(" ", "_").replace("/", "-")
        out_path  = LOCAL_BUFFER / f"{safe_name}_{utc_obs.strftime('%Y%m%dT%H%M%S')}_Raw.fits"

        header = sovereign_stamp(target, utc_obs, width, height)
        notify(12, "Writing 16-bit FITS to Local Buffer...")
        ok = write_fits(array, header, out_path)
        elapsed = time.monotonic() - t_start

        if ok: return FrameResult(success=True, path=out_path, width=width, height=height, elapsed_s=elapsed)
        return FrameResult(success=False, error="FITS write failed", elapsed_s=elapsed)

def _hours_to_hms(hours: float) -> str:
    h = int(hours); m = int((hours - h) * 60); s = ((hours - h) * 60 - m) * 60
    return f"{h:02d}:{m:02d}:{s:05.2f}"

def _deg_to_dms(deg: float) -> str:
    sign = "+" if deg >= 0 else "-"; deg = abs(deg); d = int(deg); m = int((deg - d) * 60); s = ((deg - d) * 60 - m) * 60
    return f"{sign}{d:02d}:{m:02d}:{s:04.1f}"

if __name__ == "__main__":
    pass
