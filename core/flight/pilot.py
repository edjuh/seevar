#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/pilot.py
Version: 1.7.1
Objective: Direct TCP control of ZWO S30-Pro for AAVSO-compliant Sovereign RAW acquisition. Dynamically routes network IP from config.
"""

import json
import logging
import socket
import struct
import time
import math
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
from astropy.coordinates import EarthLocation, AltAz, SkyCoord, get_body
from astropy.time import Time
import astropy.units as u

from core.utils.env_loader import DATA_DIR, ENV_STATUS, load_config

# ---------------------------------------------------------------------------
# Dynamic IP Resolution
# ---------------------------------------------------------------------------
def _get_seestar_ip() -> str:
    cfg = load_config()
    seestars = cfg.get("seestars", [{}])
    ip = seestars[0].get("ip", "TBD")
    if ip == "TBD" or not ip:
        return "10.0.0.1"  # Default AP-mode fallback
    return ip

# ---------------------------------------------------------------------------
# Constants — single source of truth
# ---------------------------------------------------------------------------

SEESTAR_HOST    = _get_seestar_ip()
CTRL_PORT       = 4700          # JSON-RPC control
IMG_PORT        = 4801          # Binary frame stream (preview)

HEADER_SIZE     = 80            # Fixed header bytes per frame
HEADER_FMT      = ">HHHIHHBBHH" # big-endian; use first 20 bytes
FRAME_PREVIEW   = 21            # RAW uint16 Bayer single frame
FRAME_STACK     = 23            # ZIP stacked frame (not used)
MIN_PAYLOAD     = 1000          # Below this = heartbeat, skip

SENSOR_W        = 3840          # IMX585 full resolution (long axis)
SENSOR_H        = 2160
BAYER_PATTERN   = "GRBG"
INSTRUMENT      = "IMX585"
TELESCOPE       = "ZWO S30-Pro"
FILTER_NAME     = "CV"          # Clear/V-proxy for AAVSO

GAIN            = 80            # Fixed sensor gain
FOCALLEN        = 250           # mm
APERTURE        = 30            # mm
PIXSCALE        = 3.74          # arcsec/pixel
RDNOISE         = 1.6           # IMX585 read noise estimate (e-)
PEDESTAL        = 0             # No pedestal applied
SWCREATE        = "SeeVar v1.7.1"

SETTLE_SECONDS  = 8             # Post-slew settle — FIRST LIGHT: replace with
                                # wait_for_event() once event names confirmed
FRAME_TIMEOUT   = 60            # Max wait for preview frame (seconds)
EXP_MS_DEFAULT  = 5000          # Default exposure ms

VETO_BATTERY    = 10            # % — mandatory park below this
VETO_TEMP       = 55.0          # °C — mandatory park above this

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

@dataclass
class TelemetryBlock:
    battery_pct:    Optional[int]   = None
    temp_c:         Optional[float] = None
    charge_online:  Optional[bool]  = None
    charger_status: Optional[str]   = None
    device_name:    Optional[str]   = None
    firmware_ver:   Optional[int]   = None
    level_ok:       bool            = True
    raw:            Optional[dict]  = None
    parse_error:    Optional[str]   = None

    @classmethod
    def from_response(cls, response: Optional[dict]) -> "TelemetryBlock":
        if response is None: return cls(parse_error="No response received")
        try:
            result = response.get("result", response)
            pi  = result.get("pi_status", {})
            dev = result.get("device",    {})
            return cls(
                battery_pct    = pi.get("battery_capacity"),
                temp_c         = pi.get("temp"),
                charge_online  = pi.get("charge_online"),
                charger_status = pi.get("charger_status"),
                device_name    = dev.get("name"),
                firmware_ver   = dev.get("firmware_ver_int"),
                raw            = result,
            )
        except Exception as e:
            return cls(parse_error=str(e), raw=response)

    def veto_reason(self) -> Optional[str]:
        if self.battery_pct is not None and self.battery_pct < VETO_BATTERY:
            return f"Battery critical: {self.battery_pct}% < {VETO_BATTERY}%"
        if self.temp_c is not None and self.temp_c > VETO_TEMP:
            return f"Thermal limit: {self.temp_c}°C > {VETO_TEMP}°C"
        if not self.level_ok:
            return "Level veto: device not level (preflight check failed)"
        return None

    def is_safe(self) -> bool:
        return self.veto_reason() is None

    def summary(self) -> str:
        if self.parse_error: return f"TelemetryBlock parse error: {self.parse_error}"
        return f"bat={self.battery_pct}% temp={self.temp_c}°C charger={self.charger_status} online={self.charge_online} fw={self.firmware_ver}"

# ---------------------------------------------------------------------------
# Low-level TCP helpers
# ---------------------------------------------------------------------------

def recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    try: data = sock.recv(n, socket.MSG_WAITALL)
    except socket.timeout: return None
    except socket.error: return None
    if data is None or len(data) == 0 or len(data) != n: return None
    return data

def parse_header(header: bytes) -> Tuple[int, int, int, int]:
    if header is None or len(header) < 20: return 0, 0, 0, 0
    try:
        _s1, _s2, _s3, size, _s5, _s6, code, frame_id, width, height = struct.unpack(HEADER_FMT, header[:20])
        return size, frame_id, width, height
    except struct.error: return 0, 0, 0, 0

# ---------------------------------------------------------------------------
# Control Socket (TCP — port 4700)
# ---------------------------------------------------------------------------

class ControlSocket:
    """
    JSON-RPC client for port 4700.

    Port 4700 is a stateful event stream. The telescope pushes unsolicited
    telemetry (PiStatus, ViewState, etc.) on the same connection as command
    responses. recv_response() loops the stream and matches by cmd_id,
    dropping all unsolicited Event packets. This eliminates the race
    condition where a stray Event is mistaken for a command ACK.

    send()        → Tuple[bool, int]  (ok, cmd_id)
    recv_response → ID-matched, Event-filtered
    send_and_recv → convenience wrapper
    """

    def __init__(self, host: str = SEESTAR_HOST, port: int = CTRL_PORT, timeout: float = 15.0):
        self.host, self.port, self.timeout = host, port, timeout
        self._sock: Optional[socket.socket] = None
        self._cmdid: int = 10000
        
        # Concurrency protections
        self._send_lock = threading.Lock()
        self._stop_hb = threading.Event()
        self._hb_thread: Optional[threading.Thread] = None

    def connect(self) -> bool:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(self.timeout)
            s.connect((self.host, self.port))
            self._sock = s
            
            # Ignite Heartbeat thread
            self._stop_hb.clear()
            self._hb_thread = threading.Thread(target=self._heartbeat_worker, daemon=True)
            self._hb_thread.start()
            
            return True
        except socket.error:
            return False

    def disconnect(self):
        self._stop_hb.set()
        if self._hb_thread and self._hb_thread.is_alive():
            self._hb_thread.join(timeout=2.0)
            
        if self._sock:
            try: self._sock.close()
            except Exception: pass
            self._sock = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()
        
    def _heartbeat_worker(self):
        """Background loop pushing get_app_state every 5 seconds to bypass idle drop."""
        payload = json.dumps({"jsonrpc": "2.0", "method": "get_app_state", "id": 99999}) + "\r\n"
        cmd_bytes = payload.encode("utf-8")

        while not self._stop_hb.is_set():
            try:
                with self._send_lock:
                    if self._sock:
                        self._sock.sendall(cmd_bytes)
            except Exception as e:
                logger.debug("Heartbeat transmission failure: %s", e)
                break
            
            self._stop_hb.wait(5.0)

    def send(self, method: str, params=None) -> Tuple[bool, int]:
        """
        Send a JSON-RPC command.
        Returns (True, cmd_id) on success, (False, -1) on failure.
        cmd_id is used by recv_response() to match the reply.
        """
        if self._sock is None:
            return False, -1
        cmd_id = self._cmdid
        msg = {"id": cmd_id, "method": method}
        if params is not None:
            msg["params"] = params
        self._cmdid += 1
        
        try:
            with self._send_lock:
                self._sock.sendall((json.dumps(msg) + "\r\n").encode("utf-8"))
            return True, cmd_id
        except socket.error:
            return False, -1

    def recv_response(self, expected_id: int) -> Optional[dict]:
        """
        Read the port 4700 stream until the response matching expected_id
        is found. Unsolicited Event packets are logged at DEBUG and discarded.
        Returns None on timeout, connection loss, or send failure (expected_id == -1).
        """
        if self._sock is None or expected_id == -1:
            return None

        buf = b""
        deadline = time.monotonic() + self.timeout

        try:
            while time.monotonic() < deadline:
                try:
                    chunk = self._sock.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf += chunk

                while b"\r\n" in buf:
                    line, buf = buf.split(b"\r\n", 1)
                    if not line:
                        continue
                    try:
                        msg = json.loads(line.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue

                    # Unsolicited telemetry — drop and keep waiting
                    if "Event" in msg:
                        logger.debug("Dropping unsolicited Event: %s", msg.get("Event"))
                        continue

                    # Matched response
                    if msg.get("id") == expected_id:
                        return msg

                    # Response for a different cmd_id — log and discard
                    logger.debug("Dropping stale response id=%s (expected %d)",
                                 msg.get("id"), expected_id)

        except socket.error as e:
            logger.warning("ControlSocket recv error: %s", e)

        logger.warning("recv_response timed out waiting for id=%d", expected_id)
        return None

    def send_and_recv(self, method: str, params=None) -> Optional[dict]:
        """Send command and return the matched response. Returns None on failure."""
        ok, cmd_id = self.send(method, params)
        if not ok:
            return None
        return self.recv_response(expected_id=cmd_id)

# ---------------------------------------------------------------------------
# Image Socket (TCP — port 4801)
# ---------------------------------------------------------------------------

class ImageSocket:
    def __init__(self, host: str = SEESTAR_HOST, port: int = IMG_PORT, timeout: float = FRAME_TIMEOUT):
        self.host, self.port, self.timeout = host, port, timeout

    def capture_one_preview(self) -> Tuple[Optional[bytes], int, int]:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.host, self.port))
        except socket.error:
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
                if frame_id == FRAME_PREVIEW: return data, width, height
        finally:
            sock.close()
        return None, 0, 0

# ---------------------------------------------------------------------------
# FITS construction
# ---------------------------------------------------------------------------

def _read_gps_ram() -> dict:
    try:
        data = json.loads(ENV_STATUS.read_text())
        lat  = float(data.get("lat",       0.0))
        lon  = float(data.get("lon",       0.0))
        elev = float(data.get("elevation", 0.0))
        return {"lat": lat, "lon": lon, "elevation": elev}
    except Exception:
        return {"lat": 0.0, "lon": 0.0, "elevation": 0.0}

def sovereign_stamp(target: AcquisitionTarget, utc_obs: datetime,
                    width: int, height: int,
                    ccd_temp: Optional[float] = None) -> dict:
    ra_deg     = target.ra_hours * 15.0
    t_astropy  = Time(utc_obs)

    gps = _read_gps_ram()
    site_lat, site_lon, site_elev = gps["lat"], gps["lon"], gps["elevation"]
    gps_valid = not (site_lat == 0.0 and site_lon == 0.0)

    airmass = moon_phase = moon_alt = None
    if gps_valid:
        try:
            location     = EarthLocation(lat=site_lat * u.deg,
                                         lon=site_lon * u.deg,
                                         height=site_elev * u.m)
            frame        = AltAz(obstime=t_astropy, location=location)
            target_coord = SkyCoord(ra=ra_deg * u.deg,
                                    dec=target.dec_deg * u.deg, frame="icrs")
            altaz        = target_coord.transform_to(frame)
            alt_deg      = float(altaz.alt.deg)
            if alt_deg > 0.0:
                airmass = round(1.0 / math.sin(math.radians(alt_deg)), 4)

            moon      = get_body("moon", t_astropy, location)
            moon_alt  = round(float(moon.transform_to(frame).alt.deg), 2)
            sun       = get_body("sun",  t_astropy, location)
            sep       = moon.separation(sun).deg
            moon_phase = round(
                min(max((1.0 - math.cos(math.radians(sep))) / 2.0, 0.0), 1.0), 4
            )
        except Exception:
            pass

    h = {
        "SIMPLE":   True,   "BITPIX": 16,  "NAXIS":  2,
        "NAXIS1":   width,  "NAXIS2": height,
        "BZERO":    32768.0, "BSCALE": 1.0,
        "OBJECT":   target.name,
        "OBJCTRA":  _hours_to_hms(target.ra_hours),
        "OBJCTDEC": _deg_to_dms(target.dec_deg),
        "CRVAL1":   ra_deg,       "CRVAL2": target.dec_deg,
        "CRPIX1":   width / 2.0,  "CRPIX2": height / 2.0,
        "CDELT1":  -0.001042,     "CDELT2":  0.001042,
        "CTYPE1":  "RA---TAN",    "CTYPE2": "DEC--TAN",
        "DATE-OBS": utc_obs.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
        "EXPTIME":  target.exp_ms / 1000.0,
        "INSTRUME": INSTRUMENT,   "TELESCOP": TELESCOPE,
        "FILTER":   FILTER_NAME,  "BAYERPAT": BAYER_PATTERN,
        "GAIN":     GAIN,         "FOCALLEN": FOCALLEN,
        "APERTURE": APERTURE,     "PIXSCALE": PIXSCALE,
        "RDNOISE":  RDNOISE,      "PEDESTAL": PEDESTAL,
        "OBSERVER": target.observer_code or "UNKNOWN",
        "SITELAT":  site_lat, "SITELONG": site_lon, "SITEELEV": site_elev,
        "SWCREATE": SWCREATE,
    }

    h["CCD-TEMP"] = ccd_temp if ccd_temp is not None else "UNKNOWN"
    if airmass    is not None: h["AIRMASS"]   = airmass
    if moon_phase is not None: h["MOONPHASE"] = moon_phase
    if moon_alt   is not None: h["MOONALT"]   = moon_alt
    if target.auid:            h["AUID"]      = target.auid
    h["JD"] = round(t_astropy.jd, 6)

    return h

def write_fits(array: np.ndarray, header_dict: dict, output_path: Path) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    array_signed = (array.astype(np.int32) - 32768).astype(np.int16)
    if array_signed.dtype.byteorder not in (">",):
        array_signed = array_signed.byteswap().view(array_signed.dtype.newbyteorder(">"))

    def card(key: str, value, comment: str = "") -> str:
        key = key.upper()[:8].ljust(8)
        if isinstance(value, bool):   val_str = f"{'T' if value else 'F':>20}"
        elif isinstance(value, int):  val_str = f"{value:>20}"
        elif isinstance(value, float):val_str = f"{value:>20.10G}"
        elif isinstance(value, str):  val_str = f"'{value.replace(chr(39), chr(39)*2):<8}'".ljust(20)
        else:                         val_str = f"'{str(value):<8}'".ljust(20)
        return f"{key}= {val_str}{f' / {comment}' if comment else ''}"[:80].ljust(80)

    priority_keys = ["SIMPLE", "BITPIX", "NAXIS", "NAXIS1", "NAXIS2", "BZERO", "BSCALE"]
    records  = [card(k, header_dict[k]) for k in priority_keys if k in header_dict]
    records += [card(k, v) for k, v in header_dict.items() if k not in priority_keys]
    records.append("COMMENT   SeeVar v1.7.1 -- BZERO Signed-Integer Protected".ljust(80))
    records.append("END".ljust(80))

    while (len(records) * 80) % 2880 != 0:
        records.append(" " * 80)

    header_bytes = "".join(records).encode("ascii")
    data_bytes   = array_signed.tobytes()
    remainder    = len(data_bytes) % 2880
    if remainder:
        data_bytes += b"\x00" * (2880 - remainder)

    try:
        with open(output_path, "wb") as f:
            f.write(header_bytes)
            f.write(data_bytes)
        return True
    except OSError:
        return False

# ---------------------------------------------------------------------------
# Diamond Sequence
# ---------------------------------------------------------------------------

class DiamondSequence:
    def __init__(self, host: str = SEESTAR_HOST):
        self.host = host

    def init_session(self, level_ok: bool = True) -> TelemetryBlock:
        ctrl = ControlSocket(host=self.host)
        if not ctrl.connect():
            t = TelemetryBlock(parse_error="Control socket connect failed")
            t.level_ok = level_ok
            return t
        try:
            # Fire-and-forget stops — no response needed
            _ok, _ = ctrl.send("iscope_stop_view")

            gps = _read_gps_ram()
            if gps["lat"] != 0.0 or gps["lon"] != 0.0:
                _ok, _ = ctrl.send("set_user_location",
                                   {"lat": gps["lat"], "lon": gps["lon"], "force": True})

            ctrl.send_and_recv("set_control_value", ["gain", GAIN])

            resp_state = ctrl.send_and_recv("get_device_state")
            telemetry  = TelemetryBlock.from_response(resp_state)
            telemetry.level_ok = level_ok

            if telemetry.veto_reason():
                return telemetry

            ctrl.send_and_recv("scope_get_track_state")
            _ok, _ = ctrl.send("scope_set_track_state", [True])
            ctrl.send_and_recv("scope_get_ra_dec")
            return telemetry

        except Exception as e:
            t = TelemetryBlock(parse_error=f"init_session exception: {e}")
            t.level_ok = level_ok
            return t
        finally:
            ctrl.disconnect()

    def acquire(self, target: AcquisitionTarget,
                status_cb=None,
                telemetry: Optional[TelemetryBlock] = None) -> FrameResult:

        def notify(step, msg):
            if status_cb: status_cb(f"[{step}] {msg}")
            logger.info("[%s] %s", step, msg)

        t_start  = time.monotonic()
        utc_obs  = datetime.now(timezone.utc)
        ccd_temp = telemetry.temp_c if telemetry else None

        ctrl = ControlSocket(host=self.host)
        if not ctrl.connect():
            return FrameResult(success=False, error="Control socket connect failed")

        try:
            # T1 — Set exposure time
            notify("T1", f"set_setting exp_ms={target.exp_ms} for {target.name}")
            _ok, _ = ctrl.send("set_setting", {"exp_ms": {"stack_l": target.exp_ms}})

            # T2 — Slew to target
            # FIRST LIGHT: replace time.sleep with wait_for_event() once
            # event field names confirmed via ssh_monitor.py on Wilhelmina.
            notify("T2", f"scope_goto RA={target.ra_hours:.4f}h DEC={target.dec_deg:.4f}°")
            _ok, _ = ctrl.send("scope_goto", [target.ra_hours, target.dec_deg])
            time.sleep(SETTLE_SECONDS)

            # T3 — Autofocus
            # FIRST LIGHT: confirm get_event_state response shape and add
            # completion poll. Firmware typo preserved — must be one 's'.
            notify("T3", "start_auto_focuse")
            _ok, _ = ctrl.send("start_auto_focuse")

            # T4 — Open frame stream
            notify("T4", "iscope_start_view mode=star")
            _ok, _ = ctrl.send("iscope_start_view", {"mode": "star"})
            time.sleep(2.0)

        except Exception as e:
            ctrl.disconnect()
            return FrameResult(success=False, error=f"Control sequence error: {e}")

        # T5 — Receive science frame on port 4801
        notify("T5", "Receiving RAW frame port 4801...")
        img_sock = ImageSocket(host=self.host, timeout=FRAME_TIMEOUT)
        raw_data, width, height = img_sock.capture_one_preview()

        # T6 — Close stream and check hardware state
        try:
            _ok, _ = ctrl.send("iscope_stop_view")
            resp_state    = ctrl.send_and_recv("get_device_state")
            post_telemetry = TelemetryBlock.from_response(resp_state)
            post_telemetry.level_ok = telemetry.level_ok if telemetry else True
            ccd_temp = post_telemetry.temp_c or ccd_temp
            veto = post_telemetry.veto_reason()
            if veto and raw_data is None:
                return FrameResult(success=False, error=f"Veto + no frame: {veto}")
        finally:
            ctrl.disconnect()

        if raw_data is None:
            return FrameResult(success=False, error="No preview frame received")

        expected = width * height * 2
        if len(raw_data) != expected:
            return FrameResult(success=False,
                               error=f"Payload size mismatch: got {len(raw_data)}, expected {expected}")

        # T7 — Write FITS
        notify("T7", f"Writing FITS — AUID={target.auid} CCD-TEMP={ccd_temp}")
        array     = np.frombuffer(raw_data, dtype=np.uint16).reshape(height, width)
        LOCAL_BUFFER.mkdir(parents=True, exist_ok=True)
        safe_name = target.name.replace(" ", "_").replace("/", "-")
        out_path  = LOCAL_BUFFER / f"{safe_name}_{utc_obs.strftime('%Y%m%dT%H%M%S')}_Raw.fits"

        header  = sovereign_stamp(target, utc_obs, width, height, ccd_temp=ccd_temp)
        ok      = write_fits(array, header, out_path)
        elapsed = time.monotonic() - t_start

        if ok:
            return FrameResult(success=True, path=out_path,
                               width=width, height=height, elapsed_s=elapsed)
        return FrameResult(success=False, error="FITS write failed", elapsed_s=elapsed)

# ---------------------------------------------------------------------------
# Coordinate helpers
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

if __name__ == "__main__":
    pass

