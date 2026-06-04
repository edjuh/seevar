#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tests/test_lite_executor.py
Version: 0.1.0
Objective: Verify SeeVar Lite plan executor and monitor proof output.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.lite.executor import SeestarPyPlanExecutor, normalize_running_plan
from core.lite.monitor import LitePlanMonitor


class FakePlanModule:
    # Function: FakePlanModule.__init__
    def __init__(self):
        self.submitted = None
        self.stopped = False
        self.running = {
            "state": "working",
            "plan": {
                "plan_name": "Lite Test",
                "list": [
                    {"target_id": 1, "target_name": "ST Boo", "state": "working", "lapse_ms": 1000},
                    {"target_id": 2, "target_name": "TT Boo", "state": "pending", "skip": False},
                ],
            },
        }

    # Function: FakePlanModule.set_view_plan
    def set_view_plan(self, payload):
        self.submitted = payload

    # Function: FakePlanModule.get_running_plan
    def get_running_plan(self):
        return self.running

    # Function: FakePlanModule.stop_view_plan
    def stop_view_plan(self):
        self.stopped = True


# Function: test_normalize_running_plan_handles_idle
def test_normalize_running_plan_handles_idle():
    status = normalize_running_plan(None)

    assert status["state"] == "idle"
    assert status["active"] is False
    assert status["targets"] == []


# Function: test_seestarpy_executor_wraps_plan_module
def test_seestarpy_executor_wraps_plan_module():
    fake = FakePlanModule()
    executor = SeestarPyPlanExecutor(fake)
    payload = {"plan_name": "Lite Test", "list": [{"target_name": "ST Boo"}]}

    submit = executor.submit_plan(payload)
    poll = executor.poll_plan()
    stop = executor.stop_plan()

    assert fake.submitted == payload
    assert submit["target_count"] == 1
    assert poll["state"] == "working"
    assert poll["active"] is True
    assert poll["targets"][0]["target_name"] == "ST Boo"
    assert stop["success"] is True
    assert fake.stopped is True


# Function: test_lite_monitor_writes_status_and_proof
def test_lite_monitor_writes_status_and_proof(tmp_path):
    executor = SeestarPyPlanExecutor(FakePlanModule())
    status_path = tmp_path / "status.json"
    proof_path = tmp_path / "proof.jsonl"
    monitor = LitePlanMonitor(executor, status_path, proof_path)

    status = monitor.sample_once()

    assert status["target_state_counts"] == {"working": 1, "pending": 1}
    assert status_path.exists()
    assert proof_path.exists()
    saved = json.loads(status_path.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in proof_path.read_text(encoding="utf-8").splitlines()]
    assert saved["plan_name"] == "Lite Test"
    assert rows[0]["proof_path"] == str(proof_path)
