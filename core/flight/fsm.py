#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/fsm.py
Version: 1.1.0
Objective: The Finite State Machine governing S30-PRO Sovereign Operations.
           Wired to DiamondSequence for robust AAVSO target acquisition.
"""

import logging
from typing import Optional
from core.flight.pilot import DiamondSequence, AcquisitionTarget, TelemetryBlock

logger = logging.getLogger("seevar.fsm")

class SovereignFSM:
    def __init__(self):
        # Aligned with the Bridge states: IDLE, WORKING, SUCCESS, ERROR
        self.state = "IDLE"
        self.telemetry: Optional[TelemetryBlock] = None
        self.sequence = DiamondSequence()
        logger.info(f"🧠 FSM Initialized in state: {self.state}")

    def update(self, new_state: str):
        """Transition the internal state representation."""
        self.state = new_state
        logger.info(f"🔄 FSM State updated to: {self.state}")

    def get_status(self) -> str:
        """Return current operational state."""
        return self.state
        
    def execute_target(self, target: AcquisitionTarget) -> bool:
        """
        Run the full Diamond Sequence for a specific target.
        Manages FSM transitions and error recovery.
        """
        self.update("WORKING")
        
        try:
            # Step 1: Initialize Session & Check Hardware
            logger.info(f"🚀 Initiating session for {target.name}...")
            self.telemetry = self.sequence.init_session()
            
            if not self.telemetry.is_safe():
                logger.error(f"❌ Hardware veto: {self.telemetry.veto_reason()}")
                self.update("ERROR")
                return False
            
            # Step 2: Acquire Target
            logger.info(f"🔭 Acquiring {target.n_frames} frames for {target.name}...")
            
            # Frame loop for the requested integration stack
            successful_frames = 0
            for i in range(target.n_frames):
                logger.info(f"📸 Exposing frame {i+1}/{target.n_frames}...")
                
                result = self.sequence.acquire(
                    target=target,
                    status_cb=lambda msg: logger.info(f"Bridge: {msg}"),
                    telemetry=self.telemetry
                )
                
                if result.success:
                    logger.info(f"✅ Frame {i+1} saved to {result.path}")
                    successful_frames += 1
                else:
                    logger.error(f"❌ Frame {i+1} failed: {result.error}")
                    # Decide whether to abort the target entirely or keep pushing
                    # For strict AAVSO cadence, if one frame fails, we abort the sequence to recover hardware
                    self.update("ERROR")
                    return False
            
            if successful_frames == target.n_frames:
                logger.info(f"🏁 Acquisition complete for {target.name}.")
                self.update("SUCCESS")
                return True
            else:
                self.update("ERROR")
                return False
                
        except Exception as e:
            logger.exception(f"💥 FSM Critical Failure: {e}")
            self.update("ERROR")
            return False
        finally:
            # Always return the FSM to IDLE if successful, so the Orchestrator can pull the next target
            if self.state == "SUCCESS":
                self.update("IDLE")
