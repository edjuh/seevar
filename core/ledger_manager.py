#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/ledger_manager.py
Version: 1.6.1
Objective: The High-Authority Mission Brain. Manages target cadence and observation history. Filters tonights_plan.json by cadence, records attempts and successes during flight.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
from pathlib import Path
import fcntl

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s"
)
logger = logging.getLogger("Ledger")

PROJECT_ROOT  = Path(__file__).resolve().parents[1]
LEDGER_FILE   = PROJECT_ROOT / "data" / "ledger.json"
LEDGER_LOCK   = PROJECT_ROOT / "data" / "ledger.lock"
PLAN_FILE     = PROJECT_ROOT / "data" / "tonights_plan.json"
CATALOG_FILE  = PROJECT_ROOT / "catalogs" / "federation_catalog.json"


# ---------------------------------------------------------------------------
# Cadence calculation — period-based with type floors per PREFLIGHT.MD
# ---------------------------------------------------------------------------

# Types that override period-based cadence — always daily
DAILY_TYPES = {"CV", "UG", "UGSS", "RR", "NA", "NB", "NC", "NR"}

# Minimum cadence floors per type group (days)
TYPE_FLOORS = {
    "M":   7, "LPV": 7,
    "SR":  4, "SRC": 5,
}

def calculate_cadence(target: dict) -> int:
    """Return cadence in days for a target.

    Rules (in priority order):
    1. Daily types (CV/UG/RR etc) → 1 day always
    2. period_days present → max(floor, period * 0.05)
    3. recommended_cadence_days from catalog → use as-is
    4. Default → 3 days
    """
    var_type = str(target.get("type", "")).upper()

    # Rule 1 — daily types
    for daily in DAILY_TYPES:
        if daily in var_type:
            return 1

    period = target.get("period_days")
    floor  = 3
    for key, val in TYPE_FLOORS.items():
        if key in var_type:
            floor = val
            break

    # Rule 2 — period-based
    if period and float(period) > 0:
        cadence = max(floor, int(float(period) * 0.05))
        return cadence

    # Rule 3 — recommended_cadence_days
    rec = target.get("recommended_cadence_days")
    if rec:
        return int(rec)

    # Rule 4 — default
    return 3


# ---------------------------------------------------------------------------
# Ledger I/O
# ---------------------------------------------------------------------------

def load_ledger() -> dict:
    if not LEDGER_FILE.exists():
        return {}
    try:
        with open(LEDGER_FILE, "r") as f:
            data = json.load(f)
            return data.get("entries", {}) if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        logger.warning("Ledger unreadable — starting fresh.")
        return {}


def save_ledger(entries: dict):
    output = {
        "#objective": "Master Observational Register and Status Ledger",
        "metadata": {
            "last_updated":   datetime.now(timezone.utc).isoformat(),
            "schema_version": "2026.2",
        },
        "entries": entries,
    }
    LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = LEDGER_FILE.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
        json.dump(output, f, indent=4)
    tmp_path.replace(LEDGER_FILE)


@contextmanager
def _locked_ledger_entries():
    LEDGER_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_LOCK, "w") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            yield load_ledger()
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _blank_entry() -> dict:
    return {
        "status":        "PENDING",
        "last_success":  None,
        "attempts":      0,
        "priority":      "NORMAL",
        "last_mag":      None,
        "last_err":      None,
        "last_snr":      None,
        "last_filter":   None,
        "last_comps":    None,
        "last_zp":       None,
        "last_zp_std":   None,
        "last_obs_utc":  None,
        "last_peak_adu": None,
    }


# ---------------------------------------------------------------------------
# Public API — called by orchestrator
# ---------------------------------------------------------------------------

def filter_by_cadence(targets: list) -> list:
    """Filter a target list to those due tonight by cadence.

    Uses original target name as key — matches accountant.py schema.
    Called by orchestrator after _run_planning().

    Returns filtered list. Updates ledger with any new target entries.
    """
    now = datetime.now(timezone.utc)
    due = []
    skipped = 0

    with _locked_ledger_entries() as ledger:
        for t in targets:
            name = t.get("name", "")
            if not name:
                continue

            if name not in ledger:
                ledger[name] = _blank_entry()

            cadence_days = calculate_cadence(t)
            last_success = ledger[name].get("last_success")

            if not last_success:
                due.append(t)
            else:
                try:
                    last_dt = datetime.fromisoformat(last_success)
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    if now - last_dt >= timedelta(days=cadence_days):
                        due.append(t)
                    else:
                        skipped += 1
                        logger.debug(
                            "Cadence skip: %s (last=%s cadence=%dd)",
                            name, last_success[:10], cadence_days
                        )
                except (ValueError, TypeError):
                    due.append(t)

        save_ledger(ledger)

    logger.info(
        "Cadence filter: %d due tonight, %d deferred.", len(due), skipped
    )
    return due


def record_attempt(name: str):
    """Increment acquisition-attempt counter for a target before runtime capture."""
    with _locked_ledger_entries() as ledger:
        if name not in ledger:
            ledger[name] = _blank_entry()
        ledger[name]["attempts"] += 1
        save_ledger(ledger)


def record_capture(name: str, fits_path: str = ""):
    """Record a raw science capture without claiming scientific success."""
    with _locked_ledger_entries() as ledger:
        if name not in ledger:
            ledger[name] = _blank_entry()

        entry = ledger[name]
        entry["status"] = "CAPTURED_RAW"
        entry["last_capture_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if fits_path:
            entry["last_capture_path"] = str(fits_path)

        save_ledger(ledger)
    logger.info("Ledger: %s → CAPTURED_RAW", name)


def record_success(name: str, fits_path: str = ""):
    """Stamp scientific success after postflight closure, not mere runtime capture."""
    with _locked_ledger_entries() as ledger:
        if name not in ledger:
            ledger[name] = _blank_entry()

        entry = ledger[name]
        entry["status"] = "OBSERVED"
        entry["last_success"] = datetime.now(timezone.utc).isoformat()
        if fits_path:
            entry["last_capture_path"] = str(fits_path)
        save_ledger(ledger)
    logger.info("Ledger: %s → OBSERVED", name)


# ---------------------------------------------------------------------------
# Legacy entry point — retained for manual use
# ---------------------------------------------------------------------------

def execute_ledger_sync():
    """Standalone cadence filter — reads plan, filters, writes back."""
    plan_raw = {}
    if PLAN_FILE.exists():
        with open(PLAN_FILE, "r") as f:
            plan_raw = json.load(f)

    targets = plan_raw.get("targets", []) if isinstance(plan_raw, dict) else plan_raw
    if not targets:
        logger.warning("No targets in plan — nothing to filter.")
        return

    due = filter_by_cadence(targets)

    final = {
        "#objective": "Tactical flight plan filtered by Ledger Cadence.",
        "metadata": {
            "generated":  datetime.now(timezone.utc).isoformat(),
            "due_count":  len(due),
        },
        "targets": due,
    }
    with open(PLAN_FILE, "w") as f:
        json.dump(final, f, indent=4)
    logger.info("Ledger Sync Complete: %d targets due tonight.", len(due))


if __name__ == "__main__":
    execute_ledger_sync()
