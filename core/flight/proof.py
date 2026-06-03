#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/proof.py
Objective: Append-only per-target proof records for SeeVar flight continuity.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.utils.env_loader import DATA_DIR

RUNS_DIR = DATA_DIR / "flight_runs"


# Function: _safe_name
def _safe_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(value))
    return cleaned.strip("_") or "target"


class FlightProofRecorder:
    # Function: FlightProofRecorder.__init__
    def __init__(self, target_name: str, run_id: str | None = None):
        self.target_name = target_name
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        self.path = RUNS_DIR / f"{self.run_id}_{_safe_name(target_name)}.jsonl"

    # Function: FlightProofRecorder.record
    def record(
        self,
        step: str,
        status: str,
        *,
        detail: str = "",
        evidence_path: str | Path | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        row: dict[str, Any] = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "target": self.target_name,
            "step": step,
            "status": status,
        }
        if detail:
            row["detail"] = detail
        if evidence_path:
            row["evidence_path"] = str(evidence_path)
        if extra:
            row.update(extra)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
