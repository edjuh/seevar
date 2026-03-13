#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/postflight/post_to_pre_feedback.py
Version: 1.2.1
Objective: Updates the master targets.json with successful observation dates extracted from QC reports.
"""

import json
import os
from datetime import datetime

REPORT_PATH = os.path.expanduser("~/seevar/core/postflight/data/qc_report.json")
TARGETS_PATH = os.path.expanduser("~/seevar/data/targets.json")

def apply_feedback():
    if not os.path.exists(REPORT_PATH): return
    with open(REPORT_PATH, 'r') as f:
        data = json.load(f)
        qc_results = data.get("results", [])
    if not os.path.exists(TARGETS_PATH): return
    with open(TARGETS_PATH, 'r') as f:
        targets = json.load(f)

    successful_targets = [r['target'] for r in qc_results if r['status'] == "PASS"]
    now_str = datetime.now().strftime("%Y-%m-%d")

    for t in targets:
        if t['star_name'] in successful_targets:
            t['last_observed'] = now_str

    with open(TARGETS_PATH, 'w') as f:
        json.dump(targets, f, indent=4)

if __name__ == "__main__":
    apply_feedback()
