#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seestar_organizer/core/preflight/sync_location.py
Version: 1.3.1
Objective: Synchronize S30 location using dynamic config coordinates to the verified open Port 80.
"""

import requests
import time
import tomllib
import os
from pathlib import Path

def load_config(path_str):
    path = Path(os.path.expanduser(path_str))
    if path.exists():
        try:
            with open(path, "rb") as f:
                return tomllib.load(f)
        except Exception:
            pass
    return {}

def get_seestar_ip():
    alp = load_config("~/seestar_alp/device/config.toml")
    if ip := alp.get("device", {}).get("ip"): return ip
    
    org = load_config("~/seestar_organizer/config.toml")
    if ip := org.get("seestar", {}).get("ip"): return ip
    
    return "127.0.0.1" # Safe fallback

def sync_hardware():
    config = load_config("~/seestar_organizer/config.toml")
    loc = config.get("location", {})
    lat = loc.get("lat", 0.0)
    lon = loc.get("lon", 0.0)
    
    s30_ip = get_seestar_ip()
    port = 80
    
    print(f"🌍 Pushing dynamic coordinates ({lat}, {lon}) to {s30_ip}:{port}...")
    
    payload = {
        "lat": lat,
        "lon": lon,
        "timezone": "Europe/Amsterdam",
        "timestamp": int(time.time())
    }
    
    try:
        url = f"http://{s30_ip}:{port}/api/location"
        response = requests.post(url, json=payload, timeout=5)
        
        if response.status_code == 200:
            print("✅ Success! Hardware location synchronized.")
        else:
            print(f"⚠️ Port 80 rejected JSON. Trying legacy GET params...")
            fallback_url = f"http://{s30_ip}:{port}/api/set_location?lat={lat}&lon={lon}"
            requests.get(fallback_url, timeout=5)
            print("✅ Legacy command sent to Port 80.")

    except Exception as e:
        print(f"❌ Failed to reach {s30_ip}:{port}: {e}")

if __name__ == "__main__":
    sync_hardware()
