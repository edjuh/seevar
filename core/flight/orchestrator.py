#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/orchestrator.py
Version: 1.7.0
Objective: Full pipeline state machine wired to the TCP Diamond Sequence via the SovereignFSM. 
           M4: DarkLibrary wired into post-session flow.
           v1.7.0: Integrated SovereignFSM to handle direct hardware execution and state transitions.
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
from core.flight.pilot import DiamondSequence, AcquisitionTarget, SEESTAR_HOST, GAIN, TelemetryBlock, FrameResult
from core.flight.exposure_planner import plan_exposure
from core.flight.dark_library import DarkLibrary
from core.flight.neutralizer import enforce_zero_state
from core.preflight.vsx_catalog import get_target_mag
from core.flight.pilot import write_fits, sovereign_stamp
from core.flight.fsm import SovereignFSM
import core.ledger_manager as ledger_manager

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
log = logging.getLogger("seevar.orchestrator")

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
    """Mock hardware sequence for the Full Mission Simulator."""
    def init_session(self, level_ok: bool = True) -> TelemetryBlock:
        t = TelemetryBlock(
            battery_pct=95, temp_c=22.5, charge_online=False,
            charger_status="Discharging", device_name="S30-Sim", firmware_ver=100,
        )
        t.level_ok = level_ok
        log.info("[SIM] init_session — mock telemetry generated")
        return t

    def acquire(self, target: AcquisitionTarget, status_cb=None, telemetry: Optional[TelemetryBlock] = None) -> FrameResult:
        def step(tag, msg):
            log.info(f"  [{tag}] SIM {msg}")
            if status_cb: status_cb(f"[{tag}] {msg}")

        step("T1", f"Simulating {target.exp_ms}ms exposure for {target.name}")
        time.sleep(2.0)
        
        # Generate a valid mock FITS frame with a "star" in the middle
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
        
        step("T7", f"write_fits — SIM payload saved to {out_path}")
        return FrameResult(success=True, path=out_path, width=width, height=height, elapsed_s=4.0)

