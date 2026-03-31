#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/pilot.py
Version: 3.0.0
Objective: Full Alpaca REST control of ZWO S30-Pro for AAVSO-compliant
           autonomous RAW acquisition. Replaces TCP/JSON-RPC (port 4700)
           and binary frame stream (port 4801) with the official ZWO Alpaca
           driver on port 32323.

Confirmed 2026-03-30:
  - Alpaca v1.2.0-3 on port 32323 — slew, expose, download ALL WORK
  - No phone app required. No session master lock.
  - 7 devices: 2 cameras, 2 focusers, filter wheel, telescope, switch
  - Camera #0 (Telephoto IMX585): 2160x3840, 2.9µm, gain 0-600
  - Telescope #0: SlewToCoordinatesAsync, Park, Unpark, Tracking
  - FilterWheel #0: positions Dark(0), IR(1), LP(2)

Interface contract (unchanged from v1.7.1):
  - DiamondSequence.init_session(level_ok) → TelemetryBlock
  - DiamondSequence.acquire(target, status_cb, telemetry) → FrameResult
  - AcquisitionTarget, FrameResult, TelemetryBlock dataclasses
  - sovereign_stamp(), write_fits() utility functions

This preserves FSM and orchestrator compatibility — zero changes needed
in fsm.py or orchestrator.py.
"""

import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import requests
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
        return "10.0.0.1"
    return ip

# ---------------------------------------------------------------------------
# Constants — single source of truth (S30-Pro / Alpaca v1.2.0-3)
# ---------------------------------------------------------------------------

SEESTAR_HOST    = _get_seestar_ip()
ALPACA_PORT     = 32323
TELESCOPE_NUM   = 0
CAMERA_NUM      = 0       # Telephoto (IMX585)
FILTERWHEEL_NUM = 0
SWITCH_NUM      = 0       # Dew heater

# Sensor / optics
SENSOR_W        = 3840
SENSOR_H        = 2160
BAYER_PATTERN   = "GRBG"
INSTRUMENT      = "IMX585"
TELESCOPE       = "ZWO Seestar S30-Pro"
FILTER_NAME     = "TG"    # Tri-color Green for AAVSO

GAIN            = 80      # HCG sweet spot — 12 stops dynamic range
FOCALLEN        = 160     # mm (confirmed S30-Pro quadruplet APO)
APERTURE        = 30      # mm
PIXSCALE        = 3.74    # arcsec/pixel  (206.265 * 2.9 / 160)
PIXEL_SIZE_UM   = 2.9     # µm (confirmed via Alpaca)
RDNOISE         = 1.6     # e- estimate
PEDESTAL        = 0
SWCREATE        = "SeeVar v3.0.0 (Alpaca)"

# Timing
SETTLE_SECONDS  = 8       # Post-slew settle
SLEW_TIMEOUT    = 60      # Max wait for slew completion
EXPOSE_TIMEOUT  = 120     # Max wait for exposure + readout
DOWNLOAD_TIMEOUT = 300    # Image download (JSON is slow for 8MP)
EXP_MS_DEFAULT  = 5000

# Vetoes
VETO_BATTERY    = 10      # % — mandatory park below this
VETO_TEMP       = 55.0    # °C — mandatory park above this

# Alpaca client identity
CLIENT_ID       = 42      # SeeVar

LOCAL_BUFFER    = DATA_DIR / "local_buffer"
logger = logging.getLogger("seevar.pilot")


# ---------------------------------------------------------------------------
# Data classes (interface contract — unchanged)
# ---------------------------------------------------------------------------

@dataclass
class AcquisitionTarget:
    name:          str
    ra_hours:      float
    dec_deg:       float
    auid:          str   = ""
    exp_ms:        int   = EXP_MS_DEFAULT
    observer_code: str   = ""
    n_frames:      int   = 1

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

    # Alpaca-specific extras
    tracking:       Optional[bool]  = None
    at_park:        Optional[bool]  = None
    ra_hours:       Optional[float] = None
    dec_deg:        Optional[float] = None
    altitude:       Optional[float] = None
    azimuth:        Optional[float] = None
    alpaca_version: Optional[str]   = None

    @classmethod
    def from_alpaca(cls, telescope: "AlpacaTelescope",
                    camera: "AlpacaCamera") -> "TelemetryBlock":
        """Build TelemetryBlock from Alpaca device reads."""
        try:
            temp = camera.safe_get("ccdtemperature")
            name = telescope.safe_get("name")
            tracking = telescope.safe_get("tracking")
            at_park = telescope.safe_get("atpark")
            ra = telescope.safe_get("rightascension")
            dec = telescope.safe_get("declination")
            alt = telescope.safe_get("altitude")
            az = telescope.safe_get("azimuth")
            version = telescope.safe_get("driverversion")

            return cls(
                temp_c=temp,
                device_name=name,
                tracking=tracking,
                at_park=at_park,
                ra_hours=ra,
                dec_deg=dec,
                altitude=alt,
                azimuth=az,
                alpaca_version=version,
                # Battery/charger not available via Alpaca — leave None
                # Dashboard gets these from WilhelminaMonitor event stream
            )
        except Exception as e:
            return cls(parse_error=f"Alpaca telemetry read failed: {e}")

    @classmethod
    def from_response(cls, response: Optional[dict]) -> "TelemetryBlock":
        """Legacy compatibility — parse JSON-RPC response dict."""
        if response is None:
            return cls(parse_error="No response received")
        try:
            result = response.get("result", response)
            pi  = result.get("pi_status", {})
            dev = result.get("device", {})
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
        if self.parse_error:
            return f"TelemetryBlock parse error: {self.parse_error}"
        parts = []
        if self.temp_c is not None:
            parts.append(f"temp={self.temp_c:.1f}°C")
        if self.battery_pct is not None:
            parts.append(f"bat={self.battery_pct}%")
        if self.tracking is not None:
            parts.append(f"tracking={'ON' if self.tracking else 'OFF'}")
        if self.at_park is not None:
            parts.append(f"park={'YES' if self.at_park else 'NO'}")
        if self.device_name:
            parts.append(f"name={self.device_name}")
        if self.alpaca_version:
            parts.append(f"alpaca={self.alpaca_version}")
        return " ".join(parts) if parts else "no data"


# ---------------------------------------------------------------------------
# Alpaca REST Client — thin HTTP wrapper
# ---------------------------------------------------------------------------

class AlpacaClient:
    """Base Alpaca REST client. Telescope, Camera, etc. inherit from this."""

    def __init__(self, ip: str, port: int, device_type: str, device_number: int):
        self.base = f"http://{ip}:{port}/api/v1/{device_type}/{device_number}"
        self._txid = 0

    def _next_tx(self) -> int:
        self._txid += 1
        return self._txid

    def _get(self, prop: str, timeout: float = 10.0):
        """GET a device property. Returns the Value field."""
        params = {"ClientID": CLIENT_ID,
                  "ClientTransactionID": self._next_tx()}
        r = requests.get(f"{self.base}/{prop}", params=params, timeout=timeout)
        data = r.json()
        err = data.get("ErrorNumber", 0)
        if err:
            raise RuntimeError(
                f"Alpaca GET {prop}: error {err} — {data.get('ErrorMessage', '')}")
        return data.get("Value")

    def _put(self, method: str, timeout: float = 15.0, **kwargs):
        """PUT a device method. Returns the Value field (usually None)."""
        payload = {"ClientID": CLIENT_ID,
                   "ClientTransactionID": self._next_tx()}
        payload.update(kwargs)
        r = requests.put(f"{self.base}/{method}", data=payload, timeout=timeout)
        data = r.json()
        err = data.get("ErrorNumber", 0)
        if err:
            raise RuntimeError(
                f"Alpaca PUT {method}: error {err} — {data.get('ErrorMessage', '')}")
        return data.get("Value")

    def safe_get(self, prop: str, default=None):
        """GET with exception swallowed — returns default on any failure."""
        try:
            return self._get(prop)
        except Exception:
            return default

    def connect(self):
        self._put("connected", Connected="true")

    def disconnect(self):
        try:
            self._put("connected", Connected="false")
        except Exception:
            pass

    @property
    def connected(self) -> bool:
        return self._get("connected")


# ---------------------------------------------------------------------------
# Alpaca Telescope
# ---------------------------------------------------------------------------

class AlpacaTelescope(AlpacaClient):
    def __init__(self, ip: str = SEESTAR_HOST, port: int = ALPACA_PORT,
                 device_number: int = TELESCOPE_NUM):
        super().__init__(ip, port, "telescope", device_number)

    def unpark(self):
        self._put("unpark")

    def park(self):
        self._put("park")

    def set_tracking(self, on: bool):
        self._put("tracking", Tracking=str(on).lower())

    def slew_to_coordinates_async(self, ra_hours: float, dec_deg: float):
        self._put("slewtocoordinatesasync",
                   RightAscension=str(ra_hours),
                   Declination=str(dec_deg),
                   timeout=20.0)

    def wait_for_slew(self, timeout: float = SLEW_TIMEOUT) -> bool:
        """Poll until slewing completes. Returns True if slew finished."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self._get("slewing"):
                return True
            time.sleep(1.0)
        logger.warning("Slew timeout after %.0fs", timeout)
        return False

    @property
    def tracking(self) -> bool:
        return self._get("tracking")

    @property
    def at_park(self) -> bool:
        return self._get("atpark")

    @property
    def ra(self) -> float:
        return self._get("rightascension")

    @property
    def dec(self) -> float:
        return self._get("declination")

    @property
    def altitude(self) -> float:
        return self._get("altitude")

    @property
    def azimuth(self) -> float:
        return self._get("azimuth")

    @property
    def sidereal_time(self) -> float:
        return self._get("siderealtime")


