#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/fsm.py
Version: 1.2.0
Objective: Finite State Machine governing A1-A12 target execution and failure handling for Sovereign flight operations.
"""

import logging
from typing import Optional
from core.flight.pilot import DiamondSequence, AcquisitionTarget, TelemetryBlock

logger = logging.getLogger("seevar.fsm")


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

    def execute_target(self, target: AcquisitionTarget) -> bool:
        """
        Run the per-target sovereign sequence.

        Orchestrator owns A1, A2, A9, A12 framing.
        FSM owns A3-A11 execution and state handling.
        """
        self.update("WORKING")

        try:
            logger.info("[A3] Session init for %s", target.name)
            self.telemetry = self.sequence.init_session()

            if not self.telemetry.is_safe():
                logger.error("[A3] Hardware veto: %s", self.telemetry.veto_reason())
                self.update("ERROR")
                return False

            logger.info("[A10] Acquire %d frame(s) for %s", target.n_frames, target.name)

            successful_frames = 0
            for i in range(target.n_frames):
                logger.info("[A10] Executing frame %d/%d", i + 1, target.n_frames)

                result = self.sequence.acquire(
                    target=target,
                    status_cb=lambda msg: logger.info("Bridge: %s", msg),
                    telemetry=self.telemetry,
                )

                if result.success:
                    logger.info("[A11] Frame %d accepted: %s", i + 1, result.path)
                    successful_frames += 1
                else:
                    logger.error("[A11] Frame %d failed: %s", i + 1, result.error)
                    self.update("ERROR")
                    return False

            if successful_frames == target.n_frames:
                logger.info("[A11] Acquisition complete for %s", target.name)
                self.update("SUCCESS")
                return True

            self.update("ERROR")
            return False

        except Exception as e:
            logger.exception("💥 FSM Critical Failure: %s", e)
            self.update("ERROR")
            return False

        finally:
            if self.state == "SUCCESS":
                self.update("IDLE")
