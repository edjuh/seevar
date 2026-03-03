#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: utils/audit_setup.py
Version: 1.2.0 (Pee Pastinakel)
Objective: Dumps current Horizon and Target configuration for architectural review.
"""

import toml
import os

def audit():
    config_path = os.path.expanduser("~/seestar_organizer/config.toml")
    print("\n🔍 === VIRTUAL SETUP AUDIT ===")
    
    if not os.path.exists(config_path):
        print("❌ ERROR: config.toml not found.")
        return

    config = toml.load(config_path)
    planner = config.get("planner", {})
    horizon_file = planner.get("horizon_profile", "NOT_DEFINED")
    print(f"📍 Horizon Profile : {horizon_file}")
    
    target_dir = config.get("storage", {}).get("target_dir", "~/seestar_organizer/data/targets")
    target_path = os.path.expanduser(target_dir)
    print(f"🎯 Target Directory : {target_path}")
    
    if os.path.exists(target_path):
        files = os.listdir(target_path)
        print(f"📂 Found {len(files)} target files: {files[:5]}...")
    else:
        print("⚠️  WARNING: Target directory does not exist.")

    plan_path = os.path.expanduser("~/seestar_organizer/core/flight/data/nightly_plan.json")
    if os.path.exists(plan_path):
        print(f"📋 Nightly Plan    : FOUND ({os.path.getmtime(plan_path)} modified)")
    else:
        print("📋 Nightly Plan    : NOT GENERATED YET")
        
    print("==============================\n")

if __name__ == "__main__":
    audit()
