#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/vault_manager.py
Version: 1.3.0
Objective: Manages secure access to observational metadata. Implements Live GPS RAM Override.
"""

import os
import json
import logging
import tomllib
from datetime import datetime

logger = logging.getLogger("VaultManager")

class VaultManager:
    def __init__(self):
        self.config_path = os.path.expanduser("~/seestar_organizer/config.toml")
        self.live_gps_path = "/dev/shm/env_status.json"
        self.data = self._load_config()

    def _load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "rb") as f:
                    return tomllib.load(f)
            except Exception as e:
                logger.error(f"❌ VaultManager failed to parse config.toml: {e}")
                return {}
        logger.warning(f"⚠️ config.toml not found at {self.config_path}")
        return {}

    def get_observer_config(self):
        aavso = self.data.get("aavso", {})
        loc = self.data.get("location", {})
        planner = self.data.get("planner", {})
        
        # 1. Base Config Fallbacks (From config.toml)
        lat = loc.get("lat", 52.3874)
        lon = loc.get("lon", 4.6462)
        maidenhead = loc.get("maidenhead", "JO22hj")
        
        # 2. Live GPS Override (From gps_monitor.py RAM disk)
        if os.path.exists(self.live_gps_path):
            try:
                with open(self.live_gps_path, "r") as f:
                    live = json.load(f)
                    if live.get("gps_status") == "FIXED":
                        lat = live.get("lat", lat)
                        lon = live.get("lon", lon)
                        maidenhead = live.get("maidenhead", maidenhead)
            except Exception:
                pass
        
        return {
            "observer_id": aavso.get("observer_code", "MISSING_ID"),
            "maidenhead": maidenhead,
            "lat": lat,
            "lon": lon,
            "elevation": loc.get("elevation", 0.0),
            "sun_altitude_limit": planner.get("sun_altitude_limit", -18.0),
            "last_refresh": loc.get("last_refresh", "NEVER")
        }
