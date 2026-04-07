#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/dashboard/dashboard.py
Version: 5.0.1
Objective: Fleet-ready dashboard with Alpaca REST telemetry on port 32323 and nightly-plan funnel visibility.
"""
import json
import logging
import os
import sys
import time
import subprocess
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from flask import Flask, render_template, jsonify, Response
import flask.cli

import requests as http_requests
from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, get_sun
from astropy.time import Time
from astropy.io import fits
import numpy as np
from PIL import Image
import io

BASE_DIR          = Path(__file__).resolve().parent
PROJECT_ROOT      = Path(__file__).resolve().parents[2]
DATA_DIR          = PROJECT_ROOT / "data"
PLAN_FILE         = DATA_DIR / "tonights_plan.json"
SSC_FILE          = DATA_DIR / "ssc_payload.json"
STATE_FILE        = DATA_DIR / "system_state.json"
LEDGER_FILE       = DATA_DIR / "ledger.json"
WEATHER_FILE      = DATA_DIR / "weather_state.json"
SIRIL_LOG         = PROJECT_ROOT / "logs" / "siril_extraction.log"
ENV_STATUS        = Path("/dev/shm/env_status.json")
LOCAL_BUFFER      = DATA_DIR / "local_buffer"
VERIFY_BUFFER     = DATA_DIR / "verify_buffer"
ARCHIVE_DIR       = DATA_DIR / "archive"
PROCESS_DIR       = DATA_DIR / "process"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    force=True,
)
log = logging.getLogger("dashboard")
log.setLevel(logging.INFO)
logging.getLogger("werkzeug").setLevel(logging.WARNING)

sys.path.append(str(PROJECT_ROOT))
from core.hardware.live_scope_status import poll_scope_status
try:
    from core.utils.observer_math import get_maidenhead_6char
except ImportError:
    def get_maidenhead_6char(lat, lon):
        return "UNKNOWN"

TEMPLATE_DIR = BASE_DIR / "templates"
app = Flask(__name__, template_folder=str(TEMPLATE_DIR))
flask.cli.show_server_banner = lambda *args, **kwargs: None

@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

ALPACA_TIMEOUT = 2.0


HW_CACHE = {
    "timestamp": 0,
    "scope_failures": {},
    "last_good": {},
    "data": {
        "link_status": "WAITING",
        "alpaca_version": "N/A",
        "device_count": 0,
        "battery": "N/A",
        "temp_c": "N/A",
        "tracking": False,
        "at_park": False,
        "level_angle": None,
        "level_ok": True,
        "ra": "N/A",
        "dec": "N/A",
        "altitude": "N/A",
        "azimuth": "N/A",
    },
    "fleet": [],
}
HW_CACHE_TTL = 5
WEATHER_STALE_SEC = 1800
TELEMETRY_STALE_SEC = 300

DASHBOARD_EVENT_STATE = {
    "gps": None,
    "orchestrator": None,
    "weather": None,
    "hardware": None,
    "env_missing": None,
    "state_missing": None,
    "weather_missing": None,
}

def _set_event_flag(key: str, active: bool, message: str, *, level: int = logging.WARNING):
    previous = DASHBOARD_EVENT_STATE.get(key)
    if previous is active:
        return
    DASHBOARD_EVENT_STATE[key] = active
    if previous is None:
        if active:
            log.log(level, message)
        return
    if active:
        log.log(level, message)
    else:
        log.info("Recovered: %s", message)


def _log_dashboard_deltas(state: dict, orchestrator: dict, weather: dict, hardware: dict):
    gps_now = (
        state.get("gps_status"),
        state.get("maidenhead"),
        state.get("lat"),
        state.get("lon"),
    )
    if DASHBOARD_EVENT_STATE["gps"] != gps_now:
        log.info(
            "GPS -> status=%s maidenhead=%s lat=%s lon=%s",
            state.get("gps_status"),
            state.get("maidenhead"),
            state.get("lat"),
            state.get("lon"),
        )
        DASHBOARD_EVENT_STATE["gps"] = gps_now

    orch_now = (
        orchestrator.get("state"),
        orchestrator.get("sub"),
        orchestrator.get("msg"),
    )
    if DASHBOARD_EVENT_STATE["orchestrator"] != orch_now:
        log.info(
            "Orchestrator -> state=%s sub=%s msg=%s",
            orch_now[0],
            orch_now[1],
            orch_now[2],
        )
        DASHBOARD_EVENT_STATE["orchestrator"] = orch_now

    weather_now = (
        weather.get("status"),
        weather.get("stale"),
        weather.get("imaging_go"),
    )
    if DASHBOARD_EVENT_STATE["weather"] != weather_now:
        log.info(
            "Weather -> status=%s current=%s stale=%s imaging_go=%s age_s=%s",
            weather.get("status"),
            weather.get("current_status"),
            weather.get("stale"),
            weather.get("imaging_go"),
            round(weather.get("age_s"), 1) if weather.get("age_s") is not None else "n/a",
        )
        DASHBOARD_EVENT_STATE["weather"] = weather_now

    hardware_now = (
        hardware.get("link_status"),
        hardware.get("operational_state"),
        hardware.get("battery"),
    )
    if DASHBOARD_EVENT_STATE["hardware"] != hardware_now:
        log.info(
            "Hardware -> link=%s op=%s battery=%s temp=%s",
            hardware.get("link_status"),
            hardware.get("operational_state"),
            hardware.get("battery"),
            hardware.get("temp_c"),
        )
        DASHBOARD_EVENT_STATE["hardware"] = hardware_now


def _check_dashboard_sources(env: dict, state_data: dict, weather_data: dict):
    _set_event_flag(
        "env_missing",
        not bool(env),
        f"Live GPS RAM status unavailable: {ENV_STATUS} (using configured site fallback)",
        level=logging.INFO,
    )
    _set_event_flag(
        "state_missing",
        not bool(state_data),
        f"System state unavailable: {STATE_FILE}",
    )
    _set_event_flag(
        "weather_missing",
        not bool(weather_data),
        f"Weather state unavailable: {WEATHER_FILE}",
    )

def _payload_age_seconds(payload: dict) -> float | None:
    if not isinstance(payload, dict):
        return None

    ts = payload.get("last_update")
    if isinstance(ts, (int, float)):
        return max(0.0, time.time() - float(ts))

    for key in ("updated_utc", "updated", "timestamp"):
        value = payload.get(key)
        if not value:
            continue
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0.0, time.time() - dt.timestamp())
        except Exception:
            pass

    return None


def refresh_hw_cache():
    now = time.time()
    if now - HW_CACHE["timestamp"] < HW_CACHE_TTL:
        return

    HW_CACHE["data"] = {
        "link_status": "OFFLINE",
        "alpaca_version": "N/A",
        "device_count": 0,
        "battery": "N/A",
        "temp_c": "N/A",
        "tracking": False,
        "at_park": False,
        "level_angle": None,
        "level_ok": True,
        "ra": "N/A",
        "dec": "N/A",
        "altitude": "N/A",
        "azimuth": "N/A",
    }

    cfg = load_config("~/seevar/config.toml")
    seestars = cfg.get("seestars", [])

    fleet = []
    primary = None

    for entry in seestars:
        name = entry.get("name", "Unknown")
        ip   = entry.get("ip", "TBD")
        port = entry.get("alpaca_port", 32323)

        if ip == "TBD" or not ip:
            fleet.append({"name": name, "ip": ip, "link_status": "UNCONFIGURED", "alpaca_version": "N/A"})
            continue

        state = poll_scope_status(ip, port)
        previous_good = HW_CACHE["last_good"].get(name)
        failures = int(HW_CACHE["scope_failures"].get(name, 0))

        if state:
            HW_CACHE["scope_failures"][name] = 0
            HW_CACHE["last_good"][name] = dict(state)
            fleet.append({
                "name": name,
                "ip": ip,
                "link_status": state.get("link_status", "ONLINE"),
                "alpaca_version": state.get("alpaca_version", "?"),
                "device_count": state.get("device_count", 0),
                "tracking": state.get("tracking", False),
                "at_park": state.get("at_park", False),
                "temp_c": state.get("temp_c"),
                "slewing": state.get("slewing", False),
                "camera_state_name": state.get("camera_state_name", "UNKNOWN"),
                "operational_state": state.get("operational_state", "IDLE"),
            })
            if primary is None:
                primary = {**state, "ip": ip}
        else:
            failures += 1
            HW_CACHE["scope_failures"][name] = failures
            if previous_good and failures == 1:
                transient = dict(previous_good)
                transient["link_status"] = "WAITING"
                transient["operational_state"] = previous_good.get("operational_state", "IDLE")
                fleet.append({
                    "name": name,
                    "ip": ip,
                    "link_status": "WAITING",
                    "alpaca_version": transient.get("alpaca_version", "?"),
                    "device_count": transient.get("device_count", 0),
                    "tracking": transient.get("tracking", False),
                    "at_park": transient.get("at_park", False),
                    "temp_c": transient.get("temp_c"),
                    "slewing": transient.get("slewing", False),
                    "camera_state_name": transient.get("camera_state_name", "UNKNOWN"),
                    "operational_state": transient.get("operational_state", "IDLE"),
                })
                if primary is None:
                    primary = {**transient, "ip": ip}
            else:
                fleet.append({"name": name, "ip": ip, "link_status": "OFFLINE", "alpaca_version": "N/A", "operational_state": "OFFLINE"})

    HW_CACHE["fleet"] = fleet

    if primary:
        HW_CACHE["data"]["link_status"] = primary.get("link_status", "ONLINE")
        HW_CACHE["data"]["alpaca_version"] = primary.get("alpaca_version", "N/A")
        HW_CACHE["data"]["device_count"] = primary.get("device_count", 0)
        HW_CACHE["data"]["tracking"] = primary.get("tracking", False)
        HW_CACHE["data"]["slewing"] = primary.get("slewing", False)
        HW_CACHE["data"]["camera_state_name"] = primary.get("camera_state_name", "UNKNOWN")
        HW_CACHE["data"]["operational_state"] = primary.get("operational_state", "IDLE")
        HW_CACHE["data"]["at_park"] = primary.get("at_park", False)

        if primary.get("ra") is not None:
            HW_CACHE["data"]["ra"] = primary["ra"]
            HW_CACHE["data"]["dec"] = primary["dec"]
        if primary.get("altitude") is not None:
            HW_CACHE["data"]["altitude"] = primary["altitude"]
            HW_CACHE["data"]["azimuth"] = primary["azimuth"]
        if primary.get("temp_c") is not None:
            HW_CACHE["data"]["temp_c"] = str(round(primary["temp_c"], 1))
    if primary and primary.get("battery_pct") is not None:
        HW_CACHE["data"]["battery"] = str(primary.get("battery_pct"))
    if primary and primary.get("charge_online") is not None:
        HW_CACHE["data"]["charge_online"] = bool(primary.get("charge_online"))
    if primary and primary.get("charger_status"):
        HW_CACHE["data"]["charger_status"] = str(primary.get("charger_status"))
    if primary and primary.get("battery_updated_utc"):
        HW_CACHE["data"]["battery_updated_utc"] = primary.get("battery_updated_utc")

    HW_CACHE["timestamp"] = now

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
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default if default is not None else {}

def _primary_scope_ip() -> str | None:
    cfg = load_config("~/seevar/config.toml")
    seestars = cfg.get("seestars", [])
    if not seestars:
        return None
    ip = seestars[0].get("ip")
    return ip if ip and ip != "TBD" else None


def _rtsp_snapshot_jpeg(kind: str) -> bytes | None:
    ip = _primary_scope_ip()
    stream_port = {"tele": 4554, "wide": 4555}.get(kind)
    if not ip or stream_port is None:
        return None
    url = f"rtsp://{ip}:{stream_port}/stream"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-rtsp_transport", "tcp",
        "-i", url,
        "-frames:v", "1",
        "-f", "image2pipe",
        "-vcodec", "mjpeg",
        "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=8, check=True)
        return result.stdout or None
    except Exception as e:
        log.info("RTSP snapshot unavailable for %s: %s", kind, e)
        return None


def _latest_preview_file(kind: str) -> Path | None:
    groups = {
        "science": [LOCAL_BUFFER, PROCESS_DIR, ARCHIVE_DIR],
        "verify": [VERIFY_BUFFER, LOCAL_BUFFER, ARCHIVE_DIR],
    }
    candidates = []
    for directory in groups.get(kind, []):
        if not directory.exists():
            continue
        candidates.extend(directory.glob("*.fits"))
        candidates.extend(directory.glob("*.fit"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _render_preview_jpeg(fits_path: Path) -> bytes:
    data = fits.getdata(fits_path, 0).astype(np.float32)
    if data.ndim != 2:
        raise ValueError("preview expects 2D FITS")

    if min(data.shape) >= 2:
        data = data[::2, ::2]

    finite = data[np.isfinite(data)]
    if finite.size == 0:
        raise ValueError("preview image has no finite pixels")

    lo, hi = np.percentile(finite, [1.0, 99.5])
    if hi <= lo:
        hi = lo + 1.0
    scaled = np.clip((data - lo) / (hi - lo), 0.0, 1.0)
    image = (scaled * 255.0).astype(np.uint8)
    rgb = np.dstack([image, image, image])

    out = io.BytesIO()
    Image.fromarray(rgb, mode="RGB").save(out, format="JPEG", quality=82)
    return out.getvalue()


def load_plan():
    data = load_json_file(PLAN_FILE, [])
    return data if isinstance(data, list) else data.get("targets", [])

def build_target_funnel():
    catalog = load_json_file(PROJECT_ROOT / "catalogs" / "federation_catalog.json", {})
    plan = load_json_file(PLAN_FILE, {})
    ssc = load_json_file(SSC_FILE, {})

    catalog_count = len(catalog.get("data", [])) if isinstance(catalog, dict) else 0
    plan_count = len(plan.get("targets", [])) if isinstance(plan, dict) else 0
    plan_meta = plan.get("metadata", {}) if isinstance(plan, dict) else {}

    visible_count = int(plan_meta.get("visible_target_count", plan_count))
    due_count = int(plan_meta.get("planned_target_count", plan_count))

    compiled_count = 0
    if isinstance(ssc, dict):
        compiled_count = sum(1 for item in ssc.get("list", []) if item.get("action") == "start_mosaic")

    return {
        "catalog_count": catalog_count,
        "visible_count": visible_count,
        "due_count": due_count,
        "compiled_count": compiled_count,
    }

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

def _parse_utcish(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def build_nightly_progress(plan_targets: list, ledger: dict, dusk_dt, now_utc: datetime) -> dict:
    entries = ledger.get("entries", {}) if isinstance(ledger, dict) else {}

    done_names = set()
    for name, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("status") != "OBSERVED":
            continue
        obs_dt = _parse_utcish(entry.get("last_obs_utc") or entry.get("last_success"))
        if obs_dt is None:
            continue
        if dusk_dt and obs_dt < dusk_dt:
            continue
        done_names.add(name)

    done = 0
    remaining = 0
    expired = 0
    next_name = "—"
    next_reason = "No active target window."

    for target in plan_targets:
        name = target.get("name", "UNKNOWN")

        if name in done_names:
            done += 1
            continue

        start_dt = _parse_utcish(target.get("best_start_utc"))
        end_dt = _parse_utcish(target.get("best_end_utc"))

        if end_dt and end_dt <= now_utc:
            expired += 1
            continue

        remaining += 1

        if next_name == "—":
            next_name = name
            if start_dt and now_utc < start_dt:
                next_reason = f"Waiting for {name} window at {start_dt.strftime('%H:%M UTC')}"
            else:
                next_reason = f"Next eligible target: {name}"

    planned = len(plan_targets)

    return {
        "planned": planned,
        "done": done,
        "remaining": remaining,
        "expired": expired,
        "next_name": next_name,
        "next_reason": next_reason,
    }


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

def build_postflight(ledger: dict, dusk_dt) -> dict:
    entries = ledger.get("entries", {})
    plan_data = load_json_file(PLAN_FILE, [])
    scheduled = len(plan_data) if isinstance(plan_data, list) else len(plan_data.get("targets", []))
    attempted = 0
    observed = 0
    failed = 0
    log_rows = []

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
            row_class = "fail" if "SNR" in status or status in ("FAILED_NO_WCS", "ERROR") else "warn"
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

        mag = e.get("last_mag")
        err = e.get("last_err")
        snr = e.get("last_snr")
        zp = e.get("last_zp")

        mag_str = f"{mag:.3f} ±{err:.3f}" if mag is not None and err is not None else status.replace("FAILED_","")
        snr_str = f"{snr:.0f}" if snr is not None else "—"
        zp_str = f"{zp:.2f}±{zp_std:.2f}" if zp is not None and zp_std is not None else "—"
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

    phot_led = "green" if observed > 0 else ("orange" if attempted > 0 else "grey")
    aavso_led = "grey"

    return {
        "scoreboard": {"scheduled": scheduled, "attempted": attempted, "observed": observed, "failed": failed},
        "overall": overall, "phot_led": phot_led, "aavso_led": aavso_led,
        "log": log_rows,
    }

@app.route('/preview/<kind>.jpg')
def preview_image(kind: str):
    if kind in {'tele', 'wide'}:
        jpeg = _rtsp_snapshot_jpeg(kind)
        if jpeg:
            return Response(jpeg, mimetype='image/jpeg')

    fits_path = _latest_preview_file(kind)
    if fits_path is None:
        return Response(status=404)
    try:
        jpeg = _render_preview_jpeg(fits_path)
        resp = Response(jpeg, mimetype='image/jpeg')
        resp.headers['X-Preview-File'] = fits_path.name
        return resp
    except Exception as e:
        log.warning('Preview render failed for %s: %s', fits_path.name, e)
        return Response(status=500)

@app.route('/')
def index():
    target_data = load_plan()
    config = load_config("~/seevar/config.toml")
    loc = config.get('location', {})
    fw_text = get_flight_window(
        loc.get('lat', 51.4769),
        loc.get('lon', 0.0),
        loc.get('elevation', 0.0)
    )
    return render_template('index.html', target_data=target_data, flight_window=fw_text)

@app.route('/telemetry')
def get_telemetry():
    config = load_config("~/seevar/config.toml")
    loc = config.get('location', {})

    state = {
        "gps_status": "NO-GPS-LOCK",
        "lat": loc.get('lat', 51.4769),
        "lon": loc.get('lon', 0.0),
        "maidenhead": loc.get('maidenhead', "IO81qm"),
        "system_msg": "System Ready."
    }

    env = load_json_file(ENV_STATUS, {})
    if env:
        state.update(env)

    weather = {"status": "FETCHING", "icon": "❓", "stale": False, "age_s": None}
    weather_data = load_json_file(WEATHER_FILE, {})
    if weather_data:
        weather.update(weather_data)
        age_s = _payload_age_seconds(weather_data)
        weather["age_s"] = age_s
        weather["stale"] = age_s is None or age_s > WEATHER_STALE_SEC
        if weather["stale"]:
            weather["imaging_go"] = None

    science = {"photometry": "grey", "aavso_ready": "grey", "siril_tail": []}
    if SIRIL_LOG.exists():
        try:
            with open(SIRIL_LOG, 'r') as f:
                science["siril_tail"] = [line.strip() for line in f.readlines()[-5:]]
        except OSError:
            pass

    orchestrator = {
        "state": "PARKED",
        "sub": "OFF-DUTY",
        "msg": "No state file found.",
        "flight_log": [],
        "done_count": 0,
        "remaining_count": 0,
        "planned_count": 0,
    }
    state_data = load_json_file(STATE_FILE, {})
    if state_data:
        orchestrator.update({
            "state": state_data.get("state", orchestrator["state"]),
            "sub": state_data.get("sub", state_data.get("substate", orchestrator["sub"])),
            "msg": state_data.get("msg", state_data.get("message", orchestrator["msg"])),
            "flight_log": state_data.get("flight_log", orchestrator["flight_log"]),
            "current_target": state_data.get("current_target", None),
            "done_count": state_data.get("done_count", 0),
            "remaining_count": state_data.get("remaining_count", 0),
            "planned_count": state_data.get("planned_count", 0),
        })

    ledger = load_json_file(LEDGER_FILE, {})
    _check_dashboard_sources(env, state_data, weather_data)
    last_audit = ledger.get("metadata", {}).get("last_updated", "N/A")

    dusk_dt = get_dusk_utc(
        loc.get('lat', 51.4769), loc.get('lon', 0.0), loc.get('elevation', 0.0)
    )
    postflight = build_postflight(ledger, dusk_dt)

    plan_targets = load_plan()
    nightly_progress = build_nightly_progress(plan_targets, ledger, dusk_dt, datetime.now(timezone.utc))

    orchestrator["done_count"] = nightly_progress["done"]
    orchestrator["remaining_count"] = nightly_progress["remaining"]
    orchestrator["planned_count"] = nightly_progress["planned"]
    orchestrator["expired_count"] = nightly_progress["expired"]
    orchestrator["next_target_name"] = nightly_progress["next_name"]
    orchestrator["next_reason"] = nightly_progress["next_reason"]

    refresh_hw_cache()
    _log_dashboard_deltas(state, orchestrator, weather, HW_CACHE["data"])

    return jsonify({
        "gps_status": state.get("gps_status"),
        "lat": state.get("lat"),
        "lon": state.get("lon"),
        "maidenhead": state.get("maidenhead"),
        "system_msg": state.get("system_msg"),
        "weather": weather,
        "science": science,
        "orchestrator": orchestrator,
        "hardware": HW_CACHE["data"],
        "fleet": HW_CACHE["fleet"],
        "last_audit": last_audit,
        "target_funnel": build_target_funnel(),
        "postflight": postflight,
    })

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5050, debug=False)
