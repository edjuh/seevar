#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: utils/purify_catalog.py
Version: 1.1.0
Objective: Wraps the raw 409-target list into a Federation-standard JSON with metadata.
"""

import json
from pathlib import Path

def purify():
    root = Path(__file__).resolve().parents[1]
    path = root / "data/targets.json"

    with open(path, 'r') as f:
        data = json.load(f)

    # If it's already a list, wrap it.
    if isinstance(data, list):
        clean_data = {
            "header": {
                "objective": "The Research Catalog: Immutable Master Target List",
                "federation_version": "1.5.0",
                "target_count": len(data)
            },
            "targets": data
        }
        with open(path, 'w') as f:
            json.dump(clean_data, f, indent=4)
        print(f"✅ targets.json purified with {len(data)} stars.")
    else:
        print("ℹ️ targets.json already has a header.")

if __name__ == "__main__":
    purify()
