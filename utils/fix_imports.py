#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: utils/fix_imports.py
Version: 1.2.0 (Pee Pastinakel)
Objective: Automated namespace correction utility for project-wide absolute import resolution.
"""

import os
import re

PILLAR_MAP = {
    "preflight": ["harvester", "nightly_planner", "weather", "fog_monitor", "gps", "horizon", "aavso_client", "librarian", "ephemeris", "planner", "scheduler"],
    "flight": ["orchestrator", "hardware_profiles", "sequence_engine", "vault_manager", "env_loader"],
    "postflight": ["photometry_engine", "calibration_engine", "sync_manager", "pixel_mapper", "analyst", "master_analyst", "notifier"],
    "dashboard": ["dashboard", "logger", "validator"]
}

def fix_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    new_content = content
    for pillar, modules in PILLAR_MAP.items():
        for mod in modules:
            new_content = re.sub(fr'import {mod}\b', f'from core.{pillar} import {mod}', new_content)
            new_content = re.sub(fr'from {mod} import', f'from core.{pillar}.{mod} import', new_content)
    
    if new_content != content:
        with open(filepath, 'w') as f:
            f.write(new_content)
        print(f"✅ Fixed imports in: {filepath}")

def run_repair():
    root_dir = os.path.expanduser("~/seestar_organizer/core")
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if file.endswith(".py"):
                fix_file(os.path.join(root, file))

if __name__ == "__main__":
    run_repair()
