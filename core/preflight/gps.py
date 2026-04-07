#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/gps.py
Version: 1.5.1
Objective: Bi-directional GPS provider with lazy initialization. Reads from RAM status and actively syncs to config.toml via VaultManager to maintain a live last_refresh heartbeat.
"""

import json
import logging
import sys
from pathlib import Path
from astropy.coordinates import EarthLocation
import astropy.units as u

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.flight.vault_manager import VaultManager
from core.utils.env_loader import ENV_STATUS

logger = logging.getLogger("GPSProvider")
_gps_location = None

class GPSLocation:
    def __init__(self):
        self.vault = VaultManager()
        self._sync_ram_to_config()
        self._refresh_local_cache()

    def _sync_ram_to_config(self):
        """Reads latest fix from ENV_STATUS (RAM) and pushes to config.toml to bump last_refresh."""
        if not ENV_STATUS.exists():
            return

        try:
            with open(ENV_STATUS, "r") as f:
                status = json.load(f)

            if str(status.get("gps_status", "")).startswith("FIXED"):
                ram_lat = status.get("lat")
                ram_lon = status.get("lon")
                ram_mh = status.get("maidenhead")

                # Only sync if we have valid, non-Null Island coordinates
                if ram_lat and ram_lon and (ram_lat != 0.0 or ram_lon != 0.0):
                    logger.info("📡 Valid GPS fix in RAM. Syncing config.toml to bump last_refresh...")
                    self.vault.sync_gps(ram_lat, ram_lon, ram_mh or "AUTO")
        except Exception as e:
            logger.error("Failed to sync RAM GPS to config: %s", e)

    def _refresh_local_cache(self):
        # VaultManager's get_observer_config naturally merges RAM and config
        cfg = self.vault.get_observer_config()
        self.lat = cfg.get('lat', 0.0)
        self.lon = cfg.get('lon', 0.0)
        self.height = cfg.get('elevation', 0.0)

    def update_config(self, lat, lon, height=None, maidenhead=None):
        logger.info("🛰️ Synchronizing manual GPS to config: %s, %s", lat, lon)
        self.vault.sync_gps(lat, lon, maidenhead or "AUTO")
        self._refresh_local_cache()

    def get_earth_location(self):
        if self.lat == 0.0 and self.lon == 0.0:
            logger.error("❌ Reference coordinates are 0.0 (Null Island). Halting to prevent bad astronomy.")
            raise ValueError("Invalid GPS Coordinates: 0.0, 0.0")
            
        return EarthLocation(lat=self.lat * u.deg, lon=self.lon * u.deg, height=self.height * u.m)

def get_gps_location() -> GPSLocation:
    """Lazy initialization to prevent import-time crashes."""
    global _gps_location
    if _gps_location is None:
        _gps_location = GPSLocation()
    return _gps_location

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    loc = get_gps_location().get_earth_location()
    print(f"🌍 Current Federation Reference: {loc.geodetic}")
