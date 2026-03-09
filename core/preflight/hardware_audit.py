#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seestar_organizer/core/preflight/hardware_audit.py
Version: 1.2.1
Objective: Deep hardware audit using the get_event_state bus to catch internal ZWO errors (501/502).
"""

import requests
import json
import logging
import sys
import tomllib
import os
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger("PreflightAudit")

class HardwareGuard:
    def __init__(self):
        self.endpoint = f"http://{self._get_bridge_ip()}:5555/api/v1/telescope/1/action"

    def _get_bridge_ip(self):
        """Retrieves bridge IP from configs; defaults to localhost for the Alpaca bridge."""
        paths = ["~/seestar_alp/device/config.toml", "~/seestar_organizer/config.toml"]
        for p in paths:
            path = Path(os.path.expanduser(p))
            if path.exists():
                try:
                    with open(path, "rb") as f:
                        cfg = tomllib.load(f)
                        if ip := cfg.get("device", {}).get("ip") or cfg.get("network", {}).get("nas_ip"):
                            return ip
                except Exception:
                    continue
        return "127.0.0.1"

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
        
        if not bus:
            logger.error("❌ Hardware Unresponsive. Check Alpaca Bridge status.")
            return False

        audit_passed = True
        warnings = []

        balance = bus.get("BalanceSensor", {}).get("data", {})
        tilt_x = balance.get("x", 0.0)
        tilt_y = balance.get("y", 0.0)
        
        if abs(tilt_x) > 0.05 or abs(tilt_y) > 0.05:
            warnings.append(f"MOUNT_NOT_LEVEL (X:{tilt_x}, Y:{tilt_y})")
            audit_passed = False

        track_error = bus.get("ScopeTrack", {}).get("code", 0)
        goto_error = bus.get("AutoGotoStep", {}).get("code", 0)
        
        if track_error == 502:
            warnings.append("MOUNT_SYNC_FAILED (Code 502)")
            audit_passed = False
        if goto_error == 501:
            warnings.append("MOUNT_GOTO_FAILED (Code 501)")
            audit_passed = False

        temp = bus.get("PiStatus", {}).get("temp", 0.0)
        if temp > 65.0:
            warnings.append(f"HIGH_CPU_TEMP ({temp}C)")

        if not audit_passed:
            logger.error(f"🛑 AUDIT FAILED: {', '.join(warnings)}")
        else:
            if warnings:
                logger.warning(f"⚠️ AUDIT PASSED WITH WARNINGS: {', '.join(warnings)}")
            else:
                logger.info("🟢 HARDWARE NOMINAL: All systems green.")
        
        return audit_passed

if __name__ == "__main__":
    guard = HardwareGuard()
    if not guard.run_audit():
        sys.exit(1)
