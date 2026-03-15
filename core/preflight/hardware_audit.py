#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/hardware_audit.py
Version: 2.0.0
Objective: Sovereign TCP hardware audit via get_device_state on port 4700.
           Exports hardware_telemetry.json for dashboard vitals.
           Confirmed fields only: battery_capacity, temp, charger_status
           from pi_status block. No BalanceSensor (key unconfirmed on
           S30-Pro — verify on first light via get_event_state response).
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.flight.pilot import ControlSocket, TelemetryBlock, SEESTAR_HOST
from core.utils.env_loader import DATA_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
logger = logging.getLogger("HardwareAudit")

TELEMETRY_PATH = DATA_DIR / "hardware_telemetry.json"

# Veto thresholds — must match STATE_MACHINE.md and pilot.py
VETO_BATTERY = 10    # %
VETO_TEMP    = 55.0  # °C


class HardwareAudit:
    """
    Sovereign hardware gate for preflight.

    Sends get_device_state to port 4700, parses TelemetryBlock,
    applies veto thresholds, writes hardware_telemetry.json.

    BalanceSensor / tilt fields are NOT included — key names are
    unconfirmed on the S30-Pro. Add after first-light get_event_state
    response is captured and key names are verified.
    """

    def __init__(self, host: str = SEESTAR_HOST):
        self.host = host

    def run_audit(self) -> bool:
        """
        Query hardware state and write telemetry file.
        Returns True if hardware is safe to proceed, False if veto.
        """
        logger.info("Hardware audit starting — port 4700 get_device_state")

        ctrl = ControlSocket(host=self.host)
        telemetry = TelemetryBlock(parse_error="not yet queried")

        if not ctrl.connect():
            logger.error("Cannot connect to %s:4700", self.host)
            telemetry = TelemetryBlock(parse_error="connection failed")
        else:
            try:
                resp = ctrl.send_and_recv("get_device_state")
                telemetry = TelemetryBlock.from_response(resp)
            except Exception as e:
                telemetry = TelemetryBlock(parse_error=str(e))
            finally:
                ctrl.disconnect()

        passed  = telemetry.parse_error is None
        veto    = telemetry.veto_reason() if passed else None
        safe    = passed and veto is None

        warnings = []
        if not passed:
            warnings.append(f"parse_error: {telemetry.parse_error}")
        if veto:
            warnings.append(veto)
            passed = False

        if passed and not veto:
            logger.info("Audit PASSED — %s", telemetry.summary())
        else:
            logger.error("Audit FAILED — %s", warnings)

        payload = {
            "#objective": "Sovereign hardware telemetry from get_device_state port 4700.",
            "timestamp":      datetime.now(timezone.utc).isoformat(),
            "passed":         safe,
            "link_status":    "ACTIVE" if telemetry.parse_error is None else "OFFLINE",
            "warnings":       warnings,
            "battery_pct":    telemetry.battery_pct,
            "temp_c":         telemetry.temp_c,
            "charger_status": telemetry.charger_status,
            "charge_online":  telemetry.charge_online,
            "device_name":    telemetry.device_name,
            "firmware_ver":   telemetry.firmware_ver,
            # tilt_x / tilt_y: NOT included — BalanceSensor key unconfirmed
            # on S30-Pro. Verify via get_event_state on first light and
            # update TelemetryBlock + this audit accordingly.
            # Ref: logic/STATE_MACHINE.md VETO LOGIC — level > 1.5 deg
        }

        try:
            TELEMETRY_PATH.parent.mkdir(parents=True, exist_ok=True)
            TELEMETRY_PATH.write_text(json.dumps(payload, indent=2))
            logger.info("hardware_telemetry.json written.")
        except OSError as e:
            logger.error("Failed to write hardware_telemetry.json: %s", e)

        return safe


# SeeVar-v5-M6-hardware_audit
if __name__ == "__main__":
    import sys
    audit = HardwareAudit()
    sys.exit(0 if audit.run_audit() else 1)
