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
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body
from astropy.io import fits
from astropy.time import Time

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.env_loader import DATA_DIR, effective_fleet_mode, load_config, selected_scope, selected_scope_id, scope_file_tag
from core.flight.pilot import (
    AcquisitionTarget,
    DiamondSequence,
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

try:
    from core.preflight.horizon import required_altitude
except Exception:
    def required_altitude(az: float, clearance_margin_deg: float = 0.0) -> float:
        return 15.0 + max(0.0, float(clearance_margin_deg))

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_SCOPE = selected_scope(load_config(), selected_scope_id())
_LOG_SCOPE_ID = _LOG_SCOPE.get("scope_id")
_LOG_SCOPE_TAG = scope_file_tag(_LOG_SCOPE)
_LOG_FILE = LOG_DIR / (f"orchestrator.{_LOG_SCOPE_ID}.log" if _LOG_SCOPE_ID else "orchestrator.log")
_LOG_MAX_BYTES = 5 * 1024 * 1024
_LOG_BACKUP_COUNT = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            _LOG_FILE,
            mode="a",
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
        ),
    ],
    force=True,
)
log = logging.getLogger("seevar.orchestrator")

PLAN_FILE = DATA_DIR / "tonights_plan.json"
STATE_FILE = DATA_DIR / "system_state.json"
WEATHER_FILE = DATA_DIR / "weather_state.json"
MISSION_FILE = DATA_DIR / "tonights_plan.json"
FLEET_PLAN_DIR = DATA_DIR / "fleet_plans"
COMMAND_FILE = DATA_DIR / "operator_command.json"
CATALOG_DIR = PROJECT_ROOT / "catalogs"


def _safe_load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log.warning("Failed to load JSON from %s: %s", path, exc)
        return default


