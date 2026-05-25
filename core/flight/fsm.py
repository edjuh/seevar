#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/fsm.py
Version: 1.3.0
Objective: Finite State Machine governing A1-A12 target execution and failure handling for Sovereign flight operations, with live bridge-state updates back into system_state.json.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.flight.pilot import AcquisitionTarget, DiamondSequence, TelemetryBlock
from core.utils.env_loader import DATA_DIR, load_config

logger = logging.getLogger("seevar.fsm")

STATE_FILE = DATA_DIR / "system_state.json"


# Function: _flight_cfg
def _flight_cfg() -> dict:
    cfg = load_config()
    return cfg.get("flight", {}) if isinstance(cfg, dict) else {}


# Function: _cfg_int
def _cfg_int(key: str, default: int) -> int:
    try:
        return int(round(float(_flight_cfg().get(key, default))))
    except Exception:
        return default


FRAME_RETRY_LIMIT = max(0, _cfg_int("frame_retry_limit", 0))
POINTING_REVERIFY_INTERVAL_FRAMES = max(1, _cfg_int("pointing_reverify_interval_frames", 5))
TAG_STATE = {
    "[A4]": "SLEWING",
    "[A5]": "SLEWING",
    "[A6]": "SLEWING",
    "[A7]": "EXPOSING",
    "[A8]": "TRACKING",
    "[A10]": "EXPOSING",
    "[A11]": "TRACKING",
}


