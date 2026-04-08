#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/hardware/live_battery.py
Version: 1.3.0
Objective: Poll live Seestar battery and charger state from JSON-RPC pi_get_info on port 4701,
           while preserving the older poll_battery_snapshot() interface used by dashboard/seetop.
"""

from __future__ import annotations

import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.toml"


def _load_scope_ip() -> str | None:
    try:
        import tomllib
        cfg = tomllib.loads(CONFIG_PATH.read_text())
        scopes = cfg.get("seestars", [])
        if not scopes:
            return None
        ip = scopes[0].get("ip")
        if not ip or str(ip).strip() in {"", "TBD"}:
            return None
        return str(ip).strip()
    except Exception:
        return None


def _rpc_call(ip: str, method: str, params: list[Any] | None = None, port: int = 4701, timeout: float = 3.0) -> dict:
    payload = {"id": 1, "method": method, "params": params or []}

    with socket.create_connection((ip, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))

        chunks = []
        while True:
            try:
                data = sock.recv(65536)
            except socket.timeout:
                break
            if not data:
                break
            chunks.append(data)

    raw = b"".join(chunks).decode("utf-8", errors="replace").strip()
    if not raw:
        return {}

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict) and "result" in obj:
            return obj

    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and "result" in obj:
            return obj
    except Exception:
        pass

    return {}


def read_live_battery(ip: str | None = None) -> dict:
    ip = ip or _load_scope_ip()
    if not ip:
        return {}

    try:
        reply = _rpc_call(ip, "pi_get_info")
        result = reply.get("result", {}) if isinstance(reply, dict) else {}
        if not isinstance(result, dict):
            return {}

        out = {
            "updated_utc": datetime.now(timezone.utc).isoformat(),
        }

        if result.get("battery_capacity") is not None:
            out["battery"] = str(int(result["battery_capacity"]))
        if result.get("charge_online") is not None:
            out["charge_online"] = bool(result["charge_online"])
        if result.get("charger_status") is not None:
            out["charger_status"] = str(result["charger_status"])
        if result.get("battery_temp") is not None:
            out["battery_temp_c"] = float(result["battery_temp"])
        if result.get("temp") is not None:
            out["device_temp_c"] = float(result["temp"])

        return out
    except Exception:
        return {}


def poll_battery_snapshot(ip: str | None = None) -> dict:
    """
    Backward-compatible wrapper for dashboard/seetop callers.
    """
    return read_live_battery(ip)
