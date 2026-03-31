#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/hardware_audit.py
Version: 3.0.0
Objective: Alpaca REST hardware audit — reads telescope and camera state
           via port 32323. Exports hardware_telemetry.json for dashboard.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.flight.pilot import (
    AlpacaTelescope, AlpacaCamera, TelemetryBlock,
    SEESTAR_HOST, ALPACA_PORT,
)
from core.utils.env_loader import DATA_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
logger = logging.getLogger("HardwareAudit")

TELEMETRY_PATH = DATA_DIR / "hardware_telemetry.json"
VETO_BATTERY = 10
VETO_TEMP    = 55.0


class HardwareAudit:
    """Alpaca hardware gate for preflight."""

    def __init__(self, host: str = SEESTAR_HOST, port: int = ALPACA_PORT):
        self.host = host
        self.port = port

    def run_audit(self) -> bool:
        """Query hardware state via Alpaca and write telemetry file."""
        logger.info("Hardware audit — Alpaca REST on %s:%d", self.host, self.port)

        telescope = AlpacaTelescope(self.host, self.port)
        camera    = AlpacaCamera(self.host, self.port)

        try:
            telescope.connect()
            camera.connect()
            telemetry = TelemetryBlock.from_alpaca(telescope, camera)
        except Exception as e:
            telemetry = TelemetryBlock(parse_error=str(e))
        finally:
            try:
                telescope.disconnect()
                camera.disconnect()
            except Exception:
                pass

        passed = telemetry.parse_error is None
        veto   = telemetry.veto_reason() if passed else None
        safe   = passed and veto is None

        warnings = []
        if not passed:
            warnings.append(f"parse_error: {telemetry.parse_error}")
        if veto:
            warnings.append(veto)

        if safe:
            logger.info("Audit PASSED — %s", telemetry.summary())
        else:
            logger.error("Audit FAILED — %s", warnings)

        payload = {
            "#objective": "Alpaca hardware telemetry from port 32323.",
            "timestamp":      datetime.now(timezone.utc).isoformat(),
            "passed":         safe,
            "link_status":    "ACTIVE" if passed else "OFFLINE",
            "warnings":       warnings,
            "temp_c":         telemetry.temp_c,
            "tracking":       telemetry.tracking,
            "at_park":        telemetry.at_park,
            "device_name":    telemetry.device_name,
            "alpaca_version": telemetry.alpaca_version,
            "ra_hours":       telemetry.ra_hours,
            "dec_deg":        telemetry.dec_deg,
            "altitude":       telemetry.altitude,
            "azimuth":        telemetry.azimuth,
            # battery_pct not available via Alpaca — dashboard reads
            # from WilhelminaMonitor event stream instead
        }

        try:
            TELEMETRY_PATH.parent.mkdir(parents=True, exist_ok=True)
            TELEMETRY_PATH.write_text(json.dumps(payload, indent=2))
            logger.info("hardware_telemetry.json written.")
        except OSError as e:
            logger.error("Failed to write hardware_telemetry.json: %s", e)

        return safe


if __name__ == "__main__":
    audit = HardwareAudit()
    sys.exit(0 if audit.run_audit() else 1)
