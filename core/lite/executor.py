#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/lite/executor.py
Version: 0.1.0
Objective: Provide the small SeeVar Lite plan-executor interface.
"""

from __future__ import annotations

from typing import Any, Protocol


ACTIVE_STATES = {"working", "waiting", "pending", "running"}


class PlanExecutor(Protocol):
    # Function: PlanExecutor.submit_plan
    def submit_plan(self, plan_payload: dict[str, Any]) -> dict[str, Any]: ...

    # Function: PlanExecutor.poll_plan
    def poll_plan(self) -> dict[str, Any]: ...

    # Function: PlanExecutor.stop_plan
    def stop_plan(self) -> dict[str, Any]: ...


# Function: _target_summary
def _target_summary(target: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_id": target.get("target_id"),
        "target_name": target.get("target_name"),
        "state": target.get("state", "pending"),
        "skip": bool(target.get("skip", False)),
        "lapse_ms": int(target.get("lapse_ms", 0) or 0),
        "start_min": target.get("start_min"),
        "duration_min": target.get("duration_min"),
    }


# Function: normalize_running_plan
def normalize_running_plan(raw: dict[str, Any] | None) -> dict[str, Any]:
    if raw is None:
        return {
            "success": True,
            "state": "idle",
            "active": False,
            "plan_name": None,
            "targets": [],
            "raw": None,
        }

    plan = raw.get("plan", raw)
    state = str(raw.get("state") or plan.get("state") or "unknown").lower()
    targets = [_target_summary(target) for target in plan.get("list", [])]
    return {
        "success": True,
        "state": state,
        "active": state in ACTIVE_STATES,
        "plan_name": plan.get("plan_name"),
        "targets": targets,
        "raw": raw,
    }


class SeestarPyPlanExecutor:
    # Function: SeestarPyPlanExecutor.__init__
    def __init__(self, plan_module: Any | None = None):
        if plan_module is None:
            from seestarpy import plan as plan_module

        self.plan_module = plan_module

    # Function: SeestarPyPlanExecutor.submit_plan
    def submit_plan(self, plan_payload: dict[str, Any]) -> dict[str, Any]:
        self.plan_module.set_view_plan(plan_payload)
        return {
            "success": True,
            "action": "set_view_plan",
            "plan_name": plan_payload.get("plan_name"),
            "target_count": len(plan_payload.get("list", [])),
        }

    # Function: SeestarPyPlanExecutor.poll_plan
    def poll_plan(self) -> dict[str, Any]:
        return normalize_running_plan(self.plan_module.get_running_plan())

    # Function: SeestarPyPlanExecutor.stop_plan
    def stop_plan(self) -> dict[str, Any]:
        self.plan_module.stop_view_plan()
        return {"success": True, "action": "stop_view_plan"}
