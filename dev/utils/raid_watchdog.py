#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/utils/raid_watchdog.py
Version: 1.0.0
Objective: Check mdadm RAID health and publish a small SeeVar state file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


# Convert the md device path into the array name used by /proc/mdstat.
def _array_name(array_path: str) -> str:
    return Path(array_path).name


# Read /proc/mdstat as the primary mdadm health source available to users.
def _read_mdstat(path: Path = Path("/proc/mdstat")) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# Extract the block of mdstat text belonging to one md array.
def _array_block(mdstat: str, array_name: str) -> str:
    lines = mdstat.splitlines()
    for idx, line in enumerate(lines):
        if line.startswith(f"{array_name} :"):
            block = [line]
            for extra in lines[idx + 1 :]:
                if re.match(r"^md\d+\s+:", extra):
                    break
                if extra.strip() == "unused devices: <none>":
                    break
                block.append(extra)
            return "\n".join(block)
    return ""


# Parse mdstat into simple fields that are stable enough for watchdog use.
def _parse_mdstat(mdstat: str, array_name: str) -> dict[str, object]:
    block = _array_block(mdstat, array_name)
    if not block:
        return {
            "array": array_name,
            "present": False,
            "ok": False,
            "severity": "CRITICAL",
            "reasons": [f"{array_name} not present in /proc/mdstat"],
            "mdstat_block": "",
        }

    reasons: list[str] = []
    severity = "OK"
    active_match = re.search(r"\[(U+_*)\]", block)
    active_map = active_match.group(1) if active_match else None
    failed = "(F)" in block or "faulty" in block.lower() or "failed" in block.lower()
    degraded = bool(active_map and "_" in active_map)
    recovering = "recovery =" in block or "resync =" in block or "reshape =" in block

    if failed:
        severity = "CRITICAL"
        reasons.append("RAID member marked failed/faulty")
    if degraded:
        severity = "CRITICAL"
        reasons.append(f"RAID array degraded: [{active_map}]")
    if recovering:
        severity = "WARN" if severity == "OK" else severity
        reasons.append("RAID array is rebuilding/resyncing")
    if not active_map:
        severity = "WARN" if severity == "OK" else severity
        reasons.append("Could not read active mirror map from mdstat")

    return {
        "array": array_name,
        "present": True,
        "ok": severity == "OK",
        "severity": severity,
        "reasons": reasons,
        "active_map": active_map,
        "failed": failed,
        "degraded": degraded,
        "recovering": recovering,
        "mdstat_block": block,
    }


# Check that the expected RAID mount is mounted and points to the md array.
def _check_mount(mountpoint: Path, array_path: str) -> dict[str, object]:
    result: dict[str, object] = {
        "mountpoint": str(mountpoint),
        "mounted": False,
        "source": None,
        "ok": False,
        "reasons": [],
    }
    try:
        with Path("/proc/mounts").open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == str(mountpoint):
                    result["mounted"] = True
                    result["source"] = parts[0]
                    break
    except OSError as exc:
        result["reasons"] = [f"could not read /proc/mounts: {exc}"]
        return result

    if not result["mounted"]:
        result["reasons"] = [f"{mountpoint} is not mounted"]
        return result

    if result["source"] != array_path:
        result["reasons"] = [f"{mountpoint} source is {result['source']}, expected {array_path}"]
        return result

    result["ok"] = True
    return result


# Prove the mounted filesystem can accept a tiny fsync write.
def _write_probe(mountpoint: Path) -> dict[str, object]:
    probe = mountpoint / ".seevar_raid_watchdog_probe"
    result: dict[str, object] = {"enabled": True, "ok": False, "path": str(probe), "error": None}
    try:
        with probe.open("wb") as handle:
            handle.write(b"seevar raid watchdog\n")
            handle.flush()
            os.fsync(handle.fileno())
        probe.unlink(missing_ok=True)
        result["ok"] = True
    except OSError as exc:
        result["error"] = str(exc)
    return result


# Stop services that may write into the damaged RAID-backed data tree.
def _stop_services(services: list[str]) -> dict[str, object]:
    result: dict[str, object] = {"enabled": bool(services), "services": services, "ok": True, "error": None}
    if not services:
        return result
    cmd = ["systemctl", "--user", "stop", *services]
    try:
        subprocess.run(cmd, check=True, timeout=20)
    except Exception as exc:
        result["ok"] = False
        result["error"] = str(exc)
    return result


# Store the watchdog result where the dashboard or operators can inspect it.
def _write_state(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


# Build a complete status payload and process exit code.
def run_check(args: argparse.Namespace) -> tuple[int, dict[str, object]]:
    now = datetime.now(timezone.utc).isoformat()
    array_name = _array_name(args.array)
    mdstat = _read_mdstat()
    raid = _parse_mdstat(mdstat, array_name)
    mount = _check_mount(args.mountpoint, args.array)
    write = {"enabled": False, "ok": True}
    reasons = list(raid.get("reasons", []))
    severity = str(raid["severity"])

    if not mount["ok"]:
        severity = "CRITICAL"
        reasons.extend(mount.get("reasons", []))
    elif args.write_probe and severity != "CRITICAL":
        write = _write_probe(args.mountpoint)
        if not write["ok"]:
            severity = "CRITICAL"
            reasons.append(f"write probe failed: {write.get('error')}")
    elif args.write_probe and severity == "CRITICAL":
        write = {"enabled": True, "ok": False, "skipped": True, "error": "skipped because RAID is already critical"}

    service_action = {"enabled": False, "ok": True}
    if severity == "CRITICAL" and args.stop_services:
        service_action = _stop_services(args.service)

    ok = severity == "OK"
    payload: dict[str, object] = {
        "checked_utc": now,
        "last_update": time.time(),
        "status": severity,
        "ok": ok,
        "array": args.array,
        "mountpoint": str(args.mountpoint),
        "reasons": reasons,
        "raid": raid,
        "mount": mount,
        "write_probe": write,
        "service_action": service_action,
    }
    return (0 if ok else 2), payload


# Parse CLI flags for systemd and manual operator checks.
def main() -> int:
    parser = argparse.ArgumentParser(description="Check SeeVar mdadm RAID health.")
    parser.add_argument("--array", default="/dev/md0", help="mdadm array device to check")
    parser.add_argument("--mountpoint", type=Path, default=Path("/mnt/raid1"), help="RAID mountpoint")
    parser.add_argument(
        "--state",
        type=Path,
        default=Path.home() / "seevar" / "logs" / "raid_state.json",
        help="JSON state output path",
    )
    parser.add_argument("--no-write-probe", action="store_false", dest="write_probe", help="Skip fsync write probe")
    parser.add_argument(
        "--stop-services",
        action="store_true",
        help="Stop SeeVar writer services when RAID health is CRITICAL",
    )
    parser.add_argument(
        "--service",
        action="append",
        default=[
            "seevar-orchestrator.service",
            "seevar-weather.service",
            "seevar-dashboard.service",
            "seevar-telescope.service",
            "seevar-gps.service",
        ],
        help="User service to stop on CRITICAL; may be repeated",
    )
    args = parser.parse_args()

    code, payload = run_check(args)
    _write_state(args.state, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
