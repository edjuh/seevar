#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/preflight/state_flusher.py
Version: 1.1.1
Objective: Preflight utility to flush stale system state and reset the dashboard to IDLE before a new flight.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger("StateFlusher")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE_FILE = PROJECT_ROOT / "data" / "system_state.json"

def flush_state():
    logger.info("🧹 Sweeping stale telemetry from system_state.json...")
    
    clean_state = {
        "#objective": "System state initialization to safe IDLE before flight operations.",
        "metadata": {
            "generated": datetime.now().isoformat(),
            "schema_version": "2026.1"
        },
        "state": "IDLE",
        "sub": "STANDBY",
        "msg": "Preflight complete. Awaiting Flight Controller...",
        "flight_log": ["✅ Preflight pipeline executed.", "⏳ Standing by for nightfall..."],
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "storage": {
            "total_gb": 0.0,
            "free_gb": 0.0,
            "percent": 0.0,
            "status": "UNKNOWN"
        }
    }
    
    with open(STATE_FILE, "w") as f:
        json.dump(clean_state, f, indent=4)
        
    logger.info("✅ Pipe flushed. Dashboard should now read IDLE.")

if __name__ == "__main__":
    flush_state()
