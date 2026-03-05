#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: logic/scout.py
Version: 1.1.0
Objective: Crawl local Bruno collection to extract commands and payloads for the PSV dictionary using absolute paths.
"""

import os
import re

# Using absolute paths to prevent "FileNotFound" errors
BASE_DIR = os.path.expanduser("~/seestar_organizer")
BRUNO_PATH = os.path.expanduser("~/seestar_alp/bruno/Seestar Alpaca API")
PSV_PATH = os.path.join(BASE_DIR, "logic/seestar_dict.psv")

def extract_bru_data(file_path):
    """Parses a .bru file to find the command payload."""
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Priority 1: Check for JSON-style "method" (Common in Action calls)
        method_match = re.search(r'"method":\s*"([^"]+)"', content)
        if method_match:
            return method_match.group(1)
            
        # Priority 2: Check for simple command=...
        cmd_match = re.search(r'command=([a-zA-Z0-9_]+)', content)
        if cmd_match:
            return cmd_match.group(1)
            
        return None
    except Exception:
        return None

def main():
    if not os.path.exists(BRUNO_PATH):
        print(f"❌ Bruno path not found: {BRUNO_PATH}")
        return

    # Ensure logic directory exists
    os.makedirs(os.path.dirname(PSV_PATH), exist_ok=True)

    print(f"🕵️ Scouting {BRUNO_PATH}...")
    
    # Create file with headers
    with open(PSV_PATH, "w") as psv:
        psv.write("Category|Command|Endpoint_Payload|Expected_Response\n")

        found_count = 0
        for root, dirs, files in os.walk(BRUNO_PATH):
            # Category is the folder name
            category = os.path.basename(root)
            for file in files:
                if file.endswith(".bru"):
                    command_name = extract_bru_data(os.path.join(root, file))
                    if command_name:
                        # Clean up file name for display
                        display_name = file.replace(".bru", "").replace("-", " ").title()
                        payload = f"/1/command command={command_name}"
                        psv.write(f"{category}|{display_name}|{payload}|TBD\n")
                        found_count += 1

    print(f"✅ Scout finished. Map secured at: {PSV_PATH}")
    print(f"📊 Total Entries: {found_count}")

if __name__ == "__main__":
    main()
