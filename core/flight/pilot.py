#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/pilot.py
Version: 2.0.0
Objective: Direct control of ZWO S30-Pro for AAVSO-compliant Sovereign RAW
           acquisition. Hybrid architecture: Alpaca (port 32323) for motor
           control, JSON-RPC (port 4700) for camera/event commands.

Architecture (firmware 7.18 / March 2026):
  AlpacaControl  — park, unpark, slew, track via HTTP port 32323
  ControlSocket  — JSON-RPC camera/session commands via TCP port 4700
                   with correct UDP handshake + master claim + heartbeat
  ImageSocket    — Binary frame stream via TCP port 4801
  DiamondSequence — Full acquisition sequence using hybrid path
"""

import json
import logging
import math
import socket
import struct
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple
from urllib import request as urllib_request
from urllib.parse import urlencode

import numpy as np
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body
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
    if ip in ("TBD", "", None):
        return "10.0.0.1"
    return ip

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SEESTAR_HOST    = _get_seestar_ip()
CTRL_PORT       = 4700
IMG_PORT        = 4801
ALPACA_PORT     = 32323
DISCOVERY_PORT  = 4720          # UDP — scan_iscope broadcast

HEADER_SIZE     = 80
HEADER_FMT      = ">HHHIHHBBHH"
FRAME_PREVIEW   = 21            # RAW uint16 Bayer
FRAME_STACK     = 23            # ZIP stack (not used)
MIN_PAYLOAD     = 1000          # Below = heartbeat, skip

SENSOR_W        = 3840
SENSOR_H        = 2160
BAYER_PATTERN   = "GRBG"
INSTRUMENT      = "IMX585"
TELESCOPE       = "ZWO S30-Pro"
FILTER_NAME     = "TG"          # TG = Tri-colour Green proxy for AAVSO V-band
GAIN            = 80
FOCALLEN        = 160           # mm — S30-Pro confirmed spec
APERTURE        = 30            # mm
PIXSCALE        = 3.74          # arcsec/pixel
RDNOISE         = 1.6
PEDESTAL        = 0
SWCREATE        = "SeeVar v2.0.0"

HB_INTERVAL     = 3.0           # seconds — pi_is_verified heartbeat
SETTLE_SECONDS  = 8             # post-slew settle
FRAME_TIMEOUT   = 60
EXP_MS_DEFAULT  = 5000
VETO_BATTERY    = 10
VETO_TEMP       = 55.0

LOCAL_BUFFER    = DATA_DIR / "local_buffer"
logger          = logging.getLogger("seevar.pilot")

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AcquisitionTarget:
    name:          str
    ra_hours:      float
    dec_deg:       float
    auid:          str  = ""
    exp_ms:        int  = EXP_MS_DEFAULT
    observer_code: str  = ""
    n_frames:      int  = 1

@dataclass
class FrameResult:
    success:   bool
    path:      Optional[Path]  = None
    width:     int             = 0
    height:    int             = 0
    elapsed_s: float           = 0.0
    error:     str             = ""

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
        if response is None:
            return cls(parse_error="No response received")
        try:
            result = response.get("result", response)
            pi     = result.get("pi_status", {})
            dev    = result.get("device",    {})
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

    @classmethod
    def from_event_stream(cls, state_path: Path) -> "TelemetryBlock":
        """Read from WilhelminaMonitor /dev/shm/wilhelmina_state.json."""
        try:
            data = json.loads(state_path.read_text())
            return cls(
                battery_pct = data.get("battery_pct"),
                temp_c      = data.get("temp_c"),
                level_ok    = data.get("level_ok", True),
            )
        except Exception as e:
            return cls(parse_error=str(e))

    def veto_reason(self) -> Optional[str]:
        if self.battery_pct is not None and self.battery_pct < VETO_BATTERY:
            return f"Battery critical: {self.battery_pct}% < {VETO_BATTERY}%"
        if self.temp_c is not None and self.temp_c > VETO_TEMP:
            return f"Thermal limit: {self.temp_c}°C > {VETO_TEMP}°C"
        if not self.level_ok:
            return "Level veto: device not level"
        return None

    def is_safe(self) -> bool:
        return self.veto_reason() is None

    def summary(self) -> str:
        if self.parse_error:
            return f"TelemetryBlock error: {self.parse_error}"
        return (f"bat={self.battery_pct}% temp={self.temp_c}°C "
                f"charger={self.charger_status} fw={self.firmware_ver}")

# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    try:
        data = sock.recv(n, socket.MSG_WAITALL)
    except (socket.timeout, socket.error):
        return None
    if not data or len(data) != n:
        return None
    return data

def parse_header(header: bytes) -> Tuple[int, int, int, int]:
    if header is None or len(header) < 20:
        return 0, 0, 0, 0
    try:
        _s1, _s2, _s3, size, _s5, _s6, code, frame_id, width, height = \
            struct.unpack(HEADER_FMT, header[:20])
        return size, frame_id, width, height
    except struct.error:
        return 0, 0, 0, 0

# ---------------------------------------------------------------------------
# Alpaca HTTP Control (port 32323) — motor/mount commands
# ---------------------------------------------------------------------------

class AlpacaControl:
    """
    ASCOM Alpaca HTTP client for port 32323.

    No session lock. No heartbeat required. Works regardless of phone
    app connection. Use for: park, unpark, slew, tracking, sync, abort.

    Camera/focuser/viewing modes are NOT available via Alpaca —
    those go through ControlSocket (port 4700).
    """

    def __init__(self, host: str = SEESTAR_HOST, port: int = ALPACA_PORT,
                 timeout: float = 30.0):
        self.base    = f"http://{host}:{port}/api/v1/telescope/0"
        self.timeout = timeout
        self._txid   = 1

    def _get(self, endpoint: str) -> dict:
        url = f"{self.base}/{endpoint}?ClientID=1&ClientTransactionID={self._txid}"
        self._txid += 1
        try:
            with urllib_request.urlopen(url, timeout=self.timeout) as r:
                return json.loads(r.read())
        except Exception as e:
            return {"ErrorNumber": -1, "ErrorMessage": str(e)}

    def _put(self, endpoint: str, params: dict) -> dict:
        params["ClientID"] = 1
        params["ClientTransactionID"] = self._txid
        self._txid += 1
        data = urlencode(params).encode()
        req  = urllib_request.Request(
            f"{self.base}/{endpoint}", data=data, method="PUT",
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        try:
            with urllib_request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except Exception as e:
            return {"ErrorNumber": -1, "ErrorMessage": str(e)}

    def _ok(self, resp: dict) -> bool:
        return resp.get("ErrorNumber", -1) == 0

    def connect(self) -> bool:
        return self._ok(self._put("connected", {"Connected": "true"}))

    def unpark(self) -> bool:
        return self._ok(self._put("unpark", {}))

    def park(self) -> bool:
        return self._ok(self._put("park", {}))

    def slew_to(self, ra_hours: float, dec_deg: float) -> bool:
        resp = self._put("slewtocoordinatesasync", {
            "RightAscension": str(ra_hours),
            "Declination":    str(dec_deg),
        })
        return self._ok(resp)

    def abort_slew(self) -> bool:
        return self._ok(self._put("abortslew", {}))

    def set_tracking(self, enabled: bool) -> bool:
        return self._ok(self._put("tracking", {
            "Tracking": "true" if enabled else "false"
        }))

    def sync_to(self, ra_hours: float, dec_deg: float) -> bool:
        return self._ok(self._put("synctocoordinates", {
            "RightAscension": str(ra_hours),
            "Declination":    str(dec_deg),
        }))

    def wait_for_slew(self, poll_s: float = 2.0, timeout_s: float = 120.0) -> bool:
        """Poll until slewing=False or timeout."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            resp = self._get("slewing")
            if self._ok(resp) and not resp.get("Value", True):
                return True
            time.sleep(poll_s)
        return False

    def get_position(self) -> Tuple[float, float]:
        """Returns (ra_hours, dec_deg) or (0, 0) on error."""
        ra  = self._get("rightascension")
        dec = self._get("declination")
        if self._ok(ra) and self._ok(dec):
            return ra["Value"], dec["Value"]
        return 0.0, 0.0

    def get_state(self) -> dict:
        """Return key mount state fields."""
        return {
            "connected": self._get("connected").get("Value"),
            "tracking":  self._get("tracking").get("Value"),
            "slewing":   self._get("slewing").get("Value"),
            "atpark":    self._get("atpark").get("Value"),
            "athome":    self._get("athome").get("Value"),
            "ra":        self._get("rightascension").get("Value"),
            "dec":       self._get("declination").get("Value"),
            "altitude":  self._get("altitude").get("Value"),
            "azimuth":   self._get("azimuth").get("Value"),
        }

