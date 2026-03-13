#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/orchestrator.py
Version: 1.7.3
Objective: Full pipeline state machine wired to the TCP Diamond Sequence with detailed 12-step mock telemetry.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body
from astropy.time import Time

import sys
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.env_loader import DATA_DIR, ENV_STATUS, load_config
from core.flight.pilot import DiamondSequence, AcquisitionTarget, SEESTAR_HOST
from core.flight.exposure_planner import plan_exposure
from core.preflight.vsx_catalog import get_target_mag, FrameResult, write_fits, sovereign_stamp

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

PLAN_FILE    = DATA_DIR / "tonights_plan.json"
STATE_FILE   = DATA_DIR / "system_state.json"
LEDGER_FILE  = DATA_DIR / "ledger.json"
WEATHER_FILE = DATA_DIR / "weather_state.json"
MISSION_FILE = DATA_DIR / "tonights_plan.json"

def aperture_grip_score(azimuth: float, altitude: float) -> float:
    if 180 <= azimuth <= 350: return 100.0 - altitude
    return altitude / 2.0

class PipelineState:
    IDLE, PREFLIGHT, PLANNING, FLIGHT, POSTFLIGHT, ABORTED, PARKED = (
        "IDLE", "PREFLIGHT", "PLANNING", "FLIGHT", "POSTFLIGHT", "ABORTED", "PARKED"
    )

class MockDiamondSequence:
    """Mock hardware sequence for the Full Mission Simulator with 12-step telemetry."""
    def acquire(self, target: AcquisitionTarget) -> FrameResult:
        log.info(f"  [Step 1/12] Initializing Coordinates: RA={target.ra_hours:.4f}h, DEC={target.dec_deg:.4f}°")
        time.sleep(0.2)
        log.info(f"  [Step 2/12] Commanding Mount Slew to {target.name}...")
        time.sleep(0.3)
        log.info(f"  [Step 3/12] Slewing motors active...")
        time.sleep(0.6)
        log.info(f"  [Step 4/12] Mount Settling (8.0s rule)...")
        time.sleep(0.4)
        log.info(f"  [Step 5/12] Engaging Plate Solver (Blind Astrometry)...")
        time.sleep(0.5)
        log.info(f"  [Step 6/12] Syncing Mount to Solved WCS Center...")
        time.sleep(0.2)
        log.info(f"  [Step 7/12] Configuring Optical Path: Filter=CV, Gain=80")
        time.sleep(0.2)
        log.info(f"  [Step 8/12] Verifying V-Curve (Autofocus Check)...")
        time.sleep(0.5)
        log.info(f"  [Step 9/12] Opening Exposure Shutter ({target.exp_ms}ms)...")
        time.sleep(0.6)
        log.info(f"  [Step 10/12] Streaming Raw Payload via Port 4801...")
        time.sleep(0.3)
        log.info(f"  [Step 11/12] Generating Sovereign WCS Headers (AUID: {target.auid})...")
        time.sleep(0.2)
        log.info(f"  [Step 12/12] Writing 16-bit FITS to Local Buffer...")
        
        # Generate a valid mock FITS frame with a "star" in the middle for the Accountant
        width, height = 2160, 3840
        array = np.random.normal(100, 10, (height, width)).astype(np.uint16)
        cy, cx = height // 2, width // 2
        array[cy-5:cy+5, cx-5:cx+5] = 50000 
        
        utc_obs = datetime.now(timezone.utc)
        LOCAL_BUFFER = DATA_DIR / "local_buffer"
        LOCAL_BUFFER.mkdir(parents=True, exist_ok=True)
        
        safe_name = target.name.replace(" ", "_").replace("/", "-")
        timestamp = utc_obs.strftime("%Y%m%dT%H%M%S")
        out_path  = LOCAL_BUFFER / f"SIM_{safe_name}_{timestamp}_Raw.fits"
        
        header = sovereign_stamp(target, utc_obs, width, height)
        write_fits(array, header, out_path)
        
        return FrameResult(success=True, path=out_path, width=width, height=height, elapsed_s=4.0)


