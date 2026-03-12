#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/orchestrator.py
Version: 1.7.1
Objective: Full pipeline state machine wired to the v4.0.0 TCP Diamond
           Sequence. Authoritative flight daemon.

Changes vs 1.7.0:
  - REPLACED: aperture_grip_score(az, alt) — pure azimuth heuristic
  - ADDED:    meridian_aware_score(coord, now, location)
              Uses true hour angle to avoid/manage meridian flips:
              * Targets in the flip zone (|HA| < MERIDIAN_BUFFER_H) are
                deprioritised — let other targets go first
              * Targets west of meridian (HA > 0) get an urgency boost —
                they are declining, grab them now
              * Targets well east of meridian score on altitude alone —
                they have time, no rush
  - ADDED:    target["_ha"] stored for diagnostics / dashboard
  - ADDED:    safe_stop() called in _run_preflight() before hardware check
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body
from astropy.time import Time

import sys
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.env_loader import DATA_DIR, ENV_STATUS, load_config
from core.utils.notifier import alert, info as notify_info
from core.flight.pilot import DiamondSequence, AcquisitionTarget, SEESTAR_HOST

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


# ---------------------------------------------------------------------------
# Meridian-aware target scoring
# ---------------------------------------------------------------------------

# Hour angle boundaries (hours)
MERIDIAN_BUFFER_H = 0.3    # ±18 min around meridian — the flip zone
WEST_URGENCY_H    = 3.0    # targets west of meridian up to this HA get boosted
ALT_FLOOR_DEG     = 30.0   # also used as score floor