# ---------------------------------------------------------------------------
# Control Socket (TCP — port 4700) — camera/session commands
# ---------------------------------------------------------------------------

class ControlSocket:
    """
    JSON-RPC client for port 4700.

    Connection sequence (firmware 7.18, per technical reference March 2026):
      1. UDP broadcast scan_iscope to port 4720 (guest mode handshake)
      2. TCP connect to port 4700
      3. Initialization: set_user_location, pi_set_time, pi_is_verified
      4. Master claim: set_setting {"master_cli": true}
      5. Client ID:    set_setting {"cli_name": "SeeVar"}
      6. Heartbeat:    pi_is_verified every 3s (background thread)

    verify parameter (firmware >=2706 with dict params): omit verify.
    verify parameter (any, list params): append "verify" string to list.
    verify parameter (any, no params): add top-level "verify": true.
    S30-Pro firmware 7.18 appears to use the >=2706 ruleset.
    """

    def __init__(self, host: str = SEESTAR_HOST, port: int = CTRL_PORT,
                 timeout: float = 20.0):
        self.host    = host
        self.port    = port
        self.timeout = timeout
        self._sock:     Optional[socket.socket] = None
        self._cmdid:    int = 10000
        self._send_lock = threading.Lock()
        self._stop_hb   = threading.Event()
        self._hb_thread: Optional[threading.Thread] = None

    def _udp_handshake(self):
        """Broadcast scan_iscope to port 4720 — guest mode handshake."""
        try:
            msg = json.dumps({
                "jsonrpc": "2.0", "id": 1,
                "method":  "scan_iscope",
                "verify":  True
            }).encode()
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                udp.settimeout(2.0)
                udp.sendto(msg, ("255.255.255.255", DISCOVERY_PORT))
                logger.debug("UDP scan_iscope broadcast sent to port %d", DISCOVERY_PORT)
        except Exception as e:
            logger.debug("UDP handshake failed (non-fatal): %s", e)

    def _build_msg(self, method: str, params=None) -> dict:
        """Build JSON-RPC message with correct verify parameter."""
        cmd_id = self._cmdid
        self._cmdid += 1
        msg = {"jsonrpc": "2.0", "id": cmd_id, "method": method}
        if params is None:
            msg["verify"] = True
        elif isinstance(params, list):
            params = list(params) + ["verify"]
            msg["params"] = params
        else:
            # dict params, firmware >=2706: omit verify
            msg["params"] = params
        return msg, cmd_id

    def connect(self) -> bool:
        """UDP handshake → TCP connect → init sequence → master claim → heartbeat."""
        self._udp_handshake()
        time.sleep(0.5)

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(self.timeout)
            s.connect((self.host, self.port))
            self._sock = s
        except socket.error as e:
            logger.error("ControlSocket connect failed: %s", e)
            return False

        # Initialization sequence
        self._init_sequence()

        # Start heartbeat
        self._stop_hb.clear()
        self._hb_thread = threading.Thread(
            target=self._heartbeat_worker, daemon=True, name="SeeVar-HB"
        )
        self._hb_thread.start()

        logger.info("ControlSocket connected and initialized @ %s:%d", self.host, self.port)
        return True

    def _init_sequence(self):
        """Fire-and-forget initialization commands."""
        gps = _read_gps_ram()
        if gps["lat"] != 0.0 or gps["lon"] != 0.0:
            self._fire("set_user_location",
                       {"lat": gps["lat"], "lon": gps["lon"], "force": True})

        now = datetime.now(timezone.utc)
        self._fire("pi_set_time", {
            "year": now.year, "month": now.month, "day": now.day,
            "hour": now.hour, "minute": now.minute, "second": now.second,
            "time_zone": "UTC"
        })

        self._fire("pi_is_verified")
        time.sleep(0.3)

        # Claim master control
        self._fire("set_setting", {"master_cli": True})
        self._fire("set_setting", {"cli_name": "SeeVar"})
        time.sleep(0.3)
        logger.debug("Init sequence complete — master claimed")

    def _fire(self, method: str, params=None):
        """Send without waiting for response."""
        if self._sock is None:
            return
        msg, _ = self._build_msg(method, params)
        try:
            with self._send_lock:
                self._sock.sendall((json.dumps(msg) + "\r\n").encode("utf-8"))
        except socket.error:
            pass

    def disconnect(self):
        self._stop_hb.set()
        if self._hb_thread and self._hb_thread.is_alive():
            self._hb_thread.join(timeout=2.0)
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()

    def _heartbeat_worker(self):
        """Send pi_is_verified every 3s to keep connection alive."""
        while not self._stop_hb.is_set():
            self._fire("pi_is_verified")
            self._stop_hb.wait(HB_INTERVAL)

    def send(self, method: str, params=None) -> Tuple[bool, int]:
        if self._sock is None:
            return False, -1
        msg, cmd_id = self._build_msg(method, params)
        try:
            with self._send_lock:
                self._sock.sendall((json.dumps(msg) + "\r\n").encode("utf-8"))
            return True, cmd_id
        except socket.error:
            return False, -1

    def recv_response(self, expected_id: int) -> Optional[dict]:
        if self._sock is None or expected_id == -1:
            return None
        buf      = b""
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
                    if "Event" in msg:
                        logger.debug("Event: %s", msg.get("Event"))
                        continue
                    if msg.get("id") == expected_id:
                        return msg
        except socket.error as e:
            logger.warning("ControlSocket recv error: %s", e)
        logger.warning("recv_response timeout for id=%d", expected_id)
        return None

    def send_and_recv(self, method: str, params=None) -> Optional[dict]:
        ok, cmd_id = self.send(method, params)
        if not ok:
            return None
        return self.recv_response(expected_id=cmd_id)

