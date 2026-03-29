#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/dashboard/dashboard.py
Version: 4.6.1
Objective: Wire wilhelmina_state.json (WilhelminaMonitor event stream)
           into hardware cache as Source 3. Dashboard now shows real
           link_status, battery, temp_c from port 4700 event stream.
           v4.6.1: Added Source 4 — Direct TCP polling for live RA/DEC mount coordinates.
"""
import json
import logging
import os
import sys
import time
import socket
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from flask import Flask, render_template, jsonify

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
# Hardware cache
# ---------------------------------------------------------------------------
HW_CACHE = {
    "timestamp": 0,
    "data": {
        "link_status": "WAITING",
        "battery":     "N/A",
        "temp_c":      "N/A",
        "storage_mb":  "N/A",
        "tracking":    False,
        "slewing":     False,
        "level_angle": None,
        "level_ok":    True,
        "ra":          "N/A",
        "dec":         "N/A"
    }
}
HW_CACHE_TTL = 10

def _poll_seestar_coords(ip: str):
    """Direct TCP JSON-RPC poll for live coordinates with a 500ms timeout."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        s.connect((ip, 4700))
        
        msg = {"jsonrpc": "2.0", "method": "scope_get_equ_coord", "id": 9999}
        s.sendall((json.dumps(msg) + "\r\n").encode("utf-8"))
        
        buf = b""
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            chunk = s.recv(4096)
            if not chunk: break
            buf += chunk
            while b"\r\n" in buf:
                line, buf = buf.split(b"\r\n", 1)
                if not line: continue
                try:
                    resp = json.loads(line.decode("utf-8"))
                    if resp.get("id") == 9999 and "result" in resp:
                        s.close()
                        return resp["result"].get("ra"), resp["result"].get("dec")
                except Exception: pass
        s.close()
    except Exception:
        pass
    return None, None

def refresh_hw_cache():
    """Refresh hardware cache from multiple sources."""
    now = time.time()
    if now - HW_CACHE["timestamp"] < HW_CACHE_TTL:
        # We can bypass TTL exclusively for the live coordinate poll to keep it fresh
        pass

    # Source 1: GPS/network state
    if ENV_STATUS.exists():
        try:
            with open(ENV_STATUS, 'r') as f:
                env = json.load(f)
            for key in ("link_status", "storage_mb"):
                if key in env:
                    HW_CACHE["data"][key] = env[key]
        except (json.JSONDecodeError, OSError) as e:
            log.warning("HW_CACHE env_status refresh failed: %s", e)

    # Source 1b: storage_mb fallback
    if HW_CACHE["data"]["storage_mb"] in ("N/A", None):
        try:
            local_buffer = DATA_DIR / "local_buffer"
            if local_buffer.exists():
                total_bytes = sum(
                    f.stat().st_size
                    for f in local_buffer.rglob("*")
                    if f.is_file()
                )
                HW_CACHE["data"]["storage_mb"] = round(total_bytes / (1024 * 1024), 1)
            else:
                HW_CACHE["data"]["storage_mb"] = 0.0
        except OSError:
            pass

    # Source 2: TelemetryBlock from orchestrator via system_state.json
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
            tel = state.get("telemetry", {})
            batt = tel.get("battery_pct")
            if batt is not None:
                HW_CACHE["data"]["battery"] = str(batt)
            temp = tel.get("temp_c")
            if temp is not None:
                HW_CACHE["data"]["temp_c"] = str(round(temp, 1))
            link = state.get("link_status")
            if link:
                HW_CACHE["data"]["link_status"] = link
                
            # Fallback for target coordinates if everything else fails
            ct = state.get("current_target")
            if ct:
                HW_CACHE["data"]["ra"] = ct.get("ra", HW_CACHE["data"]["ra"])
                HW_CACHE["data"]["dec"] = ct.get("dec", HW_CACHE["data"]["dec"])
                
        except (json.JSONDecodeError, OSError) as e:
            log.warning("HW_CACHE state refresh failed: %s", e)

    # Source 3: WilhelminaMonitor event stream
    if WILHELMINA_STATE.exists():
        try:
            with open(WILHELMINA_STATE, 'r') as f:
                w = json.load(f)

            link = w.get("link_status")
            if link:
                HW_CACHE["data"]["link_status"] = link

            batt = w.get("battery_pct")
            if batt is not None:
                HW_CACHE["data"]["battery"] = f"{batt}%"

            temp = w.get("temp_c")
            if temp is not None:
                HW_CACHE["data"]["temp_c"] = str(temp)

            HW_CACHE["data"]["tracking"]    = w.get("tracking", False)
            HW_CACHE["data"]["slewing"]     = w.get("slewing", False)
            HW_CACHE["data"]["level_angle"] = w.get("level_angle")
            HW_CACHE["data"]["level_ok"]    = w.get("level_ok", True)

        except (json.JSONDecodeError, OSError) as e:
            log.warning("HW_CACHE wilhelmina_state refresh failed: %s", e)

    # Source 4: Direct Live TCP Polling (Overrides state-file fallbacks if Seestar is reachable)
    cfg = load_config("~/seevar/config.toml")
    seestars = cfg.get("seestars", [{}])
    target_ip = seestars[0].get("ip", "192.168.178.251") if seestars else "192.168.178.251"
    
    live_ra, live_dec = _poll_seestar_coords(target_ip)
    if live_ra is not None and live_dec is not None:
        HW_CACHE["data"]["ra"] = live_ra
        HW_CACHE["data"]["dec"] = live_dec
        HW_CACHE["data"]["link_status"] = "ACTIVE" # If it responds, it's definitively active

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
            log.warning("load_config failed for %s: %s", file_path, e)
    return {}

