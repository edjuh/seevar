#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/weather.py
Version: 1.8.0
Objective: Tri-source weather consensus daemon providing dark-window timing and hard-abort imaging veto state for preflight and flight.
           conditions (rain, snow, fog, storm, wind) per hour within
           tonight's astronomical dark window. Cloud cover at any level
           is a warning only — never an abort. Reports best contiguous
           imaging window within the dark period. Feeds status,
           imaging_window_start, imaging_window_end, clouds_pct,
           humidity_pct to the Orchestrator via data/weather_state.json.
           Poll interval: 4 hours.
           Source 1 — open-meteo   : precipitation, wind, humidity (forecast)
           Source 2 — Clear Outside: per-layer clouds, fog (forecast)
           Source 3 — KNMI EDR     : measured oktas, visibility, ww from
                                     Schiphol (ground truth — hard aborts only)
"""

import json
import fcntl
import time
import logging
import requests
import sys
import tomllib
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.env_loader import DATA_DIR, CONFIG_PATH
from core.flight.vault_manager import VaultManager

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("WeatherSentinel")

POLL_INTERVAL_S = 14400  # 4 hours
LOCK_FILE = DATA_DIR / "locks" / "weather.lock"
_LOCK_HANDLE = None



def _acquire_singleton_lock() -> bool:
    global _LOCK_HANDLE
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LOCK_HANDLE = open(LOCK_FILE, "w")
        fcntl.flock(_LOCK_HANDLE.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _LOCK_HANDLE.write("weather\n")
        _LOCK_HANDLE.flush()
        return True
    except BlockingIOError:
        log.warning("Another WeatherSentinel instance already holds %s — exiting duplicate process.", LOCK_FILE)
        return False
    except Exception as e:
        log.error("Could not acquire weather singleton lock %s: %s", LOCK_FILE, e)
        return False


# ---------------------------------------------------------------------------
# KNMI ww codes — hard abort triggers
# Ref: WMO present weather codes used by KNMI
# ---------------------------------------------------------------------------

# ww 50–99: precipitation of any kind (drizzle, rain, snow, hail, showers)
WW_PRECIP_MIN = 50

# ww 10–12: mist / fog
WW_FOG_MIN = 10
WW_FOG_MAX = 12

# ww 17: thunderstorm (without precip at station)
# ww 29: thunderstorm (with precip)
# ww 91–99: thunderstorm + hail ranges
WW_THUNDER = {17, 29}
WW_THUNDER_RANGE = range(91, 100)


def _ww_is_precip(ww: float) -> bool:
    return ww >= WW_PRECIP_MIN


def _ww_is_fog(ww: float) -> bool:
    return WW_FOG_MIN <= ww <= WW_FOG_MAX


def _ww_is_thunder(ww: float) -> bool:
    w = int(ww)
    return w in WW_THUNDER or w in WW_THUNDER_RANGE


# ---------------------------------------------------------------------------
# Config loaders
# ---------------------------------------------------------------------------

def _load_thresholds() -> dict:
    """Load hard-abort thresholds from config.toml [weather].
    Cloud cover thresholds are retained for display/warning only —
    they do not trigger abort in v1.8+."""
    defaults = {
        "precip_limit":    0.5,    # mm — open-meteo forecast abort
        "wind_limit":      30.0,   # km/h
        "humidity_limit":  90.0,   # % — warning/dew heater cue, not abort
        "fog_abort":       True,
        "min_window_hours": 1,     # minimum contiguous clear hours to report
    }
    try:
        with open(CONFIG_PATH, "rb") as f:
            config = tomllib.load(f)
        w = config.get("weather", {})
        return {
            "precip_limit":     float(w.get("max_precip_mm",   defaults["precip_limit"])),
            "wind_limit":       float(w.get("max_wind_kmh",    defaults["wind_limit"])),
            "humidity_limit":   float(w.get("max_humidity_pct", defaults["humidity_limit"])),
            "fog_abort":        bool(w.get("fog_abort",        defaults["fog_abort"])),
            "min_window_hours": int(w.get("min_window_hours",  defaults["min_window_hours"])),
        }
    except Exception as e:
        log.warning("Could not load weather thresholds: %s — using defaults", e)
        return defaults


def _load_sun_limit() -> float:
    """Load sun_altitude_limit from config.toml [planner]."""
    try:
        with open(CONFIG_PATH, "rb") as f:
            config = tomllib.load(f)
        return float(config.get("planner", {}).get("sun_altitude_limit", -18.0))
    except Exception:
        return -18.0


def _load_knmi_config() -> dict:
    """Load KNMI EDR config from config.toml [knmi]. Returns {} if missing."""
    try:
        with open(CONFIG_PATH, "rb") as f:
            config = tomllib.load(f)
        k = config.get("knmi", {})
        if not k.get("edr_api_key"):
            return {}
        return {
            "api_key":      k["edr_api_key"],
            "station_id":   k.get("station_id",    "0-20000-0-06240"),
            "station_name": k.get("station_name",  "Schiphol"),
            "vv_limit":     int(k.get("vv_limit",      5000)),
            "ww_rain":      int(k.get("ww_rain_limit",  50)),
            "ww_fog":       int(k.get("ww_fog_limit",   10)),
        }
    except Exception as e:
        log.warning("Could not load KNMI config: %s", e)
        return {}


# ---------------------------------------------------------------------------
# Astronomical dark window
# ---------------------------------------------------------------------------

def get_dark_window(lat: float, lon: float,
                    sun_limit: float = -18.0) -> tuple | None:
    """Calculate tonight's astronomical dark window using skyfield."""
    try:
        from skyfield.api import wgs84, load, Loader
        from skyfield import almanac

        ts       = load.timescale()
        sky_load = Loader(str(PROJECT_ROOT / "catalogs"))
        eph      = sky_load("de421.bsp")
        location = wgs84.latlon(lat, lon)

        now_utc = datetime.now(timezone.utc)
        t0 = ts.from_datetime(now_utc)
        t1 = ts.from_datetime(now_utc + timedelta(hours=36))

        f = almanac.risings_and_settings(eph, eph["sun"], location,
                                          horizon_degrees=sun_limit)
        times, events = almanac.find_discrete(t0, t1, f)

        dark_start = dark_end = None
        for t, event in zip(times, events):
            dt = t.utc_datetime()
            if event == 0 and dark_start is None:
                dark_start = dt
            elif event == 1 and dark_start is not None:
                dark_end = dt
                break

        if dark_start and dark_end:
            log.info("Dark window: %s → %s UTC",
                     dark_start.strftime("%H:%M"),
                     dark_end.strftime("%H:%M"))
            return dark_start, dark_end

        log.warning("Could not determine dark window — falling back to next 12h")
        return None

    except Exception as e:
        log.warning("Dark window calculation failed: %s — falling back to next 12h", e)
        return None


