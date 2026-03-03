#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Seestar Organizer - Target Harvester (v1.5.3)
# ----------------------------------------------------------------

import sys, os, json
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))

from core.flight.vault_manager import VaultManager

class TargetHarvester:
    def __init__(self):
        self.vault = VaultManager()
        self.obs = self.vault.get_observer_config()
        # We are now strictly hunting targets.json
        self.target_file = PROJECT_ROOT / "data" / "targets.json"

    def audit_mission(self):
        if not self.target_file.exists():
            print("[HARVESTER] Mission Profile: EMPTY (targets.json missing)")
            return

        try:
            with open(self.target_file, 'r') as f:
                targets = json.load(f)
            
            profiles = []
            for t in targets:
                # Type-Resilient Logic: Handle strings or dicts
                name = t.get('name', '') if isinstance(t, dict) else str(t)
                
                if any(tag in name for tag in ["[BAA]", "[NL]", "[FR]"]):
                    profiles.append("Scientific (Variable Stars)")
                elif any(m in name for m in ["M", "NGC", "IC"]):
                    profiles.append("DSO (Deep Sky Objects)")
                else:
                    profiles.append("General/Unknown")

            summary = Counter(profiles)
            print("--- [v1.5] CURRENT MISSION PROFILE ---")
            for profile, count in summary.items():
                print(f" > {profile}: {count} targets")
            print(f" > Location: {self.obs.get('maidenhead', 'DYNAMIC')}")
            print("--------------------------------------")
        except Exception as e:
            print(f"[FATAL] Harvester Crash: {e}")

if __name__ == "__main__":
    TargetHarvester().audit_mission()
