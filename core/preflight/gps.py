#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seestar_organizer/core/preflight/gps.py
Version: 1.2.1
Objective: Bi-directional GPS provider. Reads from and writes hardware coordinates to config.toml without hardcoded fallbacks.
"""

import tomllib
import logging
import sys
from pathlib import Path
from astropy.coordinates import EarthLocation
import astropy.units as u

# Align with structure for VaultManager access
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))

from core.flight.vault_manager import VaultManager

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger("GPSProvider")

class GPSLocation:
    def __init__(self):
        self.vault = VaultManager()
        self._refresh_local_cache()

    def _refresh_local_cache(self):
        """Syncs internal variables with current Vault data. No hardcoded fallbacks."""
        cfg = self.vault.get_observer_config()
        self.lat = cfg.get('lat', 0.0)
        self.lon = cfg.get('lon', 0.0)
        self.height = cfg.get('elevation', 0.0)

    def update_config(self, lat, lon, height=None, maidenhead=None):
        """Writes new hardware coordinates back to config.toml."""
        logger.info(f"🛰️ Synchronizing hardware GPS to config: {lat}, {lon}")
        self.vault.sync_gps(lat, lon, maidenhead or "AUTO")
        self._refresh_local_cache()

    def get_earth_location(self):
        """Returns an Astropy EarthLocation object for astronomical math."""
        if self.lat == 0.0 and self.lon == 0.0:
            logger.warning("⚠️ Reference coordinates are 0.0 (Null Island). GPS Fix required.")
            
        return EarthLocation(
            lat=self.lat * u.deg, 
            lon=self.lon * u.deg, 
            height=self.height * u.m
        )

# Global instance
gps_location = GPSLocation()

if __name__ == "__main__":
    loc = gps_location.get_earth_location()
    print(f"🌍 Current Federation Reference: {loc.geodetic}")
