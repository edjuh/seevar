#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/preflight/preflight_checklist.py
Version: 1.0.1
Objective: Verify bridge connectivity, mount orientation, and imaging pipeline status prior to flight.
"""

import os
import sys
import importlib.util

# Project root discovery
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MOUNT_PATH = os.path.join(BASE_DIR, "core/flight/mount_control.py")
CAMERA_PATH = os.path.join(BASE_DIR, "core/flight/camera_control.py")

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def main():
    print("🚀 Initiating Preflight Checklist...\n")
    
    try:
        mount = load_module("mount_control", MOUNT_PATH)
        cam = load_module("camera_control", CAMERA_PATH)
    except Exception as e:
        print(f"❌ [FAIL] Core module load error: {e}")
        sys.exit(1)

    # Pillar 1: Situational Awareness
    print("🛰️ Pillar 1: Mount Orientation")
    coords = mount.get_mount_coords()
    if coords and coords.get("ra") is not None:
        print(f"  ✅ SUCCESS: RA {coords['ra']:.4f} | DEC {coords['dec']:.4f}")
    else:
        print("  ❌ FAIL: Could not secure equatorial coordinates.")

    # Pillar 2: Imaging Pipeline
    print("\n📸 Pillar 2: Imaging Pipeline Status")
    view_state = cam.get_view_status()
    if view_state and isinstance(view_state, dict):
        view_data = view_state.get("result", {}).get("View", {})
        state = view_data.get("state", "Unknown")
        mode = view_data.get("mode", "Unknown")
        print(f"  ✅ SUCCESS: State [{state}] | Mode [{mode}]")
    else:
        print("  ❌ FAIL: Could not retrieve view state.")

    print("\n✨ Preflight routine complete.")

if __name__ == "__main__":
    main()