def load_json_file(path: Path, default):
    if path.exists():
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("load_json_file failed for %s: %s", path, e)
    return default

def load_plan() -> list:
    data = load_json_file(PLAN_FILE, [])
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("targets", [])
    return []

# ---------------------------------------------------------------------------
# Astronomical Twilight Engine (-18.0°)
# ---------------------------------------------------------------------------
FLIGHT_WINDOW_CACHE = {"date": None, "text": "CALCULATING..."}
DUSK_CACHE = {"date": None, "dt": None}

def get_dusk_utc(lat: float, lon: float, elev: float):
    today_str = datetime.now().strftime("%Y-%m-%d")
    if DUSK_CACHE["date"] == today_str:
        return DUSK_CACHE["dt"]
    try:
        loc = EarthLocation(lat=lat*u.deg, lon=lon*u.deg, height=elev*u.m)
        utc_now = datetime.now(timezone.utc)
        start_time = datetime(utc_now.year, utc_now.month, utc_now.day, 12, 0, tzinfo=timezone.utc)
        if utc_now.hour < 12:
            start_time -= timedelta(days=1)
        is_night = False
        for m in range(0, 24 * 60, 5):
            t_dt = start_time + timedelta(minutes=m)
            t = Time(t_dt)
            frame = AltAz(obstime=t, location=loc)
            sun_alt = get_sun(t).transform_to(frame).alt.deg
            if sun_alt <= -18.0 and not is_night:
                is_night = True
                DUSK_CACHE["date"] = today_str
                DUSK_CACHE["dt"]   = t_dt
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
            "time":      time_str,
            "name":      name,
            "filter":    e.get("last_filter", "—"),
            "mag_str":   mag_str,
            "snr_str":   snr_str,
            "zp_str":    zp_str,
            "zp_class":  zp_class,
            "row_class": row_class,
            "ts":        ts.isoformat(),
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
        "scoreboard": {
            "scheduled": scheduled,
            "attempted": attempted,
            "observed":  observed,
            "failed":    failed,
        },
        "overall":   overall,
        "phot_led":  phot_led,
        "aavso_led": aavso_led,
        "log":       log_rows,
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
        except OSError as e:
            log.warning("SIRIL_LOG read failed: %s", e)

    orchestrator = {
        "state":      "PARKED",
        "sub":        "OFF-DUTY",
        "msg":        "No state file found.",
        "flight_log": []
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
        loc.get('lat', 51.4769),
        loc.get('lon', 0.0),
        loc.get('elevation', 0.0)
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
        "last_audit":   last_audit,
        "postflight":   postflight,
    })

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5050, debug=False)
