#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/preflight/hardware_audit.py
Version: 1.3.1
Objective: Deep hardware audit using the get_event_state bus, exporting to hardware_telemetry.json for Dashboard vitals.
"""

import requests
import json
import logging
import sys
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger("PreflightAudit")

class HardwareGuard:
    def __init__(self):
        self.endpoint = "http://127.0.0.1:5555/api/v1/telescope/1/action"
        self.telemetry_path = Path("~/seevar/data/hardware_telemetry.json").expanduser()

    def _fetch_event_bus(self):
        payload = {
            "Action": "method_sync",
            "Parameters": json.dumps({"method": "get_event_state"}),
            "ClientID": "1", 
            "ClientTransactionID": "999"
        }
        try:
            response = requests.put(self.endpoint, data=payload, timeout=10)
            if response.status_code == 200:
                return response.json().get("Value", {}).get("result", {})
            return None
        except Exception as e:
            logger.error(f"Failed to reach hardware bus at {self.endpoint}: {e}")
            return None

    def run_audit(self):
        logger.info("🔍 S30-PRO FEDERATION: INITIATING EVENT-BUS AUDIT")
        bus = self._fetch_event_bus()
        
        # We do not pretend; if bus is None, link_status is OFFLINE
        link_status = "ACTIVE" if bus else "OFFLINE"
        audit_passed = False
        warnings = []
        tilt_x, tilt_y, temp = 0.0, 0.0, 0.0

        if bus:
            audit_passed = True
            balance = bus.get("BalanceSensor", {}).get("data", {})
            tilt_x = balance.get("x", 0.0)
            tilt_y = balance.get("y", 0.0)
            
            if abs(tilt_x) > 0.05 or abs(tilt_y) > 0.05:
                warnings.append(f"MOUNT_NOT_LEVEL (X:{tilt_x}, Y:{tilt_y})")
                audit_passed = False

            temp = bus.get("PiStatus", {}).get("temp", 0.0)
            if temp > 65.0:
                warnings.append(f"HIGH_CPU_TEMP ({temp}C)")

        # Generate the JSON file for the dashboard
        self.telemetry_path.parent.mkdir(parents=True, exist_ok=True)
        telemetry_payload = {
            "#objective": "Live hardware telemetry and safety audit results.",
            "timestamp": datetime.now().isoformat(),
            "passed": audit_passed,
            "link_status": link_status,
            "warnings": warnings,
            "tilt_x": tilt_x,
            "tilt_y": tilt_y,
            "temperature": temp
        }
        
        with open(self.telemetry_path, "w") as f:
            json.dump(telemetry_payload, f, indent=4)
        
        return audit_passed

if __name__ == "__main__":
    guard = HardwareGuard()
    guard.run_audit()
