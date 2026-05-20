#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/telescope/seestar_pem_diagnostics.py
Objective: Read-only authenticated Seestar JSON-RPC diagnostics using the APK PEM.
"""

from __future__ import annotations

import argparse
import base64
import json
import socket
import subprocess
import sys
import tempfile
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = PROJECT_ROOT / "config.toml"
DEFAULT_PEM = Path.home() / ".config" / "seestar" / "seestar_3.1.2.pem"


# Load scope names and IP addresses from SeeVar config.toml.
def configured_hosts() -> list[dict[str, str]]:
    if not CONFIG_PATH.exists():
        return []
    with CONFIG_PATH.open("rb") as handle:
        cfg = tomllib.load(handle)
    hosts = []
    for idx, entry in enumerate(cfg.get("seestars", []), start=1):
        ip = str(entry.get("ip", "")).strip()
        if not ip or ip == "TBD":
            continue
        hosts.append(
            {
                "scope_id": f"scope{idx:02d}",
                "name": str(entry.get("name") or f"scope{idx:02d}"),
                "ip": ip,
            }
        )
    return hosts


# Send one JSON-RPC line over the open authenticated socket.
def send_json(sock: socket.socket, payload: dict[str, Any]) -> None:
    sock.sendall((json.dumps(payload, separators=(",", ":")) + "\r\n").encode("utf-8"))


# Read one CRLF-delimited JSON line from the scope.
def read_json_line(file_obj) -> dict[str, Any]:
    line = file_obj.readline()
    if not line:
        raise RuntimeError("empty response from scope")
    try:
        return json.loads(line.decode("utf-8").strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON from scope: {line!r}") from exc


# Skip asynchronous event pushes and return the requested response object.
def read_response(file_obj) -> dict[str, Any]:
    while True:
        payload = read_json_line(file_obj)
        if "Event" not in payload:
            return payload


# Sign the challenge with RSA/SHA1/PKCS1v1.5 via OpenSSL.
def sign_challenge(pem_path: Path, challenge: str) -> str:
    with tempfile.NamedTemporaryFile("wb", delete=True) as handle:
        handle.write(challenge.encode("utf-8"))
        handle.flush()
        result = subprocess.run(
            ["openssl", "dgst", "-sha1", "-sign", str(pem_path), handle.name],
            check=True,
            capture_output=True,
        )
    return base64.b64encode(result.stdout).decode("ascii")


# Authenticate to the scope's port-4700 API and return an open stream.
def authenticate(host: str, port: int, pem_path: Path, timeout: float) -> tuple[socket.socket, Any]:
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(timeout)
    file_obj = sock.makefile("rb")

    send_json(sock, {"id": 1, "method": "get_verify_str", "params": "verify"})
    verify = read_json_line(file_obj)
    result = verify.get("result")
    challenge = result.get("str") if isinstance(result, dict) else result
    if not isinstance(challenge, str) or not challenge:
        raise RuntimeError(f"missing challenge string: {verify}")

    signature = sign_challenge(pem_path, challenge)
    send_json(sock, {"id": 2, "method": "verify_client", "params": {"sign": signature, "data": challenge}})
    ack = read_json_line(file_obj)
    if int(ack.get("code", -1)) != 0:
        raise RuntimeError(f"authentication failed: {ack}")

    send_json(sock, {"id": 3, "method": "pi_is_verified", "params": "verify"})
    read_json_line(file_obj)
    return sock, file_obj


# Run the read-only authenticated diagnostics calls.
def run_diagnostics(host: str, port: int, pem_path: Path, timeout: float) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    sock, file_obj = authenticate(host, port, pem_path, timeout)
    try:
        send_json(sock, {"id": 4, "method": "get_device_state", "params": []})
        device_state = read_response(file_obj)
        send_json(sock, {"id": 5, "method": "pi_get_info", "params": []})
        pi_info = read_response(file_obj)
    finally:
        try:
            file_obj.close()
        finally:
            sock.close()

    finished = datetime.now(timezone.utc)
    return {
        "checked_utc": finished.isoformat(),
        "elapsed_ms": round((finished - started).total_seconds() * 1000.0, 1),
        "host": host,
        "port": port,
        "device_state": device_state,
        "pi_info": pi_info,
    }


# Return a compact status object for dashboard-style operator checks.
def compact_summary(scope: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    state = payload.get("device_state", {}).get("result", {})
    info = payload.get("pi_info", {}).get("result", {})
    device = state.get("device", {}) if isinstance(state, dict) else {}
    pi_status = state.get("pi_status", {}) if isinstance(state, dict) else {}
    return {
        "scope_id": scope.get("scope_id"),
        "name": scope.get("name"),
        "ip": scope.get("ip"),
        "ok": True,
        "elapsed_ms": payload.get("elapsed_ms"),
        "product_model": device.get("product_model"),
        "firmware": device.get("firmware_ver_string"),
        "battery": pi_status.get("battery_capacity") or info.get("battery_capacity"),
        "charger": pi_status.get("charger_status") or info.get("charger_status"),
    }


# Parse command line arguments.
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", action="append", help="Scope IP/host. May be repeated. Defaults to config.toml scopes.")
    parser.add_argument("--port", type=int, default=4700, help="Seestar authenticated JSON-RPC port.")
    parser.add_argument("--pem", type=Path, default=DEFAULT_PEM, help="Private PEM path.")
    parser.add_argument("--timeout", type=float, default=5.0, help="Socket timeout in seconds.")
    parser.add_argument("--json", action="store_true", help="Emit full JSON diagnostics.")
    parser.add_argument("--output", type=Path, default=None, help="Write full diagnostics JSON to this path.")
    return parser.parse_args()


# CLI entry point.
def main() -> int:
    args = parse_args()
    pem_path = args.pem.expanduser()
    if not pem_path.exists():
        print(f"PEM missing: {pem_path}", file=sys.stderr)
        return 2

    scopes = [{"scope_id": None, "name": host, "ip": host} for host in args.host] if args.host else configured_hosts()
    if not scopes:
        print("No hosts supplied and no usable [[seestars]] entries found.", file=sys.stderr)
        return 2

    full_results = []
    summaries = []
    rc = 0
    for scope in scopes:
        try:
            payload = run_diagnostics(scope["ip"], args.port, pem_path, args.timeout)
            full_results.append({**scope, **payload})
            summaries.append(compact_summary(scope, payload))
        except Exception as exc:
            rc = 1
            item = {**scope, "ok": False, "error": str(exc)}
            full_results.append(item)
            summaries.append(item)

    if args.output:
        args.output.expanduser().parent.mkdir(parents=True, exist_ok=True)
        args.output.expanduser().write_text(json.dumps(full_results, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(full_results, indent=2, sort_keys=True))
    else:
        for item in summaries:
            if item.get("ok"):
                print(
                    f"{item.get('name')} {item.get('ip')} OK "
                    f"{item.get('elapsed_ms')}ms bat={item.get('battery')} charger={item.get('charger')} "
                    f"{item.get('product_model')} fw={item.get('firmware')}"
                )
            else:
                print(f"{item.get('name')} {item.get('ip')} FAIL {item.get('error')}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
