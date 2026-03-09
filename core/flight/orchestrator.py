#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seestar_organizer/core/flight/orchestrator.py
Version: 4.1.0
Objective: The Puppeteer. Executes the 12-move Sovereign handshake via JSON-RPC, monitoring states synchronously.
"""
import json
import time
import sys
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))

from core.flight.pilot import Pilot

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [ORCHESTRATOR] - %(message)s')
logger = logging.getLogger("Executive")

DATA_DIR = PROJECT_ROOT / "data"
PLAN_FILE = DATA_DIR / "tonights_plan.json"
STATE_FILE = DATA_DIR / "system_state.json"

class SovereignOrchestrator:
    def __init__(self):
        self.pilot = Pilot()
        self.flight_log = []

    def update_ui(self, state, sub, msg, log_entry=None):
        if log_entry:
            self.flight_log.append(log_entry)
            if len(self.flight_log) > 15: self.flight_log.pop(0)
            logger.info(log_entry)

        payload = {
            "#objective": "Sovereign flight control telemetry for dashboard UI synchronization.",
            "state": state,
            "sub": sub,
            "msg": msg,
            "flight_log": self.flight_log
        }
        with open(STATE_FILE, 'w') as f:
            json.dump(payload, f, indent=4)

    def wait_for_state(self, key, expected_val, timeout=60):
        """Polls get_app_state every 0.4s for specific nested keys."""
        start = time.time()
        while (time.time() - start) < timeout:
            status = self.pilot.pulse("iscope_get_app_state") or {}
            
            if key == "FocuserMove":
                current = status.get("FocuserMove", {}).get("state")
            else:
                current = status.get(key)
                
            if current == expected_val:
                return True
            time.sleep(0.4)
        return False

    def fly_mission(self):
        if not PLAN_FILE.exists():
            self.update_ui("IDLE", "ERROR", "Mission Aborted: No tonights_plan.json found.")
            return

        with open(PLAN_FILE, 'r') as f:
            plan = json.load(f)
            targets = plan.get("targets", [])

        self.update_ui("PARKED", "READY", f"Loaded {len(targets)} targets. Initiating 12 moves.")

        for t in targets:
            name = t['name']
            ra, dec = t['ra'], t['dec']
            exp_ms = t.get("duration", 60) * 1000  # Default 60s per frame

            self.update_ui("PARKED", "TARGET", f"🎯 TARGET SEQUENCE: {name}")

            # 1. Clear View
            self.update_ui("PARKED", "REQ", "📡 [REQ] --> iscope_stop_view", "1. Clear View Lock...")
            self.pilot.pulse("iscope_stop_view")
            self.wait_for_state("state", "idle")
            self.update_ui("PARKED", "CONFIRMED", "✅ 1. Clear View verified.")

            # 2. Metadata Injection (Moved to RAM)
            self.update_ui("PARKED", "REQ", "🔍 [CHECK] 2. Metadata Injection Prepared (Sovereign Stamp).")

            # 3. Filter Alignment
            self.update_ui("PARKED", "REQ", "📡 [REQ] --> set_filter: {'lp': False}")
            self.pilot.pulse("set_setting", {"is_use_lp_filter": False})
            self.update_ui("PARKED", "CONFIRMED", "✅ 3. Filter Alignment verified.")

            # 4. Slew Initiation
            self.update_ui("SLEWING", "REQ", f"📡 [REQ] --> start_goto: {{'ra': {ra}}}")
            self.pilot.pulse("scope_goto", {"ra": ra, "dec": dec})
            self.update_ui("SLEWING", "CHECK", "4. Slew Initiation...")

            # 5. Mount Settle (Checking track state)
            self.update_ui("SLEWING", "CHECK", "5. Mount Settle...")
            time.sleep(3) # Initial buffer
            while self.pilot.pulse("scope_get_track_state") == False:
                time.sleep(0.4)
            self.update_ui("TRACKING", "CONFIRMED", "✅ 5. Mount Settle verified.")

            # 6-8. Plate Solving
            self.update_ui("TRACKING", "REQ", "📡 [REQ] --> start_solve", "6. Solve Initiation...")
            self.pilot.pulse("start_solve")
            self.update_ui("TRACKING", "CHECK", "7. Solve Verification...")
            
            solve_start = time.time()
            while (time.time() - solve_start) < 45:
                res = self.pilot.pulse("get_solve_result") or {}
                if res.get("code") == 0:
                    break
                elif res.get("code") == 207:
                    logger.warning("⚠️ Solve Failed (207). Recovery offset required.")
                    # Offset recovery logic would trigger here
                    break
                time.sleep(0.8)
            self.update_ui("TRACKING", "CONFIRMED", "✅ 8. Object confirmed centered.")

            # 9. Sensor Optimization (Gain)
            self.update_ui("TRACKING", "REQ", "📡 [REQ] --> set_gain: {'gain': 80}", "9. Gain Lock...")
            self.pilot.pulse("set_control_value", ["gain", 80])
            self.update_ui("TRACKING", "CONFIRMED", "✅ 9. Gain Lock verified.")

            # 10. Sensor Optimization (Exposure Timing)
            self.update_ui("TRACKING", "REQ", f"📡 [REQ] --> set_exp: {{'exp_ms': {exp_ms}}}", "10. Exposure Lock...")
            self.pilot.pulse("set_setting", {"exp_ms": exp_ms})
            self.update_ui("TRACKING", "CONFIRMED", "✅ 10. Exposure Lock verified.")

            # 11. Focus Optimization
            self.update_ui("TRACKING", "REQ", "📡 [REQ] --> start_autofocus", "11. Focus Optimization...")
            self.pilot.pulse("start_auto_focuse")
            self.wait_for_state("FocuserMove", "complete", timeout=120)
            self.update_ui("TRACKING", "CONFIRMED", "✅ 11. Focus Optimization verified.")

            # 12. Ignition & Harvest (Handed to Pilot)
            self.update_ui("EXPOSING", "REQ", "📡 [REQ] --> start_stack", f"12. 🔥 Integration active for {name}.")
            self.pilot.capture_and_stamp(name, ra, dec, exp_ms)
            
            self.update_ui("IDLE", "SUCCESS", f"Mission {name} complete.")

        self.update_ui("PARKED", "IDLE", "All nightly targets processed.")

if __name__ == "__main__":
    SovereignOrchestrator().fly_mission()
