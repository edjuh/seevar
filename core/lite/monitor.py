#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/lite/monitor.py
Version: 0.1.0
Objective: Monitor a SeeVar Lite plan run and write proof/status artifacts.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.lite.executor import PlanExecutor


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATUS_PATH = PROJECT_ROOT / "data" / "system_state_lite.json"
DEFAULT_PROOF_DIR = PROJECT_ROOT / "data" / "flight_runs"


# Function: utc_timestamp
def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# Function: target_state_counts
def target_state_counts(status: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for target in status.get("targets", []):
        state = str(target.get("state") or "unknown")
        counts[state] = counts.get(state, 0) + 1
    return counts


class LitePlanMonitor:
    # Function: LitePlanMonitor.__init__
    def __init__(
        self,
        executor: PlanExecutor,
        status_path: Path = DEFAULT_STATUS_PATH,
        proof_path: Path | None = None,
    ):
        self.executor = executor
        self.status_path = status_path
        self.proof_path = proof_path or DEFAULT_PROOF_DIR / f"lite_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.jsonl"

    # Function: LitePlanMonitor._write_json
    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    # Function: LitePlanMonitor._append_jsonl
    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    # Function: LitePlanMonitor.sample_once
    def sample_once(self) -> dict[str, Any]:
        status = dict(self.executor.poll_plan())
        status["timestamp_utc"] = utc_timestamp()
        status["target_state_counts"] = target_state_counts(status)
        status["proof_path"] = str(self.proof_path)
        self._write_json(self.status_path, status)
        self._append_jsonl(self.proof_path, status)
        return status

    # Function: LitePlanMonitor.monitor_until_inactive
    def monitor_until_inactive(self, poll_sec: float = 30.0, timeout_sec: float | None = None) -> dict[str, Any]:
        started = time.monotonic()
        latest = self.sample_once()
        while latest.get("active"):
            if timeout_sec is not None and time.monotonic() - started >= timeout_sec:
                latest["timeout"] = True
                self._write_json(self.status_path, latest)
                self._append_jsonl(self.proof_path, latest)
                return latest
            time.sleep(max(0.1, float(poll_sec)))
            latest = self.sample_once()
        return latest
