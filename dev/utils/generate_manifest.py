#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/utils/generate_manifest.py
Version: 1.5.0
Objective: Generate FILE_MANIFEST.md for SeeVar and mirror it to NAS for quick reference.
"""

import os
import re

BASE_DIR = "/home/ed/seevar"
TARGET_DIRECTORIES = ['core', 'logic', 'tests', 'utils', 'data', 'systemd', 'catalogs']
MANIFEST_FILE = os.path.join(BASE_DIR, 'logic/FILE_MANIFEST.md')
NAS_MANIFEST = "/mnt/astronas/SEE_VAR_MANIFEST.md"

def get_file_info(filepath):
    version, objective = "N/A", "No objective defined."
    if filepath.endswith('.json'):
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
    os.makedirs(os.path.dirname(MANIFEST_FILE), exist_ok=True)
    manifest_content = "# 🔭 SeeVar: File Manifest\n\n"
    manifest_content += "> **System State**: Diamond Revision (Sovereign)\n\n"
    manifest_content += "| Path | Version | Objective |\n| :--- | :--- | :--- |\n"
    
    for directory in TARGET_DIRECTORIES:
        dir_path = os.path.join(BASE_DIR, directory)
        if not os.path.exists(dir_path): continue
        for root, _, files in os.walk(dir_path):
            for filename in sorted(files):
                if filename.startswith('.') or filename == '__init__.py' or 'reference_stars' in root: continue
                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(full_path, BASE_DIR)
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
