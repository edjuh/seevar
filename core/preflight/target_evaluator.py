#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/target_evaluator.py
Version: 1.2.1
Objective: Audits canonical nightly artifacts for freshness and quantity to update dashboard UI with funnel-aware counts.
"""

import json
import os
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class TargetEvaluator:
    def __init__(self):
        self.base_dir = PROJECT_ROOT / "data"
        self.catalog_path = PROJECT_ROOT / "catalogs" / "federation_catalog.json"
        self.plan_path = self.base_dir / "tonights_plan.json"
        self.payload_path = self.base_dir / "ssc_payload.json"

    def _load_json(self, path: Path):
        if not path.exists():
            return None
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return None

    def _count_targets(self, payload) -> int:
        if payload is None:
            return 0
        if isinstance(payload, list):
            return len(payload)
        if isinstance(payload, dict):
            if isinstance(payload.get("targets"), list):
                return len(payload["targets"])
            if isinstance(payload.get("data"), list):
                return len(payload["data"])
        return 0

    def _count_compiled_targets(self, payload) -> int:
        if not isinstance(payload, dict):
            return 0
        items = payload.get("list", [])
        return sum(1 for item in items if item.get("action") == "start_mosaic")

    def _is_fresh_today(self, path: Path) -> bool:
        if not path.exists():
            return False
        file_time = os.path.getmtime(path)
        return datetime.fromtimestamp(file_time).date() == datetime.now().date()

    def evaluate(self):
        catalog = self._load_json(self.catalog_path)
        plan = self._load_json(self.plan_path)
        payload = self._load_json(self.payload_path)

        catalog_count = self._count_targets(catalog)
        plan_count = self._count_targets(plan)
        compiled_count = self._count_compiled_targets(payload)

        plan_meta = plan.get("metadata", {}) if isinstance(plan, dict) else {}
        visible_count = int(plan_meta.get("visible_target_count", plan_count))
        due_count = int(plan_meta.get("planned_target_count", plan_count))

        details = {
            "catalog_count": catalog_count,
            "visible_count": visible_count,
            "due_count": due_count,
            "compiled_count": compiled_count,
            "plan_fresh": self._is_fresh_today(self.plan_path),
            "payload_fresh": self._is_fresh_today(self.payload_path),
        }

        if self.plan_path.exists() and details["plan_fresh"]:
            if plan_count > 0:
                if self.payload_path.exists() and details["payload_fresh"] and compiled_count > 0:
                    return {
                        "status": f"READY ({due_count})",
                        "led": "led-green",
                        "count": due_count,
                        "details": details,
                        "summary": f"Catalog {catalog_count} | Visible {visible_count} | Due {due_count} | Compiled {compiled_count}",
                    }
                return {
                    "status": f"PLANNED ({due_count})",
                    "led": "led-green",
                    "count": due_count,
                    "details": details,
                    "summary": f"Catalog {catalog_count} | Visible {visible_count} | Due {due_count}",
                }
            return {
                "status": "EMPTY PLAN",
                "led": "led-red",
                "count": 0,
                "details": details,
                "summary": f"Catalog {catalog_count} | Visible {visible_count} | Due 0",
            }

        if catalog_count > 0:
            return {
                "status": "CATALOG READY",
                "led": "led-orange",
                "count": catalog_count,
                "details": details,
                "summary": f"Catalog {catalog_count} | Visible {visible_count} | Due {due_count}",
            }

        return {
            "status": "NO TARGETS",
            "led": "led-red",
            "count": 0,
            "details": details,
            "summary": "No federation catalog available",
        }


if __name__ == "__main__":
    evaluator = TargetEvaluator()
    print(evaluator.evaluate())
