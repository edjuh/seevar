#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/ledger_manager.py
Version: 2.3.1
Objective: Applies cadence history to the canonical nightly plan while preserving nightly-planner metadata and contract.
"""

import json
import logging
import tomllib
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger("Ledger")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEDGER_FILE = PROJECT_ROOT / "data" / "ledger.json"
FEDERATED_CATALOG = PROJECT_ROOT / "catalogs" / "federation_catalog.json"
TONIGHTS_PLAN = PROJECT_ROOT / "data" / "tonights_plan.json"
CONFIG_PATH = PROJECT_ROOT / "config.toml"


def _load_cadence_config() -> tuple[float, float]:
    defaults = (20.0, 3.0)
    try:
        with open(CONFIG_PATH, "rb") as f:
            config = tomllib.load(f)
        planner = config.get("planner", {})
        divisor = float(planner.get("cadence_divisor", defaults[0]))
        fallback = float(planner.get("cadence_fallback_days", defaults[1]))
        return divisor, fallback
    except Exception as e:
        logger.warning("Could not load cadence config: %s — using defaults", e)
        return defaults


CADENCE_DIVISOR, CADENCE_FALLBACK_DAYS = _load_cadence_config()


def load_json(path: Path):
    if not path.exists():
        return {}
    with open(path, "r") as f:
        return json.load(f)


def save_json(path: Path, data: dict, objective: str):
    output = {
        "#objective": objective,
        "metadata": {
            "last_updated": datetime.now().isoformat(),
            "schema_version": "2026.2",
        },
        "entries": data,
    }
    with open(path, "w") as f:
        json.dump(output, f, indent=4)


def execute_ledger_sync():
    catalog_raw = load_json(FEDERATED_CATALOG)
    targets = catalog_raw.get("data", []) if isinstance(catalog_raw, dict) else catalog_raw

    plan_raw = load_json(TONIGHTS_PLAN)
    plan_targets = plan_raw.get("targets", []) if isinstance(plan_raw, dict) else []
    plan_meta = plan_raw.get("metadata", {}) if isinstance(plan_raw, dict) else {}

    ledger_raw = load_json(LEDGER_FILE)
    entries = ledger_raw.get("entries", {})

    now = datetime.now()
    due_names = []

    for t in targets:
        name = t["name"].replace(" ", "_").upper()

        if name not in entries:
            entries[name] = {
                "status": "PENDING",
                "last_success": None,
                "attempts": 0,
                "priority": "NORMAL",
            }

        last_success = entries[name].get("last_success")

        if not last_success:
            due_names.append(name)
            continue

        last_date = datetime.fromisoformat(last_success)
        period = t.get("period_days")
        if period is not None and float(period) > 0:
            cadence_days = float(period) / CADENCE_DIVISOR
        else:
            cadence_days = CADENCE_FALLBACK_DAYS

        if now - last_date > timedelta(days=cadence_days):
            due_names.append(name)

    due_plan = [
        t for t in plan_targets
        if t["name"].replace(" ", "_").upper() in due_names
    ]

    save_json(LEDGER_FILE, entries, "Master Observational Register and Status Ledger")

    final_plan = {
        "#objective": "Canonical nightly plan filtered by cadence ledger.",
        "metadata": {
            "generated": now.isoformat(),
            "schema_version": "2026.2",
            "ledger_version": "2.3.1",
            "catalog_target_count": int(plan_meta.get("catalog_target_count", len(targets))),
            "visible_target_count": int(plan_meta.get("visible_target_count", len(plan_targets))),
            "planned_target_count": len(due_plan),
            "cadence_divisor": CADENCE_DIVISOR,
            "fallback_days": CADENCE_FALLBACK_DAYS,
        },
        "targets": due_plan,
    }

    with open(TONIGHTS_PLAN, "w") as f:
        json.dump(final_plan, f, indent=4)

    logger.info(
        "Ledger Sync: visible=%d due=%d (divisor=1/%.0f fallback=%.1fd)",
        len(plan_targets),
        len(due_plan),
        CADENCE_DIVISOR,
        CADENCE_FALLBACK_DAYS,
    )


if __name__ == "__main__":
    execute_ledger_sync()
