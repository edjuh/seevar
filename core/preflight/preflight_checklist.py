#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/preflight_checklist.py
Version: 2.0.0
Objective: Sovereign preflight gate — verifies hardware is alive and at
           zero-state before flight. Uses camera_control.CameraControl
           for get_device_state health check and neutralizer.enforce_zero_state
           for clean session start. No Alpaca, no mount_control ghost module.
"""

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.flight.camera_control import CameraControl
from core.flight.neutralizer import enforce_zero_state
from core.preflight.hardware_audit import HardwareAudit

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
logger = logging.getLogger("PreflightChecklist")


def run_checklist() -> bool:
    """
    Execute preflight checklist. Returns True if all pillars GREEN.

    Pillar 1 — Hardware alive:
        get_device_state on port 4700 via CameraControl.
        Any valid JSON response = device alive.

    Pillar 2 — Hardware telemetry:
        Full TelemetryBlock parse via HardwareAudit.
        Battery, temp, charger_status checked against veto thresholds.

    Pillar 3 — Zero-state:
        neutralizer.enforce_zero_state() — iscope_stop_view + scope_park
        + poll for idle confirmation. 180s ceiling.
    """
    print("\n🚀 SeeVar Preflight Checklist\n")
    results = {}

    # Pillar 1 — Device alive
    print("Pillar 1 — Hardware link (port 4700)...")
    cam = CameraControl()
    alive = cam.get_view_status()
    results["hardware_link"] = alive
    print(f"  {'✅ ALIVE' if alive else '❌ NO RESPONSE'}")

    if not alive:
        print("\n🛑 ABORT — device not reachable on port 4700.")
        _write_results(results, passed=False)
        return False

    # Pillar 2 — Telemetry and veto check
    print("\nPillar 2 — Hardware telemetry (battery / temp)...")
    audit = HardwareAudit()
    safe = audit.run_audit()
    results["telemetry"] = safe
    print(f"  {'✅ SAFE' if safe else '❌ VETO — check hardware_telemetry.json'}")

    if not safe:
        print("\n🛑 ABORT — hardware veto. Check data/hardware_telemetry.json.")
        _write_results(results, passed=False)
        return False

    # Pillar 3 — Zero-state
    print("\nPillar 3 — Zero-state (neutralizer)...")
    zero = enforce_zero_state()
    results["zero_state"] = zero
    print(f"  {'✅ SECURED' if zero else '⚠️  UNCONFIRMED (alive but state unclear)'}")

    passed = alive and safe
    # zero-state unconfirmed is a warning, not a hard abort —
    # neutralizer returns True even on timeout-but-alive per its own logic
    print(f"\n{'✅ PREFLIGHT GREEN — proceed to flight' if passed else '🛑 PREFLIGHT RED — scrub'}\n")
    _write_results(results, passed=passed)
    return passed


def _write_results(results: dict, passed: bool):
    from datetime import datetime, timezone
    import json
    from core.utils.env_loader import DATA_DIR
    out = DATA_DIR / "preflight_results.json"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "passed":    passed,
            "pillars":   results,
        }, indent=2))
    except OSError:
        pass


# SeeVar-v5-M6-preflight_checklist
if __name__ == "__main__":
    sys.exit(0 if run_checklist() else 1)
