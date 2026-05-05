#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/hardware/fleet_monitor.py
Version: 1.1.0
Objective: Periodic generic fleet status logger for configured scopes, emitting
stable per-scope operational telemetry into both telescope.log and
data/fleet_status.json for dashboard and seetop consumption.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.hardware.live_scope_status import poll_scope_status

CONFIG_FILE = PROJECT_ROOT / "config.toml"
FLEET_STATUS_FILE = PROJECT_ROOT / "data" / "fleet_status.json"
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


def _status_row(scope: dict, status: dict) -> dict:
    row = {
        "name": scope.get("name", "UNKNOWN"),
        "model": scope.get("model", "S30-Pro"),
        "ip": scope.get("ip", ""),
        "port": int(scope.get("port", 32323)),
    }
    if status:
        row.update(status)
    else:
        row.update({
            "link_status": "OFFLINE",
            "operational_state": "OFFLINE",
        })
    return row


def write_status_file(rows: list[dict]):
    payload = {
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "fleet": rows,
    }
    FLEET_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FLEET_STATUS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=4))
    tmp.replace(FLEET_STATUS_FILE)


def main():
    log.info("Fleet monitor starting (interval=%ss)", POLL_INTERVAL_SEC)
    last_lines: dict[str, str] = {}
    ticks = 0

    while True:
        scopes = load_scopes()
        if not scopes:
            write_status_file([])
            log.warning("No configured Seestars found; sleeping.")
            time.sleep(POLL_INTERVAL_SEC)
            continue

        live_rows: list[dict] = []

        for scope in scopes:
            name = scope.get("name", scope.get("ip", "UNKNOWN"))
            status = poll_scope_status(scope.get("ip", ""), int(scope.get("port", 32323)))
            live_rows.append(_status_row(scope, status))

            line = snapshot_line(scope, status)
            if last_lines.get(name) != line:
                log.info(line)
                last_lines[name] = line
            elif ticks % HEARTBEAT_EVERY == 0:
                log.info("heartbeat | %s", line)

        write_status_file(live_rows)

        ticks += 1
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()