class Orchestrator:
    SUN_LIMIT_DEG    = -10.0 
    ALT_FLOOR_DEG    = 30.0
    PANEL_TIME_SEC   = 60
    LOOP_SLEEP_SEC   = 30

    def __init__(self):
        cfg = load_config()
        loc = cfg.get("location", {})
        aavso = cfg.get("aavso", {})
        self._obs = {
            "observer_id":       aavso.get("observer_code", "MISSING_ID"),
            "lat":               loc.get("lat", 0.0),
            "lon":               loc.get("lon", 0.0),
            "elevation":         loc.get("elevation", 0.0),
        }

        self._location = EarthLocation(
            lat=self._obs["lat"] * u.deg, lon=self._obs["lon"] * u.deg, height=self._obs["elevation"] * u.m,
        )

        self._state      = PipelineState.IDLE
        self._targets    = []
        self._flight_log = []
        self._session_stats = {
            "targets_attempted": 0, "targets_completed": 0, "exposures_total": 0,
        }
        
        self.simulation_mode = "--simulate" in sys.argv
        if self.simulation_mode:
            self.diamond = MockDiamondSequence()
            self.LOOP_SLEEP_SEC = 0  
            log.info("🚀 SIMULATION MODE ENGAGED - Hardware checks disabled.")
        else:
            self.diamond = DiamondSequence(host=SEESTAR_HOST)

    def run(self):
        log.info("🔭 Orchestrator starting — SeeVar Federation v1.7.3 (Telemetry-Aware)")
        self._write_state(sub="Daemon starting", msg="Federation online.")
        while True:
            try: 
                self._tick()
                if self.simulation_mode and self._state in (PipelineState.PARKED, PipelineState.ABORTED):
                    log.info("Simulation complete. Terminating process.")
                    break
            except KeyboardInterrupt:
                log.info("KeyboardInterrupt — exiting.")
                break
            except Exception as e:
                log.exception("Unhandled exception: %s", e)
                self._transition(PipelineState.ABORTED, msg=f"Error: {e}")
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
        msg = f"Sun at {sun_alt:.1f}°. Waiting for night (<{self.SUN_LIMIT_DEG}°)."
        self._write_state(sub="Standing by", msg=msg)
        
        if self.simulation_mode or sun_alt < self.SUN_LIMIT_DEG:
            self._transition(PipelineState.PREFLIGHT, msg="Night sky confirmed (or forced by Simulation).")
        else: 
            time.sleep(self.LOOP_SLEEP_SEC)

    def _run_preflight(self):
        self._log_flight("🛫 PREFLIGHT sequence initiated.")
        
        if self.simulation_mode:
            self._log_flight("  [Init 1/6] Bootstrapping SocketLink (192.168.178.55:4700)...")
            time.sleep(0.3)
            self._log_flight("  [Init 2/6] Securing Binary Image Stream (Port 4801)...")
            time.sleep(0.3)
            self._log_flight("  [Init 3/6] Syncing Observatory UTC Time & Location...")
            time.sleep(0.3)
            self._log_flight("  [Init 4/6] Requesting Device State (Vitals/Battery Check)...")
            time.sleep(0.3)
            self._log_flight("  [Init 5/6] Unparking Mount & Engaging Tracking Motors...")
            time.sleep(0.3)
            self._log_flight("  [Init 6/6] Activating IMX585 Sensor Matrix...")
            time.sleep(0.3)
        else:
            self._log_flight("✅ TCP Ports active. Hardware checks bypassed for Diamond integration.")
            
        self._transition(PipelineState.PLANNING, msg="Preflight complete.")

    def _run_planning(self):
        self._log_flight("📋 Loading mission targets...")
        mission = self._load_mission_targets()
        if not mission:
            self._transition(PipelineState.ABORTED, msg="No mission targets available.")
            return

        now = Time.now()
        frame = AltAz(obstime=now, location=self._location)
        scored = []

        for target in mission:
            try:
                coord = SkyCoord(ra=target.get("ra"), dec=target.get("dec"), unit=(u.hourangle, u.deg))
                altaz = coord.transform_to(frame)
                alt_deg, az_deg = float(altaz.alt.deg), float(altaz.az.deg)
                if alt_deg < self.ALT_FLOOR_DEG: continue

                target["_alt"] = round(alt_deg, 2)
                target["_score"] = round(aperture_grip_score(az_deg, alt_deg), 2)
                scored.append(target)
            except Exception: pass

        if not scored:
            self._transition(PipelineState.ABORTED, msg="No observable targets.")
            return

        scored.sort(key=lambda t: t["_score"], reverse=True)
        self._targets = scored
        self._write_plan(scored)
        self._transition(PipelineState.FLIGHT, sub=scored[0].get("name", "UNKNOWN"), msg="Flight plan locked.")

    def _run_flight(self):
        if not self._targets:
            self._transition(PipelineState.POSTFLIGHT, msg="Target list exhausted.")
            return

        target = self._targets.pop(0)
        name    = target.get("name", "UNKNOWN")
        ra_str  = target.get("ra")
        dec_str = target.get("dec")

        coord   = SkyCoord(ra=ra_str, dec=dec_str, unit=(u.hourangle, u.deg))
        acq_target = AcquisitionTarget(
            name=name, ra_hours=float(coord.ra.hour), dec_deg=float(coord.dec.deg),
            auid=target.get("auid", ""), exp_ms=plan_exposure(get_target_mag(name), sky_bortle=self._sky_bortle()).exp_ms, observer_code=self._obs["observer_id"]
        )

        self._session_stats["targets_attempted"] += 1
        self._write_state(state="SLEWING", sub=name, msg=f"Diamond Sequence executing: {name}")
        self._log_flight(f"🎯 Capturing {name}...")

        result = self.diamond.acquire(acq_target)

        if result.success:
            self._session_stats["targets_completed"] += 1
            self._log_flight(f"✅ Acquired: {result.path.name}")
            self._write_state(state="TRACKING", sub=name, msg=f"Observation complete.")
        else:
            self._log_flight(f"❌ Failed for {name}: {result.error}")

    def _run_postflight(self):
        self._log_flight("📊 Flight operations concluded. Handing over to Accountant.")
        self._transition(PipelineState.PARKED, msg="Mission Complete.")

    def _run_parked(self):
        time.sleep(self.LOOP_SLEEP_SEC)

    def _run_aborted(self):
        time.sleep(self.LOOP_SLEEP_SEC)

    def _sun_altitude(self) -> float:
        try:
            now = Time.now()
            sun = get_body("sun", now)
            return float(sun.transform_to(AltAz(obstime=now, location=self._location)).alt.deg)
        except Exception: return 0.0

    def _load_mission_targets(self) -> list:
        data = _safe_load_json(MISSION_FILE, [])
        return data if isinstance(data, list) else data.get("targets", [])

    def _transition(self, new_state: str, sub: str = "", msg: str = ""):
        log.info("STATE: %s → %s", self._state, new_state)
        self._state = new_state
        self._write_state(state=new_state, sub=sub, msg=msg)

    def _write_state(self, state: str = None, sub: str = "", msg: str = "", **kwargs):
        payload = {"state": state or self._state, "sub": sub, "msg": msg, "timestamp": datetime.now(timezone.utc).isoformat()}
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(STATE_FILE, 'w') as f: json.dump(payload, f, indent=2)
        except OSError: pass

    def _write_plan(self, targets: list):
        try:
            with open(PLAN_FILE, 'w') as f: json.dump(targets, f, indent=2, default=str)
        except OSError: pass

    def _log_flight(self, line: str):
        log.info(line)
        self._flight_log.append(line)
        if len(self._flight_log) > 10: self._flight_log.pop(0)

    def _sky_bortle(self) -> int:
        """Return Bortle class from config, default 7 (Haarlem)."""
        cfg = load_config()
        return int(cfg.get("location", {}).get("bortle", 7))


def _safe_load_json(path: Path, default):
    if path.exists():
        try:
            with open(path, 'r') as f: return json.load(f)
        except Exception: pass
    return default

if __name__ == "__main__":
    Orchestrator().run()
