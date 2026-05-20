#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/telescope/sync_fleet_orchestrators.py
Objective: Start orchestrator instance units for online scopes and stop stale ones.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.env_loader import configured_scopes, live_available_scopes, load_config


def run_systemctl(args: list[str], *, apply: bool) -> int:
    cmd = ["systemctl", "--user", *args]
    print(" ".join(cmd))
    if not apply:
        return 0
    return subprocess.run(cmd, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize SeeVar fleet orchestrator units.")
    parser.add_argument("--apply", action="store_true", help="Actually run systemctl changes.")
    args = parser.parse_args()

    cfg = load_config()
    requested = str(cfg.get("planner", {}).get("fleet_mode", "single")).strip().lower()
    scopes = configured_scopes(cfg, active_only=True)
    online = {scope["scope_id"]: scope for scope in live_available_scopes(cfg, cache_ttl=0)}

    print(f"fleet_mode={requested}")
    print("online=" + ",".join(sorted(online)) if online else "online=none")

    if requested not in {"split", "auto"}:
        print("single fleet mode; leaving unscoped orchestrator policy unchanged")
        return 0

    rc = 0
    rc |= run_systemctl(["stop", "seevar-orchestrator.service"], apply=args.apply)
    rc |= run_systemctl(["disable", "seevar-orchestrator.service"], apply=args.apply)

    for scope in scopes:
        unit = f"seevar-orchestrator@{scope['scope_id']}.service"
        if scope["scope_id"] in online:
            rc |= run_systemctl(["enable", "--now", unit], apply=args.apply)
        else:
            rc |= run_systemctl(["stop", unit], apply=args.apply)

    rc |= run_systemctl(["reset-failed"], apply=args.apply)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