def dark_window_hour_indices(dark_window: tuple | None,
                              hourly_times: list) -> list:
    """Return open-meteo hour indices within the dark window."""
    if dark_window is None:
        return list(range(min(12, len(hourly_times))))

    dark_start, dark_end = dark_window
    indices = []
    for i, ts_str in enumerate(hourly_times):
        try:
            dt = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
            if dark_start <= dt <= dark_end:
                indices.append(i)
        except Exception:
            continue

    if not indices:
        log.warning("No hourly data within dark window — falling back to next 12h")
        return list(range(min(12, len(hourly_times))))

    log.info("Evaluating %d hours within dark window", len(indices))
    return indices


# ---------------------------------------------------------------------------
# Per-hour abort evaluation
# ---------------------------------------------------------------------------

def _hour_has_hard_abort(hour_data: dict, t: dict, knmi_cfg: dict) -> tuple[bool, str]:
    """
    Evaluate a single hour's data against hard-abort conditions only.
    Cloud cover at any level is NOT an abort condition.

    Returns (abort: bool, reason: str).
    """
    # KNMI ground truth — measured precipitation (ww codes)
    ww = hour_data.get("knmi_ww")
    if ww is not None:
        if _ww_is_precip(ww):
            return True, f"RAIN (KNMI ww={ww:.0f})"
        if _ww_is_fog(ww):
            return True, f"FOG (KNMI ww={ww:.0f})"
        if _ww_is_thunder(ww):
            return True, f"THUNDER (KNMI ww={ww:.0f})"

    # KNMI visibility — fog proxy (measured)
    vv = hour_data.get("knmi_vv")
    vv_limit = knmi_cfg.get("vv_limit", 5000) if knmi_cfg else 5000
    if vv is not None and vv < vv_limit:
        return True, f"FOG (KNMI vv={vv:.0f}m < {vv_limit}m)"

    # Clear Outside forecast fog
    if t["fog_abort"] and hour_data.get("co_fog", 0) > 0:
        return True, "FOG (Clear Outside forecast)"

    # open-meteo forecast precipitation
    if hour_data.get("om_precip", 0) > t["precip_limit"]:
        return True, f"RAIN (open-meteo precip={hour_data['om_precip']:.1f}mm)"

    # Wind — forecast (open-meteo, km/h)
    if hour_data.get("om_wind", 0) > t["wind_limit"]:
        return True, f"WINDY (open-meteo wind={hour_data['om_wind']:.0f}km/h)"

    return False, ""


