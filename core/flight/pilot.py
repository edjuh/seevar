#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/pilot.py
Version: 1.6.0  # SeeVar-v1.6.0-header
Objective: Direct TCP control of ZWO S30-Pro for AAVSO-compliant Sovereign RAW acquisition. M2: TelemetryBlock, send_and_recv, session init S1-S4, veto logic on real values.
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
from astropy.coordinates import EarthLocation, AltAz, SkyCoord, get_body
from astropy.time import Time
import astropy.units as u

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

SENSOR_W        = 3840          # IMX585 full resolution (long axis)
SENSOR_H        = 2160
BAYER_PATTERN   = "GRBG"
INSTRUMENT      = "IMX585"
TELESCOPE       = "ZWO S30-Pro"
FILTER_NAME     = "CV"          # Clear/V-proxy for AAVSO

# Instrument constants — FITS header values
GAIN            = 80            # Fixed sensor gain
FOCALLEN        = 250           # mm
APERTURE        = 30            # mm
PIXSCALE        = 3.74          # arcsec/pixel
RDNOISE         = 1.6           # IMX585 read noise estimate (e-)
PEDESTAL        = 0             # No pedestal applied
SWCREATE        = "SeeVar v5.0.0"

# Acquisition parameters
SETTLE_SECONDS  = 8             # Post-slew settle time
FRAME_TIMEOUT   = 60            # Max wait for preview frame (seconds)
EXP_MS_DEFAULT  = 5000          # Default exposure ms

# Veto thresholds — STATE_MACHINE.md § VETO LOGIC
VETO_BATTERY    = 10            # % — mandatory park below this
VETO_TEMP       = 55.0          # °C — mandatory park above this

from core.utils.env_loader import DATA_DIR, ENV_STATUS
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
    """Parsed hardware state from get_device_state response.

    Key map confirmed against seestar_alp/device/event_callbacks.py
    and SEEVAR_DICT.PSV (Kriel era empirical testing).

    Response structure:
        result["pi_status"]["battery_capacity"]  → battery_pct
        result["pi_status"]["temp"]              → temp_c
        result["pi_status"]["charge_online"]     → charge_online
        result["pi_status"]["charger_status"]    → charger_status
        result["device"]["name"]                 → device_name
        result["device"]["firmware_ver_int"]     → firmware_ver

    level_deg: NOT available via get_device_state (confirmed absent from
    seestar_alp source). Leveling veto is preflight-only — set once by
    operator before session start via level_ok flag.
    """
    battery_pct:    Optional[int]   = None   # 0-100 %
    temp_c:         Optional[float] = None   # °C
    charge_online:  Optional[bool]  = None
    charger_status: Optional[str]   = None   # "Discharging" | "Charging" | ...
    device_name:    Optional[str]   = None
    firmware_ver:   Optional[int]   = None
    level_ok:       bool            = True   # Preflight-only — operator set
    raw:            Optional[dict]  = None   # Full response for diagnostics
    parse_error:    Optional[str]   = None   # Set if parsing failed

    @classmethod
    def from_response(cls, response: Optional[dict]) -> "TelemetryBlock":
        """Parse a get_device_state JSON-RPC response into a TelemetryBlock.

        Never raises — all failures captured in parse_error field.
        Returns a TelemetryBlock with all fields None on total failure.
        """
        if response is None:
            return cls(parse_error="No response received")

        try:
            # JSON-RPC wrapper: result lives under "result" key
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
        """Return veto reason string if any threshold is breached, else None.

        Battery and temp checked against STATE_MACHINE.md thresholds.
        Returns the first failing condition — caller must park on any result.
        """
        if self.battery_pct is not None and self.battery_pct < VETO_BATTERY:
            return f"Battery critical: {self.battery_pct}% < {VETO_BATTERY}%"
        if self.temp_c is not None and self.temp_c > VETO_TEMP:
            return f"Thermal limit: {self.temp_c}°C > {VETO_TEMP}°C"
        if not self.level_ok:
            return "Level veto: device not level (preflight check failed)"
        return None

    def is_safe(self) -> bool:
        """True if no veto condition is active."""
        return self.veto_reason() is None

    def summary(self) -> str:
        """One-line telemetry string for flight log."""
        if self.parse_error:
            return f"TelemetryBlock parse error: {self.parse_error}"
        return (
            f"bat={self.battery_pct}% "
            f"temp={self.temp_c}°C "
            f"charger={self.charger_status} "
            f"online={self.charge_online} "
            f"fw={self.firmware_ver}"
        )


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

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()

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

    def send_and_recv(self, method: str, params=None) -> Optional[dict]:
        """Send a command and receive its response in one call.

        Use for commands where the response payload matters (get_device_state,
        set_control_value confirmation, etc). Fire-and-forget commands that
        need no response confirmation should still use send() directly.
        Returns None on send failure or timeout — caller must handle.
        """
        if not self.send(method, params):
            logger.error("send_and_recv: send failed for method=%s", method)
            return None
        response = self.recv_response()
        if response is None:
            logger.warning("send_and_recv: no response for method=%s", method)
        return response

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
# FITS construction — no astropy dependency (except astropy for astrometry)
# ---------------------------------------------------------------------------

