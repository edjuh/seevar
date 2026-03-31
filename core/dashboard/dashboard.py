#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/dashboard/dashboard.py
Version: 5.0.0
Objective: Fleet-ready dashboard with Alpaca REST telemetry on port 32323.
           Source 4 replaced: TCP port 4700 coord poll → Alpaca telescope reads.
           Source 3 retained: WilhelminaMonitor for battery/charger (not in Alpaca).
           Fleet-ready: iterates [[seestars]] for multi-telescope support.
"""
import json
import logging
import os
import sys
import time
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from flask import Flask, render_template, jsonify

import requests as http_requests
from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, get_sun
from astropy.time import Time

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR          = Path(__file__).resolve().parent
PROJECT_ROOT      = Path(__file__).resolve().parents[2]
DATA_DIR          = PROJECT_ROOT / "data"
PLAN_FILE         = DATA_DIR / "tonights_plan.json"
STATE_FILE        = DATA_DIR / "system_state.json"
LEDGER_FILE       = DATA_DIR / "ledger.json"
WEATHER_FILE      = DATA_DIR / "weather_state.json"
SIRIL_LOG         = PROJECT_ROOT / "logs" / "siril_extraction.log"
ENV_STATUS        = Path("/dev/shm/env_status.json")
WILHELMINA_STATE  = Path("/dev/shm/wilhelmina_state.json")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("dashboard")

# ---------------------------------------------------------------------------
# Project imports
# ---------------------------------------------------------------------------
sys.path.append(str(PROJECT_ROOT))
try:
    from core.utils.observer_math import get_maidenhead_6char
except ImportError:
    def get_maidenhead_6char(lat, lon):
        return "UNKNOWN"

# ---------------------------------------------------------------------------
# Flask
# ---------------------------------------------------------------------------
TEMPLATE_DIR = BASE_DIR / "templates"
app = Flask(__name__, template_folder=str(TEMPLATE_DIR))

# ---------------------------------------------------------------------------
# Alpaca REST poller (replaces TCP port 4700 coord poll)
# ---------------------------------------------------------------------------
ALPACA_TIMEOUT = 2.0  # seconds per HTTP request

def _alpaca_get(ip: str, port: int, device_type: str, device_num: int,
                prop: str):
    """Quick Alpaca property read. Returns Value or None."""
    try:
        r = http_requests.get(
            f"http://{ip}:{port}/api/v1/{device_type}/{device_num}/{prop}",
            params={"ClientID": 42, "ClientTransactionID": 1},
            timeout=ALPACA_TIMEOUT)
        data = r.json()
        if data.get("ErrorNumber", 0) == 0:
            return data.get("Value")
    except Exception:
        pass
    return None


def _alpaca_poll_telescope(ip: str, port: int = 32323) -> dict:
    """Poll Alpaca telescope for live state. Returns dict or empty."""
    result = {}
    try:
        # Quick reachability check via management API
        r = http_requests.get(
            f"http://{ip}:{port}/management/v1/description",
            timeout=ALPACA_TIMEOUT)
        if r.status_code != 200:
            return {}
        desc = r.json().get("Value", {})
        result["alpaca_version"] = desc.get("ManufacturerVersion", "unknown")

        # Device count
        r2 = http_requests.get(
            f"http://{ip}:{port}/management/v1/configureddevices",
            timeout=ALPACA_TIMEOUT)
        if r2.status_code == 200:
            devices = r2.json().get("Value", [])
            result["device_count"] = len(devices)

        # Telescope reads
        result["ra"]       = _alpaca_get(ip, port, "telescope", 0, "rightascension")
        result["dec"]      = _alpaca_get(ip, port, "telescope", 0, "declination")
        result["tracking"] = _alpaca_get(ip, port, "telescope", 0, "tracking")
        result["at_park"]  = _alpaca_get(ip, port, "telescope", 0, "atpark")
        result["altitude"] = _alpaca_get(ip, port, "telescope", 0, "altitude")
        result["azimuth"]  = _alpaca_get(ip, port, "telescope", 0, "azimuth")

        # Camera temp
        result["temp_c"]   = _alpaca_get(ip, port, "camera", 0, "ccdtemperature")

        result["link_status"] = "ACTIVE"
        return result

    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Hardware cache (fleet-aware)
# ---------------------------------------------------------------------------
HW_CACHE = {
    "timestamp": 0,
    "data": {
        "link_status":    "WAITING",
        "alpaca_version": "N/A",
        "device_count":   0,
        "battery":        "N/A",
        "temp_c":         "N/A",
        "storage_mb":     "N/A",
        "tracking":       False,
        "at_park":        False,
        "level_angle":    None,
        "level_ok":       True,
        "ra":             "N/A",
        "dec":            "N/A",
        "altitude":       "N/A",
        "azimuth":        "N/A",
    },
    "fleet": [],  # list of {name, ip, link_status, alpaca_version}
}
HW_CACHE_TTL = 5  # seconds


def refresh_hw_cache():
    """Refresh hardware cache from all sources."""
    now = time.time()
    if now - HW_CACHE["timestamp"] < HW_CACHE_TTL:
        return

    cfg = load_config("~/seevar/config.toml")
    seestars = cfg.get("seestars", [])

    # --- Fleet polling (Alpaca REST) ---
    fleet = []
    primary = None

    for entry in seestars:
        name = entry.get("name", "Unknown")
        ip   = entry.get("ip", "TBD")
        port = entry.get("alpaca_port", 32323)

        if ip == "TBD" or not ip:
            fleet.append({"name": name, "ip": ip, "link_status": "UNCONFIGURED",
                          "alpaca_version": "N/A"})
            continue

        state = _alpaca_poll_telescope(ip, port)
        if state:
            fleet.append({
                "name":            name,
                "ip":              ip,
                "link_status":     "ACTIVE",
                "alpaca_version":  state.get("alpaca_version", "?"),
                "device_count":    state.get("device_count", 0),
                "tracking":        state.get("tracking", False),
                "at_park":         state.get("at_park", False),
                "temp_c":          state.get("temp_c"),
            })
            if primary is None:
                primary = state
        else:
            fleet.append({"name": name, "ip": ip, "link_status": "OFFLINE",
                          "alpaca_version": "N/A"})

    HW_CACHE["fleet"] = fleet

    # --- Primary telescope data into main cache ---
    if primary:
        HW_CACHE["data"]["link_status"]    = "ACTIVE"
        HW_CACHE["data"]["alpaca_version"] = primary.get("alpaca_version", "N/A")
        HW_CACHE["data"]["device_count"]   = primary.get("device_count", 0)
        HW_CACHE["data"]["tracking"]       = primary.get("tracking", False)
        HW_CACHE["data"]["at_park"]        = primary.get("at_park", False)

        if primary.get("ra") is not None:
            HW_CACHE["data"]["ra"]  = primary["ra"]
            HW_CACHE["data"]["dec"] = primary["dec"]
        if primary.get("altitude") is not None:
            HW_CACHE["data"]["altitude"] = primary["altitude"]
            HW_CACHE["data"]["azimuth"]  = primary["azimuth"]
        if primary.get("temp_c") is not None:
            HW_CACHE["data"]["temp_c"] = str(round(primary["temp_c"], 1))

    # --- Source 1: GPS/network state ---
    if ENV_STATUS.exists():
        try:
            with open(ENV_STATUS, 'r') as f:
                env = json.load(f)
            for key in ("storage_mb",):
                if key in env:
                    HW_CACHE["data"][key] = env[key]
        except (json.JSONDecodeError, OSError):
            pass

    # --- Source 1b: storage_mb fallback ---
    if HW_CACHE["data"]["storage_mb"] in ("N/A", None):
        try:
            local_buffer = DATA_DIR / "local_buffer"
            if local_buffer.exists():
                total_bytes = sum(
                    f.stat().st_size for f in local_buffer.rglob("*") if f.is_file()
                )
                HW_CACHE["data"]["storage_mb"] = round(total_bytes / (1024 * 1024), 1)
            else:
                HW_CACHE["data"]["storage_mb"] = 0.0
        except OSError:
            pass

    # --- Source 2: TelemetryBlock from orchestrator ---
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
            tel = state.get("telemetry", {})
            batt = tel.get("battery_pct")
            if batt is not None:
                HW_CACHE["data"]["battery"] = str(batt)
        except (json.JSONDecodeError, OSError):
            pass

    # --- Source 3: WilhelminaMonitor (port 4700 event stream — battery/charger) ---
    if WILHELMINA_STATE.exists():
        try:
            with open(WILHELMINA_STATE, 'r') as f:
                w = json.load(f)

            batt = w.get("battery_pct")
            if batt is not None:
                HW_CACHE["data"]["battery"] = f"{batt}%"

            HW_CACHE["data"]["level_angle"] = w.get("level_angle")
            HW_CACHE["data"]["level_ok"]    = w.get("level_ok", True)

        except (json.JSONDecodeError, OSError):
            pass

    HW_CACHE["timestamp"] = now


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_config(file_path: str) -> dict:
    path = Path(os.path.expanduser(file_path))
    if path.exists():
        try:
            with open(path, "rb") as f:
                return tomllib.load(f)
        except (tomllib.TOMLDecodeError, OSError) as e:
            log.error("Config load failed: %s", e)
    return {}


def load_json_file(path, default=None):
    if not path.exists():
        return default if default is not None else {}
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default if default is not None else {}


def load_plan():
    data = load_json_file(PLAN_FILE, [])
    return data if isinstance(data, list) else data.get("targets", [])


FLIGHT_WINDOW_CACHE = {"date": None, "text": ""}


def get_dusk_utc(lat, lon, elev):
    try:
        loc = EarthLocation(lat=lat*u.deg, lon=lon*u.deg, height=elev*u.m)
        utc_now = datetime.now(timezone.utc)
        start_time = datetime(utc_now.year, utc_now.month, utc_now.day, 12, 0, tzinfo=timezone.utc)
        if utc_now.hour < 12:
            start_time -= timedelta(days=1)
        for m in range(0, 24*60, 5):
            t_dt = start_time + timedelta(minutes=m)
            t = Time(t_dt)
            frame = AltAz(obstime=t, location=loc)
            sun_alt = get_sun(t).transform_to(frame).alt.deg
            if sun_alt <= -18.0:
                return t_dt
    except Exception as e:
        log.error("get_dusk_utc failed: %s", e)
    return None


def get_flight_window(lat: float, lon: float, elev: float) -> str:
    today_str = datetime.now().strftime("%Y-%m-%d")
    if FLIGHT_WINDOW_CACHE["date"] == today_str:
        return FLIGHT_WINDOW_CACHE["text"]
    try:
        loc = EarthLocation(lat=lat*u.deg, lon=lon*u.deg, height=elev*u.m)
        utc_now = datetime.now(timezone.utc)
        start_time = datetime(utc_now.year, utc_now.month, utc_now.day, 12, 0, tzinfo=timezone.utc)
        if utc_now.hour < 12:
            start_time -= timedelta(days=1)
        dusk_str, dawn_str = None, None
        is_night = False
        for m in range(0, 24 * 60, 5):
            t_dt = start_time + timedelta(minutes=m)
            t = Time(t_dt)
            frame = AltAz(obstime=t, location=loc)
            sun_alt = get_sun(t).transform_to(frame).alt.deg
            if sun_alt <= -18.0 and not is_night:
                is_night = True
                dusk_str = t_dt.astimezone().strftime("%H:%M")
            elif sun_alt > -18.0 and is_night:
                is_night = False
                dawn_str = t_dt.astimezone().strftime("%H:%M")
                break
        if dusk_str and dawn_str:
            res = f"{dusk_str} - {dawn_str}"
        else:
            res = "NO ASTRONOMICAL NIGHT"
        FLIGHT_WINDOW_CACHE["date"] = today_str
        FLIGHT_WINDOW_CACHE["text"] = res
        return res
    except Exception as e:
        log.error("Flight window calc failed: %s", e)
        return "ERR - CHECK LOGS"


# ---------------------------------------------------------------------------
# Postflight session builder
# ---------------------------------------------------------------------------
def build_postflight(ledger: dict, dusk_dt) -> dict:
    entries = ledger.get("entries", {})
    plan_data  = load_json_file(PLAN_FILE, [])
    scheduled  = len(plan_data) if isinstance(plan_data, list) else len(plan_data.get("targets", []))
    attempted  = 0
    observed   = 0
    failed     = 0
    log_rows   = []

    STATUS_FAIL = {"FAILED_QC", "FAILED_QC_LOW_SNR", "FAILED_SATURATED", "FAILED_NO_WCS", "ERROR"}

    for name, e in entries.items():
        obs_str = e.get("last_obs_utc")
        if not obs_str:
            continue
        try:
            ts = datetime.fromisoformat(obs_str.rstrip("Z")).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if dusk_dt and ts < dusk_dt:
            continue

        attempted += 1
        status = e.get("status", "PENDING")

        if status == "OBSERVED":
            observed += 1
            row_class = "ok"
        elif status in STATUS_FAIL:
            failed += 1
            row_class = "fail" if "SNR" in status or status in ("FAILED_NO_WCS","ERROR") else "warn"
        else:
            row_class = "warn"

        zp_std = e.get("last_zp_std")
        if zp_std is None:
            zp_class = "z-bad"
        elif zp_std < 0.30:
            zp_class = "z-good"
        elif zp_std < 0.80:
            zp_class = "z-ok"
        else:
            zp_class = "z-bad"

        mag     = e.get("last_mag")
        err     = e.get("last_err")
        snr     = e.get("last_snr")
        zp      = e.get("last_zp")

        mag_str  = f"{mag:.3f} ±{err:.3f}" if mag is not None and err is not None else status.replace("FAILED_","")
        snr_str  = f"{snr:.0f}" if snr is not None else "—"
        zp_str   = f"{zp:.2f}±{zp_std:.2f}" if zp is not None and zp_std is not None else "—"
        time_str = ts.strftime("%H:%M")

        log_rows.append({
            "time": time_str, "name": name, "filter": e.get("last_filter", "—"),
            "mag_str": mag_str, "snr_str": snr_str, "zp_str": zp_str,
            "zp_class": zp_class, "row_class": row_class, "ts": ts.isoformat(),
        })

    log_rows.sort(key=lambda r: r["ts"], reverse=True)
    log_rows = log_rows[:5]
    for r in log_rows:
        del r["ts"]

    if failed > 0:
        overall = "orange"
    else:
        overall = "green" if observed > 0 else "grey"

    phot_led  = "green" if observed > 0 else ("orange" if attempted > 0 else "grey")
    aavso_led = "grey"

    return {
        "scoreboard": {"scheduled": scheduled, "attempted": attempted,
                       "observed": observed, "failed": failed},
        "overall": overall, "phot_led": phot_led, "aavso_led": aavso_led,
        "log": log_rows,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    target_data = load_plan()
    config = load_config("~/seevar/config.toml")
    loc    = config.get('location', {})
    fw_text = get_flight_window(
        loc.get('lat', 51.4769),
        loc.get('lon', 0.0),
        loc.get('elevation', 0.0)
    )
    return render_template('index.html', target_data=target_data, flight_window=fw_text)


@app.route('/telemetry')
def get_telemetry():
    config = load_config("~/seevar/config.toml")
    loc    = config.get('location', {})

    state = {
        "gps_status": "NO-GPS-LOCK",
        "lat":        loc.get('lat', 51.4769),
        "lon":        loc.get('lon', 0.0),
        "maidenhead": loc.get('maidenhead', "IO81qm"),
        "system_msg": "System Ready."
    }

    env = load_json_file(ENV_STATUS, {})
    if env:
        state.update(env)

    weather = {"status": "FETCHING", "icon": "❓"}
    weather_data = load_json_file(WEATHER_FILE, {})
    if weather_data:
        weather.update(weather_data)

    science = {"photometry": "grey", "aavso_ready": "grey", "siril_tail": []}
    if SIRIL_LOG.exists():
        try:
            with open(SIRIL_LOG, 'r') as f:
                science["siril_tail"] = [line.strip() for line in f.readlines()[-5:]]
        except OSError:
            pass

    orchestrator = {
        "state": "PARKED", "sub": "OFF-DUTY",
        "msg": "No state file found.", "flight_log": []
    }
    state_data = load_json_file(STATE_FILE, {})
    if state_data:
        orchestrator.update({
            "state":          state_data.get("state",          orchestrator["state"]),
            "sub":            state_data.get("sub",            orchestrator["sub"]),
            "msg":            state_data.get("msg",            orchestrator["msg"]),
            "flight_log":     state_data.get("flight_log",     orchestrator["flight_log"]),
            "current_target": state_data.get("current_target", None),
        })

    ledger     = load_json_file(LEDGER_FILE, {})
    last_audit = ledger.get("metadata", {}).get("last_updated", "N/A")

    dusk_dt    = get_dusk_utc(
        loc.get('lat', 51.4769), loc.get('lon', 0.0), loc.get('elevation', 0.0)
    )
    postflight = build_postflight(ledger, dusk_dt)

    refresh_hw_cache()

    return jsonify({
        "gps_status":   state.get("gps_status"),
        "lat":          state.get("lat"),
        "lon":          state.get("lon"),
        "maidenhead":   state.get("maidenhead"),
        "system_msg":   state.get("system_msg"),
        "weather":      weather,
        "science":      science,
        "orchestrator": orchestrator,
        "hardware":     HW_CACHE["data"],
        "fleet":        HW_CACHE["fleet"],
        "last_audit":   last_audit,
        "postflight":   postflight,
    })


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5050, debug=False)
