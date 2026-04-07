#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/fsm.py
Version: 1.3.0
Objective: Finite State Machine governing A1-A12 target execution and failure handling for Sovereign flight operations, with live bridge-state updates back into system_state.json.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.flight.pilot import AcquisitionTarget, DiamondSequence, TelemetryBlock
from core.utils.env_loader import DATA_DIR

logger = logging.getLogger("seevar.fsm")

STATE_FILE = DATA_DIR / "system_state.json"


class SovereignFSM:
    def __init__(self):
        self.state = "IDLE"
        self.telemetry: Optional[TelemetryBlock] = None
        self.sequence = DiamondSequence()
        logger.info("🧠 FSM Initialized in state: %s", self.state)

    def update(self, new_state: str):
        self.state = new_state
        logger.info("🔄 FSM State updated to: %s", self.state)

    def get_status(self) -> str:
        return self.state

    def _bridge_ui_state(self, msg: str) -> str | None:
        if msg.startswith("[A4]") or msg.startswith("[A5]") or msg.startswith("[A6]") or msg.startswith("[A7]") or msg.startswith("[A8]"):
            return "SLEWING"
        if msg.startswith("[A10]"):
            return "EXPOSING"
        if msg.startswith("[A11]"):
            return "TRACKING"
        return None

    def _write_state_bridge(self, state: str | None, msg: str):
        try:
            payload = {}
            if STATE_FILE.exists():
                payload = json.loads(STATE_FILE.read_text())
                if not isinstance(payload, dict):
                    payload = {}

            now_utc = datetime.now(timezone.utc).isoformat()

            if state:
                payload["state"] = state

            current_target = payload.get("current_target") or {}
            payload["sub"] = current_target.get("name", payload.get("sub", ""))
            payload["substate"] = payload["sub"]
            payload["msg"] = msg
            payload["message"] = msg
            payload["updated"] = now_utc
            payload["updated_utc"] = now_utc

            STATE_FILE.write_text(json.dumps(payload, indent=2))
        except Exception as e:
            logger.debug("State bridge write skipped: %s", e)

    def execute_target(self, target: AcquisitionTarget, status_cb: Optional[Callable[[str], None]] = None) -> bool:
        """
        Run the per-target sovereign sequence.

        Orchestrator owns A1, A2, A9, A12 framing.
        FSM owns A3-A11 execution and state handling.
        """
        self.update("WORKING")

        def bridge(msg: str):
            logger.info("Bridge: %s", msg)
            ui_state = self._bridge_ui_state(msg)
            self._write_state_bridge(ui_state, msg)
            if status_cb:
                status_cb(msg)

        try:
            logger.info("[A3] Session init for %s", target.name)
            self._write_state_bridge("PREFLIGHT", f"[A3] Session init for {target.name}")
            self.telemetry = self.sequence.init_session()

            if not self.telemetry.is_safe():
                reason = self.telemetry.veto_reason()
                logger.error("[A3] Hardware veto: %s", reason)
                self._write_state_bridge("ABORTED", f"[A3] Hardware veto: {reason}")
                self.update("ERROR")
                return False

            target = self.sequence.prepare_target(target, telemetry=self.telemetry, notify=bridge)
            logger.info("[A10] Acquire %d frame(s) for %s", target.n_frames, target.name)

            successful_frames = 0
            for i in range(target.n_frames):
                logger.info("[A10] Executing frame %d/%d", i + 1, target.n_frames)
                self._write_state_bridge("SLEWING", f"[A4] Executing frame {i + 1}/{target.n_frames} for {target.name}")

                result = self.sequence.acquire(
                    target=target,
                    status_cb=bridge,
                    telemetry=self.telemetry,
                )

                if result.success:
                    logger.info("[A11] Frame %d accepted: %s", i + 1, result.path)
                    self._write_state_bridge("TRACKING", f"[A11] Frame {i + 1} accepted: {result.path}")
                    successful_frames += 1
                else:
                    logger.error("[A11] Frame %d failed: %s", i + 1, result.error)
                    self._write_state_bridge("ABORTED", f"[A11] Frame {i + 1} failed: {result.error}")
                    self.update("ERROR")
                    return False

            if successful_frames == target.n_frames:
                logger.info("[A11] Acquisition complete for %s", target.name)
                self._write_state_bridge("TRACKING", f"[A11] Acquisition complete for {target.name}")
                self.update("SUCCESS")
                return True

            self._write_state_bridge("ABORTED", f"[A11] Acquisition incomplete for {target.name}")
            self.update("ERROR")
            return False

        except Exception as e:
            logger.exception("💥 FSM Critical Failure: %s", e)
            self._write_state_bridge("ABORTED", f"FSM critical failure: {e}")
            self.update("ERROR")
            return False

        finally:
            if self.state == "SUCCESS":
                self.update("IDLE")
