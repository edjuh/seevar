#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/orchestrator.py
Version: 1.4.0 (Diamond Revision)
Objective: Full pipeline state machine controlling the data lifecycle.
           Realigned to use unified env_loader for paths and config fallbacks.
           Patched weather logic to prevent 'Flying in the Rain' bug.
"""

import json
import logging
import math
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body
from astropy.time import Time

# ---------------------------------------------------------------------------
# Project Imports - Unified Environment Loading
# ---------------------------------------------------------------------------
import sys
PROJECT_ROOT = Path("/home/ed/seevar")
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.env_loader import (
    DATA_DIR, ENV_STATUS, load_config
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "orchestrator.log", mode="a"),
    ],
)
log = logging.getLogger("Orchestrator")

# ---------------------------------------------------------------------------
# Local Paths
# ---------------------------------------------------------------------------
PLAN_FILE    = DATA_DIR / "tonights_plan.json"
STATE_FILE   = DATA_DIR / "system_state.json"
LEDGER_FILE  = DATA_DIR / "ledger.json"
WEATHER_FILE = DATA_DIR / "weather_state.json"
MISSION_FILE = DATA_DIR / "mission_targets.json"

# ---------------------------------------------------------------------------
# Alpaca bridge
# ---------------------------------------------------------------------------
ALPACA_HOST      = "127.0.0.1"
ALPACA_PORT      = 5432
ALPACA_BASE      = f"http://{ALPACA_HOST}:{ALPACA_PORT}"
ALPACA_CLIENT_ID = 42
_alpaca_txn_id   = 0

def _next_txn() -> int:
    global _alpaca_txn_id
    _alpaca_txn_id += 1
    return _alpaca_txn_id

# ---------------------------------------------------------------------------
# Aperture Grip priority scoring
# ---------------------------------------------------------------------------
def aperture_grip_score(azimuth: float, altitude: float) -> float:
    if 180 <= azimuth <= 350:
        return 100.0 - altitude
    return altitude / 2.0

# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------
class PipelineState:
    IDLE       = "IDLE"
    PREFLIGHT  = "PREFLIGHT"
    PLANNING   = "PLANNING"
    FLIGHT     = "FLIGHT"
    POSTFLIGHT = "POSTFLIGHT"
    ABORTED    = "ABORTED"
    PARKED     = "PARKED"


class Orchestrator:
    SUN_LIMIT_DEG    = -18.0
    ALT_FLOOR_DEG    = 30.0
    PANEL_TIME_SEC   = 60
    ALPACA_TIMEOUT   = 15
    LOOP_SLEEP_SEC   = 30

    def __init__(self):
        try:
            from core.flight.vault_manager import VaultManager
            self._vault = VaultManager()
            self._obs   = self._vault.get_observer_config()
        except ImportError:
            log.warning("VaultManager not found — falling back to env_loader config")
            cfg = load_config()
            loc = cfg.get("location", {})
            aavso = cfg.get("aavso", {})
            self._obs = {
                "observer_id":       aavso.get("observer_code", "MISSING_ID"),
                "maidenhead":        loc.get("maidenhead", "AUTO"),
                "lat":               loc.get("lat", 0.0),
                "lon":               loc.get("lon", 0.0),
                "elevation":         loc.get("elevation", 0.0),
                "sun_altitude_limit": self.SUN_LIMIT_DEG,
            }

        self._location = EarthLocation(
            lat=self._obs["lat"] * u.deg,
            lon=self._obs["lon"] * u.deg,
            height=self._obs.get("elevation", 5.0) * u.m,
        )

        self._state      = PipelineState.IDLE
        self._targets    = []
        self._flight_log = []
        self._session_stats = {
            "targets_attempted": 0,
            "targets_completed": 0,
            "exposures_total":   0,
            "start_utc":         None,
            "end_utc":           None,
        }

    def run(self):
        log.info("🔭 Orchestrator starting — Sovereign SeeVar Federation v1.4.0")
        self._write_state(sub="Daemon starting", msg="Federation online.")

        while True:
            try:
                self._tick()
            except KeyboardInterrupt:
                log.info("KeyboardInterrupt received — parking and exiting.")
                self._park_telescope()
                break
            except Exception as e:
                log.exception("Unhandled exception in main loop: %s", e)
                self._transition(PipelineState.ABORTED, msg=f"Unhandled exception: {e}")
                time.sleep(self.LOOP_SLEEP_SEC * 4)

    def _tick(self):
        if self._state == PipelineState.IDLE: self._run_idle()
        elif self._state == PipelineState.PREFLIGHT: self._run_preflight()
        elif self._state == PipelineState.PLANNING: self._run_planning()
        elif self._state == PipelineState.FLIGHT: self._run_flight()
        elif self._state == PipelineState.POSTFLIGHT: self._run_postflight()
        elif self._state == PipelineState.PARKED: self._run_parked()
        elif self._state == PipelineState.ABORTED: self._run_aborted()

    def _run_idle(self):
        sun_alt = self._sun_altitude()
        msg = f"Sun at {sun_alt:.1f}°. Waiting for astronomical night (<{self.SUN_LIMIT_DEG}°)."
        self._write_state(sub="Standing by", msg=msg)
        
        if sun_alt < self.SUN_LIMIT_DEG:
            self._transition(PipelineState.PREFLIGHT, msg="Astronomical night confirmed. Initiating preflight.")
        else:
            time.sleep(self.LOOP_SLEEP_SEC)

    def _run_preflight(self):
        self._log_flight("🛫 PREFLIGHT sequence initiated.")
        checks_passed = True

        sun_alt = self._sun_altitude()
        if sun_alt >= self.SUN_LIMIT_DEG:
            self._log_flight(f"⚠️  Sun too high ({sun_alt:.1f}°) — aborting preflight.")
            self._transition(PipelineState.IDLE, msg="Sun rose during preflight.")
            return

        self._log_flight(f"✅ Sun altitude: {sun_alt:.1f}° — GO.")

        if not self._alpaca_ping():
            self._log_flight("❌ Alpaca bridge (5432) not responding.")
            checks_passed = False
        else:
            self._log_flight("✅ Alpaca bridge: RESPONDING.")

        if checks_passed and not self._telescope_connected():
            self._log_flight("❌ Telescope reports DISCONNECTED via Alpaca.")
            checks_passed = False
        else:
            self._log_flight("✅ Telescope: CONNECTED.")

        weather_ok, weather_msg = self._check_weather()
        if not weather_ok:
            self._log_flight(f"❌ Weather abort: {weather_msg}")
            checks_passed = False
        else:
            self._log_flight(f"✅ Weather: {weather_msg}")

        gps_status = self._check_gps()
        self._log_flight(f"📡 GPS: {gps_status}")

        if not checks_passed:
            self._transition(PipelineState.ABORTED, msg="Preflight failed. See flight log.")
            return

        self._log_flight("✅ All preflight checks passed — GO FOR PLANNING.")
        self._transition(PipelineState.PLANNING, msg="Preflight complete. Building tonight's plan.")

    def _run_planning(self):
        self._log_flight("📋 Loading mission targets...")
        mission = self._load_mission_targets()
        if not mission:
            self._log_flight("❌ No mission targets found. Check mission_targets.json.")
            self._transition(PipelineState.ABORTED, msg="No mission targets available.")
            return

        now     = Time.now()
        frame   = AltAz(obstime=now, location=self._location)
        scored  = []

        for target in mission:
            try:
                ra_str  = target.get("ra")
                dec_str = target.get("dec")
                if not ra_str or not dec_str: continue

                coord = SkyCoord(ra=ra_str, dec=dec_str, unit=(u.hourangle, u.deg))
                altaz    = coord.transform_to(frame)
                alt_deg  = float(altaz.alt.deg)
                az_deg   = float(altaz.az.deg)

                if alt_deg < self.ALT_FLOOR_DEG: continue

                score = aperture_grip_score(az_deg, alt_deg)
                target["_alt"]   = round(alt_deg, 2)
                target["_az"]    = round(az_deg, 2)
                target["_score"] = round(score, 2)
                scored.append(target)
            except Exception as e:
                log.warning("Could not score target %s: %s", target.get("name", "UNKNOWN"), e)

        if not scored:
            self._log_flight("❌ No targets above altitude floor tonight.")
            self._transition(PipelineState.ABORTED, msg="No observable targets.")
            return

        scored.sort(key=lambda t: t["_score"], reverse=True)
        self._targets = scored
        self._write_plan(scored)

        self._log_flight(f"✅ Plan built: {len(scored)} targets. Lead: {scored[0].get('name')}")
        self._transition(PipelineState.FLIGHT, sub=scored[0].get("name", "UNKNOWN"), msg="Flight plan locked. Commencing.")

    def _run_flight(self):
        if not self._targets:
            self._transition(PipelineState.POSTFLIGHT, msg="Target list exhausted.")
            return

        sun_alt = self._sun_altitude()
        if sun_alt >= self.SUN_LIMIT_DEG:
            self._log_flight(f"🌅 Dawn abort — sun at {sun_alt:.1f}°.")
            self._transition(PipelineState.POSTFLIGHT, msg="Dawn abort triggered.")
            return

        weather_ok, weather_msg = self._check_weather()
        if not weather_ok:
            self._log_flight(f"🌧️  Mid-flight weather abort: {weather_msg}")
            self._transition(PipelineState.POSTFLIGHT, msg=f"Weather abort: {weather_msg}")
            return

        now   = Time.now()
        frame = AltAz(obstime=now, location=self._location)
        still_valid = []

        for target in self._targets:
            try:
                coord  = SkyCoord(ra=target["ra"], dec=target["dec"], unit=(u.hourangle, u.deg))
                altaz  = coord.transform_to(frame)
                alt    = float(altaz.alt.deg)
                az     = float(altaz.az.deg)
                if alt < self.ALT_FLOOR_DEG: continue
                
                target["_alt"]   = round(alt, 2)
                target["_az"]    = round(az, 2)
                target["_score"] = round(aperture_grip_score(az, alt), 2)
                still_valid.append(target)
            except Exception: pass

        if not still_valid:
            self._log_flight("⬇️  All targets below floor. Moving to postflight.")
            self._transition(PipelineState.POSTFLIGHT, msg="All targets set below altitude floor.")
            return

        still_valid.sort(key=lambda t: t["_score"], reverse=True)
        self._targets = still_valid
        target = still_valid[0]

        name    = target.get("name") or target.get("display_name", "UNKNOWN")
        ra_str  = target.get("ra")
        dec_str = target.get("dec")

        self._session_stats["targets_attempted"] += 1
        self._log_flight(f"🎯 Slewing → {name} | Alt:{target['_alt']}° Az:{target['_az']}° Score:{target['_score']}")
        self._write_state(state="SLEWING", sub=name, msg=f"Slewing to {name} | RA {ra_str} DEC {dec_str}")

        success = self._send_alpaca_schedule(name, ra_str, dec_str, self.PANEL_TIME_SEC)
        if not success:
            self._log_flight(f"❌ Alpaca schedule rejected for {name} — skipping.")
            self._targets.remove(target)
            return

        self._write_state(state="EXPOSING", sub=name, msg=f"Exposing {name} | {self.PANEL_TIME_SEC}s panel")
        self._log_flight(f"📷 Exposing {name} for {self.PANEL_TIME_SEC}s.")

        time.sleep(self.PANEL_TIME_SEC + 5)

        self._session_stats["targets_completed"] += 1
        self._session_stats["exposures_total"]   += 1
        self._log_flight(f"✅ {name} complete.")

        self._targets.remove(target)
        self._targets.append(target)
        self._write_state(state="TRACKING", sub=name, msg=f"Observation complete. {len(self._targets)} targets remaining.")

    def _run_postflight(self):
        self._log_flight("📊 Postflight audit initiated.")
        self._session_stats["end_utc"] = datetime.now(timezone.utc).isoformat()

        audit = {
            "last_audit":          datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "session_start":       self._session_stats.get("start_utc"),
            "session_end":         self._session_stats.get("end_utc"),
            "targets_attempted":   self._session_stats["targets_attempted"],
            "targets_completed":   self._session_stats["targets_completed"],
            "exposures_total":     self._session_stats["exposures_total"],
            "observer_id":         self._obs.get("observer_id", "MISSING_ID"),
            "aavso_ready":         self._session_stats["targets_completed"] > 0,
            "flight_log_snapshot": list(self._flight_log),
        }

        try:
            LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(LEDGER_FILE, 'w') as f:
                json.dump(audit, f, indent=2)
            self._log_flight(f"✅ Ledger written — {audit['targets_completed']} targets completed.")
        except OSError as e:
            log.error("Ledger write failed: %s", e)

        self._log_flight("🔭 Parking telescope.")
        self._park_telescope()
        self._transition(PipelineState.PARKED, msg="Postflight complete. Telescope parked.")

    def _run_parked(self):
        sun_alt = self._sun_altitude()
        self._write_state(sub="Parked", msg=f"Parked. Sun at {sun_alt:.1f}°. Waiting for next night.")
        if sun_alt > 5.0:
            self._reset_session()
            self._transition(PipelineState.IDLE, msg="Reset complete. Waiting for next night.")
        else:
            time.sleep(self.LOOP_SLEEP_SEC * 2)

    def _run_aborted(self):
        sun_alt = self._sun_altitude()
        self._write_state(sub="ABORTED", msg=f"Holding. Sun at {sun_alt:.1f}°.")
        if sun_alt > 5.0:
            self._reset_session()
            self._transition(PipelineState.IDLE, msg="Abort cleared. Ready for next night.")
        else:
            time.sleep(self.LOOP_SLEEP_SEC * 2)

    def _alpaca_get(self, path: str) -> Optional[dict]:
        url = f"{ALPACA_BASE}{path}"
        params = {"ClientID": ALPACA_CLIENT_ID, "ClientTransactionID": _next_txn()}
        try:
            r = requests.get(url, params=params, timeout=self.ALPACA_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("Alpaca GET error %s: %s", path, e)
        return None

    def _alpaca_put(self, path: str, payload: dict) -> Optional[dict]:
        url = f"{ALPACA_BASE}{path}"
        payload["ClientID"] = ALPACA_CLIENT_ID
        payload["ClientTransactionID"] = _next_txn()
        try:
            r = requests.put(url, json=payload, timeout=self.ALPACA_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("Alpaca PUT error %s: %s", path, e)
        return None

    def _alpaca_ping(self) -> bool:
        return self._alpaca_get("/management/apiversions") is not None

    def _telescope_connected(self) -> bool:
        result = self._alpaca_get("/api/v1/telescope/0/connected")
        if result: return bool(result.get("Value", False))
        return False

    def _send_alpaca_schedule(self, target_name: str, ra_str: str, dec_str: str, panel_time: int) -> bool:
        payload = {
            "schedule_item_id": str(uuid.uuid4()),
            "target_name":      target_name,
            "ra":               ra_str,
            "dec":              dec_str,
            "is_j2000":         True,
            "panel_time_sec":   panel_time,
        }
        try:
            r = requests.post(f"{ALPACA_BASE}/0/schedule", json=payload, timeout=self.ALPACA_TIMEOUT)
            if r.status_code in (200, 201): return True
            log.warning("Schedule POST returned %s: %s", r.status_code, r.text[:200])
        except Exception as e:
            log.error("Schedule POST failed for %s: %s", target_name, e)
        return False

    def _park_telescope(self):
        result = self._alpaca_put("/api/v1/telescope/0/park", {})
        if result: log.info("Telescope parked via Alpaca.")
        else: log.warning("Park command failed or timed out.")

    def _sun_altitude(self) -> float:
        try:
            now   = Time.now()
            frame = AltAz(obstime=now, location=self._location)
            sun   = get_body("sun", now)
            return float(sun.transform_to(frame).alt.deg)
        except Exception as e:
            log.error("Sun altitude calculation failed: %s", e)
            return 0.0

    def _check_weather(self) -> tuple[bool, str]:
        data = _safe_load_json(WEATHER_FILE, {})
        if not data: return True, "No weather data — proceeding optimistically."

        status = data.get("status", "UNKNOWN").upper()
        
        # FIX: Explicit abort for known bad statuses regardless of percentages
        bad_weather = ["RAIN", "STORM", "SNOW", "OVERCAST", "CLOUDY", "WINDY"]
        if status in bad_weather:
            return False, f"Weather status is {status} — observation aborted."

        clouds = data.get("clouds_pct", 0)
        if clouds > 70: return False, f"Cloud cover {clouds}% — observation aborted."

        humidity = data.get("humidity_pct", 0)
        if humidity > 90: return False, f"Humidity {humidity}% — dew risk too high."

        return True, status

    def _check_gps(self) -> str:
        data = _safe_load_json(ENV_STATUS, {})
        return data.get("gps_status", "NO-DATA")

    def _load_mission_targets(self) -> list:
        data = _safe_load_json(MISSION_FILE, [])
        if isinstance(data, list): return data
        if isinstance(data, dict): return data.get("targets", [])
        return []

    def _transition(self, new_state: str, sub: str = "", msg: str = ""):
        log.info("STATE: %s → %s", self._state, new_state)
        self._state = new_state
        self._write_state(state=new_state, sub=sub, msg=msg)

    def _write_state(self, state: str = None, sub: str = "", msg: str = "", **kwargs):
        payload = {
            "state":      state or self._state,
            "sub":        sub,
            "msg":        msg,
            "flight_log": list(self._flight_log[-20:]),
            "timestamp":  datetime.now(timezone.utc).isoformat(),
            **kwargs,
        }
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(STATE_FILE, 'w') as f:
                json.dump(payload, f, indent=2)
        except OSError as e:
            log.error("system_state.json write failed: %s", e)

    def _write_plan(self, targets: list):
        try:
            PLAN_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(PLAN_FILE, 'w') as f:
                json.dump(targets, f, indent=2, default=str)
        except OSError as e:
            log.error("Plan write failed: %s", e)

    def _log_flight(self, line: str):
        ts  = datetime.now(timezone.utc).strftime("%H:%M:%S")
        entry = f"[{ts}] {line}"
        log.info(line)
        self._flight_log.append(entry)
        if len(self._flight_log) > 20: self._flight_log.pop(0)
        self._write_state(msg=line)

    def _reset_session(self):
        self._targets    = []
        self._flight_log = []
        self._session_stats = {
            "targets_attempted": 0, "targets_completed": 0, "exposures_total": 0,
            "start_utc": datetime.now(timezone.utc).isoformat(), "end_utc": None,
        }

def _safe_load_json(path: Path, default):
    if path.exists():
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("JSON load failed for %s: %s", path, e)
    return default

if __name__ == "__main__":
    Orchestrator().run()
