#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/utils/mount_guard.py
Version: 1.1.0
Objective: Check if /mnt/raid1 is mounted and /mnt/raid1/data exists.
"""
import os
import sys

def check_mount(mount_point, required_dir):
    # Check if the base RAID is mounted
    if not os.path.ismount(mount_point):
        return False
    # Check if the data subdirectory exists
    if not os.path.isdir(required_dir):
        return False
    return True

if __name__ == "__main__":
    BASE = "/mnt/raid1"
    DATA = "/mnt/raid1/data"
    if check_mount(BASE, DATA):
        print(f"✅ SeeVar: RAID confirmed and data folder present.")
        sys.exit(0)
    else:
        print(f"❌ SeeVar: CRITICAL - RAID not mounted or data folder missing.")
        sys.exit(1)
