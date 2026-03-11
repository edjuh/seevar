#!/usr/bin/env python3
"""
Filename: core/utils/gps_monitor.py
Version: 1.3.0 (Monkel)
Objective: Monitor GPSD natively via TCP socket (bypassing broken pip libraries), 
           calculate the 6-character Maidenhead, and update status.
"""

import json
import time
import sys
import socket
import os
from pathlib import Path

# Ensure we can import from the project root
sys.path.append(os.path.expanduser("~/seevar"))
from core.utils.observer_math import get_maidenhead_6char

STATUS_PATH = Path("/dev/shm/env_status.json")
GPSD_HOST = "127.0.0.1"
GPSD_PORT = 2947

def update_status():
    # Load existing status or initialize
    try:
        with open(STATUS_PATH, "r") as f:
            status = json.load(f)
    except FileNotFoundError:
        status = {"profile": "FIELD", "gps_status": "WAITING"}

    try:
        # Connect to gpsd natively
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((GPSD_HOST, GPSD_PORT))
        
        # Tell gpsd to start streaming JSON data
        sock.sendall(b'?WATCH={"enable":true,"json":true}\n')
        
        # Read the stream line by line
        file_obj = sock.makefile('r')
        for line in file_obj:
            try:
                report = json.loads(line)
                
                # We are looking for TPV (Time-Position-Velocity) with a 3D Fix (mode 3)
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
                    
                    print(f"Fix Acquired: {status['maidenhead']}")
                    break # Exit the loop once a fix is established
                    
            except json.JSONDecodeError:
                continue
                
    except ConnectionRefusedError:
        print("Error: gpsd is not running or unreachable on port 2947.")
    except Exception as e:
        print(f"GPS Monitor Error: {e}")

if __name__ == "__main__":
    update_status()