def _read_gps_ram() -> dict:
    """Read GPS fix from RAM file. Returns dict with lat, lon, elevation.
    Returns zeros on absent/stale file — caller must guard against Null Island."""
    import json
    try:
        data = json.loads(ENV_STATUS.read_text())
        lat  = float(data.get("lat", 0.0))
        lon  = float(data.get("lon", 0.0))
        elev = float(data.get("elevation", 0.0))
        if lat == 0.0 and lon == 0.0:
            logger.warning("_read_gps_ram: Null Island coordinates — GPS fix not available")
        return {"lat": lat, "lon": lon, "elevation": elev}
    except FileNotFoundError:
        logger.warning("_read_gps_ram: %s absent — GPS not available", ENV_STATUS)
        return {"lat": 0.0, "lon": 0.0, "elevation": 0.0}
    except Exception as e:
        logger.warning("_read_gps_ram: failed to parse env_status.json: %s", e)
        return {"lat": 0.0, "lon": 0.0, "elevation": 0.0}

def sovereign_stamp(
    target: AcquisitionTarget,
    utc_obs: datetime,
    width: int,
    height: int,
    ccd_temp: Optional[float] = None,
) -> dict:
    """Build AAVSO-compliant FITS header dict.

    Args:
        target:   AcquisitionTarget with ra/dec/name/auid/exp_ms/observer_code.
        utc_obs:  UTC datetime of exposure start.
        width:    Frame width in pixels (from binary stream header).
        height:   Frame height in pixels.
        ccd_temp: Sensor temperature in °C from get_device_state (M2+).
                  None = written as UNKNOWN string — FITS-safe, flags missing telemetry.
    """
    ra_deg = target.ra_hours * 15.0
    t_astropy = Time(utc_obs)

    # --- Site from GPS RAM ---------------------------------------------------
    gps = _read_gps_ram()
    site_lat  = gps["lat"]
    site_lon  = gps["lon"]
    site_elev = gps["elevation"]
    gps_valid = not (site_lat == 0.0 and site_lon == 0.0)

    # --- Airmass -------------------------------------------------------------
    airmass = None
    if gps_valid:
        try:
            location = EarthLocation(
                lat=site_lat * u.deg,
                lon=site_lon * u.deg,
                height=site_elev * u.m,
            )
            frame = AltAz(obstime=t_astropy, location=location)
            target_coord = SkyCoord(ra=ra_deg * u.deg, dec=target.dec_deg * u.deg, frame="icrs")
            altaz = target_coord.transform_to(frame)
            alt_deg = float(altaz.alt.deg)
            if alt_deg > 0.0:
                airmass = round(1.0 / math.sin(math.radians(alt_deg)), 4)
        except Exception as e:
            logger.warning("sovereign_stamp: airmass calculation failed: %s", e)

    # --- Moon ----------------------------------------------------------------
    moon_phase = None
    moon_alt   = None
    if gps_valid:
        try:
            location = EarthLocation(
                lat=site_lat * u.deg,
                lon=site_lon * u.deg,
                height=site_elev * u.m,
            )
            frame = AltAz(obstime=t_astropy, location=location)
            moon = get_body("moon", t_astropy, location)
            moon_altaz = moon.transform_to(frame)
            moon_alt = round(float(moon_altaz.alt.deg), 2)
            # Phase: angular separation sun-moon / 180°, clamped 0.0–1.0
            sun = get_body("sun", t_astropy, location)
            sep = moon.separation(sun).deg
            moon_phase = round(min(max((1.0 - math.cos(math.radians(sep))) / 2.0, 0.0), 1.0), 4)
        except Exception as e:
            logger.warning("sovereign_stamp: moon calculation failed: %s", e)

    # --- Assemble header -----------------------------------------------------
    h = {
        # --- Mandatory FITS structural keys (priority order preserved by write_fits) ---
        "SIMPLE":   True,
        "BITPIX":   16,
        "NAXIS":    2,
        "NAXIS1":   width,
        "NAXIS2":   height,
        "BZERO":    32768.0,   # CRITICAL: unsigned uint16 → signed int16 FITS convention
        "BSCALE":   1.0,
        # --- Target identity ---
        "OBJECT":   target.name,
        "OBJCTRA":  _hours_to_hms(target.ra_hours),
        "OBJCTDEC": _deg_to_dms(target.dec_deg),
        # --- WCS ---
        "CRVAL1":   ra_deg,
        "CRVAL2":   target.dec_deg,
        "CRPIX1":   width  / 2.0,
        "CRPIX2":   height / 2.0,
        "CDELT1":   -0.001042,
        "CDELT2":    0.001042,
        "CTYPE1":   "RA---TAN",
        "CTYPE2":   "DEC--TAN",
        # --- Timing ---
        "DATE-OBS": utc_obs.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
        "EXPTIME":  target.exp_ms / 1000.0,
        # --- Instrument ---
        "INSTRUME": INSTRUMENT,
        "TELESCOP": TELESCOPE,
        "FILTER":   FILTER_NAME,
        "BAYERPAT": BAYER_PATTERN,
        "GAIN":     GAIN,
        "FOCALLEN": FOCALLEN,
        "APERTURE": APERTURE,
        "PIXSCALE": PIXSCALE,
        "RDNOISE":  RDNOISE,
        "PEDESTAL": PEDESTAL,
        # --- Observer ---
        "OBSERVER": target.observer_code or "UNKNOWN",
        # --- Site ---
        "SITELAT":  site_lat,
        "SITELONG": site_lon,
        "SITEELEV": site_elev,
        # --- Software ---
        "SWCREATE": SWCREATE,
        # SeeVar-v5-M1-sovereign_stamp
    }

    # CCD-TEMP: real value from get_device_state (M2+), else UNKNOWN string
    h["CCD-TEMP"] = ccd_temp if ccd_temp is not None else "UNKNOWN"

    # Airmass / moon — only written when successfully computed
    if airmass is not None:
        h["AIRMASS"] = airmass
    if moon_phase is not None:
        h["MOONPHASE"] = moon_phase
    if moon_alt is not None:
        h["MOONALT"] = moon_alt

    if target.auid:
        h["AUID"] = target.auid

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
    
    records.append("COMMENT   SeeVar v5.1.0 M2 -- BZERO Signed-Integer Protected".ljust(80))
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
    """Sovereign acquisition loop — STATE_MACHINE.md DiamondSequence.

    Session init (call once per night via init_session()):
        S1 — iscope_stop_view       clear any active session
        S2 — set_user_location      push GPS fix to mount
        S3 — set_control_value      gain=80
        S4 — get_device_state       parse TelemetryBlock → veto if unsafe

    Per-target (acquire()):
        T1 — set_setting exp_ms     from target.exp_ms
        T2 — scope_goto             slew → SETTLE_SECONDS
        T3 — start_auto_focuse      firmware typo preserved
        T4 — iscope_start_view      mode:star → sleep 2s
        T5 — port 4801              frame_id==21 → validate payload
        T6 — iscope_stop_view       get_device_state → veto check
        T7 — write_fits             sovereign_stamp (full header) → RAID1
    """

    def __init__(self, host: str = SEESTAR_HOST):
        self.host = host

    # ------------------------------------------------------------------ #
    # Session init — S1–S4 — call once per night before target loop       #
    # ------------------------------------------------------------------ #

    def init_session(self, level_ok: bool = True) -> TelemetryBlock:
        """Execute session init sequence S1–S4.

        Args:
            level_ok: Operator-confirmed leveling result from preflight.
                      Cannot be derived from get_device_state (not exposed
                      in firmware). Defaults True — preflight must set False
                      if physical leveling check fails.

        Returns:
            TelemetryBlock with parsed hardware state.
            Caller must check telemetry.is_safe() before proceeding.
        """
        ctrl = ControlSocket(host=self.host)
        if not ctrl.connect():
            t = TelemetryBlock(parse_error="Control socket connect failed")
            t.level_ok = level_ok
            return t

        try:
            # S1 — clear any active session
            logger.info("[S1] iscope_stop_view — clearing active session")
            ctrl.send("iscope_stop_view")

            # S2 — push GPS fix to mount
            gps = _read_gps_ram()
            if gps["lat"] != 0.0 or gps["lon"] != 0.0:
                logger.info("[S2] set_user_location lat=%.4f lon=%.4f", gps["lat"], gps["lon"])
                ctrl.send("set_user_location", {
                    "lat":   gps["lat"],
                    "lon":   gps["lon"],
                    "force": True,
                })
            else:
                logger.warning("[S2] GPS not available — set_user_location skipped")

            # S3 — set gain
            logger.info("[S3] set_control_value gain=%d", GAIN)
            resp_gain = ctrl.send_and_recv("set_control_value", ["gain", GAIN])
            if resp_gain is None:
                logger.warning("[S3] No response to set_control_value — proceeding")

            # S4 — health check → TelemetryBlock
            logger.info("[S4] get_device_state — parsing telemetry")
            resp_state = ctrl.send_and_recv("get_device_state")
            telemetry = TelemetryBlock.from_response(resp_state)
            telemetry.level_ok = level_ok
            logger.info("[S4] %s", telemetry.summary())

            veto = telemetry.veto_reason()
            if veto:
                logger.error("[S4] VETO: %s", veto)
                return telemetry  # SeeVar-init-s5-s7

            # S5 — query current track state (confirms mount is parked)
            logger.info("[S5] scope_get_track_state — querying mount state")
            resp_track = ctrl.send_and_recv("scope_get_track_state")
            track_state = resp_track.get("result", False) if resp_track else False
            logger.info("[S5] tracking=%s", track_state)

            # S6 — explicit unpark: engage sidereal tracking
            # scope_goto would do this implicitly, but sovereign architecture
            # asserts state explicitly before any movement.
            logger.info("[S6] scope_set_track_state [true] — unpark + engage tracking")
            ctrl.send("scope_set_track_state", [True])

            # S7 — confirm mount is live and reporting position
            logger.info("[S7] scope_get_ra_dec — confirming mount position")
            resp_radec = ctrl.send_and_recv("scope_get_ra_dec")
            if resp_radec:
                pos = resp_radec.get("result", [])
                logger.info("[S7] mount position: %s", pos)
            else:
                logger.warning("[S7] scope_get_ra_dec — no response")

            return telemetry

        except Exception as e:
            t = TelemetryBlock(parse_error=f"init_session exception: {e}")
            t.level_ok = level_ok
            return t
        finally:
            ctrl.disconnect()

    # ------------------------------------------------------------------ #
    # Per-target acquisition — T1–T7                                      #
    # ------------------------------------------------------------------ #

    def acquire(
        self,
        target: AcquisitionTarget,
        status_cb=None,
        telemetry: Optional[TelemetryBlock] = None,
    ) -> FrameResult:
        """Execute per-target DiamondSequence T1–T7.

        Args:
            target:    AcquisitionTarget with ra/dec/exp_ms/auid.
            status_cb: Optional callback for dashboard step notifications.
            telemetry: TelemetryBlock from init_session() or previous
                       acquire(). Used for CCD-TEMP in FITS header.
                       None = CCD-TEMP written as UNKNOWN.
        """
        def notify(step, msg):
            if status_cb: status_cb(f"[{step}] {msg}")
            logger.info("[%s] %s", step, msg)

        t_start = time.monotonic()
        utc_obs = datetime.now(timezone.utc)
        ccd_temp = telemetry.temp_c if telemetry else None

        ctrl = ControlSocket(host=self.host)
        if not ctrl.connect():
            return FrameResult(success=False, error="Control socket connect failed")

        try:
            # T1 — set exposure from target
            notify("T1", f"set_setting exp_ms={target.exp_ms} for {target.name}")
            ctrl.send("set_setting", {"exp_ms": {"stack_l": target.exp_ms}})

            # T2 — slew to target
            notify("T2", f"scope_goto RA={target.ra_hours:.4f}h DEC={target.dec_deg:.4f}°")
            ctrl.send("scope_goto", [target.ra_hours, target.dec_deg])
            notify("T2", f"Settling {SETTLE_SECONDS}s...")
            time.sleep(SETTLE_SECONDS)

            # T3 — autofocus (firmware typo preserved: one 's')
            notify("T3", "start_auto_focuse")
            ctrl.send("start_auto_focuse")

            # T4 — open exposure stream
            notify("T4", "iscope_start_view mode=star")
            ctrl.send("iscope_start_view", {"mode": "star"})
            time.sleep(2.0)

        except Exception as e:
            ctrl.disconnect()
            return FrameResult(success=False, error=f"Control sequence error: {e}")

        # T5 — receive frame from port 4801
        notify("T5", "Receiving RAW frame port 4801...")
        img_sock = ImageSocket(host=self.host, timeout=FRAME_TIMEOUT)
        raw_data, width, height = img_sock.capture_one_preview()

        # T6 — stop view, post-frame health check
        try:
            ctrl.send("iscope_stop_view")
            notify("T6", "iscope_stop_view — post-frame health check")
            resp_state = ctrl.send_and_recv("get_device_state")
            post_telemetry = TelemetryBlock.from_response(resp_state)
            post_telemetry.level_ok = telemetry.level_ok if telemetry else True
            ccd_temp = post_telemetry.temp_c or ccd_temp
            logger.info("[T6] %s", post_telemetry.summary())
            veto = post_telemetry.veto_reason()
            if veto:
                logger.error("[T6] VETO: %s — flagging for orchestrator", veto)
                # Return the frame if we got one — orchestrator decides to park
                # We do not park here: pilot has no park authority mid-sequence
                if raw_data is None:
                    return FrameResult(success=False, error=f"Veto + no frame: {veto}")
        except Exception as e:
            logger.warning("[T6] Post-frame health check failed: %s", e)
        finally:
            ctrl.disconnect()

        if raw_data is None:
            return FrameResult(success=False, error="No preview frame received")

        # Validate payload size — STATE_MACHINE.md § PHASE 3
        expected = width * height * 2
        if len(raw_data) != expected:
            return FrameResult(
                success=False,
                error=f"Payload size mismatch: got {len(raw_data)}, expected {expected}"
            )

        # T7 — write FITS
        notify("T7", f"Writing FITS — AUID={target.auid} CCD-TEMP={ccd_temp}")
        array = np.frombuffer(raw_data, dtype=np.uint16).reshape(height, width)
        LOCAL_BUFFER.mkdir(parents=True, exist_ok=True)
        safe_name = target.name.replace(" ", "_").replace("/", "-")
        out_path  = LOCAL_BUFFER / f"{safe_name}_{utc_obs.strftime('%Y%m%dT%H%M%S')}_Raw.fits"

        header = sovereign_stamp(target, utc_obs, width, height, ccd_temp=ccd_temp)
        ok = write_fits(array, header, out_path)
        elapsed = time.monotonic() - t_start

        # SeeVar-v5-M2-TelemetryBlock
# SeeVar-v5-M6-ControlSocket
        if ok:
            return FrameResult(success=True, path=out_path, width=width, height=height, elapsed_s=elapsed)
        return FrameResult(success=False, error="FITS write failed", elapsed_s=elapsed)

def _hours_to_hms(hours: float) -> str:
    h = int(hours); m = int((hours - h) * 60); s = ((hours - h) * 60 - m) * 60
    return f"{h:02d}:{m:02d}:{s:05.2f}"

def _deg_to_dms(deg: float) -> str:
    sign = "+" if deg >= 0 else "-"; deg = abs(deg); d = int(deg); m = int((deg - d) * 60); s = ((deg - d) * 60 - m) * 60
    return f"{sign}{d:02d}:{m:02d}:{s:04.1f}"

if __name__ == "__main__":
    pass