# ---------------------------------------------------------------------------
# Image Socket (TCP — port 4801)
# ---------------------------------------------------------------------------

class ImageSocket:
    def __init__(self, host: str = SEESTAR_HOST, port: int = IMG_PORT,
                 timeout: float = FRAME_TIMEOUT):
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
                if header is None:
                    break
                size, frame_id, width, height = parse_header(header)
                if size < MIN_PAYLOAD:
                    continue
                data = recv_exact(sock, size)
                if data is None:
                    break
                if frame_id == FRAME_PREVIEW:
                    return data, width, height
        finally:
            sock.close()
        return None, 0, 0

# ---------------------------------------------------------------------------
# FITS construction
# ---------------------------------------------------------------------------

def _read_gps_ram() -> dict:
    try:
        data = json.loads(ENV_STATUS.read_text())
        return {
            "lat":       float(data.get("lat",       0.0)),
            "lon":       float(data.get("lon",       0.0)),
            "elevation": float(data.get("elevation", 0.0)),
        }
    except Exception:
        return {"lat": 0.0, "lon": 0.0, "elevation": 0.0}

def sovereign_stamp(target: AcquisitionTarget, utc_obs: datetime,
                    width: int, height: int,
                    ccd_temp: Optional[float] = None) -> dict:
    ra_deg    = target.ra_hours * 15.0
    t_astropy = Time(utc_obs)
    gps       = _read_gps_ram()
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
        "SIMPLE":   True,   "BITPIX": 16, "NAXIS": 2,
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
        if isinstance(value, bool):    val_str = f"{'T' if value else 'F':>20}"
        elif isinstance(value, int):   val_str = f"{value:>20}"
        elif isinstance(value, float): val_str = f"{value:>20.10G}"
        elif isinstance(value, str):   val_str = f"'{value.replace(chr(39), chr(39)*2):<8}'".ljust(20)
        else:                          val_str = f"'{str(value):<8}'".ljust(20)
        return f"{key}= {val_str}{f' / {comment}' if comment else ''}"[:80].ljust(80)

    priority = ["SIMPLE", "BITPIX", "NAXIS", "NAXIS1", "NAXIS2", "BZERO", "BSCALE"]
    records  = [card(k, header_dict[k]) for k in priority if k in header_dict]
    records += [card(k, v) for k, v in header_dict.items() if k not in priority]
    records.append("COMMENT   SeeVar v2.0.0 -- BZERO Signed-Integer Protected".ljust(80))
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
# Diamond Sequence — Hybrid Alpaca + JSON-RPC acquisition
# ---------------------------------------------------------------------------

