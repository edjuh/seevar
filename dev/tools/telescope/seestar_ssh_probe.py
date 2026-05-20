#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/telescope/seestar_ssh_probe.py
Objective: Read-only SSH health and inventory probe for Seestar scopes.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = PROJECT_ROOT / "config.toml"


# Load configured Seestar hosts from config.toml.
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


# Execute one SSH command and return text plus status.
def ssh_text(host: str, user: str, command: str, timeout: float) -> tuple[int, str, str]:
    cmd = [
        "ssh",
        "-o",
        f"ConnectTimeout={int(timeout)}",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        f"{user}@{host}",
        command,
    ]
    result = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout + 5, check=False)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


# Parse /etc/os-release style key/value output.
def parse_os_release(text: str) -> dict[str, str]:
    parsed = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key] = value.strip().strip('"')
    return parsed


# Run the standard read-only probe set against one host.
def probe_host(host: dict[str, str], user: str, timeout: float) -> dict[str, Any]:
    ip = host["ip"]
    out: dict[str, Any] = {
        "scope_id": host.get("scope_id"),
        "name": host.get("name"),
        "ip": ip,
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "ssh_ok": False,
    }

    rc, hostname, err = ssh_text(ip, user, "hostname", timeout)
    if rc != 0:
        out["error"] = err or hostname or f"ssh exited {rc}"
        return out

    out["ssh_ok"] = True
    out["hostname"] = hostname

    commands = {
        "os_release_raw": "cat /etc/os-release 2>/dev/null || true",
        "kernel": "uname -a",
        "clock": "date -Iseconds 2>/dev/null || date",
        "uptime": "uptime",
        "network": "for i in /sys/class/net/*; do n=$(basename \"$i\"); echo \"$n $(cat \"$i/address\")\"; done; ip addr show",
        "storage": "df -h / /boot /home/pi/.ZWO /usr/local/astrometry/data 2>/dev/null || df -h",
        "zwo_dir": "ls -lah /home/pi/.ZWO 2>/dev/null || true",
        "astrometry_indexes": "ls -lh /usr/local/astrometry/data/index-*.fits 2>/dev/null || true",
        "view_plan": (
            "python3 - <<'PY'\n"
            "import json, pathlib\n"
            "p=pathlib.Path('/home/pi/.ZWO/view_plan.json')\n"
            "if not p.exists():\n"
            "    print('missing')\n"
            "else:\n"
            "    d=json.loads(p.read_text())\n"
            "    plan=d.get('plan', {})\n"
            "    items=plan.get('list', [])\n"
            "    print(json.dumps({\n"
            "      'state': d.get('state'),\n"
            "      'plan_name': plan.get('plan_name'),\n"
            "      'update_time_seestar': plan.get('update_time_seestar'),\n"
            "      'targets': len(items),\n"
            "      'target_names': [x.get('target_name') for x in items[:10]],\n"
            "    }, sort_keys=True))\n"
            "PY"
        ),
    }

    for key, command in commands.items():
        rc, stdout, stderr = ssh_text(ip, user, command, timeout)
        out[key] = stdout
        if rc != 0:
            out[f"{key}_error"] = stderr or f"ssh exited {rc}"

    out["os_release"] = parse_os_release(str(out.get("os_release_raw", "")))
    try:
        out["view_plan_summary"] = json.loads(str(out.get("view_plan", "")))
    except Exception:
        out["view_plan_summary"] = {"raw": out.get("view_plan")}
    return out


# Print a compact human-readable summary.
def print_text_report(results: list[dict[str, Any]]) -> None:
    for result in results:
        print(f"{result.get('name')} ({result.get('ip')})")
        if not result.get("ssh_ok"):
            print(f"  SSH: FAIL {result.get('error')}")
            continue
        os_name = result.get("os_release", {}).get("PRETTY_NAME", "unknown")
        print(f"  SSH: OK as {result.get('hostname')}")
        print(f"  OS : {os_name}")
        print(f"  Plan: {result.get('view_plan_summary')}")
        indexes = str(result.get("astrometry_indexes", "")).splitlines()
        print(f"  Astrometry indexes: {len(indexes)}")
        print("  Storage:")
        for line in str(result.get("storage", "")).splitlines()[:6]:
            print(f"    {line}")


# CLI entry point.
def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only SSH health probe for Seestar scopes.")
    parser.add_argument("--user", default="pi", help="SSH user, usually pi or ed.")
    parser.add_argument("--host", action="append", help="Host/IP to probe. May be repeated.")
    parser.add_argument("--timeout", type=float, default=5.0, help="SSH timeout in seconds.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    args = parser.parse_args()

    hosts = [{"scope_id": None, "name": h, "ip": h} for h in args.host] if args.host else configured_hosts()
    if not hosts:
        print("No hosts supplied and no usable [[seestars]] entries found.", file=sys.stderr)
        return 2

    results = [probe_host(host, args.user, args.timeout) for host in hosts]
    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        print_text_report(results)
    return 1 if any(not item.get("ssh_ok") for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
