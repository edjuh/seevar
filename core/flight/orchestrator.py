#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Objective: Single-Point Flight Master. 
Logic: Safety -> Manifest Audit -> Sequencing -> Alpaca Injection.
Path: ~/seestar_organizer/core/flight/orchestrator.py
Version: 2.0.0 (Federation Standard)
"""

import os
import sys
import json
import time
import requests
import logging
import socket
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger("FlightMaster")

class FlightMaster:
    def __init__(self):
        self.root = Path(__file__).resolve().parents[2]
        self.plan_path = self.root / "data/tonights_plan.json"
        self.state_file = self.root / "core/flight/data/system_state.json"
        self.bridge_url = "http://127.0.0.1:5432/0/schedule" # Alpaca Proxy Port

    def _check_safety(self):
        """Absorbs preflight_check.py vitals."""
        # Simple Bridge Check
        try:
            with socket.create_connection(("127.0.0.1", 5432), timeout=1):
                logger.info("📡 Alpaca Bridge: ONLINE")
                return True
        except:
            logger.error("❌ Alpaca Bridge: OFFLINE. Port 5432 unreachable.")
            return False

    def _audit_manifest(self):
        """Verifies Librarian's stamps before flight."""
        if not self.plan_path.exists():
            logger.error(f"❌ No plan found at {self.plan_path}")
            return None

        with open(self.plan_path, 'r') as f:
            plan = json.load(f)

        header = plan.get("header", {})
        today = datetime.now().strftime("%Y-%m-%d")
        
        if header.get("$date") != today:
            logger.warning(f"⚠️ Plan Date Mismatch: Plan is {header.get('$date')}, Today is {today}")
            # In a real mission, we might abort here. For now, we log it.

        targets = plan.get("targets", [])
        logger.info(f"📋 Manifest Verified: {len(targets)} targets for {today}.")
        return targets

    def inject_to_bridge(self, targets):
        """Absorbs block_injector.py logic."""
        logger.info("💉 Injecting science blocks to Seestar queue...")
        # Clear existing schedule for a clean start
        try:
            requests.post(f"{self.bridge_url}/clear", timeout=2)
        except: pass

        for t in targets:
            name = t.get('star_name') or t.get('name')
            try:
                # Dispatch sequence: Startup -> Image -> Dark
                requests.post(f"{self.bridge_url}/startup", data={"auto_focus":"on","dark_frames":"off"})
                requests.post(f"{self.bridge_url}/image", data={
                    "targetName": name, 
                    "ra": t['ra'], 
                    "dec": t['dec'],
                    "useJ2000": "on", 
                    "panelTime": "240", 
                    "gain": "80", 
                    "action": "append"
                })
                logger.info(f"  ✅ Dispatched: {name}")
            except Exception as e:
                logger.error(f"  ❌ Failed to inject {name}: {e}")

    def run_mission(self):
        print("\n" + "="*50)
        print("🚀 S30-PRO FEDERATION: FLIGHT MASTER STARTING")
        print("="*50)

        if not self._check_safety(): return
        
        targets = self._audit_manifest()
        if not targets: return

        # Handover to bridge
        self.inject_to_bridge(targets)

        print("\n" + "="*50)
        print("🏁 FLIGHT MASTER: MISSION DISPATCHED")
        print("="*50 + "\n")

if __name__ == "__main__":
    FlightMaster().run_mission()
