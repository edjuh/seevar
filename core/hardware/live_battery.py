#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/hardware/live_battery.py
Version: 1.0.1
Objective: Live battery and charger polling helper for configured scopes, returning only fresh JSON-RPC telemetry without telescope-specific hardcoding.
"""

import json
import socket
from datetime import datetime, timezone


def poll_battery_snapshot(ip: str, port: int = 4700, timeout: float = 3.0) -> dict:
    if not ip or ip == "TBD":
        return {}

    payload = {"id": 10001, "method": "get_device_state"}
    wire = (json.dumps(payload) + "\\r\\n").encode("utf-8")

    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(wire)
            response = sock.recv(16384)
    except Exception:
        return {}

    if not response:
        return {}

    try:
        data = json.loads(response.decode("utf-8"))
    except Exception:
        return {}

    result = data.get("result", {}) if isinstance(data, dict) else {}
    pi = result.get("pi_status", {}) if isinstance(result, dict) else {}
    if not isinstance(pi, dict):
        return {}

    battery_pct = pi.get("battery_capacity")
    charge_online = pi.get("charge_online")
    charger_status = pi.get("charger_status")
    if battery_pct is None and charge_online is None and not charger_status:
        return {}

    return {
        "battery_pct": battery_pct,
        "battery_capacity": battery_pct,
        "charge_online": charge_online,
        "charger_status": charger_status,
        "battery_updated_utc": datetime.now(timezone.utc).isoformat(),
    }
