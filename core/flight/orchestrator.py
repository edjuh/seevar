#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/orchestrator.py
Version: 1.8.3
Objective: Autonomous night daemon consuming tonights_plan.json as the canonical mission order,
logging A1-A12, executing targets via SovereignFSM, and closing the session with automatic
dark acquisition followed by postflight accounting.
"""

import json
import logging
import math
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body
from astropy.io import fits
from astropy.time import Time

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.env_loader import DATA_DIR, load_config, selected_scope, selected_scope_id
from core.flight.pilot import (
    AcquisitionTarget,
    SEESTAR_HOST,
    GAIN,
    TelemetryBlock,
    VETO_BATTERY,
    FrameResult,
    write_fits,
    sovereign_stamp,
)
from core.flight.exposure_planner import plan_exposure
from core.flight.dark_library import DarkLibrary
from core.flight.neutralizer import enforce_zero_state
from core.preflight.vsx_catalog import get_target_mag
from core.flight.fsm import SovereignFSM
import core.ledger_manager as ledger_manager
from core.hardware.live_battery import poll_battery_snapshot

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

PLAN_FILE = DATA_DIR / "tonights_plan.json"
STATE_FILE = DATA_DIR / "system_state.json"
WEATHER_FILE = DATA_DIR / "weather_state.json"
MISSION_FILE = DATA_DIR / "tonights_plan.json"
FLEET_PLAN_DIR = DATA_DIR / "fleet_plans"


def _safe_load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default


def _parse_plan_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


class PipelineState:
    IDLE, PREFLIGHT, PLANNING, FLIGHT, WAITING, POSTFLIGHT, ABORTED, PARKED = (
        "IDLE", "PREFLIGHT", "PLANNING", "FLIGHT", "WAITING", "POSTFLIGHT", "ABORTED", "PARKED"
    )


class MockDiamondSequence:
    """Mock hardware sequence for the Full Mission Simulator."""

    def prepare_target(self, target, telemetry=None, notify=None):
        if notify:
            notify("A9", f"Simulation prepare target - exp_ms={target.exp_ms} n_frames={target.n_frames}")
        return target

    def init_session(self, level_ok: bool = True) -> TelemetryBlock:
        t = TelemetryBlock(
            battery_pct=95,
            temp_c=22.5,
            charge_online=False,
            charger_status="Discharging",
            device_name="S30-Sim",
            firmware_ver=100,
        )
        t.level_ok = level_ok
        log.info("[SIM][A3] Session init — mock telemetry generated")
        return t

    def _pixel_from_world(self, header: dict, ra_deg: float, dec_deg: float) -> tuple[float, float]:
        crval1 = float(header["CRVAL1"])
        crval2 = float(header["CRVAL2"])
        crpix1 = float(header["CRPIX1"])
        crpix2 = float(header["CRPIX2"])
        cdelt1 = float(header["CDELT1"])
        cdelt2 = float(header["CDELT2"])

        px = crpix1 + (crval1 - ra_deg) / abs(cdelt1)
        py = crpix2 + (dec_deg - crval2) / abs(cdelt2)
        return px, py

    def _draw_star(self, array: np.ndarray, x: float, y: float, amplitude: float, sigma: float = 2.0):
        h, w = array.shape
        x0 = int(round(x))
        y0 = int(round(y))
        radius = max(6, int(round(4 * sigma)))

        xs = np.arange(max(0, x0 - radius), min(w, x0 + radius + 1))
        ys = np.arange(max(0, y0 - radius), min(h, y0 + radius + 1))
        if len(xs) == 0 or len(ys) == 0:
            return

        xx, yy = np.meshgrid(xs, ys)
        spot = amplitude * np.exp(-(((xx - x) ** 2 + (yy - y) ** 2) / (2.0 * sigma ** 2)))
        array[np.ix_(ys, xs)] += spot

    def _build_sim_comp_stars(self, target: AcquisitionTarget) -> list[dict]:
        ra_deg = target.ra_hours * 15.0
        dec_deg = target.dec_deg
        cos_dec = max(0.2, math.cos(math.radians(dec_deg)))

        synthetic = [
            (-18.0, 10.0, 10.8),
            (22.0, 12.0, 11.2),
            (-14.0, -16.0, 11.7),
            (26.0, -10.0, 12.0),
            (8.0, 20.0, 11.4),
            (-24.0, 4.0, 12.1),
        ]

        stars = []
        for idx, (dx_arcmin, dy_arcmin, vmag) in enumerate(synthetic, start=1):
            comp_ra = ra_deg + (dx_arcmin / 60.0) / cos_dec
            comp_dec = dec_deg + (dy_arcmin / 60.0)
            stars.append({
                "source_id": f"SIMC{idx:03d}",
                "ra": round(comp_ra, 6),
                "dec": round(comp_dec, 6),
                "gmag": round(vmag, 4),
                "v_mag": round(vmag, 4),
                "bp_rp": 1.0,
                "bands": [{"band": "V", "mag": round(vmag, 4)}],
            })
        return stars

    def _write_wcs_sidecar(self, out_path: Path, header: dict):
        wcs_header = fits.Header()
        for key in (
            "CRVAL1", "CRVAL2", "CRPIX1", "CRPIX2", "CDELT1", "CDELT2",
            "CTYPE1", "CTYPE2", "RA", "DEC", "OBJECT"
        ):
            if key in header:
                wcs_header[key] = header[key]
        hdu = fits.PrimaryHDU(data=np.zeros((2, 2), dtype=np.uint16), header=wcs_header)
        hdu.writeto(out_path.with_suffix(".wcs"), overwrite=True)

    def _write_sim_gaia_cache(self, target: AcquisitionTarget, comp_stars: list[dict]):
        from core.postflight.gaia_resolver import _cache_path

        ra_deg = target.ra_hours * 15.0
        dec_deg = target.dec_deg
        cache_path = _cache_path(ra_deg, dec_deg)
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "ra": ra_deg,
            "dec": dec_deg,
            "n": len(comp_stars),
            "stars": comp_stars,
        }
        with open(cache_path, "w") as f:
            json.dump(payload, f, indent=2)

    def acquire(self, target: AcquisitionTarget, status_cb=None, telemetry: Optional[TelemetryBlock] = None, skip_pointing=False) -> FrameResult:
        def step(tag, msg):
            log.info("  [%s] SIM %s", tag, msg)
            if status_cb:
                status_cb(f"[{tag}] {msg}")

        width, height = 2160, 3840
        array = np.random.normal(300.0, 12.0, (height, width)).astype(np.float64)

        utc_obs = datetime.now(timezone.utc)
        local_buffer = DATA_DIR / "local_buffer"
        local_buffer.mkdir(parents=True, exist_ok=True)

        safe_name = target.name.replace(" ", "_").replace("/", "-")
        timestamp = utc_obs.strftime("%Y%m%dT%H%M%S")
        out_path = local_buffer / f"SIM_{safe_name}_{timestamp}_Raw.fits"

        step("A4", f"Slew command to {target.name}")
        time.sleep(0.2)

        step("A5", "Slew verify complete")
        time.sleep(0.2)

        step("A6", "Settle complete")
        time.sleep(0.2)

        step("A7", "Pointing verify placeholder")
        time.sleep(0.2)

        ra_deg = target.ra_hours * 15.0
        dec_deg = target.dec_deg

        header = fits.Header()
        header["OBJECT"] = target.name
        header["DATE-OBS"] = utc_obs.isoformat()
        header["EXPTIME"] = target.exp_ms / 1000.0
        header["EXPMS"] = int(target.exp_ms)
        header["GAIN"] = int(GAIN)
        header["CCD-TEMP"] = float(telemetry.temp_c if telemetry and telemetry.temp_c is not None else 22.5)
        header["RA"] = float(ra_deg)
        header["DEC"] = float(dec_deg)
        header["CRVAL1"] = float(ra_deg)
        header["CRVAL2"] = float(dec_deg)
        header["CRPIX1"] = width / 2
        header["CRPIX2"] = height / 2
        header["CDELT1"] = -0.000305
        header["CDELT2"] = 0.000305
        header["CTYPE1"] = "RA---TAN"
        header["CTYPE2"] = "DEC--TAN"

        self._draw_star(array, width / 2, height / 2, amplitude=15000)

        comp_stars = self._build_sim_comp_stars(target)
        for comp in comp_stars:
            x, y = self._pixel_from_world(header, comp["ra"], comp["dec"])
            self._draw_star(array, x, y, amplitude=9000)

        final = np.clip(array, 0, 65535).astype(np.uint16)
        fits.PrimaryHDU(data=final, header=header).writeto(out_path, overwrite=True)
        # Header already stamped above; no legacy side-effect stamp call in simulation.
        self._write_wcs_sidecar(out_path, header)
        self._write_sim_gaia_cache(target, comp_stars)

        step("A8", "Science frame written")
        time.sleep(0.2)

        return FrameResult(success=True, path=out_path, width=width, height=height, elapsed_s=0.2, error="")


class Orchestrator:
    SUN_LIMIT_DEG = -18.0
    LOOP_SLEEP_SEC = 30

    def __init__(self):
        cfg = load_config()
        loc = cfg.get("location", {})
        aavso = cfg.get("aavso", {})
        self._cfg = cfg
        self._fleet_mode = str(cfg.get("planner", {}).get("fleet_mode", "single")).strip().lower()
        self._scope_id = selected_scope_id()
        self._scope = selected_scope(cfg, self._scope_id)
        self._scope_name = self._scope.get("scope_name") or self._scope.get("name") or self._scope_id or "primary"
        self._mission_file = MISSION_FILE
        self._state_file = STATE_FILE
        self._plan_file = PLAN_FILE

        if self._fleet_mode == "split" and self._scope_id:
            scoped_mission = FLEET_PLAN_DIR / f"tonights_plan.{self._scope_id}.json"
            if scoped_mission.exists():
                self._mission_file = scoped_mission
            self._state_file = DATA_DIR / f"system_state.{self._scope_id}.json"
            self._plan_file = FLEET_PLAN_DIR / f"flight_plan.{self._scope_id}.json"

        self._obs = {
            "observer_id": aavso.get("observer_code", "MISSING_ID"),
            "lat": loc.get("lat", 0.0),
            "lon": loc.get("lon", 0.0),
            "elevation": loc.get("elevation", 0.0),
        }

        self._location = EarthLocation(
            lat=self._obs["lat"] * u.deg,
            lon=self._obs["lon"] * u.deg,
            height=self._obs["elevation"] * u.m,
        )

        self._state = PipelineState.IDLE
        self._targets = []
        self._flight_log = []
        self._current_target = None
        self._session_stats = {
            "targets_attempted": 0,
            "targets_completed": 0,
            "exposures_total": 0,
        }

        self._dark_library = DarkLibrary(host=SEESTAR_HOST)
        self._tonights_sequences = set()
        self._last_telemetry = None
        self._planned_target_count = 0
        self._battery_park_pct = int(self._cfg.get("power", {}).get("battery_park_pct", VETO_BATTERY))

        self.simulation_mode = "--simulate" in sys.argv

        self.fsm = SovereignFSM()

        if self.simulation_mode:
            self.fsm.sequence = MockDiamondSequence()
            self.LOOP_SLEEP_SEC = 0
            log.info("🚀 SIMULATION MODE ENGAGED - Hardware checks disabled.")

    def run(self):
        log.info(
            "🔭 Orchestrator starting — SeeVar Federation v2.0.0 (FSM-Governed) | scope=%s | mission=%s",
            self._scope_name,
            self._mission_file.name,
        )
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
                time.sleep(max(1, self.LOOP_SLEEP_SEC * 4))

    def _tick(self):
        if not self.simulation_mode and self._state not in (PipelineState.PARKED, PipelineState.ABORTED):
            if self._enforce_battery_guard():
                return

        if self._state == PipelineState.IDLE:
            self._run_idle()
        elif self._state == PipelineState.PREFLIGHT:
            self._run_preflight()
        elif self._state == PipelineState.PLANNING:
            self._run_planning()
        elif self._state == PipelineState.FLIGHT:
            self._run_flight()
        elif self._state == PipelineState.WAITING:
            self._run_flight()
        elif self._state == PipelineState.POSTFLIGHT:
            self._run_postflight()
        elif self._state == PipelineState.PARKED:
            self._run_parked()
        elif self._state == PipelineState.ABORTED:
            self._run_aborted()

    def _check_weather_veto(self) -> tuple[bool, str]:
        hard_abort = {"RAIN", "FOGGY", "WINDY", "THUNDER"}
        try:
            if not WEATHER_FILE.exists():
                log.warning("weather_state.json not found — proceeding without weather veto")
                return True, "NO_WEATHER_FILE"

            with open(WEATHER_FILE) as f:
                w = json.load(f)

            status = w.get("status", "UNKNOWN")
            icon = w.get("icon", "")
            age_s = time.time() - w.get("last_update", 0)

            if age_s > 21600:
                log.warning("Weather data is %.0fh old — proceeding with caution", age_s / 3600)

            if status in hard_abort:
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
                    time.sleep(max(1, self.LOOP_SLEEP_SEC * 4))
                    return
            self._transition(PipelineState.PREFLIGHT, msg="Night sky confirmed (or forced by Simulation).")
        else:
            time.sleep(max(1, self.LOOP_SLEEP_SEC))

    def _run_preflight(self):
        self._log_flight("🛫 PREFLIGHT sequence initiated.")

        if not self.simulation_mode:
            self._log_flight("[A2] Safety gate — securing zero-state")
            zero = enforce_zero_state()
            if not zero:
                self._log_flight("[A2] ⚠️ zero-state unconfirmed — continuing to session init")
            else:
                self._log_flight("[A2] ✅ zero-state secured")

        self._log_flight("[A3] Session init baseline")
        self._last_telemetry = self.fsm.sequence.init_session(level_ok=True)

        if self._last_telemetry:
            try:
                self._log_flight(f"[A3] Telemetry — {self._last_telemetry.summary()}")
            except Exception:
                pass

        if not self._last_telemetry.is_safe():
            reason = self._last_telemetry.parse_error or self._last_telemetry.veto_reason()
            self._log_flight(f"[A3] 🛑 VETO at preflight: {reason}")
            self._transition(PipelineState.ABORTED, msg=f"Preflight veto: {reason}")
            return

        self._transition(PipelineState.PLANNING, msg="Preflight complete.")

    def _run_planning(self):
        def _extract_targets(payload):
            return payload if isinstance(payload, list) else payload.get("targets", [])

        def _plan_is_stale(payload, now_utc):
            if not isinstance(payload, dict):
                return False
            meta = payload.get("metadata", {})
            planning_end = _parse_plan_dt(meta.get("planning_end_utc"))
            generated = _parse_plan_dt(meta.get("generated"))

            if planning_end and planning_end <= now_utc:
                return True

            if generated and generated.date() != now_utc.date():
                return True

            return False

        def _order_and_filter(mission, now_utc):
            if any("recommended_order" in t for t in mission):
                ordered = sorted(
                    mission,
                    key=lambda t: (
                        int(t.get("recommended_order", 999999)),
                        -float(t.get("efficiency_score", 0.0)),
                        t.get("name", ""),
                    ),
                )
            else:
                ordered = list(mission)

            ready_now = []
            later = []
            expired = 0

            for target in ordered:
                start_dt = _parse_plan_dt(target.get("best_start_utc"))
                end_dt = _parse_plan_dt(target.get("best_end_utc"))

                if end_dt and end_dt <= now_utc:
                    expired += 1
                    continue

                if start_dt and start_dt > now_utc:
                    later.append(target)
                else:
                    ready_now.append(target)

            return ready_now + later, expired

        self._log_flight("📋 Loading mission targets...")
        now_utc = datetime.now(timezone.utc)
        payload = _safe_load_json(self._mission_file, {})
        refreshed = False

        if not payload or _plan_is_stale(payload, now_utc):
            why = "missing" if not payload else "stale"
            self._log_flight(f"♻️ Nightly plan {why} — attempting refresh")
            refreshed = self._refresh_mission_plan()
            if refreshed:
                payload = _safe_load_json(self._mission_file, {})

        mission = _extract_targets(payload)
        if not mission:
            self._transition(PipelineState.PARKED, msg="No mission targets available for current night.")
            return

        final, expired = _order_and_filter(mission, now_utc)

        mission_cfg = self._cfg.get("mission", {}) if isinstance(self._cfg, dict) else {}
        max_targets = mission_cfg.get("max_targets")
        try:
            max_targets = int(max_targets) if max_targets not in (None, "", 0) else 0
        except Exception:
            max_targets = 0
        if max_targets > 0 and len(final) > max_targets:
            self._log_flight(f"✂️ Mission cap active — limiting tonight to first {max_targets} target(s)")
            final = final[:max_targets]

        if not final and not refreshed:
            self._log_flight("♻️ All current target windows expired — refreshing nightly plan once")
            if self._refresh_mission_plan():
                payload = _safe_load_json(self._mission_file, {})
                mission = _extract_targets(payload)
                now_utc = datetime.now(timezone.utc)
                final, expired = _order_and_filter(mission, now_utc)

        if not final:
            reason = "All planned target windows have expired." if expired else "No executable mission targets."
            self._transition(PipelineState.PARKED, msg=reason)
            return

        self._targets = final
        self._planned_target_count = len(final)
        self._write_plan(final)
        self._log_flight(f"✅ Flight plan locked from {self._mission_file.name}: {len(final)} target(s)")
        if expired:
            self._log_flight(f"⏭️ Skipped {expired} expired target window(s)")
        self._transition(PipelineState.FLIGHT, sub=final[0].get("name", "UNKNOWN"), msg="Flight plan locked.")

    def _run_flight(self):
        if not self._targets:
            self._transition(PipelineState.POSTFLIGHT, msg="Target list exhausted.")
            return

        target = self._targets[0]
        name = target.get("name", "UNKNOWN")
        now_utc = datetime.now(timezone.utc)
        start_dt = _parse_plan_dt(target.get("best_start_utc"))
        end_dt = _parse_plan_dt(target.get("best_end_utc"))

        ra_str = target.get("ra")
        dec_str = target.get("dec")
        ra_deg_val = float(ra_str) if isinstance(ra_str, (int, float)) else float(SkyCoord(ra=ra_str, dec=dec_str, unit=(u.hourangle, u.deg)).ra.hour * 15)
        dec_deg_val = float(dec_str) if isinstance(dec_str, (int, float)) else float(SkyCoord(ra=ra_str, dec=dec_str, unit=(u.hourangle, u.deg)).dec.deg)
        ra_hours_val = ra_deg_val / 15.0

        if not self.simulation_mode:
            if end_dt and now_utc >= end_dt:
                self._targets.pop(0)
                self._log_flight(f"⏭️ Skipping {name} — planning window expired.")
                return

            if start_dt and now_utc < start_dt:
                wait_s = int((start_dt - now_utc).total_seconds())
                wait_s = max(1, min(wait_s, max(1, self.LOOP_SLEEP_SEC)))
                open_utc = start_dt.strftime("%H:%M UTC")

                alt_deg = self._target_altitude_deg(ra_deg_val, dec_deg_val)
                if alt_deg is not None and alt_deg < 0.0:
                    reason = f"Waiting for {name} to rise above horizon (alt {alt_deg:.1f}°) until {open_utc}."
                else:
                    reason = f"Waiting for {name} window to open at {open_utc} ({wait_s}s)."

                self._write_state(
                    state="WAITING",
                    sub=name,
                    msg=reason,
                )
                time.sleep(wait_s)
                return
        else:
            self._log_flight(f"[simulation] ignoring real-time window gate for {name}")

        target = self._targets.pop(0)
        name = target.get("name", "UNKNOWN")
        self._log_flight(f"[A1] Target lock — {name}")
        self._log_flight("[A2] Safety gate passed")

        planned_n_frames = target.get("n_frames")

        if target.get("exp_ms") is not None:
            exp_ms = int(target.get("exp_ms"))
            n_frames = max(1, int(planned_n_frames or 1))
        else:
            try:
                exp_plan = plan_exposure(get_target_mag(name), sky_bortle=self._sky_bortle())
                exp_ms = int(exp_plan.exp_ms)
                n_frames = max(1, int(planned_n_frames or getattr(exp_plan, "n_frames", 1)))
            except Exception:
                exp_ms = 5000
                n_frames = max(1, int(planned_n_frames or 1))

        self._log_flight(f"[A9] Exposure plan — exp_ms={exp_ms} n_frames={n_frames}")

        integration_sec = float(target.get("integration_sec")) if target.get("integration_sec") is not None else (float(exp_ms) / 1000.0) * float(n_frames)

        acq_target = AcquisitionTarget(
            name=name,
            ra_hours=ra_hours_val,
            dec_deg=dec_deg_val,
            auid=target.get("auid", ""),
            exp_ms=exp_ms,
            observer_code=self._obs["observer_id"],
            n_frames=n_frames,
            integration_sec=integration_sec,
        )

        self._session_stats["targets_attempted"] += 1
        self._current_target = {
            "name": name,
            "ra": round(ra_deg_val, 4),
            "dec": round(dec_deg_val, 4),
            "type": target.get("type", ""),
            "mag_max": target.get("mag_max"),
            "min_mag": target.get("min_mag"),
            "period_days": target.get("period_days"),
            "auid": target.get("auid", ""),
        }

        done, remaining, planned = self._progress_counts()
        self._write_state(
            state="SLEWING",
            sub=name,
            msg=f"FSM handover: {name} ({done} done / {remaining} left / {planned} planned)",
        )
        self._log_flight(f"Executing target via FSM: {name} RA={acq_target.ra_hours:.2f}h")

        ledger_manager.record_attempt(name)
        success = self.fsm.execute_target(acq_target, telemetry=self._last_telemetry)

        if self.fsm.telemetry:
            self._last_telemetry = self.fsm.telemetry

        if success:
            self._session_stats["targets_completed"] += 1
            self._log_flight("[A12] Commit success to ledger/system state")
            ledger_manager.record_capture(name, fits_path="LOCAL_BUFFER")
            self._log_flight(f"✅ FSM Sequence complete for {name}")
            self._write_state(state="TRACKING", sub=name, msg="Observation complete.")
            used_target = getattr(self.fsm, "last_prepared_target", None) or acq_target
            self._tonights_sequences.add((int(used_target.exp_ms), GAIN))
        else:
            self._log_flight("[A12] Commit failure state")
            self._log_flight(f"❌ FSM Sequence failed for {name}")

    def _summarize_dark_results(self, dark_results: dict) -> tuple[int, int, int]:
        ok = 0
        fail = 0
        frames = 0

        for result in dark_results.values():
            if result.get("status") == "ok":
                ok += 1
            else:
                fail += 1
            try:
                frames += int(result.get("n_frames", 0))
            except Exception:
                pass

        return ok, fail, frames

    def _run_postflight(self):
        self._log_flight("📊 Flight operations concluded.")

        dark_ok = 0
        dark_fail = 0
        dark_frames = 0

        if self._tonights_sequences and not self.simulation_mode:
            seqs = sorted(self._tonights_sequences)
            self._log_flight(f"🌑 Acquiring darks for {len(seqs)} sequence(s): {seqs}")
            self._write_state(
                state="POSTFLIGHT",
                sub="dark_acquisition",
                msg=f"Acquiring darks for {len(seqs)} sequence(s)",
            )

            try:
                dark_results = self._dark_library.acquire_darks(
                    sequences=seqs,
                    telemetry=getattr(self, "_last_telemetry", None),
                )
                dark_ok, dark_fail, dark_frames = self._summarize_dark_results(dark_results)

                for key, res in dark_results.items():
                    status = res.get("status", "unknown")
                    n_frames = res.get("n_frames", 0)
                    master_path = res.get("master_path", "")
                    if master_path:
                        self._log_flight(f"  dark {key}: {status} ({n_frames} frames) -> {Path(master_path).name}")
                    else:
                        self._log_flight(f"  dark {key}: {status} ({n_frames} frames)")

                if dark_ok > 0 and dark_frames > 0 and dark_fail == 0:
                    self._log_flight(
                        f"✅ Dark closure complete: {dark_ok}/{len(seqs)} master(s), {dark_frames} raw dark frame(s)"
                    )
                elif dark_ok == 0 and dark_frames == 0:
                    self._log_flight(
                        f"⚠️ Dark acquisition yielded no usable darks: 0/{len(seqs)} master(s), 0 raw dark frame(s)"
                    )
                else:
                    self._log_flight(
                        f"⚠️ Dark closure partial: ok={dark_ok} fail={dark_fail} total_frames={dark_frames}"
                    )
            except Exception as e:
                dark_fail = len(self._tonights_sequences)
                self._log_flight(f"⚠️ Dark acquisition error: {e}")
        else:
            if self.simulation_mode:
                self._log_flight("  [simulation] dark acquisition skipped")
            else:
                self._log_flight("  no sequences recorded — dark acquisition skipped")

        self._log_flight("🧮 Handing over to Accountant.")
        self._write_state(
            state="POSTFLIGHT",
            sub="accountant",
            msg="Applying dark calibration and stamping ledger",
        )

        if not self.simulation_mode:
            try:
                from core.postflight.accountant import process_buffer
                process_buffer()
                if dark_fail == 0:
                    self._log_flight("✅ Accountant complete — ledger stamped after dark closure.")
                else:
                    self._log_flight("✅ Accountant complete — ledger stamped with honest dark-failure handling.")
            except Exception as e:
                self._log_flight(f"⚠️ Accountant error: {e}")
        else:
            self._log_flight("  [simulation] accountant skipped")

        if dark_ok > 0 and dark_fail == 0:
            final_msg = "Mission complete. Hardware park not confirmed by this state alone."
        elif dark_fail == 0 and dark_frames == 0:
            final_msg = "Mission complete. No usable darks captured. Hardware park not confirmed by this state alone."
        else:
            final_msg = f"Mission complete with partial dark failures ({dark_fail}). Hardware park not confirmed by this state alone."
        self._transition(PipelineState.PARKED, msg=final_msg)

    def _run_parked(self):
        self._current_target = None
        time.sleep(max(1, self.LOOP_SLEEP_SEC))

    def _run_aborted(self):
        self._current_target = None
        time.sleep(max(1, self.LOOP_SLEEP_SEC))

    def _sun_altitude(self) -> float:
        try:
            now = Time.now()
            sun = get_body("sun", now)
            return float(sun.transform_to(AltAz(obstime=now, location=self._location)).alt.deg)
        except Exception:
            return 0.0

    def _load_mission_targets(self) -> list:
        data = _safe_load_json(self._mission_file, [])
        return data if isinstance(data, list) else data.get("targets", [])

    def _refresh_mission_plan(self) -> bool:
        planner = PROJECT_ROOT / "core/preflight/nightly_planner.py"
        compiler = PROJECT_ROOT / "core/preflight/schedule_compiler.py"

        try:
            self._log_flight("♻️ Regenerating tonights_plan.json")
            subprocess.run([sys.executable, str(planner)], cwd=str(PROJECT_ROOT), check=True)
            subprocess.run([sys.executable, str(compiler)], cwd=str(PROJECT_ROOT), check=True)
            if self._fleet_mode == "split" and self._scope_id:
                scoped_mission = FLEET_PLAN_DIR / f"tonights_plan.{self._scope_id}.json"
                if scoped_mission.exists():
                    self._mission_file = scoped_mission
            return True
        except Exception as e:
            self._log_flight(f"⚠️ Nightly plan refresh failed: {e}")
            return False

    def _current_battery_snapshot(self) -> dict:
        if self._scope:
            snapshot = poll_battery_snapshot(self._scope.get("ip"))
            if snapshot:
                return snapshot

        for scope in self._cfg.get("seestars", []):
            snapshot = poll_battery_snapshot(scope.get("ip"))
            if snapshot:
                return snapshot

        tel = getattr(self, "_last_telemetry", None)
        if tel and tel.battery_pct is not None:
            return {
                "battery_pct": int(tel.battery_pct),
                "charge_online": tel.charge_online,
                "charger_status": tel.charger_status,
            }

        return {}

    def _enforce_battery_guard(self) -> bool:
        snapshot = self._current_battery_snapshot()
        battery_pct = snapshot.get("battery_pct", snapshot.get("battery_capacity"))
        if battery_pct in (None, "", "N/A"):
            return False

        try:
            battery_pct = int(float(battery_pct))
        except Exception:
            return False

        if battery_pct > self._battery_park_pct:
            return False

        charger_status = snapshot.get("charger_status") or ("Charging" if snapshot.get("charge_online") else "Discharging")
        self._log_flight(f"🔋 Battery guard triggered at {battery_pct}% ({charger_status})")
        try:
            self.fsm.sequence.park()
            self._log_flight("🔋 Battery guard requested telescope park")
        except Exception as e:
            self._log_flight(f"⚠️ Battery guard park request failed: {e}")

        self._current_target = None
        self._transition(PipelineState.PARKED, msg=f"Battery guard parked telescope at {battery_pct}%.")
        return True

    def _progress_counts(self) -> tuple[int, int, int]:
        done = int(self._session_stats.get("targets_completed", 0))
        current = 1 if self._current_target else 0
        remaining = len(self._targets) + current
        planned = max(self._planned_target_count, done + remaining)
        return done, remaining, planned

    def _target_altitude_deg(self, ra_deg: float, dec_deg: float) -> float | None:
        try:
            now = Time.now()
            coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")
            altaz = coord.transform_to(AltAz(obstime=now, location=self._location))
            return float(altaz.alt.deg)
        except Exception:
            return None

    def _sky_bortle(self) -> float:
        try:
            return float(self._cfg.get("location", {}).get("bortle", 6.0))
        except Exception:
            return 6.0

    def _log_flight(self, message: str):
        stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        line = f"{stamp} {message}"
        self._flight_log.append(line)
        self._flight_log = self._flight_log[-100:]
        log.info(message)

    def _write_plan(self, targets: list):
        payload = {
            "#objective": "Tactical flight plan as locked by orchestrator.",
            "metadata": {
                "generated": datetime.now(timezone.utc).isoformat(),
                "count": len(targets),
                "scope_name": self._scope_name,
                "scope_id": self._scope_id,
            },
            "targets": targets,
        }
        self._plan_file.write_text(json.dumps(payload, indent=2))

    def _write_state(self, state=None, sub="", msg=""):
        now_utc = datetime.now(timezone.utc).isoformat()
        done, remaining, planned = self._progress_counts()
        payload = _safe_load_json(self._state_file, {})
        payload.update({
            "state": state or self._state,
            "scope_name": self._scope_name,
            "scope_id": self._scope_id,
            "sub": sub,
            "substate": sub,
            "msg": msg,
            "message": msg,
            "updated": now_utc,
            "updated_utc": now_utc,
            "current_target": self._current_target,
            "session_stats": self._session_stats,
            "flight_log": self._flight_log[-20:],
            "done_count": done,
            "remaining_count": remaining,
            "planned_count": planned,
        })
        self._state_file.write_text(json.dumps(payload, indent=2))

    def _transition(self, new_state, sub="", msg=""):
        self._state = new_state
        self._write_state(state=new_state, sub=sub, msg=msg)
        log.info("STATE -> %s | %s", new_state, msg)


if __name__ == "__main__":
    Orchestrator().run()