def meridian_aware_score(coord: SkyCoord,
                         now:   Time,
                         location: EarthLocation) -> tuple[float, float]:
    """
    Score a target for scheduling priority, taking the meridian into account.
    Returns (score, hour_angle_hours).

    Hour angle convention (standard):
      HA < 0  →  target is EAST  of meridian, rising
      HA = 0  →  target is ON    the meridian (flip point)
      HA > 0  →  target is WEST  of meridian, setting

    Scoring logic:
      Flip zone  |HA| < MERIDIAN_BUFFER_H  →  score  0..20   (go last)
      East side  HA < -MERIDIAN_BUFFER_H   →  score 40..70   (altitude based, no rush)
      West side  0 < HA < WEST_URGENCY_H   →  score 70..100  (declining, observe now)
      West side  HA > WEST_URGENCY_H       →  score 30..50   (getting low, normal)

    Altitude still modulates within each band — a higher target always
    beats a lower one in the same HA zone.
    """
    # Altitude for the floor check and modulation
    altaz   = coord.transform_to(AltAz(obstime=now, location=location))
    alt_deg = float(altaz.alt.deg)

    if alt_deg < ALT_FLOOR_DEG:
        return -1.0, 0.0   # caller should skip this target

    # Hour angle — LST minus RA, in hours, wrapped to (-12, +12)
    lst      = now.sidereal_time("apparent", longitude=location.lon)
    ha_hours = float((lst - coord.ra).wrap_at(180 * u.deg).hour)

    # Altitude contribution within band: 0..1
    alt_norm = (alt_deg - ALT_FLOOR_DEG) / (90.0 - ALT_FLOOR_DEG)

    if abs(ha_hours) < MERIDIAN_BUFFER_H:
        # Flip zone — deprioritise, let other targets go first.
        # Score 0–20. Still schedulable if nothing else is available.
        score = alt_norm * 20.0

    elif ha_hours > MERIDIAN_BUFFER_H:
        # West of meridian — already flipped, target is declining.
        if ha_hours < WEST_URGENCY_H:
            # Prime west window: highest priority.
            # Score 70–100 modulated by altitude and how far west.
            # Targets further west (more urgent) score slightly higher.
            urgency = ha_hours / WEST_URGENCY_H          # 0..1
            score   = 70.0 + alt_norm * 20.0 + urgency * 10.0
        else:
            # Getting late west — still observable but normal priority.
            score = 30.0 + alt_norm * 20.0

    else:
        # East of meridian — rising, no flip needed, no rush.
        # Score 40–70 modulated by altitude.
        # Closer to meridian (HA approaching 0 from east) scores higher
        # so we naturally sequence east targets late in their window.
        proximity = 1.0 - (abs(ha_hours) / 12.0)        # 0..1
        score     = 40.0 + alt_norm * 20.0 + proximity * 10.0

    return round(score, 2), round(ha_hours, 3)


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------
class PipelineState:
    IDLE, PREFLIGHT, PLANNING, FLIGHT, POSTFLIGHT, ABORTED, PARKED = (
        "IDLE", "PREFLIGHT", "PLANNING", "FLIGHT",
        "POSTFLIGHT", "ABORTED", "PARKED"
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
class Orchestrator:
    SUN_LIMIT_DEG  = -18.0     # Astronomical twilight
    ALT_FLOOR_DEG  = ALT_FLOOR_DEG
    PANEL_TIME_SEC = 60
    LOOP_SLEEP_SEC = 30

    def __init__(self):
        cfg   = load_config()
        loc   = cfg.get("location", {})
        aavso = cfg.get("aavso", {})

        self._obs = {
            "observer_id": aavso.get("observer_code", "MISSING_ID"),
            "lat":         loc.get("lat", 0.0),
            "lon":         loc.get("lon", 0.0),
            "elevation":   loc.get("elevation", 0.0),
        }

        self._location = EarthLocation(
            lat=self._obs["lat"] * u.deg,
            lon=self._obs["lon"] * u.deg,
            height=self._obs["elevation"] * u.m,
        )

        self._state       = PipelineState.IDLE
        self._targets     = []
        self._flight_log  = []
        self._session_stats = {
            "targets_attempted": 0,
            "targets_completed": 0,
            "exposures_total":   0,
            "start_utc":         None,
            "end_utc":           None,
        }

        self.diamond  = DiamondSequence(host=SEESTAR_HOST)
        self._science = None

    def _get_science_processor(self):
        if self._science is None:
            try:
                from core.postflight.science_processor import ScienceProcessor
                self._science = ScienceProcessor()
            except ImportError as e:
                log.warning(f"ScienceProcessor not available: {e}")
        return self._science

    # -----------------------------------------------------------------------
    # Main loop
    # -----------------------------------------------------------------------
    def run(self):
        log.info("Orchestrator starting — SeeVar v1.7.1 (Meridian-Aware)")
        self._session_stats["start_utc"] = datetime.now(timezone.utc).isoformat()
        self._write_state(sub="Daemon starting", msg="Federation online.")

        while True:
            try:
                self._tick()
            except KeyboardInterrupt:
                log.info("KeyboardInterrupt — exiting.")
                break
            except Exception as e:
                log.exception("Unhandled exception: %s", e)
                self._transition(PipelineState.ABORTED, msg=f"Error: {e}")
                alert(f"⚠️ SeeVar orchestrator error: {e}")
                time.sleep(self.LOOP_SLEEP_SEC * 4)

    def _tick(self):
        s = self._state
        if   s == PipelineState.IDLE:       self._run_idle()
        elif s == PipelineState.PREFLIGHT:  self._run_preflight()
        elif s == PipelineState.PLANNING:   self._run_planning()
        elif s == PipelineState.FLIGHT:     self._run_flight()
        elif s == PipelineState.POSTFLIGHT: self._run_postflight()
        elif s == PipelineState.PARKED:     self._run_parked()
        elif s == PipelineState.ABORTED:    self._run_aborted()

    # -----------------------------------------------------------------------
    # States
    # -----------------------------------------------------------------------
    def _run_idle(self):
        sun_alt = self._sun_altitude()
        self._write_state(
            sub="Standing by",
            msg=f"Sun at {sun_alt:.1f}°. Waiting for night (<{self.SUN_LIMIT_DEG}°)."
        )
        if sun_alt < self.SUN_LIMIT_DEG:
            self._transition(PipelineState.PREFLIGHT, msg="Astronomical night confirmed.")
        else:
            time.sleep(self.LOOP_SLEEP_SEC)

    def _run_preflight(self):
        self._log_flight("PREFLIGHT sequence initiated.")
        checks_passed = True

        # Sun gate
        sun_alt = self._sun_altitude()
        if sun_alt >= self.SUN_LIMIT_DEG:
            self._log_flight(f"Sun too high ({sun_alt:.1f}°) — aborting preflight.")
            self._transition(PipelineState.IDLE, msg="Sun rose during preflight.")
            return
        self._log_flight(f"Sun altitude: {sun_alt:.1f}° — GO.")

        # Hardware: safe_stop then get_device_state on port 4700
        from core.flight.camera_control import CameraControl
        cam = CameraControl()
        cam.safe_stop()   # clear any lingering session before health check
        time.sleep(1.0)
        if not cam.get_view_status():
            self._log_flight("Hardware check FAILED — device not responding on port 4700.")
            checks_passed = False
        else:
            self._log_flight("Hardware: RESPONDING.")

        # Weather
        weather_ok, weather_msg = self._check_weather()
        if not weather_ok:
            self._log_flight(f"Weather abort: {weather_msg}")
            checks_passed = False
        else:
            self._log_flight(f"Weather: {weather_msg}")

        # GPS
        gps = self._check_gps()
        self._log_flight(f"GPS: {gps}")

        if not checks_passed:
            self._transition(PipelineState.ABORTED, msg="Preflight failed.")
            alert("⚠️ SeeVar preflight FAILED — mission scrubbed.")
            return

        self._log_flight("All preflight checks passed — GO FOR PLANNING.")
        self._transition(PipelineState.PLANNING, msg="Preflight complete.")

    def _run_planning(self):
        self._log_flight("Loading mission targets...")
        mission = self._load_mission_targets()
        if not mission:
            self._transition(PipelineState.ABORTED, msg="No mission targets available.")
            return

        now    = Time.now()
        scored = []

        for target in mission:
            try:
                coord = SkyCoord(
                    ra=target.get("ra"), dec=target.get("dec"),
                    unit=(u.hourangle, u.deg)
                )
                score, ha = meridian_aware_score(coord, now, self._location)
                if score < 0:
                    continue   # below altitude floor

                target["_score"] = score
                target["_ha"]    = ha
                # Store alt/az for diagnostics
                altaz = coord.transform_to(AltAz(obstime=now, location=self._location))
                target["_alt"] = round(float(altaz.alt.deg), 2)
                target["_az"]  = round(float(altaz.az.deg),  2)
                scored.append(target)
            except Exception as e:
                log.warning("Could not score %s: %s", target.get("name", "?"), e)

        if not scored:
            self._transition(PipelineState.ABORTED, msg="No observable targets.")
            return

        scored.sort(key=lambda t: t["_score"], reverse=True)
        self._targets = scored
        self._write_plan(scored)

        # Log the flip picture for tonight
        flip_zone = [t for t in scored if abs(t.get("_ha", 99)) < MERIDIAN_BUFFER_H]
        west      = [t for t in scored if t.get("_ha", 0) > MERIDIAN_BUFFER_H]
        east      = [t for t in scored if t.get("_ha", 0) < -MERIDIAN_BUFFER_H]
        self._log_flight(
            f"Plan: {len(scored)} targets — "
            f"{len(east)} east, {len(flip_zone)} in flip zone, {len(west)} west. "
            f"Lead: {scored[0].get('name')} (HA={scored[0].get('_ha'):+.2f}h, "
            f"score={scored[0].get('_score')})"
        )
        self._transition(
            PipelineState.FLIGHT,
            sub=scored[0].get("name", "UNKNOWN"),
            msg="Flight plan locked."
        )

    def _run_flight(self):
        if not self._targets:
            self._transition(PipelineState.POSTFLIGHT, msg="Target list exhausted.")
            return

        # Dawn gate
        sun_alt = self._sun_altitude()
        if sun_alt >= self.SUN_LIMIT_DEG:
            self._log_flight(f"Dawn abort — sun at {sun_alt:.1f}°.")
            self._transition(PipelineState.POSTFLIGHT, msg="Dawn abort.")
            return

        # Mid-flight weather check
        weather_ok, weather_msg = self._check_weather()
        if not weather_ok:
            self._log_flight(f"Mid-flight weather abort: {weather_msg}")
            alert(f"🌧️ SeeVar weather abort: {weather_msg}")
            self._transition(PipelineState.POSTFLIGHT, msg=f"Weather abort: {weather_msg}")
            return

        # Re-score all targets with current time — meridian moves ~1h per hour
        now    = Time.now()
        valid  = []
        for target in self._targets:
            try:
                coord = SkyCoord(
                    ra=target["ra"], dec=target["dec"],
                    unit=(u.hourangle, u.deg)
                )
                score, ha = meridian_aware_score(coord, now, self._location)
                if score < 0:
                    continue
                target["_score"] = score
                target["_ha"]    = ha
                altaz = coord.transform_to(AltAz(obstime=now, location=self._location))
                target["_alt"] = round(float(altaz.alt.deg), 2)
                target["_az"]  = round(float(altaz.az.deg),  2)
                valid.append(target)
            except Exception:
                pass

        if not valid:
            self._log_flight("All targets below floor or set. Moving to postflight.")
            self._transition(PipelineState.POSTFLIGHT, msg="All targets set.")
            return

        valid.sort(key=lambda t: t["_score"], reverse=True)
        self._targets = valid
        target = valid[0]

        name    = target.get("name", "UNKNOWN")
        ha      = target.get("_ha", 0.0)
        score   = target.get("_score", 0.0)
        ra_str  = target.get("ra")
        dec_str = target.get("dec")

        coord = SkyCoord(ra=ra_str, dec=dec_str, unit=(u.hourangle, u.deg))
        acq   = AcquisitionTarget(
            name          = name,
            ra_hours      = float(coord.ra.hour),
            dec_deg       = float(coord.dec.deg),
            auid          = target.get("auid", ""),
            exp_ms        = self.PANEL_TIME_SEC * 1000,
            observer_code = self._obs["observer_id"],
        )

        self._session_stats["targets_attempted"] += 1
        ha_side = "W" if ha > 0 else "E"
        self._log_flight(
            f"Target: {name}  HA={ha:+.2f}h ({ha_side})  "
            f"alt={target.get('_alt')}°  score={score}"
        )
        self._write_state(state="SLEWING", sub=name,
                         msg=f"Diamond Sequence: {name} HA={ha:+.2f}h")

        result = self.diamond.acquire(acq)

        if result.success:
            self._session_stats["targets_completed"] += 1
            self._session_stats["exposures_total"]   += 1
            self._log_flight(f"Acquisition complete: {result.path.name}")
            notify_info(f"✅ SeeVar acquired {name} → {result.path.name}")

            self._handoff_to_science(name, result.path)
            self._ledger_update(name, success=True)

            self._targets.remove(target)
            self._targets.append(target)
            self._write_state(state="TRACKING", sub=name, msg="Observation complete.")
        else:
            self._log_flight(f"TCP Acquisition FAILED for {name}: {result.error}")
            alert(f"❌ SeeVar acquisition failed: {name} — {result.error}")
            self._ledger_update(name, success=False)
            self._targets.remove(target)

    def _run_postflight(self):
        self._log_flight("Postflight audit initiated.")
        self._session_stats["end_utc"] = datetime.now(timezone.utc).isoformat()
        completed = self._session_stats["targets_completed"]
        attempted = self._session_stats["targets_attempted"]
        notify_info(
            f"🔭 SeeVar session complete — {completed}/{attempted} targets acquired."
        )
        self._transition(PipelineState.PARKED, msg="Postflight complete.")

    def _run_parked(self):
        sun_alt = self._sun_altitude()
        self._write_state(
            sub="Parked",
            msg=f"Parked. Sun at {sun_alt:.1f}°. Waiting for next night."
        )
        if sun_alt > 5.0:
            self._reset_session()
            self._transition(PipelineState.IDLE, msg="Reset. Ready for next night.")
        else:
            time.sleep(self.LOOP_SLEEP_SEC * 2)

    def _run_aborted(self):
        sun_alt = self._sun_altitude()
        self._write_state(sub="ABORTED", msg=f"Holding. Sun at {sun_alt:.1f}°.")
        if sun_alt > 5.0:
            self._reset_session()
            self._transition(PipelineState.IDLE, msg="Abort cleared.")
        else:
            time.sleep(self.LOOP_SLEEP_SEC * 2)

    # -----------------------------------------------------------------------
    # Per-target postflight handoff
    # -----------------------------------------------------------------------
    def _handoff_to_science(self, name: str, fits_path: Path):
        processor = self._get_science_processor()
        if processor is None:
            log.warning("ScienceProcessor unavailable — skipping science extraction.")
            return
        try:
            processed = processor.process_green_stack(name.replace(" ", "_"))
            if processed:
                self._log_flight(f"Science extraction complete: {processed}")
            else:
                log.warning(f"Science extraction returned nothing for {name}.")
        except Exception as e:
            log.error(f"ScienceProcessor error for {name}: {e}")

    # -----------------------------------------------------------------------
    # Ledger — per-target append-only update
    # -----------------------------------------------------------------------
    def _ledger_update(self, name: str, success: bool):
        try:
            LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
            ledger = {}
            if LEDGER_FILE.exists():
                try:
                    with open(LEDGER_FILE, "r") as f:
                        ledger = json.load(f)
                except (json.JSONDecodeError, OSError):
                    log.warning("Ledger read failed — starting fresh entry.")

            entries = ledger.setdefault("entries", {})
            key     = name.upper().replace(" ", "_")
            entry   = entries.setdefault(key, {"attempts": 0})

            entry["attempts"] = entry.get("attempts", 0) + 1
            if success:
                entry["last_success"] = datetime.now(timezone.utc).isoformat()
                entry["status"]       = "OK"
            else:
                entry["status"] = "FAILED"

            with open(LEDGER_FILE, "w") as f:
                json.dump(ledger, f, indent=2)
        except OSError as e:
            log.error(f"Ledger write failed for {name}: {e}")

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------
    def _sun_altitude(self) -> float:
        try:
            now = Time.now()
            sun = get_body("sun", now)
            return float(
                sun.transform_to(
                    AltAz(obstime=now, location=self._location)
                ).alt.deg
            )
        except Exception:
            return 0.0

    def _check_weather(self) -> tuple[bool, str]:
        data = _safe_load_json(WEATHER_FILE, {})
        if not data:
            return True, "No weather data — proceeding optimistically."
        status = data.get("status", "UNKNOWN").upper()
        if status in ("RAIN", "STORM", "SNOW", "OVERCAST", "CLOUDY", "WINDY"):
            return False, f"Weather status: {status}"
        if data.get("clouds_pct", 0) > 70:
            return False, f"Cloud cover {data['clouds_pct']}%"
        if data.get("humidity_pct", 0) > 90:
            return False, f"Humidity {data['humidity_pct']}% — dew risk"
        return True, status

    def _check_gps(self) -> str:
        return _safe_load_json(ENV_STATUS, {}).get("gps_status", "NO-DATA")

    def _load_mission_targets(self) -> list:
        data = _safe_load_json(MISSION_FILE, [])
        return data if isinstance(data, list) else data.get("targets", [])

    def _transition(self, new_state: str, sub: str = "", msg: str = ""):
        log.info("STATE: %s → %s", self._state, new_state)
        self._state = new_state
        self._write_state(state=new_state, sub=sub, msg=msg)

    def _write_state(self, state: str = None, sub: str = "", msg: str = "", **kwargs):
        payload = {
            "state":     state or self._state,
            "sub":       sub,
            "msg":       msg,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **kwargs,
        }
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(STATE_FILE, "w") as f:
                json.dump(payload, f, indent=2)
        except OSError as e:
            log.error("system_state.json write failed: %s", e)

    def _write_plan(self, targets: list):
        try:
            with open(PLAN_FILE, "w") as f:
                json.dump(targets, f, indent=2, default=str)
        except OSError as e:
            log.error("Plan write failed: %s", e)

    def _log_flight(self, line: str):
        ts    = datetime.now(timezone.utc).strftime("%H:%M:%S")
        entry = f"[{ts}] {line}"
        log.info(line)
        self._flight_log.append(entry)
        if len(self._flight_log) > 20:
            self._flight_log.pop(0)
        self._write_state(msg=line)

    def _reset_session(self):
        self._targets    = []
        self._flight_log = []
        self._session_stats = {
            "targets_attempted": 0,
            "targets_completed": 0,
            "exposures_total":   0,
            "start_utc": datetime.now(timezone.utc).isoformat(),
            "end_utc":   None,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _safe_load_json(path: Path, default):
    if path.exists():
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("JSON load failed for %s: %s", path, e)
    return default


if __name__ == "__main__":
    Orchestrator().run()