class Orchestrator:
    SUN_LIMIT_DEG    = -18.0 
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

        self._state          = PipelineState.IDLE
        self._targets        = []
        self._flight_log     = []
        self._current_target = None
        self._session_stats = {
            "targets_attempted": 0, "targets_completed": 0, "exposures_total": 0,
        }
        
        self._dark_library       = DarkLibrary(host=SEESTAR_HOST)
        self._tonights_sequences = set()  # (exp_ms, gain) pairs acquired tonight
        self._last_telemetry     = None   
        
        self.simulation_mode = "--simulate" in sys.argv
        
        # Initialize FSM
        self.fsm = SovereignFSM()
        
        if self.simulation_mode:
            self.fsm.sequence = MockDiamondSequence()
            self.LOOP_SLEEP_SEC = 0  
            log.info("🚀 SIMULATION MODE ENGAGED - Hardware checks disabled.")

    def run(self):
        log.info("🔭 Orchestrator starting — SeeVar Federation v2.0.0 (FSM-Governed)")
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

    def _check_weather_veto(self) -> tuple[bool, str]:
        """Read weather_state.json and return (go, reason)."""
        HARD_ABORT = {"RAIN", "FOGGY", "CLOUDY", "WINDY"}
        try:
            if not WEATHER_FILE.exists():
                log.warning("weather_state.json not found — proceeding without weather veto")
                return True, "NO_WEATHER_FILE"

            with open(WEATHER_FILE) as f:
                w = json.load(f)

            status = w.get("status", "UNKNOWN")
            icon   = w.get("icon",   "")
            age_s  = time.time() - w.get("last_update", 0)

            if age_s > 21600:
                log.warning("Weather data is %.0fh old — proceeding with caution", age_s / 3600)

            if status in HARD_ABORT:
                reason = (
                    f"Weather veto: {status} {icon} — "
                    f"KNMI oktas:{w.get('knmi_oktas','?')} "
                    f"CO_low:{w.get('low_cloud','?')}% "
                    f"window:{w.get('dark_start','?')}→{w.get('dark_end','?')}"
                )
                return False, reason

            log.info("Weather GO: %s %s (age: %.0fmin)", status, icon, age_s / 60)
            return True, status

        except Exception as e:
            log.warning("Weather veto check failed: %s — proceeding", e)
            return True, "WEATHER_CHECK_ERROR"

    def _run_idle(self):
        sun_alt = self._sun_altitude()
        msg = f"Sun at {sun_alt:.1f}°. Waiting for night (<{self.SUN_LIMIT_DEG}°)."
        self._write_state(sub="Standing by", msg=msg)
        
        if self.simulation_mode or sun_alt < self.SUN_LIMIT_DEG:
            if not self.simulation_mode:
                go, reason = self._check_weather_veto()
                if not go:
                    self._write_state(sub="Weather Hold", msg=reason)
                    log.warning("🌧️ %s", reason)
                    time.sleep(self.LOOP_SLEEP_SEC * 4)  
                    return
            self._transition(PipelineState.PREFLIGHT, msg="Night sky confirmed (or forced by Simulation).")
        else:
            time.sleep(self.LOOP_SLEEP_SEC)

    def _run_preflight(self):
        self._log_flight("🛫 PREFLIGHT sequence initiated.")
        
        if not self.simulation_mode:
            self._log_flight("[B1] enforce_zero_state...")
            zero = enforce_zero_state()
            if not zero:
                self._log_flight("[B1] ❌ zero-state failed — aborting")
                self._transition(PipelineState.ABORTED, msg="Hardware zero-state not secured")
                return
            self._log_flight("[B1] ✅ zero-state secured")

        # Perform one initial hardware check to populate _last_telemetry for the UI
        self._log_flight("Validating hardware baseline via FSM...")
        self._last_telemetry = self.fsm.sequence.init_session(level_ok=True)
        
        if not self._last_telemetry.is_safe():
            reason = self._last_telemetry.veto_reason()
            self._log_flight(f"🛑 VETO at preflight: {reason}")
            self._transition(PipelineState.ABORTED, msg=f"Preflight veto: {reason}")
            return

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
                coord = SkyCoord(
                    ra=float(target.get("ra")) * u.deg,
                    dec=float(target.get("dec")) * u.deg
                )
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
        scored = ledger_manager.filter_by_cadence(scored)
        
        if not scored:
            self._transition(PipelineState.ABORTED, msg="No targets due tonight by cadence.")
            return

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

        ra_deg_val  = float(ra_str)  if isinstance(ra_str,  (int, float)) else float(SkyCoord(ra=ra_str,  dec=dec_str, unit=(u.hourangle, u.deg)).ra.hour * 15)
        dec_deg_val = float(dec_str) if isinstance(dec_str, (int, float)) else float(SkyCoord(ra=ra_str,  dec=dec_str, unit=(u.hourangle, u.deg)).dec.deg)
        ra_hours_val = ra_deg_val / 15.0
        
        # Determine exposure parameters
        try:
            exp_plan = plan_exposure(get_target_mag(name), sky_bortle=self._sky_bortle())
            exp_ms = exp_plan.exp_ms
        except Exception:
            exp_ms = 5000 # Default fallback
            
        acq_target = AcquisitionTarget(
            name=name, ra_hours=ra_hours_val, dec_deg=dec_deg_val,
            auid=target.get("auid", ""), exp_ms=exp_ms, 
            observer_code=self._obs["observer_id"], n_frames=1
        )

        self._session_stats["targets_attempted"] += 1
        self._current_target = {
            "name":        name,
            "ra":          round(ra_deg_val, 4),
            "dec":         round(dec_deg_val, 4),
            "type":        target.get("type", ""),
            "mag_max":     target.get("mag_max"),
            "min_mag":     target.get("min_mag"),
            "period_days": target.get("period_days"),
            "auid":        target.get("auid", ""),
        }
        
        self._write_state(state="SLEWING", sub=name, msg=f"FSM Handing over: {name}")
        self._log_flight(f"Executing target via FSM: {name} RA={acq_target.ra_hours:.2f}h")

        ledger_manager.record_attempt(name)

        # Handoff to the Finite State Machine
        success = self.fsm.execute_target(acq_target)

        # Update telemetry context from the FSM for UI display
        if self.fsm.telemetry:
            self._last_telemetry = self.fsm.telemetry

        if success:
            self._session_stats["targets_completed"] += 1
            # In a multi-frame scenario, the ledger manager might need updating to handle multiple paths.
            # Assuming success means at least one frame was captured.
            ledger_manager.record_success(name, fits_path="LOCAL_BUFFER") 
            self._log_flight(f"✅ FSM Sequence complete for {name}")
            self._write_state(state="TRACKING", sub=name, msg=f"Observation complete.")
            self._tonights_sequences.add((acq_target.exp_ms, GAIN))
        else:
            self._log_flight(f"❌ FSM Sequence failed for {name}")
            # If the FSM transitions to ERROR, we can abort the entire flight or continue.
            # Currently continuing to the next target.

    def _run_postflight(self):
        self._log_flight("📊 Flight operations concluded.")
        if self._tonights_sequences and not self.simulation_mode:
            seqs = sorted(self._tonights_sequences)
            self._log_flight(f"🌑 Acquiring darks for {len(seqs)} sequence(s): {seqs}")
            self._write_state(state="POSTFLIGHT", sub="dark_acquisition", msg=f"Acquiring darks: {seqs}")
            
            dark_results = self._dark_library.acquire_darks(
                sequences=seqs,
                telemetry=getattr(self, "_last_telemetry", None),
            )
            for key, res in dark_results.items():
                self._log_flight(f"  dark {key}: {res['status']} ({res['n_frames']} frames)")
        else:
            if self.simulation_mode:
                self._log_flight("  [simulation] dark acquisition skipped")
            else:
                self._log_flight("  no sequences recorded — dark acquisition skipped")
                
        self._log_flight("Handing over to Accountant.") 
        if not self.simulation_mode:
            try:
                from core.postflight.accountant import process_buffer
                process_buffer()
                self._log_flight("✅ Accountant complete — ledger stamped.")
            except Exception as e:
                self._log_flight(f"⚠️ Accountant error: {e}")
        else:
            self._log_flight("  [simulation] accountant skipped")
            
        self._transition(PipelineState.PARKED, msg="Mission Complete.")

    def _run_parked(self):
        self._current_target = None
        time.sleep(self.LOOP_SLEEP_SEC)

    def _run_aborted(self):
        self._current_target = None
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
