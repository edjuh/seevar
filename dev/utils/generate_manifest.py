#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/utils/generate_manifest.py
Version: 1.5.2
Objective: Generate FILE_MANIFEST.md for SeeVar and mirror it to NAS for quick reference. Ignores transient runtime data caches.
"""

import os
import re
from pathlib import Path

# Dynamically resolve the SeeVar root directory (2 levels up from dev/utils)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

TARGET_DIRECTORIES = ['core', 'logic', 'tests', 'dev', 'data', 'systemd', 'catalogs']
ROOT_FILES = ['requirements.txt', 'config.toml']
IGNORE_DIRS = {'local_buffer', 'gaia_cache', 'reports', 'raw', 'archive', '__pycache__'}

MANIFEST_FILE = PROJECT_ROOT / 'dev/logic' / 'FILE_MANIFEST.md'
NAS_MANIFEST = Path("/mnt/astronas/SEE_VAR_MANIFEST.md")

def get_file_info(filepath):
    version, objective = "N/A", "No objective defined."
    if str(filepath).endswith('.json'):
        return "JSON", "Data/Configuration file."
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read(1500)
            v_match = re.search(r"Version:\s*([\d\.]+)", content)
            o_match = re.search(r"Objective:\s*(.*)", content)
            if v_match: version = v_match.group(1)
            if o_match: objective = o_match.group(1).strip()
    except: pass
    return version, objective

def generate_manifest():
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    manifest_content = "# 🔭 SeeVar: File Manifest\n\n"
    manifest_content += "> **System State**: Diamond Revision (Sovereign)\n\n"
    manifest_content += "| Path | Version | Objective |\n| :--- | :--- | :--- |\n"
    
    # 1. Process root files
    for filename in ROOT_FILES:
        full_path = PROJECT_ROOT / filename
        if full_path.exists():
            ver, obj = get_file_info(full_path)
            manifest_content += f"| {filename} | {ver} | {obj} |\n"
            
    # 2. Process target directories
    for directory in TARGET_DIRECTORIES:
        dir_path = PROJECT_ROOT / directory
        if not dir_path.exists(): continue
        
        for root, dirs, files in os.walk(dir_path):
            # Prune ignored directories in-place
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            
            for filename in sorted(files):
                if filename.startswith('.') or filename == '__init__.py' or 'reference_stars' in root: continue
                full_path = Path(root) / filename
                rel_path = full_path.relative_to(PROJECT_ROOT)
                ver, obj = get_file_info(full_path)
                manifest_content += f"| {rel_path} | {ver} | {obj} |\n"

    # Write to local repo
    with open(MANIFEST_FILE, "w", encoding='utf-8') as f:
        f.write(manifest_content)
    
    # Mirror to NAS
    try:
        with open(NAS_MANIFEST, "w", encoding='utf-8') as f:
            f.write(manifest_content)
        print(f"✅ NAS Manifest mirrored to {NAS_MANIFEST}")
    except Exception as e:
        print(f"⚠️ Could not mirror to NAS: {e}")

if __name__ == "__main__":
    generate_manifest()
    print(f"✅ Local manifest updated at {MANIFEST_FILE}")
