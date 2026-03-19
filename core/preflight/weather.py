#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/weather.py
Version: 1.7.0
Objective: Tri-source weather consensus daemon. Evaluates conditions only
           within tonight's astronomical dark window (sun < sun_altitude_limit).
           Source 1 — open-meteo   : precipitation, wind, humidity (forecast)
           Source 2 — Clear Outside: per-layer clouds, fog (forecast)
           Source 3 — KNMI EDR     : measured cloud oktas, visibility, present
                                     weather from Schiphol (ground truth)
           Feeds status, clouds_pct, humidity_pct to the Orchestrator via
           data/weather_state.json. Poll interval: 4 hours.
"""

import json
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


# ---------------------------------------------------------------------------
# Config loaders
# ---------------------------------------------------------------------------

def _load_thresholds() -> dict:
    """Load weather veto thresholds from config.toml [weather]."""
    defaults = {
        "precip_limit":    0.5,
        "wind_limit":      30.0,
        "humidity_limit":  90.0,
        "low_cloud_limit": 30.0,
        "mid_cloud_limit": 50.0,
        "high_cloud_warn": 70.0,
        "fog_abort":       True,
    }
    try:
        with open(CONFIG_PATH, "rb") as f:
            config = tomllib.load(f)
        w = config.get("weather", {})
        return {
            "precip_limit":    float(w.get("max_precip_mm",      defaults["precip_limit"])),
            "wind_limit":      float(w.get("max_wind_kmh",        defaults["wind_limit"])),
            "humidity_limit":  float(w.get("max_humidity_pct",    defaults["humidity_limit"])),
            "low_cloud_limit": float(w.get("max_cloud_low_pct",   defaults["low_cloud_limit"])),
            "mid_cloud_limit": float(w.get("max_cloud_mid_pct",   defaults["mid_cloud_limit"])),
            "high_cloud_warn": float(w.get("max_cloud_high_pct",  defaults["high_cloud_warn"])),
            "fog_abort":       bool(w.get("fog_abort",            defaults["fog_abort"])),
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
            "okta_limit":   int(k.get("okta_limit",    6)),
            "vv_limit":     int(k.get("vv_limit",      5000)),
            "ww_rain":      int(k.get("ww_rain_limit", 50)),
            "ww_fog":       int(k.get("ww_fog_limit",  10)),
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
# WeatherSentinel
# ---------------------------------------------------------------------------

class WeatherSentinel:
    def __init__(self):
        self.weather_state_file = DATA_DIR / "weather_state.json"
        self.vault       = VaultManager()
        self.t           = _load_thresholds()
        self.sun_limit   = _load_sun_limit()
        self.knmi_cfg    = _load_knmi_config()

        log.info(
            "Thresholds — precip:%.1fmm wind:%.0fkm/h hum:%.0f%% "
            "low:%.0f%% mid:%.0f%% high:%.0f%% fog_abort:%s sun_limit:%.1f°",
            self.t["precip_limit"], self.t["wind_limit"],
            self.t["humidity_limit"], self.t["low_cloud_limit"],
            self.t["mid_cloud_limit"], self.t["high_cloud_warn"],
            self.t["fog_abort"], self.sun_limit
        )
        if self.knmi_cfg:
            log.info("KNMI source: %s (%s) okta_limit:%d vv_limit:%dm",
                     self.knmi_cfg["station_name"],
                     self.knmi_cfg["station_id"],
                     self.knmi_cfg["okta_limit"],
                     self.knmi_cfg["vv_limit"])
        else:
            log.info("KNMI source: disabled (no api_key in config.toml [knmi])")

    def get_coordinates(self) -> tuple:
        cfg = self.vault.get_observer_config()
        return float(cfg.get("lat", 0.0)), float(cfg.get("lon", 0.0))

    # -------------------------------------------------------------------------
    # SOURCE 1 — open-meteo
    # -------------------------------------------------------------------------

    def fetch_open_meteo(self, lat: float, lon: float,
                         dark_window: tuple | None) -> dict:
        """Forecast precipitation, wind, humidity within dark window."""
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

            def window_max(key):
                vals     = data.get(key, [])
                windowed = [vals[i] for i in idx if i < len(vals)]
                return max(windowed) if windowed else 0

            precip   = window_max("precipitation")
            clouds   = window_max("cloud_cover")
            humidity = window_max("relative_humidity_2m")
            wind     = window_max("wind_speed_10m")

            log.info("open-meteo — precip:%.1fmm wind:%.0f clouds:%d%% hum:%d%%",
                     precip, wind, clouds, humidity)
            return {"precip": precip, "clouds": clouds,
                    "humidity": humidity, "wind": wind}

        except Exception as e:
            log.warning("open-meteo fetch failed: %s", e)
            return {}

    # -------------------------------------------------------------------------
    # SOURCE 2 — Clear Outside
    # -------------------------------------------------------------------------

    def fetch_clear_outside(self, lat: float, lon: float,
                             dark_window: tuple | None) -> dict:
        """Per-layer cloud forecast within dark window."""
        try:
            from clear_outside_apy import ClearOutsideAPY
            api = ClearOutsideAPY(f"{lat:.2f}", f"{lon:.2f}", "midnight")
            api.update()
            data = api.pull()

            all_hours = []
            for day_key in sorted(data.get("forecast", {}).keys()):
                day   = data["forecast"][day_key]
                hours = day.get("hours", {})
                for hour_key in sorted(hours.keys(), key=int):
                    all_hours.append({
                        "hour": int(hour_key),
                        "data": hours[hour_key],
                    })

            if dark_window:
                dark_start, dark_end = dark_window
                sample = []
                for h in all_hours:
                    try:
                        if dark_start.hour > dark_end.hour:
                            if h["hour"] >= dark_start.hour or \
                               h["hour"] <= dark_end.hour:
                                sample.append(h["data"])
                        else:
                            if dark_start.hour <= h["hour"] <= dark_end.hour:
                                sample.append(h["data"])
                    except Exception:
                        continue
                if not sample:
                    sample = [h["data"] for h in all_hours[:3]]
            else:
                sample = [h["data"] for h in all_hours[:3]]

            if not sample:
                return {}

            low  = max(int(h.get("low-clouds",  0)) for h in sample)
            mid  = max(int(h.get("mid-clouds",  0)) for h in sample)
            high = max(int(h.get("high-clouds", 0)) for h in sample)
            fog  = max(int(h.get("fog",         0)) for h in sample)

            log.info("Clear Outside — low:%d%% mid:%d%% high:%d%% fog:%d",
                     low, mid, high, fog)
            return {"low": low, "mid": mid, "high": high, "fog": fog}

        except ImportError:
            log.warning("clear-outside-apy not installed — skipping.")
            return {}
        except Exception as e:
            log.warning("Clear Outside fetch failed: %s", e)
            return {}

    # -------------------------------------------------------------------------
    # SOURCE 3 — KNMI EDR (ground truth)
    # -------------------------------------------------------------------------

    def fetch_knmi(self) -> dict:
        """
        Fetch 10-minute measured observations from KNMI EDR API.
        Returns latest values for cloud cover (oktas), visibility,
        present weather code, temperature and humidity.
        Falls back gracefully if API key not configured.
        """
        if not self.knmi_cfg:
            return {}

        cfg     = self.knmi_cfg
        base    = "https://api.dataplatform.knmi.nl/edr/v1/collections"
        collection = "10-minute-in-situ-meteorological-observations"
        station = cfg["station_id"]
        headers = {"Authorization": cfg["api_key"]}

        # Query last 30 minutes to guarantee at least one reading
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
                """Return the most recent non-None value for a parameter."""
                vals = ranges.get(key, {}).get("values", [])
                for v in reversed(vals):
                    if v is not None:
                        return v
                return None

            n   = latest("n")    # cloud cover oktas 0-9
            nc  = latest("nc")   # cloud cover corrected
            vv  = latest("vv")   # visibility metres
            ww  = latest("ww")   # present weather code
            ta  = latest("ta")   # temperature °C
            rh  = latest("rh")   # relative humidity %
            ff  = latest("ff")   # wind speed m/s

            # Use corrected cloud cover if available, else raw
            oktas = nc if nc is not None else n

            log.info(
                "KNMI %s — oktas:%.0f vv:%.0fm ww:%.0f ta:%.1f°C rh:%.0f%% ff:%.1fm/s",
                cfg["station_name"],
                oktas or 0, vv or 0, ww or 0,
                ta or 0, rh or 0, ff or 0
            )

            return {
                "oktas":    oktas,
                "vv":       vv,
                "ww":       ww,
                "ta":       ta,
                "rh":       rh,
                "ff":       ff,
                "station":  cfg["station_name"],
                "time":     times[-1] if times else None,
            }

        except Exception as e:
            log.warning("KNMI fetch failed: %s", e)
            return {}

    # -------------------------------------------------------------------------
    # CONSENSUS
    # -------------------------------------------------------------------------

    def get_consensus(self):
        """
        Tri-source consensus — KNMI ground truth takes priority over forecasts.

        Priority order:
          1. KNMI ww >= ww_rain  → RAIN   — measured rain, hard abort
          2. KNMI vv < vv_limit  → FOGGY  — measured fog, hard abort
          3. CO fog > 0          → FOGGY  — forecast fog
          4. OM precip > limit   → RAIN   — forecast rain
          5. KNMI oktas >= limit → CLOUDY — measured overcast
          6. CO low > limit      → CLOUDY — forecast low cloud
          7. CO mid > limit      → CLOUDY — forecast mid cloud
          8. OM wind > limit     → WINDY
          9. CO high > limit     → HAZY   — warning only
         10. OM/KNMI humidity    → HUMID  — warning, dew heater cue
         11. All clear           → CLEAR
        """
        lat, lon = self.get_coordinates()
        if lat == 0.0 and lon == 0.0:
            log.error("Coordinates are 0.0 (Null Island). Cannot fetch weather.")
            return

        dark_window = get_dark_window(lat, lon, self.sun_limit)

        log.info("Fetching tri-source weather for %.4f, %.4f...", lat, lon)
        om   = self.fetch_open_meteo(lat, lon, dark_window)
        co   = self.fetch_clear_outside(lat, lon, dark_window)
        knmi = self.fetch_knmi()

        clouds_pct   = om.get("clouds",   0)
        # Use KNMI humidity if available (measured), else open-meteo forecast
        humidity_pct = knmi.get("rh") or om.get("humidity", 0)

        t = self.t
        k = self.knmi_cfg

        # KNMI oktas → percentage for dashboard display
        knmi_cloud_pct = int((knmi.get("oktas") or 0) / 9 * 100)

        # Consensus — KNMI ground truth first, forecasts second
        if knmi and knmi.get("ww") is not None and \
           knmi["ww"] >= (k.get("ww_rain", 50) if k else 50):
            status, icon = "RAIN",   "🌧️"
        elif knmi and knmi.get("vv") is not None and \
             knmi["vv"] < (k.get("vv_limit", 5000) if k else 5000):
            status, icon = "FOGGY",  "🌫️"
        elif t["fog_abort"] and co.get("fog", 0) > 0:
            status, icon = "FOGGY",  "🌫️"
        elif om.get("precip", 0) > t["precip_limit"]:
            status, icon = "RAIN",   "🌧️"
        elif knmi and knmi.get("oktas") is not None and \
             knmi["oktas"] >= (k.get("okta_limit", 6) if k else 6):
            status, icon = "CLOUDY", "☁️"
        elif co.get("low", 0) > t["low_cloud_limit"]:
            status, icon = "CLOUDY", "☁️"
        elif co.get("mid", 0) > t["mid_cloud_limit"]:
            status, icon = "CLOUDY", "☁️"
        elif om.get("wind", 0) > t["wind_limit"]:
            status, icon = "WINDY",  "💨"
        elif co.get("high", 0) > t["high_cloud_warn"]:
            status, icon = "HAZY",   "🌤️"
        elif humidity_pct > t["humidity_limit"]:
            status, icon = "HUMID",  "💧"
        else:
            status, icon = "CLEAR",  "✨"

        dark_start_str = dark_window[0].strftime("%H:%M UTC") \
                         if dark_window else "unknown"
        dark_end_str   = dark_window[1].strftime("%H:%M UTC") \
                         if dark_window else "unknown"

        state = {
            "_objective": "Tri-source weather consensus (open-meteo + Clear Outside + KNMI).",
            "status":           status,
            "icon":             icon,
            "clouds_pct":       int(clouds_pct),
            "humidity_pct":     int(humidity_pct),
            "low_cloud":        co.get("low",   0),
            "mid_cloud":        co.get("mid",   0),
            "high_cloud":       co.get("high",  0),
            "fog":              co.get("fog",   0),
            "knmi_oktas":       knmi.get("oktas"),
            "knmi_cloud_pct":   knmi_cloud_pct,
            "knmi_vv_m":        knmi.get("vv"),
            "knmi_ww":          knmi.get("ww"),
            "knmi_temp_c":      knmi.get("ta"),
            "knmi_station":     knmi.get("station"),
            "knmi_time":        knmi.get("time"),
            "dark_start":       dark_start_str,
            "dark_end":         dark_end_str,
            "last_update":      time.time(),
        }

        try:
            self.weather_state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.weather_state_file, "w") as f:
                json.dump(state, f, indent=4)
            log.info(
                "Consensus: %s %s — window:%s→%s "
                "knmi:%.0f oktas/%.0fm vv "
                "co_low:%d%% fog:%d om_hum:%d%%",
                status, icon, dark_start_str, dark_end_str,
                knmi.get("oktas") or 0,
                knmi.get("vv") or 0,
                co.get("low", 0), co.get("fog", 0),
                humidity_pct,
            )
        except OSError as e:
            log.error("Failed to write weather_state.json: %s", e)


if __name__ == "__main__":
    log.info("WeatherSentinel v1.7.0 starting...")
    sentinel = WeatherSentinel()
    while True:
        sentinel.get_consensus()
        time.sleep(POLL_INTERVAL_S)
