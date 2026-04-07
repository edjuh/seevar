#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/hardware/fleet_monitor.py
Version: 1.0.1
Objective: Periodic generic fleet status logger for configured scopes, emitting stable per-scope operational telemetry into telescope.log for dashboard and seetop consumption.
"""

from __future__ import annotations

import logging
import sys
import time
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.hardware.live_scope_status import poll_scope_status

CONFIG_FILE = PROJECT_ROOT / "config.toml"
POLL_INTERVAL_SEC = 15
HEARTBEAT_EVERY = 8

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("FleetMonitor")


def load_scopes() -> list[dict]:
    try:
        cfg = tomllib.loads(CONFIG_FILE.read_text())
    except Exception as exc:
        log.error("Could not read config.toml: %s", exc)
        return []
    scopes = cfg.get("seestars", [])
    return [s for s in scopes if isinstance(s, dict) and s.get("ip") and s.get("ip") != "TBD"]


def snapshot_line(scope: dict, status: dict) -> str:
    if not status:
        return f"{scope.get('name', 'UNKNOWN')} | state=OFFLINE | link=OFFLINE"

    parts = [
        scope.get("name", "UNKNOWN"),
        f"state={status.get('operational_state', 'UNKNOWN')}",
        f"link={status.get('link_status', 'OFFLINE')}",
    ]
    if status.get("camera_state_name") not in (None, "UNKNOWN"):
        parts.append(f"camera={status['camera_state_name']}")
    if status.get("tracking") is not None:
        parts.append(f"tracking={bool(status['tracking'])}")
    if status.get("slewing") is not None:
        parts.append(f"slewing={bool(status['slewing'])}")
    if status.get("battery") not in (None, "N/A", ""):
        parts.append(f"battery={status['battery']}%")
    if status.get("temp_c") not in (None, "N/A", ""):
        parts.append(f"ccd={status['temp_c']}C")
    return " | ".join(parts)


def main():
    log.info("Fleet monitor starting (interval=%ss)", POLL_INTERVAL_SEC)
    last_lines: dict[str, str] = {}
    ticks = 0

    while True:
        scopes = load_scopes()
        if not scopes:
            log.warning("No configured Seestars found; sleeping.")
            time.sleep(POLL_INTERVAL_SEC)
            continue

        for scope in scopes:
            name = scope.get("name", scope.get("ip", "UNKNOWN"))
            status = poll_scope_status(scope.get("ip", ""), int(scope.get("port", 32323)))
            line = snapshot_line(scope, status)
            if last_lines.get(name) != line:
                log.info(line)
                last_lines[name] = line
            elif ticks % HEARTBEAT_EVERY == 0:
                log.info("heartbeat | %s", line)

        ticks += 1
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()
