#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/utils/gps_monitor.py
Version: 1.4.0
Objective: Monitor GPSD natively via TCP socket, calculate Maidenhead, and update status.
"""

import json
import time
import sys
import socket
import os
from pathlib import Path

# Realigned to SeeVar
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))

from core.utils.observer_math import get_maidenhead_6char

STATUS_PATH = Path("/dev/shm/env_status.json")
GPSD_HOST = "127.0.0.1"
GPSD_PORT = 2947

def update_status():
    try:
        if STATUS_PATH.exists():
            with open(STATUS_PATH, "r") as f:
                status = json.load(f)
        else:
            status = {"profile": "FIELD", "gps_status": "WAITING"}

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((GPSD_HOST, GPSD_PORT))
        sock.sendall(b'?WATCH={"enable":true,"json":true}\n')
        
        file_obj = sock.makefile('r')
        for line in file_obj:
            report = json.loads(line)
            if report.get("class") == "TPV" and report.get("mode", 0) >= 3:
                lat = report.get("lat", 0.0)
                lon = report.get("lon", 0.0)
                
                status["gps_status"] = "FIXED"
                status["lat"] = round(lat, 5)
                status["lon"] = round(lon, 5)
                status["maidenhead"] = get_maidenhead_6char(lat, lon)
                status["last_update"] = time.time()
                
                with open(STATUS_PATH, "w") as f:
                    json.dump(status, f)
                print(f"✅ GPS Fix: {status['maidenhead']} ({lat}, {lon})")
                break
    except Exception as e:
        print(f"❌ GPS Monitor Error: {e}")

if __name__ == "__main__":
    update_status()
