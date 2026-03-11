#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/preflight/gps.py
Version: 1.3.0
Objective: Bi-directional GPS provider realigned for SeeVar.
"""

import logging
import sys
from pathlib import Path
from astropy.coordinates import EarthLocation
import astropy.units as u

# Resolve SeeVar root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))

from core.flight.vault_manager import VaultManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger("GPSProvider")

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
        logger.info(f"🛰️ Syncing GPS to config: {lat}, {lon}")
        self.vault.sync_gps(lat, lon, maidenhead or "AUTO")
        self._refresh_local_cache()

    def get_earth_location(self):
        return EarthLocation(
            lat=self.lat * u.deg, 
            lon=self.lon * u.deg, 
            height=self.height * u.m
        )
