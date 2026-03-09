#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seestar_organizer/core/preflight/disk_monitor.py
Version: 1.1.2
Objective: Verifies storage availability. Respects location context: NAS is only audited when on the Home Grid.
"""

import os
import shutil
import sys
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.toml"
sys.path.append(str(PROJECT_ROOT))
from core.flight.vault_manager import VaultManager

class DiskMonitor:
    def __init__(self):
        self.vault = VaultManager()
        
        try:
            with open(CONFIG_PATH, "rb") as f:
                self.config = tomllib.load(f)
        except Exception:
            self.config = {}

        self.storage_cfg = self.config.get("storage", {})
        self.net_cfg = self.config.get("network", {})
        self.loc_cfg = self.config.get("location", {})
        
        self.nas_dir = self.storage_cfg.get("primary_dir", "/mnt/astro_nas/organized_fits")
        self.usb_dir = self.storage_cfg.get("source_dir", "/home/ed/seestar_downloads")
        
        # Grid Check (Strictly dynamic fallbacks)
        self.home_grid = self.net_cfg.get("home_grid", "NONE").upper()
        self.current_grid = self.loc_cfg.get("maidenhead", "UNKNOWN").upper()

    def _check_space(self, path):
        if not os.path.exists(path):
            return False, 0.0
        try:
            total, used, free = shutil.disk_usage(path)
            if total == 0:
                return False, 0.0
            return True, (free / total) * 100
        except Exception:
            return False, 0.0

    def check_vitals(self):
        usb_ok, usb_free = self._check_space(self.usb_dir)
        led = "led-green"
        status_text = []

        # 1. NAS Logic (Only if on Home Grid and we actually have a valid grid)
        if self.home_grid != "NONE" and self.current_grid.startswith(self.home_grid[:4]):
            nas_ok, nas_free = self._check_space(self.nas_dir)
            if not nas_ok:
                led = "led-red"
                status_text.append("NAS: ERR")
            elif nas_free < 5.0:
                led = "led-red"
                status_text.append(f"NAS: {int(nas_free)}%!")
            else:
                if nas_free < 20.0 and led != "led-red": led = "led-orange"
                status_text.append(f"NAS: {int(nas_free)}%")
        else:
            status_text.append("NAS: OFFSITE")

        # 2. USB/Buffer Logic (Always checked)
        if not usb_ok:
            led = "led-red"
            status_text.append("USB: ERR")
        elif usb_free < 5.0:
            led = "led-red"
            status_text.append(f"USB: {int(usb_free)}%!")
        else:
            if usb_free < 20.0 and led != "led-red": led = "led-orange"
            status_text.append(f"USB: {int(usb_free)}%")

        return {"status": " | ".join(status_text), "led": led}

if __name__ == "__main__":
    monitor = DiskMonitor()
    print(monitor.check_vitals())
