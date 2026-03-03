#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: utils/cleanup.py
Version: 1.2.0 (Pee Pastinakel)
Objective: Housekeeping utility for purging temporary files and rotating stale logs to prevent storage bloat.
"""

import os
import time
from pathlib import Path

def purge_temp():
    root_dir = Path(__file__).parent.parent
    log_dir = root_dir / "logs"
    print(f"🧹 Cleaning logs in {log_dir}...")
    if log_dir.exists():
        for log in log_dir.glob("*.log"):
            if time.time() - log.stat().st_mtime > 604800: # 7 days
                log.unlink()
                print(f"   🗑️ Removed stale log: {log.name}")
    print("✅ Cleanup complete.")

if __name__ == "__main__":
    purge_temp()
