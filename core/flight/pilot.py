#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/pilot.py
Version: 3.1.0
Objective: Sovereign Alpaca acquisition engine for the Seestar S30-Pro, owning A4-A11 including slew, pointing verification, corrective nudging, science acquisition, image download, and FITS custody.

Confirmed 2026-03-30:
  - Alpaca v1.2.0-3 on port 32323 — slew, expose, download ALL WORK
  - No phone app required. No session master lock.
  - 7 devices: 2 cameras, 2 focusers, filter wheel, telescope, switch
  - Camera #0 (Telephoto IMX585): 2160x3840, 2.9um, gain 0-600
  - Telescope #0: SlewToCoordinatesAsync, Park, Unpark, Tracking
  - FilterWheel #0: positions Dark(0), IR(1), LP(2)

Interface contract:
  - DiamondSequence.init_session(level_ok) -> TelemetryBlock
  - DiamondSequence.acquire(target, status_cb, telemetry) -> FrameResult
  - AcquisitionTarget, FrameResult, TelemetryBlock dataclasses
  - sovereign_stamp(), write_fits() utility functions
"""

import json
import logging
import math
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import requests
from astropy.coordinates import EarthLocation, AltAz, SkyCoord, get_body
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS
import astropy.units as u

from core.utils.env_loader import DATA_DIR, ENV_STATUS, load_config, selected_scope, selected_scope_host, scope_file_tag
from core.flight.field_rotation import max_exposure_s as rotation_limited_exposure

# ---------------------------------------------------------------------------
# Dynamic IP Resolution
# ---------------------------------------------------------------------------

def _resolve_seestar_host() -> tuple[str, str]:
    return selected_scope_host(load_config())


# ---------------------------------------------------------------------------
# Constants — single source of truth (S30-Pro / Alpaca v1.2.0-3)
# ---------------------------------------------------------------------------

SEESTAR_HOST, SEESTAR_HOST_SOURCE = _resolve_seestar_host()
ALPACA_PORT = 32323
TELESCOPE_NUM = 0
CAMERA_NUM = 0
FILTERWHEEL_NUM = 0
SWITCH_NUM = 0

SENSOR_W = 3840
SENSOR_H = 2160
BAYER_PATTERN = "GRBG"
INSTRUMENT = "IMX585"
TELESCOPE = "ZWO Seestar S30-Pro"
FILTER_NAME = "TG"

GAIN = 80
FOCALLEN = 160
APERTURE = 30
PIXSCALE = 3.74
PIXEL_SIZE_UM = 2.9
RDNOISE = 1.6
PEDESTAL = 0
SWCREATE = "SeeVar v3.1.0 (Alpaca)"

SETTLE_SECONDS = 8
SLEW_TIMEOUT = 60
EXPOSE_TIMEOUT = 120
DOWNLOAD_TIMEOUT = 300
EXP_MS_DEFAULT = 5000

VETO_BATTERY = 10
VETO_TEMP = 55.0

CLIENT_ID = 42

VERIFY_EXPOSURE_SEC = 2.0
VERIFY_EXPOSURE_RETRY_SEC = 2.0
POINTING_TOLERANCE_ARCMIN = 12.0
POINTING_MAX_RETRIES = 1
PLATESOLVE_RADIUS_DEG = 5.0
PLATESOLVE_DOWNSAMPLE = 1
PLATESOLVE_TIMEOUT = 90

LOCAL_BUFFER = DATA_DIR / "local_buffer"
VERIFY_BUFFER = DATA_DIR / "verify_buffer"
ACTIVE_SCOPE = selected_scope(load_config())
ACTIVE_SCOPE_TAG = scope_file_tag(ACTIVE_SCOPE)
logger = logging.getLogger("seevar.pilot")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AcquisitionTarget:
    name: str
    ra_hours: float
    dec_deg: float
    auid: str = ""
    exp_ms: int = EXP_MS_DEFAULT
    observer_code: str = ""
    n_frames: int = 1
    integration_sec: Optional[float] = None


@dataclass
class FrameResult:
    success: bool
    path: Optional[Path] = None
    width: int = 0
    height: int = 0
    elapsed_s: float = 0.0
    error: str = ""


@dataclass
class TelemetryBlock:
    battery_pct: Optional[int] = None
    temp_c: Optional[float] = None
    charge_online: Optional[bool] = None
    charger_status: Optional[str] = None
    device_name: Optional[str] = None
    firmware_ver: Optional[int] = None
    level_ok: bool = True
    raw: Optional[dict] = None
    parse_error: Optional[str] = None

    tracking: Optional[bool] = None
    at_park: Optional[bool] = None
    ra_hours: Optional[float] = None
    dec_deg: Optional[float] = None
    altitude: Optional[float] = None
    azimuth: Optional[float] = None
    alpaca_version: Optional[str] = None

    @classmethod
    def from_alpaca(cls, telescope: "AlpacaTelescope", camera: "AlpacaCamera") -> "TelemetryBlock":
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
            )
        except Exception as e:
            return cls(parse_error=f"Alpaca telemetry read failed: {e}")

    @classmethod
    def from_response(cls, response: Optional[dict]) -> "TelemetryBlock":
        if response is None:
            return cls(parse_error="No response received")
        try:
            result = response.get("result", response)
            pi = result.get("pi_status", {})
            dev = result.get("device", {})
            return cls(
                battery_pct=pi.get("battery_capacity"),
                temp_c=pi.get("temp"),
                charge_online=pi.get("charge_online"),
                charger_status=pi.get("charger_status"),
                device_name=dev.get("name"),
                firmware_ver=dev.get("firmware_ver_int"),
                raw=result,
            )
        except Exception as e:
            return cls(parse_error=str(e), raw=response)

    def veto_reason(self) -> Optional[str]:
        if self.parse_error:
            return f"Telemetry unavailable: {self.parse_error}"
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
# Alpaca REST Client
# ---------------------------------------------------------------------------

class AlpacaClient:
    def __init__(self, ip: str, port: int, device_type: str, device_number: int):
        self.base = f"http://{ip}:{port}/api/v1/{device_type}/{device_number}"
        self._txid = 0

    def _next_tx(self) -> int:
        self._txid += 1
        return self._txid

    def _get(self, prop: str, timeout: float = 10.0):
        params = {
            "ClientID": CLIENT_ID,
            "ClientTransactionID": self._next_tx(),
        }
        r = requests.get(f"{self.base}/{prop}", params=params, timeout=timeout)
        data = r.json()
        err = data.get("ErrorNumber", 0)
        if err:
            raise RuntimeError(f"Alpaca GET {prop}: error {err} — {data.get('ErrorMessage', '')}")
        return data.get("Value")

    def _put(self, method: str, timeout: float = 15.0, **kwargs):
        payload = {
            "ClientID": CLIENT_ID,
            "ClientTransactionID": self._next_tx(),
        }
        payload.update(kwargs)
        r = requests.put(f"{self.base}/{method}", data=payload, timeout=timeout)
        data = r.json()
        err = data.get("ErrorNumber", 0)
        if err:
            raise RuntimeError(f"Alpaca PUT {method}: error {err} — {data.get('ErrorMessage', '')}")
        return data.get("Value")

    def safe_get(self, prop: str, default=None):
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


class AlpacaTelescope(AlpacaClient):
    def __init__(self, ip: str | None = None, port: int = ALPACA_PORT, device_number: int = TELESCOPE_NUM):
        host, _ = selected_scope_host(load_config()) if not ip else (ip, "explicit argument")
        super().__init__(host, port, "telescope", device_number)

    def unpark(self):
        self._put("unpark")

    def park(self):
        self._put("park")

    def set_tracking(self, on: bool):
        self._put("tracking", Tracking=str(on).lower())

    def slew_to_coordinates_async(self, ra_hours: float, dec_deg: float):
        self._put(
            "slewtocoordinatesasync",
            RightAscension=str(ra_hours),
            Declination=str(dec_deg),
            timeout=20.0,
        )

    def wait_for_slew(self, timeout: float = SLEW_TIMEOUT) -> bool:
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


class AlpacaCamera(AlpacaClient):
    IDLE = 0
    WAITING = 1
    EXPOSING = 2
    READING = 3
    DOWNLOAD = 4
    ERROR = 5

    STATE_NAMES = {
        0: "Idle",
        1: "Waiting",
        2: "Exposing",
        3: "Reading",
        4: "Download",
        5: "Error",
    }

    def __init__(self, ip: str | None = None, port: int = ALPACA_PORT, device_number: int = CAMERA_NUM):
        host, _ = selected_scope_host(load_config()) if not ip else (ip, "explicit argument")
        super().__init__(host, port, "camera", device_number)

    def set_gain(self, gain: int):
        self._put("gain", Gain=str(gain))

    def start_exposure(self, duration_sec: float, light: bool = True):
        self._put("startexposure", Duration=str(duration_sec), Light=str(light).lower())

    def abort_exposure(self):
        self._put("abortexposure")

    def wait_for_image(self, exposure_sec: float, timeout: float = EXPOSE_TIMEOUT) -> bool:
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
        params = {
            "ClientID": CLIENT_ID,
            "ClientTransactionID": self._next_tx(),
        }
        r = requests.get(f"{self.base}/imagearray", params=params, timeout=DOWNLOAD_TIMEOUT)
        data = r.json()
        err = data.get("ErrorNumber", 0)
        if err:
            raise RuntimeError(f"imagearray: error {err} — {data.get('ErrorMessage', '')}")

        value = data.get("Value")
        if value is None:
            raise RuntimeError("imagearray returned no Value")

        return np.array(value, dtype=np.int32)

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


class AlpacaFilterWheel(AlpacaClient):
    DARK = 0
    IR = 1
    LP = 2

    def __init__(self, ip: str | None = None, port: int = ALPACA_PORT, device_number: int = FILTERWHEEL_NUM):
        host, _ = selected_scope_host(load_config()) if not ip else (ip, "explicit argument")
        super().__init__(host, port, "filterwheel", device_number)

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
        lat = float(data.get("lat", 0.0))
        lon = float(data.get("lon", 0.0))
        elev = float(data.get("elevation", 0.0))
        return {"lat": lat, "lon": lon, "elevation": elev}
    except Exception:
        return {"lat": 0.0, "lon": 0.0, "elevation": 0.0}


def sovereign_stamp(
    target: AcquisitionTarget,
    utc_obs: datetime,
    width: int,
    height: int,
    ccd_temp: Optional[float] = None,
) -> dict:
    ra_deg = target.ra_hours * 15.0
    t_astropy = Time(utc_obs)

    gps = _read_gps_ram()
    site_lat, site_lon, site_elev = gps["lat"], gps["lon"], gps["elevation"]
    gps_valid = not (site_lat == 0.0 and site_lon == 0.0)

    airmass = moon_phase = moon_alt = None
    if gps_valid:
        try:
            location = EarthLocation(lat=site_lat * u.deg, lon=site_lon * u.deg, height=site_elev * u.m)
            frame = AltAz(obstime=t_astropy, location=location)
            target_coord = SkyCoord(ra=ra_deg * u.deg, dec=target.dec_deg * u.deg, frame="icrs")
            altaz = target_coord.transform_to(frame)
            alt_deg = float(altaz.alt.deg)
            if alt_deg > 0.0:
                airmass = round(1.0 / math.sin(math.radians(alt_deg)), 4)

            moon = get_body("moon", t_astropy, location)
            moon_alt = round(float(moon.transform_to(frame).alt.deg), 2)
            sun = get_body("sun", t_astropy, location)
            sep = moon.separation(sun).deg
            moon_phase = round(min(max((1.0 - math.cos(math.radians(sep))) / 2.0, 0.0), 1.0), 4)
        except Exception:
            pass

    h = {
        "SIMPLE": True,
        "BITPIX": 16,
        "NAXIS": 2,
        "NAXIS1": width,
        "NAXIS2": height,
        "BZERO": 32768.0,
        "BSCALE": 1.0,
        "OBJECT": target.name,
        "OBJCTRA": _hours_to_hms(target.ra_hours),
        "OBJCTDEC": _deg_to_dms(target.dec_deg),
        "RA": ra_deg,
        "DEC": target.dec_deg,
        "CRVAL1": ra_deg,
        "CRVAL2": target.dec_deg,
        "CRPIX1": width / 2.0,
        "CRPIX2": height / 2.0,
        "CDELT1": -0.001042,
        "CDELT2": 0.001042,
        "CTYPE1": "RA---TAN",
        "CTYPE2": "DEC--TAN",
        "DATE-OBS": utc_obs.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
        "EXPTIME": target.exp_ms / 1000.0,
        "EXPMS": int(target.exp_ms),
        "INSTRUME": INSTRUMENT,
        "TELESCOP": TELESCOPE,
        "FILTER": FILTER_NAME,
        "BAYERPAT": BAYER_PATTERN,
        "GAIN": GAIN,
        "FOCALLEN": FOCALLEN,
        "APERTURE": APERTURE,
        "PIXSCALE": PIXSCALE,
        "RDNOISE": RDNOISE,
        "PEDESTAL": PEDESTAL,
        "OBSERVER": target.observer_code or "UNKNOWN",
        "SITELAT": site_lat,
        "SITELONG": site_lon,
        "SITEELEV": site_elev,
        "SWCREATE": SWCREATE,
    }

    h["CCD-TEMP"] = ccd_temp if ccd_temp is not None else "UNKNOWN"
    h["SCOPEID"] = str(ACTIVE_SCOPE.get("scope_id", ACTIVE_SCOPE_TAG))[:68]
    h["SCOPENAM"] = str(ACTIVE_SCOPE.get("scope_name", ACTIVE_SCOPE_TAG))[:68]
    if ACTIVE_SCOPE.get("ip"):
        h["SCOPEIP"] = str(ACTIVE_SCOPE.get("ip"))[:68]
    if airmass is not None:
        h["AIRMASS"] = airmass
    if moon_phase is not None:
        h["MOONPHASE"] = moon_phase
    if moon_alt is not None:
        h["MOONALT"] = moon_alt
    if target.auid:
        h["AUID"] = target.auid
    h["JD"] = round(t_astropy.jd, 6)

    return h


def write_fits(array: np.ndarray, header_dict: dict, output_path: Path) -> bool:
    # Backward compatibility: older simulation code passed
    # write_fits(output_path, array, header_dict).
    if isinstance(array, Path) and isinstance(header_dict, np.ndarray) and isinstance(output_path, fits.Header):
        array, header_dict, output_path = header_dict, output_path, array

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if array.dtype != np.uint16:
        array = np.clip(array, 0, 65535).astype(np.uint16)
    array_signed = (array.astype(np.int32) - 32768).astype(np.int16)
    if array_signed.dtype.byteorder not in (">",):
        array_signed = array_signed.byteswap().view(array_signed.dtype.newbyteorder(">"))

    def card(key: str, value, comment: str = "") -> str:
        key = key.upper()[:8].ljust(8)
        if isinstance(value, bool):
            val_str = f"{'T' if value else 'F':>20}"
        elif isinstance(value, int):
            val_str = f"{value:>20}"
        elif isinstance(value, float):
            val_str = f"{value:>20.10G}"
        elif isinstance(value, str):
            val_str = f"'{value.replace(chr(39), chr(39) * 2):<8}'".ljust(20)
        else:
            val_str = f"'{str(value):<8}'".ljust(20)
        return f"{key}= {val_str}{f' / {comment}' if comment else ''}"[:80].ljust(80)

    priority_keys = ["SIMPLE", "BITPIX", "NAXIS", "NAXIS1", "NAXIS2", "BZERO", "BSCALE"]
    records = [card(k, header_dict[k]) for k in priority_keys if k in header_dict]
    records += [card(k, v) for k, v in header_dict.items() if k not in priority_keys]
    records.append("COMMENT   SeeVar v3.1.0 -- Alpaca REST -- BZERO Signed-Integer Protected".ljust(80))
    records.append("END".ljust(80))

    while (len(records) * 80) % 2880 != 0:
        records.append(" " * 80)

    header_bytes = "".join(records).encode("ascii")
    data_bytes = array_signed.tobytes()
    remainder = len(data_bytes) % 2880
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

    Interface contract remains:
      init_session(level_ok) -> TelemetryBlock
      acquire(target, status_cb, telemetry) -> FrameResult
    """

    def __init__(self, host: str | None = None, port: int = ALPACA_PORT):
        resolved_host, resolved_source = selected_scope_host(load_config()) if not host else (host, "explicit argument")
        self.host = resolved_host
        self.port = port
        self.host_source = resolved_source
        logger.info("DiamondSequence endpoint: %s:%d (%s)", self.host, self.port, self.host_source)
        self._telescope = AlpacaTelescope(self.host, port)
        self._camera = AlpacaCamera(self.host, port)
        self._filter = AlpacaFilterWheel(self.host, port)
        self._session_ready = False
        self._session_connects = 0
        self._last_session_error = ""

    def _management_status(self) -> tuple[bool, str]:
        try:
            r = requests.get(f"http://{self.host}:{self.port}/management/apiversions", timeout=5)
            if r.status_code != 200:
                return False, f"Alpaca management returned HTTP {r.status_code}"
            return True, ""
        except Exception as e:
            return False, f"Alpaca management unreachable: {e}"

    def _is_reachable(self) -> bool:
        ok, _ = self._management_status()
        return ok

    def _require_connected(self, client: AlpacaClient, label: str):
        try:
            connected = bool(client.connected)
        except Exception as e:
            raise RuntimeError(f"{label} connection probe failed: {e}")
        if not connected:
            raise RuntimeError(f"{label} reports connected=false after connect()")

    def _session_health(self) -> tuple[bool, str]:
        ok, err = self._management_status()
        if not ok:
            return False, err

        try:
            if not self._telescope.connected:
                return False, "Telescope disconnected"
            if not self._camera.connected:
                return False, "Camera disconnected"
            if not self._filter.connected:
                return False, "Filter wheel disconnected"

            self._telescope._get("tracking")
            self._telescope._get("atpark")
            self._telescope._get("rightascension")
            self._telescope._get("declination")
            return True, ""
        except Exception as e:
            return False, f"Alpaca backend reachable but telescope not operational: {e}"

    def _read_operational_telemetry(self, level_ok: bool) -> TelemetryBlock:
        telemetry = TelemetryBlock.from_alpaca(self._telescope, self._camera)
        telemetry.level_ok = level_ok
        if telemetry.parse_error:
            telemetry.parse_error = f"Alpaca backend reachable but telemetry unavailable: {telemetry.parse_error}"
        return telemetry

    def _site_latitude_deg(self) -> float | None:
        gps = _read_gps_ram()
        lat = gps.get("lat")
        if lat not in (None, 0.0):
            return float(lat)
        try:
            cfg = load_config()
            return float(cfg.get("location", {}).get("lat"))
        except Exception:
            return None

    def _mount_mode(self) -> str:
        try:
            scope = selected_scope(load_config())
            if scope:
                return str(scope.get("mount", "altaz")).strip().lower()
        except Exception:
            pass
        return "altaz"

    def prepare_target(self, target: AcquisitionTarget, telemetry: Optional[TelemetryBlock] = None, notify=None) -> AcquisitionTarget:
        def emit(msg: str):
            if notify:
                notify("A9", msg)
            logger.info("[A9] %s", msg)

        if self._mount_mode() not in {"altaz", "alt/az", "alt-az"}:
            return target

        lat_deg = self._site_latitude_deg()
        if lat_deg is None:
            emit("Field rotation cap skipped: site latitude unavailable")
            return target

        try:
            alt_deg = float(self._telescope.altitude)
            az_deg = float(self._telescope.azimuth)
        except Exception as e:
            emit(f"Field rotation cap skipped: live alt/az unavailable ({e})")
            return target

        try:
            rot = rotation_limited_exposure(az_deg, alt_deg, lat_deg, PIXSCALE)
        except Exception as e:
            emit(f"Field rotation cap skipped: solver failed ({e})")
            return target

        current_exp_sec = max(1.0, float(target.exp_ms) / 1000.0)
        if rot.max_exp_integ_s >= current_exp_sec - 0.05:
            return target

        capped_exp_sec = max(7.5, float(rot.max_exp_integ_s))
        capped_exp_ms = max(1000, int(round(capped_exp_sec * 1000.0)))
        planned_total_sec = float(target.integration_sec) if target.integration_sec is not None else current_exp_sec * max(1, int(target.n_frames))
        new_n_frames = max(int(target.n_frames), int(math.ceil(planned_total_sec / capped_exp_sec)))

        emit(
            f"Field rotation cap: alt={alt_deg:.1f}° az={az_deg:.1f}° mount=ALT/AZ "
            f"frame {current_exp_sec:.1f}s -> {capped_exp_sec:.1f}s; n_frames {target.n_frames} -> {new_n_frames}"
        )

        return AcquisitionTarget(
            name=target.name,
            ra_hours=target.ra_hours,
            dec_deg=target.dec_deg,
            auid=target.auid,
            exp_ms=capped_exp_ms,
            observer_code=target.observer_code,
            n_frames=new_n_frames,
            integration_sec=planned_total_sec,
        )

    def _capture_temp_frame(self, target: AcquisitionTarget, exposure_sec: float, suffix: str, ccd_temp=None) -> Path:
        self._camera.start_exposure(exposure_sec, light=True)
        image_timeout = exposure_sec + EXPOSE_TIMEOUT
        if not self._camera.wait_for_image(exposure_sec, timeout=image_timeout):
            raise RuntimeError(f"Verification image not ready after {image_timeout}s")

        img = self._camera.download_image()
        width = img.shape[1]
        height = img.shape[0]

        VERIFY_BUFFER.mkdir(parents=True, exist_ok=True)
        utc_obs = datetime.now(timezone.utc)
        safe_name = target.name.replace(" ", "_").replace("/", "-")
        out_path = VERIFY_BUFFER / f"{safe_name}_{ACTIVE_SCOPE_TAG}_{utc_obs.strftime('%Y%m%dT%H%M%S')}_{suffix}.fits"

        header = sovereign_stamp(target, utc_obs, width, height, ccd_temp=ccd_temp)
        ok = write_fits(img, header, out_path)
        if not ok:
            raise RuntimeError("Verification FITS write failed")

        return out_path

    def _solve_verify_frame(self, fits_path: Path, target: AcquisitionTarget) -> dict:
        work_dir = fits_path.parent
        ra_deg = target.ra_hours * 15.0
        dec_deg = target.dec_deg

        cmd = [
            "solve-field",
            str(fits_path),
            "--dir", str(work_dir),
            "--overwrite",
            "--no-plots",
            "--downsample", str(PLATESOLVE_DOWNSAMPLE),
            "--ra", str(ra_deg),
            "--dec", str(dec_deg),
            "--radius", str(PLATESOLVE_RADIUS_DEG),
            "--scale-units", "arcsecperpix",
            "--scale-low", "3.0",
            "--scale-high", "4.5",
            "--tweak-order", "1",
            "--cpulimit", "45",
        ]

        logger.info(
            "A7 solve-field start: file=%s ra=%.4f dec=%.4f radius=%.1f timeout=%ss",
            fits_path.name,
            ra_deg,
            dec_deg,
            PLATESOLVE_RADIUS_DEG,
            PLATESOLVE_TIMEOUT,
        )

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=PLATESOLVE_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            logger.warning("A7 solve-field timeout after %ss for %s", PLATESOLVE_TIMEOUT, fits_path.name)
            return {
                "ok": False,
                "error": f"solve-field timeout after {PLATESOLVE_TIMEOUT}s",
                "stderr": "",
            }

        wcs_path = fits_path.with_suffix(".wcs")

        if not wcs_path.exists():
            logger.warning(
                "A7 solve-field failed: rc=%s stderr=%s",
                result.returncode,
                (result.stderr or "").strip()[-300:],
            )
            return {
                "ok": False,
                "error": f"solve-field failed ({result.returncode})",
                "stderr": (result.stderr or "").strip()[-300:],
            }

        hdr = fits.getheader(wcs_path, 0)
        solved_ra_deg = float(hdr.get("CRVAL1"))
        solved_dec_deg = float(hdr.get("CRVAL2"))

        target_coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")
        solved_coord = SkyCoord(ra=solved_ra_deg * u.deg, dec=solved_dec_deg * u.deg, frame="icrs")
        error_arcmin = float(target_coord.separation(solved_coord).arcminute)

        logger.info(
            "A7 solve-field success: file=%s err=%.2f arcmin",
            fits_path.name,
            error_arcmin,
        )

        return {
            "ok": True,
            "wcs_path": wcs_path,
            "solved_ra_deg": solved_ra_deg,
            "solved_dec_deg": solved_dec_deg,
            "error_arcmin": error_arcmin,
        }

    def _pointing_verify(self, target: AcquisitionTarget, notify, ccd_temp=None) -> dict:
        notify("A7", f"Pointing verify frame {VERIFY_EXPOSURE_SEC:.1f}s")
        try:
            verify_fits = self._capture_temp_frame(target, VERIFY_EXPOSURE_SEC, "VERIFY", ccd_temp=ccd_temp)
        except Exception as e:
            notify("A7", f"Verify capture failed: {e}")
            return {
                "ok": False,
                "error_arcmin": None,
                "error": str(e),
            }

        try:
            solve = self._solve_verify_frame(verify_fits, target)
            solve["verify_fits"] = verify_fits
            if solve.get("ok"):
                notify("A7", f"Solve success error={solve['error_arcmin']:.2f} arcmin")
                return solve

            notify("A7", f"Verify solve failed: {solve.get('error', 'unknown error')}")
            return {
                "ok": False,
                "verify_fits": verify_fits,
                "error_arcmin": None,
                "error": solve.get("error", "unknown error"),
            }
        except Exception as e:
            notify("A7", f"Verify solve exception: {e}")
            return {
                "ok": False,
                "verify_fits": verify_fits,
                "error_arcmin": None,
                "error": str(e),
            }

    def _corrective_nudge(self, command_ra_hours: float, command_dec_deg: float, solve_result: dict) -> tuple[float, float]:
        solved_ra_hours = float(solve_result["solved_ra_deg"]) / 15.0
        solved_dec_deg = float(solve_result["solved_dec_deg"])

        delta_ra_hours = command_ra_hours - solved_ra_hours
        delta_dec_deg = command_dec_deg - solved_dec_deg

        corrected_ra_hours = command_ra_hours + delta_ra_hours
        corrected_dec_deg = command_dec_deg + delta_dec_deg

        corrected_ra_hours = corrected_ra_hours % 24.0
        corrected_dec_deg = max(-90.0, min(90.0, corrected_dec_deg))
        return corrected_ra_hours, corrected_dec_deg

    def init_session(self, level_ok: bool = True) -> TelemetryBlock:
        mgmt_ok, mgmt_error = self._management_status()
        if not mgmt_ok:
            self._session_ready = False
            self._last_session_error = mgmt_error
            t = TelemetryBlock(parse_error=mgmt_error)
            t.level_ok = level_ok
            return t

        if self._session_ready:
            healthy, reason = self._session_health()
            if healthy:
                telemetry = self._read_operational_telemetry(level_ok)
                self._last_session_error = telemetry.parse_error or ""
                logger.info("init_session: reusing healthy Alpaca session (%d prior connects)", self._session_connects)
                logger.info("init_session: %s", telemetry.summary())
                return telemetry

            logger.warning("init_session: cached Alpaca session unhealthy, reconnecting: %s", reason)
            self._session_ready = False

        try:
            self._telescope.connect()
            self._require_connected(self._telescope, "Telescope")

            self._camera.connect()
            self._require_connected(self._camera, "Camera")

            self._filter.connect()
            self._require_connected(self._filter, "Filter wheel")

            try:
                if self._telescope.at_park:
                    logger.info("Telescope parked — unparking...")
                    self._telescope.unpark()
                    time.sleep(2.0)
            except Exception as e:
                logger.warning("Unpark check/attempt: %s", e)

            try:
                self._telescope.set_tracking(True)
                try:
                    tracking_now = self._telescope._get("tracking")
                    if not tracking_now:
                        logger.warning("Tracking enable requested but tracking still reports OFF")
                except Exception as e:
                    logger.warning("Tracking state probe after enable: %s", e)
            except Exception as e:
                logger.warning("Tracking enable: %s", e)

            try:
                self._camera.set_gain(GAIN)
            except Exception as e:
                logger.warning("Gain set: %s", e)

            telemetry = self._read_operational_telemetry(level_ok)
            self._session_ready = telemetry.parse_error is None
            self._session_connects += 1
            self._last_session_error = telemetry.parse_error or ""
            logger.info("init_session: %s", telemetry.summary())

            return telemetry

        except Exception as e:
            self._session_ready = False
            self._last_session_error = str(e)
            t = TelemetryBlock(parse_error=f"init_session exception: {e}")
            t.level_ok = level_ok
            return t

    def acquire(self, target: AcquisitionTarget, status_cb=None, telemetry: Optional[TelemetryBlock] = None, skip_pointing: bool = False) -> FrameResult:
        """Execute A4-A11 for one target, or science-only when pointing is already established."""

        def notify(step, msg):
            if status_cb:
                status_cb(f"[{step}] {msg}")
            logger.info("[%s] %s", step, msg)

        t_start = time.monotonic()
        ccd_temp = telemetry.temp_c if telemetry else None
        command_ra_hours = float(target.ra_hours)
        command_dec_deg = float(target.dec_deg)
        exp_sec = target.exp_ms / 1000.0

        try:
            if not skip_pointing:
                for attempt in range(POINTING_MAX_RETRIES + 1):
                    notify("A4", f"Slew command RA={command_ra_hours:.4f}h DEC={command_dec_deg:.4f}° ({target.name})")
                    self._telescope.slew_to_coordinates_async(command_ra_hours, command_dec_deg)

                    notify("A5", f"Waiting for slew completion (timeout={SLEW_TIMEOUT}s)")
                    if not self._telescope.wait_for_slew(SLEW_TIMEOUT):
                        return FrameResult(success=False, error=f"Slew timeout ({SLEW_TIMEOUT}s)")

                    notify("A6", f"Settling {SETTLE_SECONDS}s after slew")
                    time.sleep(SETTLE_SECONDS)

                    verify_target = AcquisitionTarget(
                        name=target.name,
                        ra_hours=command_ra_hours,
                        dec_deg=command_dec_deg,
                        auid=target.auid,
                        exp_ms=target.exp_ms,
                        observer_code=target.observer_code,
                        n_frames=1,
                        integration_sec=target.integration_sec,
                    )

                    solve = self._pointing_verify(verify_target, notify, ccd_temp=ccd_temp)

                    if not solve.get("ok"):
                        notify("A7", f"Pointing verify failed: {solve.get('error', 'unknown error')}")
                        if attempt >= POINTING_MAX_RETRIES:
                            return FrameResult(success=False, error=f"Verify solve failed after retries: {solve.get('error', 'unknown error')}")
                        notify("A8", f"Retrying pointing loop ({attempt + 1}/{POINTING_MAX_RETRIES}) after unsolved verify frame")
                        continue

                    error_arcmin = float(solve["error_arcmin"])
                    if error_arcmin <= POINTING_TOLERANCE_ARCMIN:
                        notify("A7", f"Pointing accepted ({error_arcmin:.2f} arcmin <= {POINTING_TOLERANCE_ARCMIN:.2f})")
                        break

                    notify("A7", f"Pointing outside tolerance ({error_arcmin:.2f} arcmin > {POINTING_TOLERANCE_ARCMIN:.2f})")
                    if attempt >= POINTING_MAX_RETRIES:
                        return FrameResult(success=False, error=f"Pointing error {error_arcmin:.2f} arcmin after retries")

                    command_ra_hours, command_dec_deg = self._corrective_nudge(command_ra_hours, command_dec_deg, solve)
                    notify("A8", f"Corrective nudge -> RA={command_ra_hours:.4f}h DEC={command_dec_deg:.4f}° (retry {attempt + 1}/{POINTING_MAX_RETRIES})")
                else:
                    return FrameResult(success=False, error="Pointing loop exhausted unexpectedly")
            else:
                notify("A10", f"Reusing established pointing for {target.name}")

            try:
                tracking_now = self._telescope.safe_get("tracking")
                if tracking_now is False:
                    notify("A10", "Tracking reported OFF before science exposure; re-enabling")
                    self._telescope.set_tracking(True)
                    time.sleep(1.0)
                    tracking_after = self._telescope.safe_get("tracking")
                    if tracking_after is False:
                        logger.warning("Tracking still reports OFF after re-enable request")
                elif tracking_now is None:
                    logger.warning("Tracking state unavailable before science exposure")
            except Exception as e:
                logger.warning("Tracking verification before science exposure failed: %s", e)

            notify("A10", f"Set gain={GAIN} and start science exposure {exp_sec:.1f}s")
            try:
                self._camera.set_gain(GAIN)
            except Exception as e:
                logger.warning("Gain set during acquire: %s", e)

            self._camera.start_exposure(exp_sec, light=True)

            notify("A10", "Waiting for science exposure + readout")
            image_timeout = exp_sec + EXPOSE_TIMEOUT
            if not self._camera.wait_for_image(exp_sec, timeout=image_timeout):
                return FrameResult(success=False, error=f"Image not ready after {image_timeout}s")

            try:
                ccd_temp = self._camera.temperature
            except Exception:
                pass

            notify("A10", "Downloading science image array")
            t_dl = time.monotonic()
            img = self._camera.download_image()
            dl_time = time.monotonic() - t_dl
            notify("A10", f"Downloaded {img.shape} in {dl_time:.1f}s (min={img.min()} max={img.max()} mean={img.mean():.0f})")

            width = img.shape[1]
            height = img.shape[0]
            utc_obs = datetime.now(timezone.utc)

            notify("A10", f"Writing science FITS — AUID={target.auid} CCD-TEMP={ccd_temp}")
            LOCAL_BUFFER.mkdir(parents=True, exist_ok=True)
            safe_name = target.name.replace(" ", "_").replace("/", "-")
            out_path = LOCAL_BUFFER / f"{safe_name}_{ACTIVE_SCOPE_TAG}_{utc_obs.strftime('%Y%m%dT%H%M%S')}_Raw.fits"

            science_target = AcquisitionTarget(
                name=target.name,
                ra_hours=command_ra_hours,
                dec_deg=command_dec_deg,
                auid=target.auid,
                exp_ms=target.exp_ms,
                observer_code=target.observer_code,
                n_frames=1,
                integration_sec=target.integration_sec,
            )
            header = sovereign_stamp(science_target, utc_obs, width, height, ccd_temp=ccd_temp)
            ok = write_fits(img, header, out_path)
            if not ok:
                return FrameResult(success=False, error="FITS write failed")

            notify("A11", "Frame quality gate")
            if img.ndim != 2 or width <= 0 or height <= 0:
                return FrameResult(success=False, error="Invalid image geometry")
            if float(img.max()) <= float(img.min()):
                return FrameResult(success=False, error="Flat image statistics")

            elapsed = time.monotonic() - t_start
            notify("A11", f"Frame accepted: {out_path} ({elapsed:.1f}s total)")
            return FrameResult(success=True, path=out_path, width=width, height=height, elapsed_s=elapsed)

        except Exception as e:
            elapsed = time.monotonic() - t_start
            logger.exception("acquire() failed: %s", e)
            return FrameResult(success=False, error=f"Acquire exception: {e}", elapsed_s=elapsed)

    def park(self):
        try:
            self._telescope.park()
        except Exception as e:
            logger.warning("Park failed: %s", e)

    def disconnect_all(self):
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
    deg = abs(deg)
    d = int(deg)
    m = int((deg - d) * 60)
    s = ((deg - d) * 60 - m) * 60
    return f"{sign}{d:02d}:{m:02d}:{s:04.1f}"


if __name__ == "__main__":
    pass