def _parse_plan_dt(value: Any) -> datetime | None:
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
    ALL = {IDLE, PREFLIGHT, PLANNING, FLIGHT, WAITING, POSTFLIGHT, ABORTED, PARKED}


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

    def acquire(
        self,
        target: AcquisitionTarget,
        status_cb=None,
        telemetry: Optional[TelemetryBlock] = None,
        skip_pointing=False,
        abort_callback=None,
    ) -> FrameResult:
        def step(tag, msg):
            log.info("  [%s] SIM %s", tag, msg)
            if status_cb:
                status_cb(f"[{tag}] {msg}")

        def abort_requested() -> bool:
            return bool(abort_callback and abort_callback())

        width, height = 2160, 3840
        array = np.random.normal(300.0, 12.0, (height, width)).astype(np.float64)

        utc_obs = datetime.now(timezone.utc)
        local_buffer = DATA_DIR / "local_buffer"
        local_buffer.mkdir(parents=True, exist_ok=True)

        safe_name = target.name.replace(" ", "_").replace("/", "-")
        timestamp = utc_obs.strftime("%Y%m%dT%H%M%S")
        out_path = local_buffer / f"SIM_{safe_name}_{_LOG_SCOPE_TAG}_{timestamp}_Raw.fits"

        step("A4", f"Slew command to {target.name}")
        time.sleep(0.2)
        if abort_requested():
            return FrameResult(success=False, error="operator_abort")

        step("A5", "Slew verify complete")
        time.sleep(0.2)
        if abort_requested():
            return FrameResult(success=False, error="operator_abort")

        step("A6", "Settle complete")
        time.sleep(0.2)
        if abort_requested():
            return FrameResult(success=False, error="operator_abort")

        step("A7", "Pointing verify placeholder")
        time.sleep(0.2)
        if abort_requested():
            return FrameResult(success=False, error="operator_abort")

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
    COMMAND_MAX_AGE_SEC = 300
    SUN_CACHE_TTL_SEC = 20.0

    def __init__(self):
        cfg = load_config()
        loc = cfg.get("location", {})
        aavso = cfg.get("aavso", {})
        self._cfg = cfg
        self._fleet_mode = effective_fleet_mode(cfg)
        self._scope_id = selected_scope_id()
        self._scope = selected_scope(cfg, self._scope_id)
        self._scope_name = self._scope.get("scope_name") or self._scope.get("name") or self._scope_id or "primary"
        self._scope_host = str(self._scope.get("host") or self._scope.get("ip") or SEESTAR_HOST).strip() or SEESTAR_HOST
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

        self._dark_library = DarkLibrary(host=self._scope_host)
        self._tonights_sequences = set()
        self._last_telemetry = None
        self._planned_target_count = 0
        self._last_command_utc = ""
        self._battery_park_pct = int(self._cfg.get("power", {}).get("battery_park_pct", VETO_BATTERY))
        self._sun_limit_deg = self._configured_sun_limit_deg()
        self._sun_cache_alt = 0.0
        self._sun_cache_monotonic = 0.0
        self._prealign_done = False

        self.simulation_mode = "--simulate" in sys.argv

        self.fsm = SovereignFSM()
        self.fsm.sequence = DiamondSequence(host=self._scope_host)

        if self.simulation_mode:
            self.fsm.sequence = MockDiamondSequence()
            self.LOOP_SLEEP_SEC = 0
            log.info("🚀 SIMULATION MODE ENGAGED - Hardware checks disabled.")

        self._state_handlers: dict[str, Callable[[], None]] = {
            PipelineState.IDLE: self._run_idle,
            PipelineState.PREFLIGHT: self._run_preflight,
            PipelineState.PLANNING: self._run_planning,
            PipelineState.FLIGHT: self._run_flight,
            PipelineState.WAITING: self._run_flight,
            PipelineState.POSTFLIGHT: self._run_postflight,
            PipelineState.PARKED: self._run_parked,
            PipelineState.ABORTED: self._run_aborted,
        }

    def _reload_runtime_config(self) -> None:
        """Refresh config.toml-backed runtime settings before night gates."""
        cfg = load_config()
        old_host = self._scope_host
        self._cfg = cfg
        self._fleet_mode = effective_fleet_mode(cfg)
        self._scope = selected_scope(cfg, self._scope_id)
        self._scope_name = self._scope.get("scope_name") or self._scope.get("name") or self._scope_id or "primary"
        self._scope_host = str(self._scope.get("host") or self._scope.get("ip") or SEESTAR_HOST).strip() or SEESTAR_HOST
        self._battery_park_pct = int(self._cfg.get("power", {}).get("battery_park_pct", VETO_BATTERY))
        self._sun_limit_deg = self._configured_sun_limit_deg()

        loc = self._cfg.get("location", {})
        self._obs.update({
            "lat": loc.get("lat", self._obs["lat"]),
            "lon": loc.get("lon", self._obs["lon"]),
            "elevation": loc.get("elevation", self._obs["elevation"]),
        })
        self._location = EarthLocation(
            lat=self._obs["lat"] * u.deg,
            lon=self._obs["lon"] * u.deg,
            height=self._obs["elevation"] * u.m,
        )

        if old_host != self._scope_host and not self.simulation_mode:
            self._dark_library = DarkLibrary(host=self._scope_host)
            self.fsm.sequence = DiamondSequence(host=self._scope_host)
            self._log_flight(f"Runtime config reloaded: scope endpoint {old_host} -> {self._scope_host}")

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
        if self._handle_operator_command():
            return

        battery_guard_active = (
            not self.simulation_mode
            and self._state not in (PipelineState.PARKED, PipelineState.ABORTED)
            and (self._state != PipelineState.IDLE or self._sun_altitude() < self._sun_limit_deg)
        )
        if battery_guard_active:
            if self._enforce_battery_guard():
                return

        handler = self._state_handlers.get(self._state)
        if handler is None:
            self._transition(PipelineState.ABORTED, msg=f"Invalid orchestrator state: {self._state}")
            return
        handler()

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
            safe_to_open = w.get("safe_to_open", w.get("imaging_go"))

            if age_s > 21600:
                log.warning("Weather data is %.0fh old — proceeding with caution", age_s / 3600)

            if safe_to_open is False:
                reason = (
                    f"Weather veto: {status} {icon} — "
                    f"{w.get('current_reason') or 'conditions outside configured limits'} "
                    f"KNMI oktas:{w.get('knmi_oktas','?')} "
                    f"clouds:{w.get('clouds_pct','?')}% "
                    f"window:{w.get('imaging_window_start','none')}→{w.get('imaging_window_end','none')}"
                )
                return False, reason

            if status in hard_abort:
                reason = (
                    f"Weather veto: {status} {icon} — "
                    f"KNMI oktas:{w.get('knmi_oktas','?')} "
                    f"clouds:{w.get('clouds_pct','?')}% "
                    f"window:{w.get('dark_start','?')}→{w.get('dark_end','?')}"
                )
                return False, reason

            log.info("Weather GO: %s %s (age: %.0fmin)", status, icon, age_s / 60)
            return True, status

        except Exception as e:
            log.warning("Weather veto check failed: %s — proceeding", e)
            return True, "WEATHER_CHECK_ERROR"

    def _run_idle(self):
        self._reload_runtime_config()
        sun_alt = self._sun_altitude()
        msg = f"Sun at {sun_alt:.1f}°. Waiting for night (<{self._sun_limit_deg}°)."
        self._write_state(sub="Standing by", msg=msg)

        if self.simulation_mode or sun_alt < self._sun_limit_deg:
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

        now_utc = datetime.now(timezone.utc)
        payload = _safe_load_json(self._mission_file, {})
        if not payload or self._plan_is_stale(payload, now_utc):
            why = "missing" if not payload else "stale"
            self._log_flight(f"🛑 Nightly plan {why} before hardware init — planner timer must refresh it")
            self._transition(PipelineState.ABORTED, msg=f"Nightly plan {why}; run seevar-planner.service")
            return

        if not self.simulation_mode:
            self._log_flight("[A2] Safety gate — securing zero-state")
            zero = enforce_zero_state(host=self._scope_host)
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

        if not self.simulation_mode and not self._run_prealign_if_configured():
            return

        self._transition(PipelineState.PLANNING, msg="Preflight complete.")

    def _run_prealign_if_configured(self) -> bool:
        flight_cfg = self._cfg.get("flight", {}) if isinstance(self._cfg, dict) else {}
        if not bool(flight_cfg.get("prealign_before_flight", False)):
            return True
        if self._prealign_done:
            return True

        points = int(flight_cfg.get("prealign_points", 3))
        exposure_sec = float(flight_cfg.get("prealign_exposure_sec", 5.0))
        timeout_sec = int(flight_cfg.get("prealign_timeout_sec", 600))
        required = bool(flight_cfg.get("prealign_required", True))
        allow_partial = bool(flight_cfg.get("prealign_allow_partial", False))
        wide_fallback = bool(flight_cfg.get("prealign_wide_fallback", True))

        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "dev/tools/telescope/prealign_pointing.py"),
            "--points",
            str(points),
            "--exposure-sec",
            str(exposure_sec),
            "--min-alt",
            str(float(flight_cfg.get("prealign_min_alt", 35.0))),
            "--max-alt",
            str(float(flight_cfg.get("prealign_max_alt", 82.0))),
            "--solve-radius-deg",
            str(float(flight_cfg.get("prealign_solve_radius_deg", 20.0))),
            "--solve-timeout-sec",
            str(int(flight_cfg.get("prealign_solve_timeout_sec", 90))),
            "--solve-downsample",
            str(int(flight_cfg.get("prealign_solve_downsample", 2))),
            "--wide-exposure-sec",
            str(float(flight_cfg.get("prealign_wide_exposure_sec", exposure_sec))),
            "--wide-gain",
            str(int(flight_cfg.get("prealign_wide_gain", 0))),
            "--wide-solve-radius-deg",
            str(float(flight_cfg.get("prealign_wide_solve_radius_deg", 60.0))),
            "--ip",
            self._scope_host,
            "--state-file",
            str(self._state_file),
        ]
        if allow_partial:
            cmd.append("--allow-partial")
        if not wide_fallback:
            cmd.append("--no-wide-fallback")

        wide_text = "wide fallback on" if wide_fallback else "wide fallback off"
        self._log_flight(f"[A3] Pre-align start — {points} point(s), {exposure_sec:.1f}s, {wide_text}")
        try:
            result = subprocess.run(
                cmd,
                cwd=str(PROJECT_ROOT),
                text=True,
                capture_output=True,
                timeout=timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired:
            msg = f"Pre-align timeout after {timeout_sec}s"
            self._log_flight(f"[A3] ⚠️ {msg}")
            if required:
                self._transition(
                    PipelineState.ABORTED,
                    sub="ALIGNMENT FAILED",
                    msg=f"{msg}; science run blocked.",
                )
                return False
            return True

        output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
        for line in output.splitlines()[-8:]:
            self._log_flight(f"[A3] prealign: {line}")

        if result.returncode != 0:
            msg = f"Pre-align failed rc={result.returncode}"
            self._log_flight(f"[A3] ⚠️ {msg}")
            if required:
                self._transition(
                    PipelineState.ABORTED,
                    sub="ALIGNMENT FAILED",
                    msg=f"{msg}; science run blocked.",
                )
                return False
            return True

        self._prealign_done = True
        self._log_flight("[A3] ✅ Pre-align model ready")
        return True

    def _run_planning(self):
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

        if not payload or self._plan_is_stale(payload, now_utc):
            why = "missing" if not payload else "stale"
            self._log_flight(f"🛑 Nightly plan {why} — refusing in-session refresh")
            self._transition(PipelineState.ABORTED, msg=f"Nightly plan {why}; run seevar-planner.service")
            return

        mission = self._extract_targets(payload)
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
                exp_plan = plan_exposure(
                    get_target_mag(name),
                    sky_bortle=self._sky_bortle(),
                    mount_mode=self._mount_mode(),
                )
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
        success = self.fsm.execute_target(
            acq_target,
            telemetry=self._last_telemetry,
            abort_cb=self._operator_abort_pending,
        )

        if self._operator_abort_pending():
            self._handle_operator_command()
            return

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

    # Count dark acquisition results for the postflight state message.
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

    # Inspect staged science FITS and derive the dark sequences postflight must cover.
    def _collect_buffer_dark_sequences(self) -> set[tuple[int, int]]:
        sequences: set[tuple[int, int]] = set()
        for path in DATA_DIR.joinpath("local_buffer").glob("*_Raw.fits"):
            try:
                header = fits.getheader(path)
            except Exception as e:
                self._log_flight(f"  dark-sequence scan skipped {path.name}: header unreadable ({e})")
                continue

            exp_ms = header.get("EXPMS")
            if exp_ms is None:
                exptime = header.get("EXPTIME")
                if exptime is not None:
                    exp_ms = int(round(float(exptime) * 1000.0))

            gain = header.get("GAIN", GAIN)
            if exp_ms is None:
                self._log_flight(f"  dark-sequence scan skipped {path.name}: EXPMS/EXPTIME missing")
                continue

            try:
                sequences.add((int(exp_ms), int(gain)))
            except Exception as e:
                self._log_flight(f"  dark-sequence scan skipped {path.name}: invalid exp/gain ({e})")

        return sequences

    def _enabled_secondary_catalogs(self) -> list[str]:
        planner_cfg = self._cfg.get("planner", {}) if isinstance(self._cfg, dict) else {}
        value = planner_cfg.get("secondary_catalogs", [])
        if isinstance(value, str):
            value = [part.strip() for part in value.split(",")]
        if not isinstance(value, list):
            return []
        return [str(item).strip().lower() for item in value if str(item).strip()]

    def _secondary_output_dir(self) -> Path:
        planner_cfg = self._cfg.get("planner", {}) if isinstance(self._cfg, dict) else {}
        storage_cfg = self._cfg.get("storage", {}) if isinstance(self._cfg, dict) else {}
        configured = str(planner_cfg.get("secondary_output_dir") or "").strip()
        if configured:
            return Path(configured).expanduser()
        primary = Path(str(storage_cfg.get("primary_dir") or DATA_DIR / "archive")).expanduser()
        return primary / "secondary_catalogs"

    def _load_secondary_imaging_targets(self) -> list[dict]:
        planner_cfg = self._cfg.get("planner", {}) if isinstance(self._cfg, dict) else {}
        max_targets = int(planner_cfg.get("secondary_max_targets", 0) or 0)
        default_duration = int(planner_cfg.get("secondary_duration_sec", 900) or 900)
        targets: list[dict] = []

        for catalog in self._enabled_secondary_catalogs():
            path = CATALOG_DIR / f"{catalog}.json"
            if not path.exists():
                self._log_flight(f"🌌 Secondary catalog missing: {path.name}")
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                rows = payload.get("targets", []) if isinstance(payload, dict) else payload
            except Exception as e:
                self._log_flight(f"🌌 Secondary catalog skipped {catalog}: {e}")
                continue

            for row in rows:
                if not isinstance(row, dict):
                    continue
                item = dict(row)
                item["catalog"] = catalog
                item["secondary_target"] = True
                item.setdefault("duration", default_duration)
                targets.append(item)
                if max_targets > 0 and len(targets) >= max_targets:
                    return targets

        return targets

    def _target_altaz_deg(self, ra_deg: float, dec_deg: float) -> tuple[float, float] | None:
        try:
            now = Time.now()
            coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")
            altaz = coord.transform_to(AltAz(obstime=now, location=self._location))
            return float(altaz.alt.deg), float(altaz.az.deg)
        except Exception:
            return None

    def _secondary_target_visible(self, target: dict) -> bool:
        try:
            ra = target.get("ra")
            dec = target.get("dec")
            ra_deg = float(ra) if isinstance(ra, (int, float)) else float(SkyCoord(ra=ra, dec=dec, unit=(u.hourangle, u.deg)).ra.deg)
            dec_deg = float(dec) if isinstance(dec, (int, float)) else float(SkyCoord(ra=ra, dec=dec, unit=(u.hourangle, u.deg)).dec.deg)
            altaz = self._target_altaz_deg(ra_deg, dec_deg)
            if not altaz:
                return False
            alt_deg, az_deg = altaz
            return alt_deg >= required_altitude(az_deg, clearance_margin_deg=5.0)
        except Exception:
            return False

    def _mirror_secondary_frames(self, catalog: str, name: str, paths: list[Path]) -> int:
        if not paths:
            return 0
        safe_catalog = str(catalog or "secondary").replace("/", "-")
        safe_name = str(name or "UNKNOWN").replace("/", "-").replace(" ", "_")
        dest = self._secondary_output_dir() / safe_catalog / safe_name
        dest.mkdir(parents=True, exist_ok=True)
        copied = 0
        for src in paths:
            try:
                if not src.exists():
                    continue
                shutil.move(str(src), str(dest / src.name))
                copied += 1
            except Exception as e:
                self._log_flight(f"🌌 Secondary frame custody failed for {src.name}: {e}")
        return copied

    def _run_secondary_imaging(self) -> None:
        planner_cfg = self._cfg.get("planner", {}) if isinstance(self._cfg, dict) else {}
        if not bool(planner_cfg.get("secondary_after_photometry", False)):
            return

        targets = self._load_secondary_imaging_targets()
        if not targets:
            return

        self._log_flight(f"🌌 Secondary imaging queue ready: {len(targets)} target(s)")
        for target in targets:
            if self._operator_abort_pending():
                self._handle_operator_command()
                return
            if self._sun_altitude() >= self._sun_limit_deg:
                self._log_flight("🌌 Secondary imaging stopped: daylight limit reached")
                return
            go, reason = self._check_weather_veto()
            if not go:
                self._log_flight(f"🌌 Secondary imaging stopped: {reason}")
                return
            if self._enforce_battery_guard():
                return
            if not self._secondary_target_visible(target):
                continue

            name = target.get("name", "UNKNOWN")
            catalog = target.get("catalog", "secondary")
            try:
                ra = target.get("ra")
                dec = target.get("dec")
                ra_deg = float(ra) if isinstance(ra, (int, float)) else float(SkyCoord(ra=ra, dec=dec, unit=(u.hourangle, u.deg)).ra.deg)
                dec_deg = float(dec) if isinstance(dec, (int, float)) else float(SkyCoord(ra=ra, dec=dec, unit=(u.hourangle, u.deg)).dec.deg)
                duration = max(1, int(float(target.get("duration", planner_cfg.get("secondary_duration_sec", 900)))))
                exp_ms = max(1000, int(target.get("exp_ms", 30000)))
                n_frames = max(1, int(round(duration / (exp_ms / 1000.0))))
            except Exception as e:
                self._log_flight(f"🌌 Secondary target skipped {name}: {e}")
                continue

            acq_target = AcquisitionTarget(
                name=name,
                ra_hours=ra_deg / 15.0,
                dec_deg=dec_deg,
                exp_ms=exp_ms,
                observer_code=self._obs["observer_id"],
                n_frames=n_frames,
                integration_sec=duration,
            )
            self._current_target = {"name": name, "ra": round(ra_deg, 4), "dec": round(dec_deg, 4), "type": catalog}
            self._write_state(state="SECONDARY", sub=name, msg=f"Secondary imaging: {catalog}")
            self._log_flight(f"🌌 Secondary target — {catalog}:{name} exp_ms={exp_ms} n={n_frames}")

            ok = self.fsm.execute_target(
                acq_target,
                telemetry=self._last_telemetry,
                abort_cb=self._operator_abort_pending,
            )
            paths = list(getattr(self.fsm, "last_frame_paths", []))
            copied = self._mirror_secondary_frames(catalog, name, paths)
            if ok:
                self._log_flight(f"🌌 Secondary complete — {name}, moved={copied}")
            else:
                self._log_flight(f"🌌 Secondary failed — {name}, moved={copied}")

    # Close the flight by acquiring matching darks and handing frames to the accountant.
    def _run_postflight(self):
        self._log_flight("📊 Flight operations concluded.")

        dark_ok = 0
        dark_fail = 0
        dark_frames = 0

        disk_sequences = self._collect_buffer_dark_sequences()
        if disk_sequences - self._tonights_sequences:
            self._log_flight(f"🌑 Dark sequence scan added {sorted(disk_sequences - self._tonights_sequences)} from local_buffer")

        required_sequences = set(self._tonights_sequences) | disk_sequences

        if required_sequences and not self.simulation_mode:
            seqs = sorted(required_sequences)
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

        if not self.simulation_mode:
            try:
                from core.postflight.report_pipeline import run_postflight_report_pipeline

                report_result = run_postflight_report_pipeline()
                outputs = report_result.get("outputs") or []
                mirrored = report_result.get("mirrored") or []
                if report_result.get("staged"):
                    self._log_flight(f"📨 Reports staged: {len(outputs)} file(s), mirrored={len(mirrored)}")
                else:
                    self._log_flight(f"📨 Reports not staged: {report_result.get('skipped', 'already handled')}")

                submit = report_result.get("aavso_submit") or {}
                if submit.get("accepted"):
                    self._log_flight(f"📨 AAVSO auto-submit accepted: {Path(report_result.get('aavso_report', '')).name}")
                elif submit.get("skipped"):
                    self._log_flight(f"📨 AAVSO auto-submit skipped: {submit.get('skipped')}")
                elif submit:
                    reason = submit.get("error") or submit.get("error_lines") or "not accepted"
                    self._log_flight(f"⚠️ AAVSO auto-submit not accepted: {reason}")
            except Exception as e:
                self._log_flight(f"⚠️ Report staging/submission error: {e}")
        else:
            self._log_flight("  [simulation] report staging/submission skipped")

        if not self.simulation_mode:
            self._run_secondary_imaging()
        else:
            self._log_flight("  [simulation] secondary imaging skipped")

        postflight_cfg = self._cfg.get("postflight", {}) if isinstance(self._cfg, dict) else {}
        auto_park = bool(postflight_cfg.get("auto_park", True))
        auto_shutdown = bool(postflight_cfg.get("auto_shutdown_scope", False))

        hardware_park_msg = "Hardware park not requested by postflight."
        if not self.simulation_mode and auto_park:
            try:
                self._log_flight("🅿️ Postflight requesting telescope park.")
                self._call_with_retries("postflight park request", self.fsm.sequence.park)
                deadline = time.monotonic() + 30.0
                while time.monotonic() < deadline:
                    try:
                        if self.fsm.sequence.at_park():
                            break
                    except Exception:
                        break
                    time.sleep(2.0)
                hardware_park_msg = "Hardware park requested after postflight."
                self._log_flight("🅿️ Postflight telescope park requested.")
            except Exception as e:
                hardware_park_msg = f"Hardware park request failed: {e}"
                self._log_flight(f"⚠️ Postflight park request failed: {e}")
        elif not self.simulation_mode:
            self._log_flight("🅿️ Postflight telescope park skipped by config.")

        if not self.simulation_mode and auto_shutdown:
            try:
                self._log_flight("🔌 Postflight requesting Seestar shutdown.")
                self._call_with_retries("postflight shutdown request", self.fsm.sequence.shutdown_scope)
                hardware_park_msg += " Scope shutdown requested."
                self._log_flight("🔌 Postflight Seestar shutdown requested.")
            except Exception as e:
                hardware_park_msg += f" Scope shutdown request failed: {e}"
                self._log_flight(f"⚠️ Postflight shutdown request failed: {e}")

        if dark_ok > 0 and dark_fail == 0:
            final_msg = f"Mission complete. {hardware_park_msg}"
        elif dark_fail == 0 and dark_frames == 0:
            final_msg = f"Mission complete. No usable darks captured. {hardware_park_msg}"
        else:
            final_msg = f"Mission complete with partial dark failures ({dark_fail}). {hardware_park_msg}"
        self._transition(PipelineState.PARKED, msg=final_msg)

    def _run_parked(self):
        self._current_target = None
        sun_alt = self._sun_altitude()
        if not self.simulation_mode and sun_alt >= self._sun_limit_deg:
            self._targets = []
            self._planned_target_count = 0
            self._tonights_sequences.clear()
            self._session_stats = {
                "targets_attempted": 0,
                "targets_completed": 0,
                "exposures_total": 0,
            }
            self._flight_log = []
            self._transition(
                PipelineState.IDLE,
                sub="Standing by",
                msg=f"Daylight reset after parked mission (Sun at {sun_alt:.1f}°).",
            )
            return

        self._write_state(
            state=PipelineState.PARKED,
            sub="Parked",
            msg="Mission complete. Parked until daylight reset.",
        )
        time.sleep(max(1, self.LOOP_SLEEP_SEC))

    def _run_aborted(self):
        self._current_target = None
        time.sleep(max(1, self.LOOP_SLEEP_SEC))

    def _extract_targets(self, payload):
        return payload if isinstance(payload, list) else payload.get("targets", [])

    def _plan_is_stale(self, payload, now_utc):
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

    def _read_operator_command(self) -> dict:
        if not COMMAND_FILE.exists():
            return {}
        try:
            payload = json.loads(COMMAND_FILE.read_text())
        except Exception:
            payload = {}
        return payload if isinstance(payload, dict) else {}

    def _operator_abort_pending(self) -> bool:
        payload = self._read_operator_command()
        command = str(payload.get("command", "")).strip().lower()
        if command != "abort":
            return False

        requested_utc = str(payload.get("requested_utc", "")).strip()
        if requested_utc and requested_utc == self._last_command_utc:
            return False

        requested_dt = _parse_plan_dt(requested_utc) if requested_utc else None
        if requested_dt is not None:
            age_s = (datetime.now(timezone.utc) - requested_dt).total_seconds()
            if age_s > self.COMMAND_MAX_AGE_SEC:
                return False

        return True

    def _handle_operator_command(self) -> bool:
        payload = self._read_operator_command()
        command = str(payload.get("command", "")).strip().lower()
        requested_utc = str(payload.get("requested_utc", "")).strip()
        requested_dt = _parse_plan_dt(requested_utc) if requested_utc else None

        if not command:
            return False
        if requested_utc and requested_utc == self._last_command_utc:
            return False
        if requested_dt is not None:
            age_s = (datetime.now(timezone.utc) - requested_dt).total_seconds()
            if age_s > self.COMMAND_MAX_AGE_SEC:
                self._last_command_utc = requested_utc
                return False
        if requested_utc:
            self._last_command_utc = requested_utc

        if command == "abort":
            self._log_flight("🛑 Operator abort requested from dashboard.")
            self._targets = []
            self._current_target = None
            try:
                self._call_with_retries("abort park request", self.fsm.sequence.park)
                self._log_flight("🛑 Abort requested telescope park.")
            except Exception as e:
                self._log_flight(f"⚠️ Abort park request failed: {e}")
            self._transition(PipelineState.ABORTED, sub="OPERATOR ABORT", msg="Operator abort requested.")
            return True

        if command == "reset":
            self._log_flight("♻️ Operator reset requested from dashboard.")
            self._targets = []
            self._current_target = None
            self._planned_target_count = 0
            self._transition(PipelineState.IDLE, sub="Standing by", msg="Operator reset. Awaiting next cycle.")
            return True

        self._log_flight(f"⚠️ Ignoring unknown operator command: {command}")
        return False

    def _sun_altitude(self) -> float:
        now_mono = time.monotonic()
        if now_mono - self._sun_cache_monotonic <= self.SUN_CACHE_TTL_SEC:
            return self._sun_cache_alt
        try:
            now = Time.now()
            sun = get_body("sun", now)
            alt = float(sun.transform_to(AltAz(obstime=now, location=self._location)).alt.deg)
            self._sun_cache_alt = alt
            self._sun_cache_monotonic = now_mono
            return alt
        except Exception:
            return 0.0

    def _load_mission_targets(self) -> list:
        data = _safe_load_json(self._mission_file, [])
        return data if isinstance(data, list) else data.get("targets", [])

    def _call_with_retries(
        self,
        label: str,
        action: Callable[[], Any],
        *,
        attempts: int = 2,
        delay_sec: float = 2.0,
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, max(1, attempts) + 1):
            try:
                return action()
            except Exception as exc:
                last_error = exc
                self._log_flight(f"⚠️ {label} failed attempt {attempt}/{attempts}: {exc}")
                if attempt < attempts and not self.simulation_mode:
                    time.sleep(delay_sec)
        if last_error is not None:
            raise last_error
        return None

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
            self._call_with_retries("battery guard park request", self.fsm.sequence.park)
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

    def _configured_sun_limit_deg(self) -> float:
        try:
            return float(self._cfg.get("planner", {}).get("sun_altitude_limit", self.SUN_LIMIT_DEG))
        except Exception:
            return float(self.SUN_LIMIT_DEG)

    def _mount_mode(self) -> str:
        try:
            return str(self._scope.get("mount", "altaz")).strip().lower()
        except Exception:
            return "altaz"

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
        self._write_json(self._plan_file, payload)

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

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
        self._write_json(self._state_file, payload)

    def _transition(self, new_state: str, sub: str = "", msg: str = ""):
        if new_state not in PipelineState.ALL:
            raise ValueError(f"Invalid pipeline state: {new_state}")
        self._state = new_state
        self._write_state(state=new_state, sub=sub, msg=msg)
        log.info("STATE -> %s | %s", new_state, msg)


if __name__ == "__main__":
    Orchestrator().run()
