#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/weather.py
Version: 1.6.1
Objective: Dual-source weather consensus daemon. Evaluates conditions only
           within tonight's astronomical dark window (sun < sun_altitude_limit).
           Source 1 — open-meteo   : precipitation, wind, humidity (hard aborts)
           Source 2 — Clear Outside: per-layer clouds, fog (photometry aborts)
           Feeds status, clouds_pct, humidity_pct to the Orchestrator via
           data/weather_state.json.
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("WeatherSentinel")


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
    """Load sun_altitude_limit from config.toml [planner]. Default -18.0°."""
    try:
        with open(CONFIG_PATH, "rb") as f:
            config = tomllib.load(f)
        return float(config.get("planner", {}).get("sun_altitude_limit", -18.0))
    except Exception:
        return -18.0


# ---------------------------------------------------------------------------
# Astronomical dark window
# ---------------------------------------------------------------------------

def get_dark_window(lat: float, lon: float,
                    sun_limit: float = -18.0) -> tuple[datetime, datetime] | None:
    """
    Calculate tonight's astronomical dark window using skyfield.
    Returns (dark_start_utc, dark_end_utc) or None if calculation fails.
    Falls back to next 12 hours if skyfield unavailable or sun never sets.
    """
    try:
        from skyfield.api import load, wgs84
        from skyfield import almanac

        ts     = load.timescale()
        from skyfield.api import Loader
        sky_load = Loader(str(PROJECT_ROOT / "catalogs"))
        eph      = sky_load("de421.bsp")
        location = wgs84.latlon(lat, lon)

        now_utc = datetime.now(timezone.utc)
        # Search window: now → 36 hours ahead (catches late sunsets and early dawns)
        t0 = ts.from_datetime(now_utc)
        t1 = ts.from_datetime(now_utc + timedelta(hours=36))

        # Find sun altitude crossings at sun_limit
        f = almanac.risings_and_settings(eph, eph["sun"], location,
                                          horizon_degrees=sun_limit)
        times, events = almanac.find_discrete(t0, t1, f)

        dark_start = None
        dark_end   = None

        for t, event in zip(times, events):
            dt = t.utc_datetime()
            if event == 0 and dark_start is None:   # setting = dark start
                dark_start = dt
            elif event == 1 and dark_start is not None:  # rising = dark end
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
                              hourly_times: list[str]) -> list[int]:
    """
    Given the dark window and open-meteo hourly timestamps (ISO strings),
    return the indices of hours that fall within the dark window.
    Falls back to first 12 indices if window is None or no overlap found.
    """
    if dark_window is None:
        return list(range(min(12, len(hourly_times))))

    dark_start, dark_end = dark_window
    indices = []

    for i, ts_str in enumerate(hourly_times):
        try:
            # open-meteo format: "2026-03-18T20:00"
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
        self.vault     = VaultManager()
        self.t         = _load_thresholds()
        self.sun_limit = _load_sun_limit()
        log.info(
            "Thresholds — precip:%.1fmm wind:%.0fkm/h hum:%.0f%% "
            "low:%.0f%% mid:%.0f%% high:%.0f%% fog_abort:%s sun_limit:%.1f°",
            self.t["precip_limit"], self.t["wind_limit"], self.t["humidity_limit"],
            self.t["low_cloud_limit"], self.t["mid_cloud_limit"],
            self.t["high_cloud_warn"], self.t["fog_abort"], self.sun_limit
        )

    def get_coordinates(self) -> tuple[float, float]:
        cfg = self.vault.get_observer_config()
        return float(cfg.get("lat", 0.0)), float(cfg.get("lon", 0.0))

    # -------------------------------------------------------------------------
    # SOURCE 1 — open-meteo (dark window aware)
    # -------------------------------------------------------------------------

    def fetch_open_meteo(self, lat: float, lon: float,
                         dark_window: tuple | None) -> dict:
        """
        Fetches precipitation, wind, humidity.
        Evaluates only hours within the astronomical dark window.
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

            idx = dark_window_hour_indices(dark_window, times)

            def window_max(key):
                vals = data.get(key, [])
                windowed = [vals[i] for i in idx if i < len(vals)]
                return max(windowed) if windowed else 0

            precip   = window_max("precipitation")
            clouds   = window_max("cloud_cover")
            humidity = window_max("relative_humidity_2m")
            wind     = window_max("wind_speed_10m")

            log.info("open-meteo (dark window) — precip:%.1fmm wind:%.0f clouds:%d%% hum:%d%%",
                     precip, wind, clouds, humidity)
            return {"precip": precip, "clouds": clouds,
                    "humidity": humidity, "wind": wind}

        except Exception as e:
            log.warning("open-meteo fetch failed: %s", e)
            return {}

    # -------------------------------------------------------------------------
    # SOURCE 2 — Clear Outside (dark window aware)
    # -------------------------------------------------------------------------

    def fetch_clear_outside(self, lat: float, lon: float,
                             dark_window: tuple | None) -> dict:
        """
        Fetches per-layer cloud data and fog from Clear Outside.
        Evaluates only hours within the astronomical dark window.
        Falls back to next 3 hours if window not determinable.
        """
        try:
            from clear_outside_apy import ClearOutsideAPY
            api = ClearOutsideAPY(f"{lat:.2f}", f"{lon:.2f}", "current")
            api.update()
            data = api.pull()

            # Collect all hours across forecast days
            all_hours = []
            for day_key in sorted(data.get("forecast", {}).keys()):
                day = data["forecast"][day_key]
                sun = day.get("sun", {})
                astro_dark_start = sun.get("astro-dark", [None, None])[0]
                astro_dark_end   = sun.get("astro-dark", [None, None])[1]
                hours = day.get("hours", {})
                for hour_key in sorted(hours.keys(), key=int):
                    all_hours.append({
                        "hour": int(hour_key),
                        "day":  day_key,
                        "data": hours[hour_key],
                        "astro_dark_start": astro_dark_start,
                        "astro_dark_end":   astro_dark_end,
                    })

            # Filter to dark window if available
            if dark_window:
                dark_start, dark_end = dark_window
                sample = []
                for h in all_hours:
                    try:
                        # Reconstruct approximate UTC datetime for this hour
                        # Clear Outside hours are local time — use dark window
                        # overlap as best-effort filter
                        if dark_start.hour <= h["hour"] <= dark_end.hour or \
                           (dark_start.hour > dark_end.hour and
                            (h["hour"] >= dark_start.hour or
                             h["hour"] <= dark_end.hour)):
                            sample.append(h["data"])
                    except Exception:
                        continue
                if not sample:
                    sample = [h["data"] for h in all_hours[:3]]
            else:
                sample = [h["data"] for h in all_hours[:3]]

            if not sample:
                log.warning("Clear Outside returned no usable hourly data.")
                return {}

            low  = max(int(h.get("low-clouds",  0)) for h in sample)
            mid  = max(int(h.get("mid-clouds",  0)) for h in sample)
            high = max(int(h.get("high-clouds", 0)) for h in sample)
            fog  = max(int(h.get("fog",         0)) for h in sample)

            log.info("Clear Outside (dark window) — low:%d%% mid:%d%% high:%d%% fog:%d",
                     low, mid, high, fog)
            return {"low": low, "mid": mid, "high": high, "fog": fog}

        except ImportError:
            log.warning("clear-outside-apy not installed — skipping.")
            return {}
        except Exception as e:
            log.warning("Clear Outside fetch failed: %s", e)
            return {}

    # -------------------------------------------------------------------------
    # CONSENSUS
    # -------------------------------------------------------------------------

    def get_consensus(self):
        lat, lon = self.get_coordinates()
        if lat == 0.0 and lon == 0.0:
            log.error("Coordinates are 0.0 (Null Island). Cannot fetch weather.")
            return

        # Calculate tonight's dark window first
        dark_window = get_dark_window(lat, lon, self.sun_limit)

        log.info("Fetching dual-source weather for %.4f, %.4f...", lat, lon)
        om = self.fetch_open_meteo(lat, lon, dark_window)
        co = self.fetch_clear_outside(lat, lon, dark_window)

        clouds_pct   = om.get("clouds",   0)
        humidity_pct = om.get("humidity", 0)

        t = self.t
        if t["fog_abort"] and co.get("fog", 0) > 0:
            status, icon = "FOGGY",  "🌫️"
        elif om.get("precip", 0) > t["precip_limit"]:
            status, icon = "RAIN",   "🌧️"
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

        # Store dark window times for dashboard/orchestrator reference
        dark_start_str = dark_window[0].strftime("%H:%M UTC") if dark_window else "unknown"
        dark_end_str   = dark_window[1].strftime("%H:%M UTC") if dark_window else "unknown"

        state = {
            "_objective": "Dual-source weather consensus evaluated within astronomical dark window.",
            "status":       status,
            "icon":         icon,
            "clouds_pct":   int(clouds_pct),
            "humidity_pct": int(humidity_pct),
            "low_cloud":    co.get("low",  0),
            "mid_cloud":    co.get("mid",  0),
            "high_cloud":   co.get("high", 0),
            "fog":          co.get("fog",  0),
            "dark_start":   dark_start_str,
            "dark_end":     dark_end_str,
            "last_update":  time.time(),
        }

        try:
            self.weather_state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.weather_state_file, "w") as f:
                json.dump(state, f, indent=4)
            log.info(
                "Consensus: %s %s — window:%s→%s low:%d%% mid:%d%% fog:%d hum:%d%%",
                status, icon, dark_start_str, dark_end_str,
                co.get("low", 0), co.get("mid", 0),
                co.get("fog", 0), humidity_pct,
            )
        except OSError as e:
            log.error("Failed to write weather_state.json: %s", e)


if __name__ == "__main__":
    log.info("WeatherSentinel v1.6.1 starting...")
    sentinel = WeatherSentinel()
    while True:
        sentinel.get_consensus()
        time.sleep(600)
