#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/preflight_check.py
Version: 1.4.7 (Kriel - Grid Fix)
"""
import json, os, sys, socket, time, subprocess, re, tomllib, urllib.request
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from core.preflight.target_evaluator import TargetEvaluator

CONFIG_PATH = os.path.expanduser("~/seestar_organizer/config.toml")
SHM_STATUS = "/dev/shm/env_status.json"

def get_maidenhead_6(lat, lon):
    if lat == 0.0 or lon == 0.0: return None
    A, B = 'ABCDEFGHIJKLMNOPQR', 'ABCDEFGHIJKLMNOPQR'
    C, D = '0123456789', '0123456789'
    E, F = 'abcdefghijklmnopqrstuvwx', 'abcdefghijklmnopqrstuvwx'
    lon += 180; lat += 90
    return f"{A[int(lon/20)]}{B[int(lat/10)]}{C[int((lon%20)/2)]}{D[int(lat%10)]}{E[int((lon%2)/0.083333)]}{F[int((lat%1)/0.041666)]}"

def check_vitals():
    with open(CONFIG_PATH, "rb") as f: cfg = tomllib.load(f)
    
    # 📡 GPS - Try Live, then Config Fallback
    gps_stat, lat, lon = "WAITING", 0.0, 0.0
    try:
        with socket.create_connection(("127.0.0.1", 2947), timeout=1) as s:
            s.sendall(b'?WATCH={"enable":true,"json":true};\n')
            msg = json.loads(s.makefile().readline())
            if msg.get('class') == 'TPV' and msg.get('mode', 0) >= 2:
                gps_stat, lat, lon = "OK", msg.get('lat'), msg.get('lon')
    except: pass

    # If GPS is still hunting, use the Config coordinates for the Maidenhead
    if lat == 0.0:
        lat = cfg.get("location", {}).get("lat", 52.38)
        lon = cfg.get("location", {}).get("lon", 4.64)
    
    m_head = get_maidenhead_6(lat, lon) or cfg.get("location", {}).get("home_grid", "JO22hj")

    # ⏱️ Time Sync
    try:
        res = subprocess.check_output(['chronyc', 'tracking'], text=True)
        stratum = int(re.search(r"Stratum\s+:\s+(\d+)", res).group(1))
        pps_led = "led-green" if stratum < 16 else "led-orange"
        offset = f"{float(re.search(r'Last offset\s+:\s+([+-]?\d+\.\d+)', res).group(1))*1000:.2f}ms"
    except: pps_led, offset = "led-red", "NO SYNC"

    # 🎯 Tactical Queue
    evaluator = TargetEvaluator()
    manifest = evaluator.evaluate()

    status = {
        "maidenhead": m_head,
        "gps_led": "led-green" if gps_stat == "OK" else "led-orange",
        "pps_led": pps_led,
        "pps_offset": offset,
        "weather_led": "led-orange",
        "targets": manifest['status'],
        "targets_led": manifest['led'],
        "jd": round(2440587.5 + time.time() / 86400.0, 4),
        "bridge": "led-green" if socket.socket().connect_ex(('127.0.0.1', 5432)) == 0 else "led-red"
    }

    with open(SHM_STATUS, 'w') as f: json.dump(status, f)
    print(f"✅ Grid Locked: {m_head}")

if __name__ == "__main__":
    check_vitals()
