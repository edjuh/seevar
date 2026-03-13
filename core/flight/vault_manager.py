#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/flight/vault_manager.py
Version: 1.4.1
Objective: Secure metadata access with actual bi-directional tomli_w syncing.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.env_loader import ENV_STATUS, CONFIG_PATH, load_config

logger = logging.getLogger("VaultManager")

class VaultManager:
    def __init__(self):
        self.data = load_config()

    def get_observer_config(self):
        aavso = self.data.get("aavso", {})
        loc = self.data.get("location", {})
        planner = self.data.get("planner", {})
        
        lat = loc.get("lat", 0.0)
        lon = loc.get("lon", 0.0)
        maidenhead = loc.get("maidenhead", "AUTO")
        last_refresh = loc.get("last_refresh", "NEVER")
        
        observer_id = aavso.get("observer_code")
        if not observer_id:
            logger.error("❌ observer_code missing from config.toml — AAVSO submissions will be invalid")
            observer_id = "MISSING_ID"
            
        if ENV_STATUS.exists():
            try:
                with open(ENV_STATUS, "r") as f:
                    live = json.load(f)
                    if live.get("gps_status") == "FIXED":
                        lat = live.get("lat", lat)
                        lon = live.get("lon", lon)
                        maidenhead = live.get("maidenhead", maidenhead)
                        timestamp = live.get("last_update")
                        if timestamp:
                            last_refresh = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("⚠️ GPS RAM override read failed: %s", e)
        
        return {
            "observer_id": observer_id,
            "maidenhead": maidenhead,
            "lat": lat,
            "lon": lon,
            "elevation": loc.get("elevation", 0.0),
            "sun_altitude_limit": planner.get("sun_altitude_limit", -18.0),
            "last_refresh": last_refresh
        }

    def sync_gps(self, lat: float, lon: float, maidenhead: str):
        """Write GPS fix back to config.toml location block."""
        try:
            import tomli_w
        except ImportError:
            logger.error("❌ 'tomli-w' not installed. Cannot sync GPS to config. Run: pip install tomli-w")
            return

        self.data.setdefault("location", {})
        self.data["location"]["lat"] = lat
        self.data["location"]["lon"] = lon
        self.data["location"]["maidenhead"] = maidenhead
        self.data["location"]["last_refresh"] = datetime.now(timezone.utc).isoformat()
        
        try:
            with open(CONFIG_PATH, "wb") as f:
                tomli_w.dump(self.data, f)
            logger.info("✅ GPS sync successful: config.toml updated.")
        except OSError as e:
            logger.error("❌ Failed to write config.toml: %s", e)
