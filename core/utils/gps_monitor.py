#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/utils/gps_monitor.py
Version: 1.4.1
Objective: Continuous native GPSD socket monitor with resource safety and logging.
"""

import json
import time
import sys
import socket
import logging
from pathlib import Path

PROJECT_ROOT = Path("/home/ed/seevar")
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.env_loader import ENV_STATUS
from core.utils.observer_math import get_maidenhead_6char

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("GPSMonitor")

GPSD_HOST = "127.0.0.1"
GPSD_PORT = 2947

def update_status():
    status = {"profile": "FIELD", "gps_status": "WAITING"}
    if ENV_STATUS.exists():
        try:
            with open(ENV_STATUS, "r") as f:
                status.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(30.0)
            sock.connect((GPSD_HOST, GPSD_PORT))
            sock.sendall(b'?WATCH={"enable":true,"json":true}\n')
            
            with sock.makefile('r') as file_obj:
                for line in file_obj:
                    try:
                        report = json.loads(line)
                        if report.get("class") == "TPV" and report.get("mode", 0) >= 3:
                            status["gps_status"] = "FIXED"
                            status["lat"] = round(report.get("lat", 0.0), 5)
                            status["lon"] = round(report.get("lon", 0.0), 5)
                            status["maidenhead"] = get_maidenhead_6char(status["lat"], status["lon"])
                            status["last_update"] = time.time()
                            
                            with open(ENV_STATUS, "w") as f:
                                json.dump(status, f)
                            
                            log.info("✅ Fix Acquired: %s (%s, %s)", status['maidenhead'], status['lat'], status['lon'])
                            break
                    except json.JSONDecodeError:
                        continue
                        
    except socket.timeout:
        log.warning("Socket read timed out waiting for GPSD data.")
    except ConnectionRefusedError:
        log.error("gpsd is not running or unreachable on port %s.", GPSD_PORT)
    except Exception as e:
        log.error("GPS Monitor Error: %s", e)

if __name__ == "__main__":
    log.info("Starting continuous GPS monitoring daemon...")
    while True:
        update_status()
        time.sleep(60)