# ---------------------------------------------------------------------------
# Alpaca Camera
# ---------------------------------------------------------------------------

class AlpacaCamera(AlpacaClient):
    # ASCOM camera states
    IDLE     = 0
    WAITING  = 1
    EXPOSING = 2
    READING  = 3
    DOWNLOAD = 4
    ERROR    = 5

    STATE_NAMES = {0: "Idle", 1: "Waiting", 2: "Exposing",
                   3: "Reading", 4: "Download", 5: "Error"}

    def __init__(self, ip: str = SEESTAR_HOST, port: int = ALPACA_PORT,
                 device_number: int = CAMERA_NUM):
        super().__init__(ip, port, "camera", device_number)

    def set_gain(self, gain: int):
        self._put("gain", Gain=str(gain))

    def start_exposure(self, duration_sec: float, light: bool = True):
        self._put("startexposure",
                   Duration=str(duration_sec),
                   Light=str(light).lower())

    def abort_exposure(self):
        self._put("abortexposure")

    def wait_for_image(self, exposure_sec: float,
                       timeout: float = EXPOSE_TIMEOUT) -> bool:
        """Poll until image is ready. Returns True if image available."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if self._get("imageready"):
                    return True
            except Exception:
                pass
            time.sleep(1.0)
        return False

    def download_image(self) -> np.ndarray:
        """Download image array via Alpaca JSON transfer.

        The IMX585 at 3840x2160 takes ~33s over JSON on LAN.
        Returns numpy array (height, width).
        """
        params = {"ClientID": CLIENT_ID,
                  "ClientTransactionID": self._next_tx()}
        r = requests.get(f"{self.base}/imagearray",
                         params=params, timeout=DOWNLOAD_TIMEOUT)
        data = r.json()
        err = data.get("ErrorNumber", 0)
        if err:
            raise RuntimeError(
                f"imagearray: error {err} — {data.get('ErrorMessage', '')}")

        value = data.get("Value")
        if value is None:
            raise RuntimeError("imagearray returned no Value")

        arr = np.array(value, dtype=np.int32)
        return arr

    @property
    def camera_state(self) -> int:
        return self._get("camerastate")

    @property
    def image_ready(self) -> bool:
        return self._get("imageready")

    @property
    def gain(self) -> int:
        return self._get("gain")

    @property
    def temperature(self) -> Optional[float]:
        return self.safe_get("ccdtemperature")

    @property
    def sensor_width(self) -> int:
        return self._get("cameraxsize")

    @property
    def sensor_height(self) -> int:
        return self._get("cameraysize")


# ---------------------------------------------------------------------------
# Alpaca Filter Wheel
# ---------------------------------------------------------------------------

class AlpacaFilterWheel(AlpacaClient):
    # S30-Pro filter positions (confirmed Alpaca v1.2.0-3)
    DARK = 0
    IR   = 1
    LP   = 2

    def __init__(self, ip: str = SEESTAR_HOST, port: int = ALPACA_PORT,
                 device_number: int = FILTERWHEEL_NUM):
        super().__init__(ip, port, "filterwheel", device_number)

    def set_position(self, pos: int):
        self._put("position", Position=str(pos))

    @property
    def position(self) -> int:
        return self._get("position")


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
    """Build FITS header dictionary for AAVSO-compliant science frames."""
    ra_deg    = target.ra_hours * 15.0
    t_astropy = Time(utc_obs)

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
    """Write FITS file with hand-rolled header for zero-dependency reliability."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Ensure uint16 range then apply BZERO signed-integer encoding
    if array.dtype != np.uint16:
        array = np.clip(array, 0, 65535).astype(np.uint16)
    array_signed = (array.astype(np.int32) - 32768).astype(np.int16)
    if array_signed.dtype.byteorder not in (">",):
        array_signed = array_signed.byteswap().view(
            array_signed.dtype.newbyteorder(">"))

    def card(key: str, value, comment: str = "") -> str:
        key = key.upper()[:8].ljust(8)
        if isinstance(value, bool):    val_str = f"{'T' if value else 'F':>20}"
        elif isinstance(value, int):   val_str = f"{value:>20}"
        elif isinstance(value, float): val_str = f"{value:>20.10G}"
        elif isinstance(value, str):   val_str = f"'{value.replace(chr(39), chr(39)*2):<8}'".ljust(20)
        else:                          val_str = f"'{str(value):<8}'".ljust(20)
        return f"{key}= {val_str}{f' / {comment}' if comment else ''}"[:80].ljust(80)

    priority_keys = ["SIMPLE", "BITPIX", "NAXIS", "NAXIS1", "NAXIS2",
                     "BZERO", "BSCALE"]
    records  = [card(k, header_dict[k]) for k in priority_keys if k in header_dict]
    records += [card(k, v) for k, v in header_dict.items()
                if k not in priority_keys]
    records.append(
        "COMMENT   SeeVar v3.0.0 -- Alpaca REST -- BZERO Signed-Integer Protected"
        .ljust(80))
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
# Diamond Sequence — Alpaca implementation
# ---------------------------------------------------------------------------