class DiamondSequence:
    """
    Full autonomous acquisition sequence.

    Motor path  : AlpacaControl (port 32323) — unpark, slew, track
    Camera path : ControlSocket (port 4700)  — gain, expose, focus
    Frame path  : ImageSocket   (port 4801)  — raw uint16 preview frame
    """

    def __init__(self, host: str = SEESTAR_HOST):
        self.host   = host
        self.alpaca = AlpacaControl(host=host)

    def init_session(self, level_ok: bool = True) -> TelemetryBlock:
        """
        Connect Alpaca, unpark if parked, read telemetry from event stream.
        Returns TelemetryBlock — check veto_reason() before proceeding.
        """
        self.alpaca.connect()

        state = self.alpaca.get_state()
        if state.get("atpark"):
            logger.info("Telescope parked — sending unpark")
            self.alpaca.unpark()
            time.sleep(5.0)  # Allow arm to deploy

        # Prefer live event stream telemetry
        state_path = Path("/dev/shm/wilhelmina_state.json")
        if state_path.exists():
            tel = TelemetryBlock.from_event_stream(state_path)
        else:
            tel = TelemetryBlock()
        tel.level_ok = level_ok
        return tel

    def acquire(self, target: AcquisitionTarget,
                status_cb=None,
                telemetry: Optional[TelemetryBlock] = None) -> FrameResult:

        def notify(step, msg):
            if status_cb:
                status_cb(f"[{step}] {msg}")
            logger.info("[%s] %s", step, msg)

        t_start  = time.monotonic()
        utc_obs  = datetime.now(timezone.utc)
        ccd_temp = telemetry.temp_c if telemetry else None

        # A1 — Alpaca: slew to target
        notify("A1", f"Alpaca slew → RA={target.ra_hours:.4f}h Dec={target.dec_deg:.4f}°")
        self.alpaca.connect()
        if not self.alpaca.slew_to(target.ra_hours, target.dec_deg):
            return FrameResult(success=False, error="Alpaca slew failed")

        # A2 — Wait for slew complete (polls slewing flag)
        notify("A2", "Waiting for slew completion...")
        if not self.alpaca.wait_for_slew(timeout_s=120.0):
            return FrameResult(success=False, error="Slew timeout")

        # A3 — Enable tracking
        notify("A3", "Enabling sidereal tracking")
        self.alpaca.set_tracking(True)
        time.sleep(SETTLE_SECONDS)

        # C1 — JSON-RPC: open camera session
        ctrl = ControlSocket(host=self.host)
        if not ctrl.connect():
            return FrameResult(success=False, error="ControlSocket connect failed")

        try:
            # C2 — Set gain and exposure
            notify("C2", f"set_control_value gain={GAIN}")
            ctrl.send("set_control_value", ["gain", GAIN])

            notify("C2", f"set_setting exp_ms={target.exp_ms}")
            ctrl.send("set_setting", {"exp_ms": {"stack_l": target.exp_ms}})

            # C3 — Autofocus
            notify("C3", "start_auto_focuse")
            ctrl.send("start_auto_focuse")

            # C4 — Start view / continuous exposure
            notify("C4", "iscope_start_view mode=star")
            ctrl.send("iscope_start_view", {
                "mode": "star",
                "target_ra_dec": [target.ra_hours, target.dec_deg],
                "target_name": target.name,
            })
            time.sleep(2.0)

        except Exception as e:
            ctrl.disconnect()
            return FrameResult(success=False, error=f"Camera sequence error: {e}")

        # F1 — Receive science frame from port 4801
        notify("F1", "Receiving RAW frame from port 4801...")
        img  = ImageSocket(host=self.host, timeout=FRAME_TIMEOUT)
        raw_data, width, height = img.capture_one_preview()

        # C5 — Stop view
        try:
            notify("C5", "iscope_stop_view")
            ctrl.send("iscope_stop_view")
        finally:
            ctrl.disconnect()

        if raw_data is None:
            return FrameResult(success=False, error="No preview frame received")

        expected = width * height * 2
        if len(raw_data) != expected:
            return FrameResult(
                success=False,
                error=f"Payload mismatch: got {len(raw_data)}, expected {expected}"
            )

        # W1 — Write FITS
        notify("W1", f"Writing FITS — {target.name} AUID={target.auid}")
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
