#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/weather.py
Version: 2.0.2
Objective: Tri-Source Emoticon Aggregator for astronomical weather prediction (Strictly Dynamic Coordinates).
"""

import json, os, sys, urllib.request, tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))
from core.flight.vault_manager import VaultManager

class WeatherSentinel:
    def __init__(self):
        self.vault = VaultManager()
        self.seeing_cache = PROJECT_ROOT / "core/flight/data/seeing_cache.json"
        self.weather_state = PROJECT_ROOT / "data/weather_state.json"
        self.lat, self.lon = self.get_coordinates()

    def get_coordinates(self):
        """Strictly parses config.toml for coordinates. Zero hardcoding."""
        config_path = PROJECT_ROOT / "config.toml"
        if config_path.exists():
            try:
                with open(config_path, "rb") as f:
                    cfg = tomllib.load(f)
                    
                    # 1. Check [location] block
                    loc = cfg.get("location", {})
                    if "lat" in loc and "lon" in loc:
                        return float(loc["lat"]), float(loc["lon"])
                        
                    # 2. Check [observer] block
                    obs = cfg.get("observer", {})
                    if "lat" in obs and "lon" in obs:
                        return float(obs["lat"]), float(obs["lon"])
            except: pass
        
        # Absolute fallback: Null Island
        return 0.0, 0.0

    def get_open_meteo(self):
        """Source 1: Open-Meteo (Precipitation, Wind, Clouds)"""
        if self.lat == 0.0 and self.lon == 0.0: return None
        try:
            url = f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&hourly=precipitation,cloudcover,windspeed_10m,temperature_2m&forecast_days=1"
            req = urllib.request.Request(url, headers={'User-Agent': 'S30-Federation/2.0'})
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read().decode())
                precip = max(data['hourly']['precipitation'][:12])
                clouds = max(data['hourly']['cloudcover'][:12])
                wind = max(data['hourly']['windspeed_10m'][:12])
                temp = min(data['hourly']['temperature_2m'][:12])
                return {"precip": precip, "clouds": clouds, "wind": wind, "temp": temp}
        except: return None

    def get_7timer(self):
        """Source 2: 7Timer! (Astronomical Transparency & Clouds)"""
        if self.lat == 0.0 and self.lon == 0.0: return None
        try:
            url = f"https://www.7timer.info/bin/astro.php?lon={self.lon}&lat={self.lat}&ac=0&unit=metric&output=json"
            req = urllib.request.Request(url, headers={'User-Agent': 'S30-Federation/2.0'})
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read().decode())
                worst_cloud = max([tp['cloudcover'] for tp in data['dataseries'][:4]])
                precip = any(tp['prec_type'] != 'none' for tp in data['dataseries'][:4])
                return {"astro_cloud": worst_cloud, "precip": precip}
        except: return None

    def get_consensus(self):
        # Source 3: Local Meteoblue Cache
        transparency = "AVERAGE"
        if self.seeing_cache.exists():
            try:
                with open(self.seeing_cache, 'r') as f:
                    transparency = json.load(f).get("transparency", "AVERAGE")
            except: pass

        om = self.get_open_meteo()
        st = self.get_7timer()

        is_storm = False
        is_precip = False
        is_snow = False
        is_cloudy = False

        if om:
            if om['wind'] > 40 or om['precip'] > 10: is_storm = True
            elif om['precip'] > 0:
                is_precip = True
                if om['temp'] <= 0: is_snow = True
            elif om['clouds'] > 50: is_cloudy = True
        
        if st:
            if st['precip']: is_precip = True
            if st['astro_cloud'] >= 6: is_cloudy = True

        if transparency == "HAZY" and not (is_storm or is_precip):
            is_cloudy = True

        if self.lat == 0.0 and self.lon == 0.0:
            icon, text = "🌍", "NO GPS"
        elif is_storm:
            icon, text = "⛈️", "STORM WARNING"
        elif is_snow:
            icon, text = "❄️", "SNOW"
        elif is_precip:
            icon, text = "🌧️", "RAIN"
        elif is_cloudy:
            icon, text = "☁️", "CLOUDY"
        else:
            icon, text = "⭐", "CLEAR"

        state = {"status": text, "icon": icon}
        with open(self.weather_state, 'w') as f:
            json.dump(state, f)
        
        print(f"--- SKY AUDIT: {text} {icon} ---")
        return state

if __name__ == "__main__":
    WeatherSentinel().get_consensus()
