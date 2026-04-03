#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/orchestrator.py
Version: 1.8.2
Objective: Autonomous night daemon consuming tonights_plan.json as the canonical mission order, logging A1-A12, and executing targets via SovereignFSM.
"""

import json
import logging
import math
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

from core.utils.env_loader import DATA_DIR, load_config
from core.flight.pilot import (
    AcquisitionTarget,
    SEESTAR_HOST,
    GAIN,
    TelemetryBlock,
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
    IDLE, PREFLIGHT, PLANNING, FLIGHT, POSTFLIGHT, ABORTED, PARKED = (
        "IDLE", "PREFLIGHT", "PLANNING", "FLIGHT", "POSTFLIGHT", "ABORTED", "PARKED"
    )


class MockDiamondSequence:
    """Mock hardware sequence for the Full Mission Simulator."""

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

    def acquire(self, target: AcquisitionTarget, status_cb=None, telemetry: Optional[TelemetryBlock] = None) -> FrameResult:
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

        step("A8", "Corrective nudge not required")
        time.sleep(0.2)

        header = sovereign_stamp(target, utc_obs, width, height)

        comp_stars = self._build_sim_comp_stars(target)

        # Draw target at the commanded center.
        target_ra_deg = target.ra_hours * 15.0
        target_px, target_py = self._pixel_from_world(header, target_ra_deg, target.dec_deg)
        self._draw_star(array, target_px, target_py, amplitude=28000, sigma=2.4)

        # Draw synthetic comparison stars aligned to a fake Gaia cache.
        for idx, comp in enumerate(comp_stars, start=1):
            px, py = self._pixel_from_world(header, comp["ra"], comp["dec"])
            amplitude = 18000 - idx * 1500
            self._draw_star(array, px, py, amplitude=max(7000, amplitude), sigma=2.1)

        # Add a few nuisance stars so the frame looks less empty.
        nuisance = [
            (target_ra_deg + 0.18, target.dec_deg - 0.11, 9000),
            (target_ra_deg - 0.22, target.dec_deg + 0.09, 7500),
            (target_ra_deg + 0.05, target.dec_deg + 0.16, 6000),
        ]
        for ra_deg, dec_deg, amp in nuisance:
            px, py = self._pixel_from_world(header, ra_deg, dec_deg)
            self._draw_star(array, px, py, amplitude=amp, sigma=1.8)

        step("A10", f"Simulating {target.exp_ms}ms exposure for {target.name}")
        time.sleep(1.0)

        final = np.clip(array, 0, 65535).astype(np.uint16)
        write_fits(final, header, out_path)
        self._write_wcs_sidecar(out_path, header)
        self._write_sim_gaia_cache(target, comp_stars)

        step("A11", f"Frame quality gate passed — FITS saved to {out_path}")
        step("A11", "Synthetic WCS sidecar and Gaia cache written for postflight")
        return FrameResult(success=True, path=out_path, width=width, height=height, elapsed_s=2.5)


class Orchestrator:
    SUN_LIMIT_DEG = -18.0
    LOOP_SLEEP_SEC = 30

    def __init__(self):
        cfg = load_config()
        loc = cfg.get("location", {})
        aavso = cfg.get("aavso", {})
        self._cfg = cfg

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

        self.simulation_mode = "--simulate" in sys.argv

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
                time.sleep(max(1, self.LOOP_SLEEP_SEC * 4))

    def _tick(self):
        if self._state == PipelineState.IDLE:
            self._run_idle()
        elif self._state == PipelineState.PREFLIGHT:
            self._run_preflight()
        elif self._state == PipelineState.PLANNING:
            self._run_planning()
        elif self._state == PipelineState.FLIGHT:
            self._run_flight()
        elif self._state == PipelineState.POSTFLIGHT:
            self._run_postflight()
        elif self._state == PipelineState.PARKED:
            self._run_parked()
        elif self._state == PipelineState.ABORTED:
            self._run_aborted()

    def _check_weather_veto(self) -> tuple[bool, str]:
        hard_abort = {"RAIN", "FOGGY", "CLOUDY", "WINDY"}
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
                self._log_flight("[A2] ❌ zero-state failed — aborting")
                self._transition(PipelineState.ABORTED, msg="Hardware zero-state not secured")
                return
            self._log_flight("[A2] ✅ zero-state secured")

        self._log_flight("[A3] Session init baseline")
        self._last_telemetry = self.fsm.sequence.init_session(level_ok=True)

        if not self._last_telemetry.is_safe():
            reason = self._last_telemetry.veto_reason()
            self._log_flight(f"[A3] 🛑 VETO at preflight: {reason}")
            self._transition(PipelineState.ABORTED, msg=f"Preflight veto: {reason}")
            return

        self._transition(PipelineState.PLANNING, msg="Preflight complete.")

    def _run_planning(self):
        self._log_flight("📋 Loading mission targets...")
        mission = self._load_mission_targets()
        if not mission:
            self._transition(PipelineState.ABORTED, msg="No mission targets available.")
            return

        now_utc = datetime.now(timezone.utc)

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

        final = ready_now + later

        if not final:
            reason = "All planned target windows have expired." if expired else "No executable mission targets."
            self._transition(PipelineState.ABORTED, msg=reason)
            return

        self._targets = final
        self._write_plan(final)
        self._log_flight(f"✅ Flight plan locked from tonights_plan.json: {len(final)} target(s)")
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

        if not self.simulation_mode:
            if end_dt and now_utc >= end_dt:
                self._targets.pop(0)
                self._log_flight(f"⏭️ Skipping {name} — planning window expired.")
                return

            if start_dt and now_utc < start_dt:
                wait_s = int((start_dt - now_utc).total_seconds())
                wait_s = max(1, min(wait_s, max(1, self.LOOP_SLEEP_SEC)))
                self._write_state(state="WAITING", sub=name, msg="Waiting for observing window to open.")
                time.sleep(wait_s)
                return
        else:
            self._log_flight(f"[simulation] ignoring real-time window gate for {name}")

        target = self._targets.pop(0)
        name = target.get("name", "UNKNOWN")
        self._log_flight(f"[A1] Target lock — {name}")
        self._log_flight("[A2] Safety gate passed")

        ra_str = target.get("ra")
        dec_str = target.get("dec")

        ra_deg_val = float(ra_str) if isinstance(ra_str, (int, float)) else float(SkyCoord(ra=ra_str, dec=dec_str, unit=(u.hourangle, u.deg)).ra.hour * 15)
        dec_deg_val = float(dec_str) if isinstance(dec_str, (int, float)) else float(SkyCoord(ra=ra_str, dec=dec_str, unit=(u.hourangle, u.deg)).dec.deg)
        ra_hours_val = ra_deg_val / 15.0

        if target.get("exp_ms") is not None:
            exp_ms = int(target.get("exp_ms"))
        else:
            try:
                exp_plan = plan_exposure(get_target_mag(name), sky_bortle=self._sky_bortle())
                exp_ms = exp_plan.exp_ms
            except Exception:
                exp_ms = 5000

        self._log_flight(f"[A9] Exposure plan — exp_ms={exp_ms}")

        acq_target = AcquisitionTarget(
            name=name,
            ra_hours=ra_hours_val,
            dec_deg=dec_deg_val,
            auid=target.get("auid", ""),
            exp_ms=exp_ms,
            observer_code=self._obs["observer_id"],
            n_frames=1,
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

        self._write_state(state="SLEWING", sub=name, msg=f"FSM Handing over: {name}")
        self._log_flight(f"Executing target via FSM: {name} RA={acq_target.ra_hours:.2f}h")

        ledger_manager.record_attempt(name)
        success = self.fsm.execute_target(acq_target)

        if self.fsm.telemetry:
            self._last_telemetry = self.fsm.telemetry

        if success:
            self._session_stats["targets_completed"] += 1
            self._log_flight("[A12] Commit success to ledger/system state")
            ledger_manager.record_success(name, fits_path="LOCAL_BUFFER")
            self._log_flight(f"✅ FSM Sequence complete for {name}")
            self._write_state(state="TRACKING", sub=name, msg="Observation complete.")
            self._tonights_sequences.add((acq_target.exp_ms, GAIN))
        else:
            self._log_flight("[A12] Commit failure state")
            self._log_flight(f"❌ FSM Sequence failed for {name}")

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
        data = _safe_load_json(MISSION_FILE, [])
        return data if isinstance(data, list) else data.get("targets", [])

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
        plan = _safe_load_json(PLAN_FILE, {})
        if isinstance(plan, dict):
            plan["targets"] = targets
            meta = plan.setdefault("metadata", {})
            meta["flight_target_count"] = len(targets)
            with open(PLAN_FILE, "w") as f:
                json.dump(plan, f, indent=4)

    def _write_state(self, state: Optional[str] = None, sub: str = "", msg: str = ""):
        payload = {
            "state": state or self._state,
            "sub": sub,
            "msg": msg,
            "current_target": self._current_target,
            "flight_log": self._flight_log[-20:],
            "session_stats": self._session_stats,
            "updated": datetime.now(timezone.utc).isoformat(),
        }

        if self._last_telemetry is not None:
            payload["telemetry"] = {
                "battery_pct": self._last_telemetry.battery_pct,
                "temp_c": self._last_telemetry.temp_c,
                "tracking": self._last_telemetry.tracking,
                "at_park": self._last_telemetry.at_park,
                "ra_hours": self._last_telemetry.ra_hours,
                "dec_deg": self._last_telemetry.dec_deg,
                "altitude": self._last_telemetry.altitude,
                "azimuth": self._last_telemetry.azimuth,
                "device_name": self._last_telemetry.device_name,
                "alpaca_version": self._last_telemetry.alpaca_version,
                "level_ok": self._last_telemetry.level_ok,
                "parse_error": self._last_telemetry.parse_error,
            }

        with open(STATE_FILE, "w") as f:
            json.dump(payload, f, indent=4)

    def _transition(self, new_state: str, sub: str = "", msg: str = ""):
        log.info("STATE: %s → %s", self._state, new_state)
        self._state = new_state
        self._write_state(state=new_state, sub=sub, msg=msg)


if __name__ == "__main__":
    Orchestrator().run()
