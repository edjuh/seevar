#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/telescope/run_seevar_lite.py
Version: 0.1.0
Objective: Submit and monitor a seestarpy plan through the SeeVar Lite path.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core.lite.executor import SeestarPyPlanExecutor
from core.lite.monitor import DEFAULT_STATUS_PATH, LitePlanMonitor


# Function: _load_plan
def _load_plan(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or not isinstance(payload.get("list"), list):
        raise ValueError(f"{path} is not a seestarpy plan dictionary")
    return payload


# Function: _print_status
def _print_status(status: dict) -> None:
    counts = status.get("target_state_counts", {})
    print(
        "state={state} active={active} plan={plan} targets={targets} proof={proof}".format(
            state=status.get("state"),
            active=status.get("active"),
            plan=status.get("plan_name"),
            targets=counts,
            proof=status.get("proof_path"),
        )
    )


# Function: main
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--monitor", action="store_true")
    parser.add_argument("--poll-sec", type=float, default=30.0)
    parser.add_argument("--timeout-sec", type=float)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS_PATH)
    parser.add_argument("--proof", type=Path)
    args = parser.parse_args()

    plan_payload = _load_plan(args.plan.expanduser().resolve())
    executor = SeestarPyPlanExecutor()

    if args.submit:
        print(json.dumps(executor.submit_plan(plan_payload), sort_keys=True))

    monitor = LitePlanMonitor(executor, args.status.expanduser(), args.proof.expanduser() if args.proof else None)
    status = monitor.monitor_until_inactive(args.poll_sec, args.timeout_sec) if args.monitor else monitor.sample_once()
    _print_status(status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
