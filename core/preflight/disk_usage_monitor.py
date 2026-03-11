#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/preflight/disk_usage_monitor.py
Version: 1.1.1
Objective: Monitor S30 internal storage via SMB mount and update system state with Go/No-Go veto.
"""

import shutil
import json
import logging
import sys
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger("DiskMonitor")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
S30_MOUNT = PROJECT_ROOT / "s30_storage"
STATE_FILE = PROJECT_ROOT / "data" / "system_state.json"

def check_storage():
    logger.info("💾 Checking S30 Internal Storage...")
    
    if not S30_MOUNT.exists():
        logger.error(f"❌ Mount point missing: {S30_MOUNT}")
        return False

    try:
        stat = shutil.disk_usage(S30_MOUNT)
        total_gb = stat.total / (1024**3)
        free_gb = stat.free / (1024**3)
        percent_used = (stat.used / stat.total) * 100

        logger.info(f"📊 Storage: {percent_used:.1f}% used ({free_gb:.1f} GB free of {total_gb:.1f} GB)")

        # Update system_state.json
        state = {}
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, 'r') as f:
                    state = json.load(f)
            except json.JSONDecodeError:
                state = {}
        
        # Ensure root-level objective is present
        state["#objective"] = "Live system telemetry and hardware state tracking."
        state["storage"] = {
            "percent_used": round(percent_used, 2),
            "free_gb": round(free_gb, 2),
            "status": "NOMINAL" if percent_used < 90 else "CRITICAL"
        }

        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=4)

        # Veto Logic
        if percent_used > 95.0:
            logger.error("🛑 DISK SPACE CRITICAL: Delete old FITS files before proceeding.")
            return False
        
        return True

    except Exception as e:
        logger.error(f"❌ Storage check failed: {e}")
        return False

if __name__ == "__main__":
    if not check_storage():
        sys.exit(1)