class SovereignFSM:
    # Function: SovereignFSM.__init__
    def __init__(self):
        self.state = "IDLE"
        self.telemetry: Optional[TelemetryBlock] = None
        self.last_prepared_target: Optional[AcquisitionTarget] = None
        self.last_frame_paths: list[Path] = []
        self.frame_retry_limit = FRAME_RETRY_LIMIT
        self.pointing_reverify_interval_frames = POINTING_REVERIFY_INTERVAL_FRAMES
        self.sequence = DiamondSequence()
        logger.info("🧠 FSM Initialized in state: %s", self.state)

    # Function: SovereignFSM.update
    def update(self, new_state: str):
        self.state = new_state
        logger.info("🔄 FSM State updated to: %s", self.state)

    # Function: SovereignFSM.get_status
    def get_status(self) -> str:
        return self.state

    # Function: SovereignFSM._bridge_ui_state
    def _bridge_ui_state(self, msg: str) -> str | None:
        for tag, state in TAG_STATE.items():
            if msg.startswith(tag):
                return state
        return None

    # Function: SovereignFSM._write_state_bridge
    def _write_state_bridge(self, state: str | None, msg: str):
        try:
            payload = {}
            if STATE_FILE.exists():
                payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
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

            tmp_path = STATE_FILE.with_suffix(f"{STATE_FILE.suffix}.tmp")
            tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp_path.replace(STATE_FILE)
        except Exception as e:
            logger.debug("State bridge write skipped: %s", e)

    # Function: SovereignFSM.execute_target
    def execute_target(
        self,
        target: AcquisitionTarget,
        status_cb: Optional[Callable[[str], None]] = None,
        telemetry: Optional[TelemetryBlock] = None,
        abort_cb: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """
        Run the per-target sovereign sequence.

        Orchestrator owns A1, A2, A9, A12 framing.
        FSM owns A3-A11 execution and state handling.
        """
        self.update("WORKING")
        self.last_prepared_target = None
        self.last_frame_paths = []
        self.frame_retry_limit = max(0, _cfg_int("frame_retry_limit", self.frame_retry_limit))
        self.pointing_reverify_interval_frames = max(
            1,
            _cfg_int("pointing_reverify_interval_frames", self.pointing_reverify_interval_frames),
        )

        # Function: SovereignFSM.execute_target.bridge
        def bridge(*parts):
            if len(parts) == 1:
                msg = parts[0]
            elif len(parts) == 2:
                msg = f"[{parts[0]}] {parts[1]}"
            else:
                msg = " ".join(str(p) for p in parts)

            logger.info("Bridge: %s", msg)
            ui_state = self._bridge_ui_state(msg)
            self._write_state_bridge(ui_state, msg)
            if status_cb:
                status_cb(msg)

        # Function: SovereignFSM.execute_target.abort_requested
        def abort_requested() -> bool:
            try:
                return bool(abort_cb and abort_cb())
            except Exception as e:
                logger.warning("Abort callback failed: %s", e)
                return False

        try:
            if abort_requested():
                self._write_state_bridge("ABORTED", "Operator abort before target execution")
                self.update("ERROR")
                return False

            if telemetry and telemetry.is_safe():
                self.telemetry = telemetry
                logger.info("[A3] Reusing validated session telemetry for %s", target.name)
                self._write_state_bridge("PREFLIGHT", f"[A3] Reusing validated session telemetry for {target.name}")
            elif self.telemetry and self.telemetry.is_safe():
                logger.info("[A3] Reusing cached session telemetry for %s", target.name)
                self._write_state_bridge("PREFLIGHT", f"[A3] Reusing cached session telemetry for {target.name}")
            else:
                logger.info("[A3] Session init for %s", target.name)
                self._write_state_bridge("PREFLIGHT", f"[A3] Session init for {target.name}")
                self.telemetry = self.sequence.init_session()

            if not self.telemetry or not self.telemetry.is_safe():
                reason = self.telemetry.veto_reason() if self.telemetry else "Telemetry unavailable"
                logger.error("[A3] Hardware veto: %s", reason)
                self._write_state_bridge("ABORTED", f"[A3] Hardware veto: {reason}")
                self.update("ERROR")
                return False

            target = self.sequence.prepare_target(target, telemetry=self.telemetry, notify=bridge)
            if target is None:
                raise RuntimeError("prepare_target returned None")
            self.last_prepared_target = target
            logger.info("[A10] Acquire %d frame(s) for %s", target.n_frames, target.name)

            successful_frames = 0
            failed_frames = 0
            for i in range(target.n_frames):
                if abort_requested():
                    self._write_state_bridge("ABORTED", f"Operator abort during {target.name}")
                    self.update("ERROR")
                    return False

                logger.info("[A10] Executing frame %d/%d", i + 1, target.n_frames)
                frame_ok = False
                last_error = ""

                for attempt in range(self.frame_retry_limit + 1):
                    if attempt == 0:
                        self._write_state_bridge("EXPOSING", f"[A10] Executing frame {i + 1}/{target.n_frames} for {target.name}")
                    else:
                        logger.warning("[A10] Retrying frame %d/%d for %s (%d/%d)", i + 1, target.n_frames, target.name, attempt, self.frame_retry_limit)
                        self._write_state_bridge("EXPOSING", f"[A10] Retrying frame {i + 1}/{target.n_frames} for {target.name} ({attempt}/{self.frame_retry_limit})")

                    reverify_due = (
                        successful_frames == 0
                        or successful_frames % self.pointing_reverify_interval_frames == 0
                    )
                    result = self.sequence.acquire(
                        target=target,
                        status_cb=bridge,
                        telemetry=self.telemetry,
                        skip_pointing=not reverify_due,
                        abort_callback=abort_requested,
                    )

                    if result.error == "operator_abort":
                        self._write_state_bridge("ABORTED", f"Operator abort during {target.name}")
                        self.update("ERROR")
                        return False

                    if result.success:
                        logger.info("[A11] Frame %d accepted: %s", i + 1, result.path)
                        self._write_state_bridge("TRACKING", f"[A11] Frame {i + 1} accepted: {result.path}")
                        if result.path:
                            self.last_frame_paths.append(Path(result.path))
                        successful_frames += 1
                        frame_ok = True
                        break

                    last_error = result.error
                    logger.error("[A11] Frame %d failed: %s", i + 1, result.error)

                if not frame_ok:
                    failed_frames += 1
                    if target.n_frames == 1:
                        self._write_state_bridge("ABORTED", f"[A11] Frame {i + 1} failed after retries: {last_error}")
                        self.update("ERROR")
                        return False

                    logger.warning("[A11] Continuing after frame %d failure for %s", i + 1, target.name)
                    self._write_state_bridge(None, f"[A11] Frame {i + 1} failed after retries: {last_error}")

            if successful_frames == target.n_frames:
                logger.info("[A11] Acquisition complete for %s", target.name)
                self._write_state_bridge("TRACKING", f"[A11] Acquisition complete for {target.name}")
                self.update("SUCCESS")
                return True

            if successful_frames > 0:
                logger.warning("[A11] Acquisition partial for %s: %d/%d frame(s) accepted, %d failed", target.name, successful_frames, target.n_frames, failed_frames)
                self._write_state_bridge("TRACKING", f"[A11] Acquisition partial for {target.name}: {successful_frames}/{target.n_frames} frame(s) accepted")
                self.update("SUCCESS")
                return True

            self._write_state_bridge("ABORTED", f"[A11] Acquisition failed for {target.name}: 0/{target.n_frames} frame(s) accepted")
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