def find_best_imaging_window(hourly_evals: list, min_hours: int = 1) -> tuple | None:
    """
    Find the longest contiguous block of hours with no hard abort.
    hourly_evals: list of (datetime, abort: bool, reason: str)
    Returns (window_start: datetime, window_end: datetime) or None.
    """
    best_start = best_end = None
    best_len = 0

    run_start = None
    run_len   = 0

    for dt, abort, _reason in hourly_evals:
        if not abort:
            if run_start is None:
                run_start = dt
                run_len   = 1
            else:
                run_len += 1
            if run_len > best_len:
                best_len   = run_len
                best_start = run_start
                best_end   = dt
        else:
            run_start = None
            run_len   = 0

    if best_len >= min_hours:
        return best_start, best_end
    return None


# ---------------------------------------------------------------------------
# WeatherSentinel
# ---------------------------------------------------------------------------

class WeatherSentinel:
    def __init__(self):
        self.weather_state_file = DATA_DIR / "weather_state.json"
        self.vault     = VaultManager()
        self.t         = _load_thresholds()
        self.sun_limit = _load_sun_limit()
        self.knmi_cfg  = _load_knmi_config()

        log.info(
            "Thresholds v1.8 — precip:%.1fmm wind:%.0fkm/h hum:%.0f%% "
            "fog_abort:%s min_window:%dh | clouds: WARNING ONLY",
            self.t["precip_limit"], self.t["wind_limit"],
            self.t["humidity_limit"], self.t["fog_abort"],
            self.t["min_window_hours"],
        )
        if self.knmi_cfg:
            log.info("KNMI source: %s (%s) vv_limit:%dm",
                     self.knmi_cfg["station_name"],
                     self.knmi_cfg["station_id"],
                     self.knmi_cfg["vv_limit"])
        else:
            log.info("KNMI source: disabled (no api_key in config.toml [knmi])")

    def get_coordinates(self) -> tuple:
        cfg = self.vault.get_observer_config()
        return float(cfg.get("lat", 0.0)), float(cfg.get("lon", 0.0))

    # -------------------------------------------------------------------------
    # SOURCE 1 — open-meteo (hourly, per dark window hour)
    # -------------------------------------------------------------------------

    def fetch_open_meteo_hourly(self, lat: float, lon: float,
                                dark_window: tuple | None) -> list:
        """
        Fetch hourly precipitation, wind, humidity, cloud_cover.
        Returns list of dicts keyed by UTC datetime, one per dark window hour.
        """
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&hourly=precipitation,cloud_cover,relative_humidity_2m,"
            f"wind_speed_10m&timezone=UTC"
        )
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data  = r.json().get("hourly", {})
            times = data.get("time", [])
            idx   = dark_window_hour_indices(dark_window, times)

            hours = []
            for i in idx:
                if i >= len(times):
                    continue
                try:
                    dt = datetime.fromisoformat(times[i]).replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                hours.append({
                    "dt":         dt,
                    "om_precip":  data.get("precipitation",         [0]*len(times))[i] or 0,
                    "om_wind":    data.get("wind_speed_10m",         [0]*len(times))[i] or 0,
                    "om_humidity":data.get("relative_humidity_2m",   [0]*len(times))[i] or 0,
                    "om_clouds":  data.get("cloud_cover",            [0]*len(times))[i] or 0,
                })

            log.info("open-meteo — %d hours within dark window fetched", len(hours))
            return hours

        except Exception as e:
            log.warning("open-meteo fetch failed: %s", e)
            return []

    # -------------------------------------------------------------------------
    # SOURCE 2 — Clear Outside (hourly fog only — clouds are display only)
    # -------------------------------------------------------------------------

    def fetch_clear_outside_hourly(self, lat: float, lon: float,
                                   dark_window: tuple | None) -> dict:
        """
        Fetch per-hour fog flag and cloud layers from Clear Outside.
        Returns dict keyed by hour-of-day (int) → {co_fog, co_low, co_mid,
        co_high}. Clouds stored for display; fog used for abort evaluation.
        """
        try:
            from clear_outside_apy import ClearOutsideAPY
            api = ClearOutsideAPY(f"{lat:.2f}", f"{lon:.2f}", "midnight")
            api.update()
            data = api.pull()

            result = {}
            for day_key in sorted(data.get("forecast", {}).keys()):
                day   = data["forecast"][day_key]
                hours = day.get("hours", {})
                for hour_key in sorted(hours.keys(), key=int):
                    h = hours[hour_key]
                    result[int(hour_key)] = {
                        "co_fog":  int(h.get("fog",         0)),
                        "co_low":  int(h.get("low-clouds",  0)),
                        "co_mid":  int(h.get("mid-clouds",  0)),
                        "co_high": int(h.get("high-clouds", 0)),
                    }

            log.info("Clear Outside — %d hours fetched", len(result))
            return result

        except ImportError:
            log.warning("clear-outside-apy not installed — skipping.")
            return {}
        except Exception as e:
            log.warning("Clear Outside fetch failed: %s", e)
            return {}

    # -------------------------------------------------------------------------
    # SOURCE 3 — KNMI EDR (ground truth — single latest measurement)
    # -------------------------------------------------------------------------

    def fetch_knmi(self) -> dict:
        """
        Fetch latest 10-minute measured observation from KNMI EDR.
        Ground truth for current conditions — ww, vv, oktas, temp, rh, wind.
        Applied to the current hour in per-hour evaluation.
        """
        if not self.knmi_cfg:
            return {}

        cfg     = self.knmi_cfg
        base    = "https://api.dataplatform.knmi.nl/edr/v1/collections"
        collection = "10-minute-in-situ-meteorological-observations"
        station = cfg["station_id"]
        headers = {"Authorization": cfg["api_key"]}

        now     = datetime.now(timezone.utc)
        dt_from = (now - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        dt_to   = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        url = (
            f"{base}/{collection}/locations/{station}"
            f"?datetime={dt_from}/{dt_to}"
            f"&parameter-name=n,nc,vv,ww,ta,rh,ff"
        )

        try:
            r = requests.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            data = r.json()

            coverages = data.get("coverages", [])
            if not coverages:
                log.warning("KNMI: no coverages in response")
                return {}

            ranges = coverages[0]["ranges"]
            times  = coverages[0]["domain"]["axes"]["t"]["values"]

            def latest(key):
                vals = ranges.get(key, {}).get("values", [])
                for v in reversed(vals):
                    if v is not None:
                        return v
                return None

            n   = latest("n")
            nc  = latest("nc")
            vv  = latest("vv")
            ww  = latest("ww")
            ta  = latest("ta")
            rh  = latest("rh")
            ff  = latest("ff")

            oktas = nc if nc is not None else n

            log.info(
                "KNMI %s — oktas:%.0f vv:%.0fm ww:%.0f ta:%.1f°C rh:%.0f%% ff:%.1fm/s",
                cfg["station_name"],
                oktas or 0, vv or 0, ww or 0,
                ta or 0, rh or 0, ff or 0,
            )

            return {
                "oktas":   oktas,
                "vv":      vv,
                "ww":      ww,
                "ta":      ta,
                "rh":      rh,
                "ff":      ff,
                "station": cfg["station_name"],
                "time":    times[-1] if times else None,
            }

        except Exception as e:
            log.warning("KNMI fetch failed: %s", e)
            return {}

    # -------------------------------------------------------------------------
    # CONSENSUS — per-hour evaluation, hard aborts only
    # -------------------------------------------------------------------------

    def get_consensus(self):
        """
        Per-hour hard-abort evaluation across the dark window.

        Hard abort conditions (telescope in):
          1. KNMI ww >= 50          — measured precipitation (rain/snow/hail)
          2. KNMI ww 10–12          — measured fog/mist
          3. KNMI ww 17/29/91-99    — measured thunderstorm
          4. KNMI vv < vv_limit     — measured poor visibility (fog proxy)
          5. Clear Outside fog > 0  — forecast fog
          6. open-meteo precip      — forecast precipitation
          7. open-meteo wind        — forecast wind above limit

        Warning only (log, never abort, telescope keeps imaging):
          - Cloud cover at any level (low/mid/high) — all sources
          - KNMI oktas — display only
          - Humidity — dew heater cue only

        Outcome:
          - status: CLEAR / CLOUDY / HAZY / HUMID / RAIN / FOG / WINDY / THUNDER
            CLEAR/CLOUDY/HAZY/HUMID = imaging go
            RAIN/FOG/WINDY/THUNDER  = hard abort
          - imaging_window_start / imaging_window_end: best contiguous
            non-abort block within the dark window (UTC ISO strings)
        """
        lat, lon = self.get_coordinates()
        if lat == 0.0 and lon == 0.0:
            log.error("Coordinates are 0.0 (Null Island). Cannot fetch weather.")
            return

        dark_window = get_dark_window(lat, lon, self.sun_limit)

        log.info("Fetching tri-source weather for %.4f, %.4f...", lat, lon)
        om_hours = self.fetch_open_meteo_hourly(lat, lon, dark_window)
        co_hours = self.fetch_clear_outside_hourly(lat, lon, dark_window)
        knmi     = self.fetch_knmi()

        t = self.t

        # Merge per-hour data — open-meteo is the hour spine
        # KNMI ground truth applied to the current hour only (it's a
        # point-in-time measurement, not a forecast)
        now_utc     = datetime.now(timezone.utc)
        current_hour = now_utc.hour

        hourly_evals = []   # (datetime, abort: bool, reason: str)
        hourly_detail = []  # for state file

        for om in om_hours:
            dt   = om["dt"]
            hour = dt.hour

            # Merge Clear Outside for this hour (keyed by hour-of-day)
            co = co_hours.get(hour, {})

            # Build merged hour dict for abort evaluation
            h = {
                "om_precip":  om["om_precip"],
                "om_wind":    om["om_wind"],
                "co_fog":     co.get("co_fog", 0),
                # KNMI ground truth only applied to current hour
                "knmi_ww":    knmi.get("ww") if hour == current_hour else None,
                "knmi_vv":    knmi.get("vv") if hour == current_hour else None,
            }

            abort, reason = _hour_has_hard_abort(h, t, self.knmi_cfg)
            hourly_evals.append((dt, abort, reason))

            hourly_detail.append({
                "hour_utc":   dt.strftime("%H:%M"),
                "abort":      abort,
                "reason":     reason,
                "om_precip":  om["om_precip"],
                "om_wind":    om["om_wind"],
                "om_clouds":  om["om_clouds"],
                "co_fog":     co.get("co_fog",  0),
                "co_low":     co.get("co_low",  0),
                "co_mid":     co.get("co_mid",  0),
                "co_high":    co.get("co_high", 0),
            })

        # Best contiguous imaging window
        imaging_window = find_best_imaging_window(
            hourly_evals, min_hours=t["min_window_hours"]
        )

        # Overall status — driven by NOW, not window_max
        # Current hour abort → hard abort status
        # Otherwise: warning statuses from current conditions
        now_abort = False
        now_reason = ""
        for dt, abort, reason in hourly_evals:
            if dt.hour == current_hour:
                now_abort  = abort
                now_reason = reason
                break

        current_detail = next(
            (d for d in hourly_detail if int(d["hour_utc"][:2]) == current_hour),
            {},
        )
        current_om = next(
            (om for om in om_hours if om["dt"].hour == current_hour),
            {},
        )

        # Fallback: if no hourly data for current hour, use KNMI direct
        if not now_abort and knmi:
            h_now = {
                "om_precip": 0,
                "om_wind":   (knmi.get("ff") or 0) * 3.6,  # m/s → km/h
                "co_fog":    0,
                "knmi_ww":   knmi.get("ww"),
                "knmi_vv":   knmi.get("vv"),
            }
            now_abort, now_reason = _hour_has_hard_abort(h_now, t, self.knmi_cfg)

        if now_abort:
            # Determine specific abort status from reason string
            if "RAIN" in now_reason:
                current_status, current_icon = "RAIN",    "🌧️"
            elif "FOG" in now_reason:
                current_status, current_icon = "FOGGY",   "🌫️"
            elif "THUNDER" in now_reason:
                current_status, current_icon = "THUNDER", "⛈️"
            elif "WINDY" in now_reason:
                current_status, current_icon = "WINDY",   "💨"
            else:
                current_status, current_icon = "RAIN",    "🌧️"
        else:
            # Warning-only statuses — imaging continues
            om_humidity = current_om.get("om_humidity", 0)
            humidity_pct = knmi.get("rh") or om_humidity

            # Cloud warning — CURRENT hour only
            cur_low = current_detail.get("co_low", 0)
            cur_mid = current_detail.get("co_mid", 0)
            cur_high = current_detail.get("co_high", 0)
            knmi_oktas = knmi.get("oktas")

            if cur_low > 50 or cur_mid > 50 or (knmi_oktas is not None and knmi_oktas >= 5):
                current_status, current_icon = "CLOUDY", "☁️"
            elif cur_high > 70:
                current_status, current_icon = "HAZY",   "🌤️"
            elif humidity_pct > t["humidity_limit"]:
                current_status, current_icon = "HUMID",  "💧"
            else:
                current_status, current_icon = "CLEAR",  "✨"

        # Collect display values
        clouds_pct   = int(max((d["om_clouds"] for d in hourly_detail), default=0))
        humidity_pct = int(knmi.get("rh") or
                           max((om["om_humidity"] for om in om_hours), default=0))
        knmi_oktas   = knmi.get("oktas")
        knmi_cloud_pct = int((knmi_oktas or 0) / 9 * 100)

        dark_start_str = dark_window[0].strftime("%H:%M UTC") if dark_window else "unknown"
        dark_end_str   = dark_window[1].strftime("%H:%M UTC") if dark_window else "unknown"

        win_start_str = (imaging_window[0].strftime("%H:%M UTC")
                         if imaging_window else None)
        win_end_str   = (imaging_window[1].strftime("%H:%M UTC")
                         if imaging_window else None)

        abort_hours = sum(1 for _, a, _ in hourly_evals if a)
        clear_hours = len(hourly_evals) - abort_hours

        if imaging_window:
            if abort_hours == 0:
                status, icon = "CLEAR", "✨"
            else:
                status, icon = "MIXED", "🌤️"
        else:
            if abort_hours > 0:
                status, icon = "BLOCKED", "☁️"
            else:
                status, icon = current_status, current_icon

        log.info(
            "Consensus: tonight=%s %s | now=%s %s | dark:%s→%s | imaging window:%s→%s "
            "| clear:%dh abort:%dh | knmi:%.0f oktas ww:%.0f vv:%.0fm",
            status, icon, current_status, current_icon, dark_start_str, dark_end_str,
            win_start_str or "none", win_end_str or "none",
            clear_hours, abort_hours,
            knmi_oktas or 0,
            knmi.get("ww") or 0,
            knmi.get("vv") or 0,
        )

        if abort_hours > 0:
            abort_reasons = list({r for _, a, r in hourly_evals if a and r})
            log.info("Abort hours reasons: %s", "; ".join(abort_reasons))

        state = {
            "_objective": (
                "Tri-source weather consensus v1.8. Hard aborts: rain/fog/thunder/wind. "
                "Cloud cover is warning only. Per-hour evaluation within dark window."
            ),
            "status":                status,
            "icon":                  icon,
            "current_status":        current_status,
            "current_icon":          current_icon,
            "imaging_go":            not now_abort,
            "imaging_window_start":  win_start_str,
            "imaging_window_end":    win_end_str,
            "clear_hours":           clear_hours,
            "abort_hours":           abort_hours,
            "clouds_pct":            clouds_pct,
            "humidity_pct":          humidity_pct,
            "knmi_oktas":            knmi_oktas,
            "knmi_cloud_pct":        knmi_cloud_pct,
            "knmi_vv_m":             knmi.get("vv"),
            "knmi_ww":               knmi.get("ww"),
            "knmi_temp_c":           knmi.get("ta"),
            "knmi_station":          knmi.get("station"),
            "knmi_time":             knmi.get("time"),
            "dark_start":            dark_start_str,
            "dark_end":              dark_end_str,
            "hourly_detail":         hourly_detail,
            "last_update":           time.time(),
        }

        try:
            self.weather_state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.weather_state_file, "w") as f:
                json.dump(state, f, indent=4)
        except OSError as e:
            log.error("Failed to write weather_state.json: %s", e)


if __name__ == "__main__":
    if not _acquire_singleton_lock():
        raise SystemExit(0)
    log.info("WeatherSentinel v1.8.0 starting...")
    sentinel = WeatherSentinel()
    while True:
        sentinel.get_consensus()
        time.sleep(POLL_INTERVAL_S)
