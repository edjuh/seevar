#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Filename: core/preflight/weather_audit.py
# Version: 1.4.17 (Infrastructure Baseline)
# Objective: Queries local weather APIs based on dynamic GPS data to enforce the maximum cloud cover safety gate.
# -----------------------------------------------------------------------------
import os
import sys
import json
import urllib.request
import tomllib

# Resolve project paths dynamically
PROJECT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
CONFIG_FILE = os.path.join(PROJECT_DIR, 'config.toml')
SHM_FILE = "/dev/shm/discovery.json"

def get_coordinates(config):
    """Pulls live GPS from RAM-disk, falls back to config.toml."""
    if os.path.exists(SHM_FILE):
        try:
            with open(SHM_FILE, 'r') as f:
                data = json.load(f)
                if data.get("status") == "LOCKED":
                    return data.get("lat"), data.get("lon")
        except Exception as e:
            print(f"[WARNING] Could not read live GPS: {e}")
    
    # Fallback to config if GPS module is offline
    print("[WARNING] Live GPS not found. Falling back to config.toml coordinates.")
    return config.get("location", {}).get("lat", 51.4779), config.get("location", {}).get("lon", -0.0015)

def check_open_meteo(lat, lon, max_clouds):
    """Queries the free Open-Meteo API for current cloud cover."""
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=cloud_cover"
    try:
        req = urllib.request.urlopen(url, timeout=5.0)
        data = json.loads(req.read().decode())
        cloud_cover = data.get("current", {}).get("cloud_cover", 100)
        
        print(f"[BLOCK 3] Weather provider 'open-meteo' reports {cloud_cover}% cloud cover.")
        if cloud_cover > max_clouds:
            print(f"[FATAL] Cloud cover ({cloud_cover}%) exceeds safety limit ({max_clouds}%).")
            return False
        return True
    except Exception as e:
        print(f"[FATAL] Weather API unreachable: {e}")
        return False

def run_audit():
    print("=======================================================")
    print("[BLOCK 3] Initiating Weather Sentinel...")
    
    if not os.path.exists(CONFIG_FILE):
        print(f"[FATAL] Missing configuration: {CONFIG_FILE}. Run setup_wizard.py.")
        sys.exit(1)
        
    with open(CONFIG_FILE, "rb") as f:
        config = tomllib.load(f)
        
    weather_cfg = config.get("weather", {})
    provider = weather_cfg.get("provider", "open-meteo")
    max_clouds = weather_cfg.get("max_cloud_cover_pct", 50.0)
    
    lat, lon = get_coordinates(config)
    print(f"[BLOCK 3] Checking sky conditions for Lat: {lat:.4f}, Lon: {lon:.4f}")
    
    safe_to_fly = False
    if provider == "open-meteo":
        safe_to_fly = check_open_meteo(lat, lon, max_clouds)
    else:
        print(f"[WARNING] Provider '{provider}' not fully implemented. Defaulting to safe=False.")
        
    if safe_to_fly:
        print("[OK] Sky is clear enough for acquisition.")
        print("=======================================================")
        sys.exit(0)
    else:
        print("[RED] Mission scrubbed due to weather constraints.")
        print("=======================================================")
        sys.exit(1)

if __name__ == "__main__":
    run_audit()
