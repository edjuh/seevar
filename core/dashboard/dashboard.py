#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/dashboard/dashboard.py
Version: 4.4.9
Objective: Dynamic Astronomical Twilight (-18.0°) flight window calculations and KNVWS removal.
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

from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, get_sun
from astropy.time import Time

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR     = Path(__file__).resolve().parent
PROJECT_ROOT = Path("/home/ed/seevar")
DATA_DIR     = PROJECT_ROOT / "data"
PLAN_FILE    = DATA_DIR / "tonights_plan.json"
STATE_FILE   = DATA_DIR / "system_state.json"
LEDGER_FILE  = DATA_DIR / "ledger.json"
WEATHER_FILE = DATA_DIR / "weather_state.json"
SIRIL_LOG    = PROJECT_ROOT / "logs" / "siril_extraction.log"
ENV_STATUS   = Path("/dev/shm/env_status.json")

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
        return "JO22hj"

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
        "link_status": "OFFLINE",
        "battery":     "N/A",
        "storage_mb":  "N/A"
    }
}
HW_CACHE_TTL = 10 

def refresh_hw_cache():
    now = time.time()
    if now - HW_CACHE["timestamp"] < HW_CACHE_TTL:
        return 
    if ENV_STATUS.exists():
        try:
            with open(ENV_STATUS, 'r') as f:
                fresh = json.load(f)
            for key in ("link_status", "battery", "storage_mb"):
                if key in fresh:
                    HW_CACHE["data"][key] = fresh[key]
            HW_CACHE["timestamp"] = now
        except (json.JSONDecodeError, OSError) as e:
            log.warning("HW_CACHE refresh failed: %s", e)

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

def get_flight_window(lat: float, lon: float, elev: float) -> str:
    today_str = datetime.now().strftime("%Y-%m-%d")
    if FLIGHT_WINDOW_CACHE["date"] == today_str:
        return FLIGHT_WINDOW_CACHE["text"]
        
    try:
        loc = EarthLocation(lat=lat*u.deg, lon=lon*u.deg, height=elev*u.m)
        utc_now = datetime.now(timezone.utc)
        
        # Start scanning from Noon UTC today
        start_time = datetime(utc_now.year, utc_now.month, utc_now.day, 12, 0, tzinfo=timezone.utc)
        if utc_now.hour < 12:
            start_time -= timedelta(days=1)
            
        dusk_str, dawn_str = None, None
        is_night = False
        
        # 5-minute interval scan across 24 hours
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
# Routes
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    target_data = load_plan()
    config = load_config("~/seevar/config.toml")
    loc    = config.get('location', {})
    
    fw_text = get_flight_window(
        loc.get('lat', 52.3874), 
        loc.get('lon', 4.6462), 
        loc.get('elevation', 0.0)
    )
    
    return render_template('index.html', target_data=target_data, flight_window=fw_text)

@app.route('/telemetry')
def get_telemetry():
    config = load_config("~/seevar/config.toml")
    loc    = config.get('location', {})
    
    state = {
        "gps_status": "NO-GPS-LOCK",
        "lat":        loc.get('lat', 0),
        "lon":        loc.get('lon', 0),
        "maidenhead": loc.get('maidenhead', "N/A"),
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
            "state":      state_data.get("state",      orchestrator["state"]),
            "sub":        state_data.get("sub",        orchestrator["sub"]),
            "msg":        state_data.get("msg",        orchestrator["msg"]),
            "flight_log": state_data.get("flight_log", orchestrator["flight_log"])
        })
        
    last_audit = "N/A"
    ledger = load_json_file(LEDGER_FILE, {})
    if ledger:
        last_audit = ledger.get("last_audit", "N/A")
        
    refresh_hw_cache()
    
    return jsonify({
        "gps_status":  state.get("gps_status"),
        "lat":         state.get("lat"),
        "lon":         state.get("lon"),
        "maidenhead":  state.get("maidenhead"),
        "system_msg":  state.get("system_msg"),
        "weather":     weather,
        "science":     science,
        "orchestrator": orchestrator,
        "hardware":    HW_CACHE["data"],
        "last_audit":  last_audit,
    })

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5050, debug=False)
