#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/preflight/target_evaluator.py
Version: 1.0.1
Objective: Audits the nightly plan for freshness and quantity to update dashboard UI.
"""

import json
import os
from datetime import datetime
from pathlib import Path

class TargetEvaluator:
    def __init__(self):
        self.base_dir = Path(os.path.expanduser("~/seevar/data"))
        self.observable_path = self.base_dir / "targets" / "observable_targets.json"
        self.plan_path = self.base_dir / "tonights_plan.json"

    def evaluate(self):
        """Returns {status, led, count}"""
        if self.plan_path.exists():
            file_time = os.path.getmtime(self.plan_path)
            if datetime.fromtimestamp(file_time).date() == datetime.now().date():
                try:
                    with open(self.plan_path, 'r') as f:
                        data = json.load(f)
                        targets = data.get("targets", []) if isinstance(data, dict) else data
                        count = len(targets)
                        if count > 0:
                            return {"status": f"READY ({count})", "led": "led-green"}
                        else:
                            return {"status": "EMPTY PLAN", "led": "led-red"}
                except Exception:
                    return {"status": "PLAN ERROR", "led": "led-red"}
            else:
                return {"status": "STALE PLAN", "led": "led-orange"}

        if self.observable_path.exists():
            return {"status": "NEEDS PLAN", "led": "led-orange"}

        return {"status": "NO TARGETS", "led": "led-red"}

if __name__ == "__main__":
    evaluator = TargetEvaluator()
    print(evaluator.evaluate())
