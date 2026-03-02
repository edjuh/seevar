#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: utils/generate_manifest.py
Version: 2.0.0 (Federation Merged)
Objective: Audits both Python scripts (via regex) and JSON data (via internal keys), then mirrors to NAS.
"""

import os, re, json, shutil
from pathlib import Path
from datetime import datetime

ROOT_DIR = os.path.expanduser("~/seestar_organizer")
MANIFEST_PATH = os.path.join(ROOT_DIR, "FILE_MANIFEST.md")
NAS_DIR = "/mnt/astronas/"

def get_script_objective(filepath):
    """Extracts 'Objective:' from Python file headers."""
    try:
        with open(filepath, 'r') as f:
            content = f.read(2000)
            match = re.search(r'Objective:\s*([^"\n\r]+)', content, re.IGNORECASE)
            if match:
                return match.group(1).strip()
    except: pass
    return "No script objective defined."

def get_json_details(filepath):
    """Extracts 'objective' and target count from Federation JSONs."""
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
        obj = data.get("objective") or data.get("header", {}).get("objective", "Data file")
        count = len(data.get("targets", [])) if "targets" in data else "N/A"
        return obj, count
    except:
        return "Error reading JSON metadata.", "ERR"

def generate():
    sections = {
        "🛫 PREFLIGHT": ["core/preflight", "core/planning"],
        "🚀 FLIGHT": "core/flight",
        "🧪 POSTFLIGHT": "core/postflight",
        "🛠️ UTILS": ["utils", "core/utils", "core"]
    }
    
    with open(MANIFEST_PATH, 'w') as m:
        m.write("# 📑 Seestar Organizer: Purified Manifest\n")
        m.write(f"**Audit Timestamp:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        # 1. RAID1 Data Repository Section
        m.write("## 🗄️ RAID1 DATA REPOSITORY\n")
        m.write("| Filename | Objective | Status/Count |\n")
        m.write("| :--- | :--- | :--- |\n")
        data_dir = os.path.join(ROOT_DIR, "data")
        if os.path.exists(data_dir):
            for f_name in sorted(os.listdir(data_dir)):
                if f_name.endswith(".json"):
                    obj, count = get_json_details(os.path.join(data_dir, f_name))
                    m.write(f"| `data/{f_name}` | {obj} | {count} Targets |\n")
        m.write("\n")

        # 2. Script Sections (Original Logic)
        for title, folders in sections.items():
            m.write(f"## {title}\n")
            if isinstance(folders, str): folders = [folders]
            for fld in folders:
                target = os.path.join(ROOT_DIR, fld)
                if not os.path.exists(target): continue
                for file in sorted(os.listdir(target)):
                    if file.endswith(".py") and not file.startswith("__"):
                        obj = get_script_objective(os.path.join(target, file))
                        m.write(f"* `{fld}/{file}`: {obj}\n")
            m.write("\n")

    # NAS Sync
    if os.path.exists(NAS_DIR):
        try:
            shutil.copy2(MANIFEST_PATH, NAS_DIR)
            return True
        except: return False
    return False

if __name__ == "__main__":
    synced = generate()
    print(f"✅ Purified Manifest generated.")
    if synced:
        print(f"📦 Mirrored to NAS at {NAS_DIR}")