class DiamondSequence:
    """
    Full target acquisition via Alpaca REST.

    Interface contract identical to v1.7.1 TCP version:
      init_session(level_ok) → TelemetryBlock
      acquire(target, status_cb, telemetry) → FrameResult

    FSM and Orchestrator call these methods unchanged.
    """

    def __init__(self, host: str = SEESTAR_HOST, port: int = ALPACA_PORT):
        self.host = host
        self.port = port
        self._telescope = AlpacaTelescope(host, port)
        self._camera    = AlpacaCamera(host, port)
        self._filter    = AlpacaFilterWheel(host, port)

    def _is_reachable(self) -> bool:
        """Quick health check — can we reach the Alpaca management API?"""
        try:
            r = requests.get(
                f"http://{self.host}:{self.port}/management/apiversions",
                timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def init_session(self, level_ok: bool = True) -> TelemetryBlock:
        """Initialize hardware session. Connect, unpark, enable tracking."""
        if not self._is_reachable():
            t = TelemetryBlock(parse_error="Alpaca server not reachable")
            t.level_ok = level_ok
            return t

        try:
            # Connect all devices
            self._telescope.connect()
            self._camera.connect()
            self._filter.connect()

            # Unpark if parked
            try:
                if self._telescope.at_park:
                    logger.info("Telescope parked — unparking...")
                    self._telescope.unpark()
                    time.sleep(2.0)
            except Exception as e:
                logger.warning("Unpark check/attempt: %s", e)

            # Enable tracking
            try:
                self._telescope.set_tracking(True)
            except Exception as e:
                logger.warning("Tracking enable: %s", e)

            # Set gain
            try:
                self._camera.set_gain(GAIN)
            except Exception as e:
                logger.warning("Gain set: %s", e)

            # Read telemetry
            telemetry = TelemetryBlock.from_alpaca(self._telescope, self._camera)
            telemetry.level_ok = level_ok

            logger.info("init_session: %s", telemetry.summary())

            if telemetry.veto_reason():
                return telemetry

            return telemetry

        except Exception as e:
            t = TelemetryBlock(parse_error=f"init_session exception: {e}")
            t.level_ok = level_ok
            return t

    def acquire(self, target: AcquisitionTarget,
                status_cb=None,
                telemetry: Optional[TelemetryBlock] = None) -> FrameResult:
        """Execute full target acquisition: slew → expose → download → FITS."""

        def notify(step, msg):
            if status_cb:
                status_cb(f"[{step}] {msg}")
            logger.info("[%s] %s", step, msg)

        t_start = time.monotonic()
        utc_obs = datetime.now(timezone.utc)
        ccd_temp = telemetry.temp_c if telemetry else None

        try:
            # A1 — Slew to target
            notify("A1", f"Slew RA={target.ra_hours:.4f}h "
                         f"DEC={target.dec_deg:.4f}° ({target.name})")
            self._telescope.slew_to_coordinates_async(
                target.ra_hours, target.dec_deg)

            if not self._telescope.wait_for_slew(SLEW_TIMEOUT):
                return FrameResult(success=False,
                                   error=f"Slew timeout ({SLEW_TIMEOUT}s)")

            # A2 — Settle
            notify("A2", f"Settling {SETTLE_SECONDS}s...")
            time.sleep(SETTLE_SECONDS)

            # Update observation timestamp to post-slew
            utc_obs = datetime.now(timezone.utc)

            # A3 — Set exposure parameters
            exp_sec = target.exp_ms / 1000.0
            notify("A3", f"Gain={GAIN}, exposure={exp_sec}s")
            try:
                self._camera.set_gain(GAIN)
            except Exception as e:
                logger.warning("Gain set during acquire: %s", e)

            # A4 — Start exposure
            notify("A4", f"StartExposure {exp_sec}s light=True")
            self._camera.start_exposure(exp_sec, light=True)

            # A5 — Wait for image
            notify("A5", "Waiting for exposure + readout...")
            image_timeout = exp_sec + EXPOSE_TIMEOUT
            if not self._camera.wait_for_image(exp_sec, timeout=image_timeout):
                return FrameResult(success=False,
                                   error=f"Image not ready after {image_timeout}s")

            # Read CCD temp post-exposure
            try:
                ccd_temp = self._camera.temperature
            except Exception:
                pass

            # A6 — Download image
            notify("A6", "Downloading image array...")
            t_dl = time.monotonic()
            img = self._camera.download_image()
            dl_time = time.monotonic() - t_dl
            notify("A6", f"Downloaded {img.shape} in {dl_time:.1f}s "
                         f"(min={img.min()} max={img.max()} "
                         f"mean={img.mean():.0f})")

            width  = img.shape[1]
            height = img.shape[0]

            # A7 — Write FITS
            notify("A7", f"Writing FITS — AUID={target.auid} "
                         f"CCD-TEMP={ccd_temp}")
            LOCAL_BUFFER.mkdir(parents=True, exist_ok=True)
            safe_name = target.name.replace(" ", "_").replace("/", "-")
            out_path = (LOCAL_BUFFER /
                        f"{safe_name}_{utc_obs.strftime('%Y%m%dT%H%M%S')}_Raw.fits")

            header = sovereign_stamp(target, utc_obs, width, height,
                                     ccd_temp=ccd_temp)
            ok = write_fits(img, header, out_path)
            elapsed = time.monotonic() - t_start

            if ok:
                notify("A7", f"FITS saved: {out_path} ({elapsed:.1f}s total)")
                return FrameResult(success=True, path=out_path,
                                   width=width, height=height,
                                   elapsed_s=elapsed)
            return FrameResult(success=False, error="FITS write failed",
                               elapsed_s=elapsed)

        except Exception as e:
            elapsed = time.monotonic() - t_start
            logger.exception("acquire() failed: %s", e)
            return FrameResult(success=False,
                               error=f"Acquire exception: {e}",
                               elapsed_s=elapsed)

    def park(self):
        """Park the telescope (close arm)."""
        try:
            self._telescope.park()
        except Exception as e:
            logger.warning("Park failed: %s", e)

    def disconnect_all(self):
        """Disconnect all Alpaca devices."""
        self._camera.disconnect()
        self._filter.disconnect()
        self._telescope.disconnect()


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
