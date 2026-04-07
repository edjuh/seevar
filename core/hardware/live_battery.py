#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/hardware/live_battery.py
Version: 1.3.0
Objective: Live battery and charger polling helper for configured scopes, returning only fresh JSON-RPC telemetry without telescope-specific hardcoding.
"""

import json
import socket
from datetime import datetime, timezone



def poll_battery_snapshot(ip: str, port: int = 4702, timeout: float = 3.0) -> dict:
    if not ip or ip == "TBD":
        return {}

    payload = {"id": 10001, "method": "get_device_state"}
    wire = (json.dumps(payload) + "\r\n").encode("utf-8")

    response = b""
    for candidate_port in (port, 4700):
        if candidate_port in (None, 0):
            continue
        try:
            with socket.create_connection((ip, candidate_port), timeout=timeout) as sock:
                sock.settimeout(timeout)
                sock.sendall(wire)
                chunks = []
                while True:
                    try:
                        data = sock.recv(4096)
                    except socket.timeout:
                        break
                    if not data:
                        break
                    chunks.append(data)
                    if b"\r\n" in data:
                        break
                response = b"".join(chunks)
            if response:
                break
        except Exception:
            response = b""

    if not response:
        return {}

    try:
        data = json.loads(response.decode("utf-8", errors="replace").strip())
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
