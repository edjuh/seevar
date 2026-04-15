#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/hardware/live_scope_status.py
Version: 1.0.2
Objective: Generic live scope-status polling helper that fuses Alpaca
telescope/camera state with optional live battery telemetry into a single
operational snapshot.
"""

import requests

from core.hardware.live_battery import poll_battery_snapshot

ALPACA_TIMEOUT = 2.0
ALPACA_CLIENT_PARAMS = {"ClientID": 42, "ClientTransactionID": 1}

CAMERA_STATE_NAMES = {
    0: "IDLE",
    1: "WAITING",
    2: "EXPOSING",
    3: "READING",
    4: "DOWNLOAD",
    5: "ERROR",
}


def _alpaca_get(ip: str, port: int, device_type: str, device_num: int, prop: str):
    try:
        r = requests.get(
            f"http://{ip}:{port}/api/v1/{device_type}/{device_num}/{prop}",
            params=ALPACA_CLIENT_PARAMS,
            timeout=ALPACA_TIMEOUT,
        )
        data = r.json()
        if data.get("ErrorNumber", 0) == 0:
            return data.get("Value")
    except Exception:
        pass
    return None


def poll_scope_status(ip: str, port: int = 32323) -> dict:
    if not ip or ip == "TBD":
        return {}

    result = {"ip": ip, "port": port}

    try:
        r = requests.get(f"http://{ip}:{port}/management/v1/description", timeout=ALPACA_TIMEOUT)
        if r.status_code != 200:
            return {}

        desc = r.json().get("Value", {})
        result["alpaca_version"] = desc.get("ManufacturerVersion", "unknown")

        r2 = requests.get(f"http://{ip}:{port}/management/v1/configureddevices", timeout=ALPACA_TIMEOUT)
        if r2.status_code == 200:
            result["device_count"] = len(r2.json().get("Value", []))

        result["telescope_connected"] = bool(_alpaca_get(ip, port, "telescope", 0, "connected"))
        result["camera_connected"] = bool(_alpaca_get(ip, port, "camera", 0, "connected"))
        result["filter_connected"] = bool(_alpaca_get(ip, port, "filterwheel", 0, "connected"))

        result["ra"] = _alpaca_get(ip, port, "telescope", 0, "rightascension")
        result["dec"] = _alpaca_get(ip, port, "telescope", 0, "declination")
        result["tracking"] = bool(_alpaca_get(ip, port, "telescope", 0, "tracking"))
        result["at_park"] = bool(_alpaca_get(ip, port, "telescope", 0, "atpark"))
        result["slewing"] = bool(_alpaca_get(ip, port, "telescope", 0, "slewing"))
        result["altitude"] = _alpaca_get(ip, port, "telescope", 0, "altitude")
        result["azimuth"] = _alpaca_get(ip, port, "telescope", 0, "azimuth")
        result["temp_c"] = _alpaca_get(ip, port, "camera", 0, "ccdtemperature")

        camera_state = _alpaca_get(ip, port, "camera", 0, "camerastate")
        result["camera_state"] = camera_state
        result["camera_state_name"] = CAMERA_STATE_NAMES.get(camera_state, "UNKNOWN")

        result["link_status"] = "ONLINE"

    except Exception:
        return {}

    battery = poll_battery_snapshot(ip)
    if battery:
        result.update(battery)

    result["operational_state"] = derive_operational_state(result)
    return result


def derive_operational_state(status: dict) -> str:
    if not status:
        return "OFFLINE"
    if not status.get("telescope_connected", False):
        return "DISCONNECTED"
    if status.get("at_park"):
        return "PARKED"
    if status.get("slewing"):
        return "SLEWING"
    if status.get("camera_state_name") in {"WAITING", "EXPOSING", "READING", "DOWNLOAD"}:
        return "IMAGING"
    if status.get("tracking"):
        return "TRACKING"
    return "IDLE"

