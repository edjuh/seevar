#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/preflight/gps.py
Version: 1.4.1
Objective: Bi-directional GPS provider with lazy initialization and Null Island protection.
"""

import logging
import sys
from pathlib import Path
from astropy.coordinates import EarthLocation
import astropy.units as u

PROJECT_ROOT = Path("/home/ed/seevar")
sys.path.insert(0, str(PROJECT_ROOT))

from core.flight.vault_manager import VaultManager

logger = logging.getLogger("GPSProvider")
_gps_location = None

class GPSLocation:
    def __init__(self):
        self.vault = VaultManager()
        self._refresh_local_cache()

    def _refresh_local_cache(self):
        cfg = self.vault.get_observer_config()
        self.lat = cfg.get('lat', 0.0)
        self.lon = cfg.get('lon', 0.0)
        self.height = cfg.get('elevation', 0.0)

    def update_config(self, lat, lon, height=None, maidenhead=None):
        logger.info("🛰️ Synchronizing hardware GPS to config: %s, %s", lat, lon)
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
    loc = get_gps_location().get_earth_location()
    print(f"🌍 Current Federation Reference: {loc.geodetic}")
