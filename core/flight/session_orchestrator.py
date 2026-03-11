#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/flight/session_orchestrator.py
Version: 1.2.1
Objective: Executive Orchestrator. Ties Flight operations to Postflight science.
"""

import sys
import logging
import time
from pathlib import Path

# Aligning with PROJECT_ROOT
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))

from core.flight.pilot import Pilot
from core.postflight.science_processor import ScienceProcessor

logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s [ORCHESTRATOR] 💎 %(message)s'
)
logger = logging.getLogger("Executive")

class Orchestrator:
    def __init__(self):
        self.pilot = Pilot()
        self.processor = ScienceProcessor()

    def run_mission(self, target_name, ra, dec, exp_ms):
        """The Complete Sovereignty Lifecycle: Acquisition -> Extraction."""
        logger.info(f"🌌 Starting mission for: {target_name}")
        
        # 1. Acquisition (The Pilot commands the Librarian to RAID1 via Sovereign Stamp)
        final_fits = self.pilot.capture_and_stamp(target_name, ra, dec, exp_ms)
        
        # 2. Science Extraction (The Siril-backed Green Squeeze)
        if final_fits and final_fits.exists():
            logger.info(f"🧪 Handing over {target_name} to Science Processor...")
            processed_fits = self.processor.process_green_stack(target_name.replace(" ", "_"))
            
            if processed_fits:
                logger.info(f"🏆 Mission Success. Green-Mono Diamond ready: {processed_fits}")
            else:
                logger.error("⚠️ Flight succeeded, but Science processing failed.")
        else:
            logger.error(f"❌ Aborting handover. No valid FITS generated for {target_name}.")

if __name__ == "__main__":
    pass
