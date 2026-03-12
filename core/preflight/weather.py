#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/weather.py
Version: 1.4.2 (Diamond Revision)
Objective: Tri-source weather consensus daemon. 
           Feeds status, clouds_pct, and humidity_pct to the Orchestrator.
"""

import json
import time
import logging
import requests
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Sovereign Paths & Imports
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path("/home/ed/seevar")
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.env_loader import DATA_DIR
from core.flight.vault_manager import VaultManager

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("WeatherSentinel")

class WeatherSentinel:
    def __init__(self):
        self.weather_state_file = DATA_DIR / "weather_state.json"
        self.vault = VaultManager()

    def get_coordinates(self) -> tuple[float, float]:
        """
        Fetches coordinates from the VaultManager.
        Thanks to v1.4.1, this automatically handles the Live GPS RAM override!
        """
        cfg = self.vault.get_observer_config()
        return float(cfg.get("lat", 0.0)), float(cfg.get("lon", 0.0))

    def fetch_open_meteo(self, lat: float, lon: float) -> dict:
        """Fetches standard meteorological data for the next 12 hours."""
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=precipitation,cloud_cover,relative_humidity_2m,wind_speed_10m"
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.json().get('hourly', {})
            
            # Extract max values for the upcoming 12-hour window safely
            precip = max(data.get('precipitation', [0])[:12]) if data.get('precipitation') else 0
            clouds = max(data.get('cloud_cover', [0])[:12]) if data.get('cloud_cover') else 0
            humidity = max(data.get('relative_humidity_2m', [0])[:12]) if data.get('relative_humidity_2m') else 0
            wind = max(data.get('wind_speed_10m', [0])[:12]) if data.get('wind_speed_10m') else 0
            
            return {"precip": precip, "clouds": clouds, "humidity": humidity, "wind": wind}
        except Exception as e:
            log.warning("Open-Meteo fetch failed: %s", e)
            return {}

    def fetch_7timer(self, lat: float, lon: float) -> dict:
        """Fetches astronomical seeing and transparency."""
        url = f"https://www.7timer.info/bin/astro.php?lon={lon}&lat={lat}&ac=0&unit=metric&output=json&tzshift=0"
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            dataseries = r.json().get('dataseries', [])
            if not dataseries:
                return {}
                
            # Grab the worst seeing/transparency over the next 3 data points (9 hours)
            seeing = max([point.get('seeing', 1) for point in dataseries[:3]])
            transparency = max([point.get('transparency', 1) for point in dataseries[:3]])
            
            return {"seeing": seeing, "transparency": transparency}
        except Exception as e:
            log.warning("7timer fetch failed: %s", e)
            return {}

    def get_consensus(self):
        """Builds the consensus payload and writes to disk for the Orchestrator."""
        lat, lon = self.get_coordinates()
        if lat == 0.0 and lon == 0.0:
            log.error("Coordinates are 0.0 (Null Island). Cannot fetch weather.")
            return

        log.info("Fetching tri-source weather data for %s, %s...", lat, lon)
        om = self.fetch_open_meteo(lat, lon)
        astro = self.fetch_7timer(lat, lon)
        
        # Default optimistic state
        status = "CLEAR"
        icon = "✨"
        clouds_pct = om.get("clouds", 0)
        humidity_pct = om.get("humidity", 0)

        # 1. Hard Weather Aborts (Open-Meteo)
        if om.get("precip", 0) > 0.5:
            status, icon = "RAIN", "🌧️"
        elif clouds_pct > 70:
            status, icon = "CLOUDY", "☁️"
        elif humidity_pct > 90:
            status, icon = "HUMID", "💧"
        elif om.get("wind", 0) > 30:
            status, icon = "WINDY", "💨"
            
        # 2. Astronomical Downgrades (7timer)
        # 7timer scale: 1 is excellent, 8 is terrible.
        elif astro.get("seeing", 1) > 5 or astro.get("transparency", 1) > 5:
            status, icon = "POOR-SEEING", "🌫️"

        # Construct Orchestrator payload
        state = {
            "_objective": "Provides consensus weather data. Read by dashboard.py and orchestrator.py.",
            "status": status,
            "icon": icon,
            "clouds_pct": int(clouds_pct),
            "humidity_pct": int(humidity_pct),
            "last_update": time.time()
        }

        # Safe Write
        try:
            self.weather_state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.weather_state_file, 'w') as f:
                json.dump(state, f, indent=4)
            log.info("Consensus reached: %s %s (Clouds: %s%%, Humidity: %s%%)", status, icon, clouds_pct, humidity_pct)
        except OSError as e:
            log.error("Failed to write weather_state.json: %s", e)


if __name__ == "__main__":
    log.info("Starting WeatherSentinel daemon...")
    sentinel = WeatherSentinel()
    while True:
        sentinel.get_consensus()
        time.sleep(600)  # Sleep for 10 minutes between checks
