#!/usr/bin/env python3
import os, sys, json
from pathlib import Path

# Fix: Absolute pathing
PROJECT_ROOT = Path(__file__).resolve().parents[2]
TARGET_FILE = PROJECT_ROOT / "data" / "nightly_targets.json"

print(f"--- [REDA] LIBRARIAN PATH AUDIT ---")
print(f"Target Path: {TARGET_FILE}")
print(f"Data Dir Exists: {os.path.exists(TARGET_FILE.parent)}")
print(f"Write Permission: {os.access(TARGET_FILE.parent, os.W_OK)}")

try:
    with open(TARGET_FILE, 'w') as f:
        json.dump([{"name": "TEST_VAMPIRE", "priority": "NORMAL"}], f)
    print("[SUCCESS] Librarian successfully wrote to RAID.")
except Exception as e:
    print(f"[FATAL] Permission Denied: {e}")
