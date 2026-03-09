#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seestar_organizer/core/postflight/science_processor.py
Version: 3.0.0
Objective: Automate Siril Green-channel extraction with dynamic flat-field detection.
"""

import os
import subprocess
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger("ScienceProcessor")

PROJECT_ROOT = Path(__file__).resolve().parents[2]

class ScienceProcessor:
    def __init__(self, raw_dir="data/local_buffer", process_dir="data/process"):
        self.raw_path = PROJECT_ROOT / raw_dir
        self.process_path = PROJECT_ROOT / process_dir
        self.process_path.mkdir(parents=True, exist_ok=True)

    def process_green_stack(self, target_name):
        """
        Generates and executes a dynamic Siril Script (.ssf) for the target.
        """
        script_path = self.process_path / f"{target_name}_macro.ssf"
        safe_name = target_name.replace(" ", "_")
        
        # Start Siril Macro
        siril_commands = [
            f'cd "{self.raw_path.absolute()}"',
            f'convert {safe_name}_ -out="{self.process_path.absolute()}/"',
            f'cd "{self.process_path.absolute()}"'
        ]
        
        # Dynamic Calibration Check
        flat_path = self.raw_path / "master-flat.fits"
        if flat_path.exists():
            logger.info("🪟 Master Flat detected. Injecting calibration step...")
            siril_commands.append(f'calibrate {safe_name}_ -flat="{flat_path.absolute()}" -cfa')
            seq_to_extract = f'pp_{safe_name}_'
        else:
            logger.warning("⚠️ No Master Flat found. Proceeding with uncalibrated raw extraction.")
            seq_to_extract = f'{safe_name}_'
            
        # Extraction and Stacking
        siril_commands.extend([
            f'extract {seq_to_extract} -green',
            f'register g_{seq_to_extract}',
            f'stack r_g_{seq_to_extract} rej 3 3 -norm=none -out={safe_name}_Green_Final',
            'close'
        ])
        
        try:
            with open(script_path, 'w') as f:
                f.write('\n'.join(siril_commands))
            
            logger.info(f"🧪 Handing over to Siril CLI for {target_name}...")
            
            result = subprocess.run(
                ['siril-cli', '-s', str(script_path)], 
                capture_output=True, 
                text=True
            )
            
            if result.returncode == 0:
                logger.info(f"🏆 Green Diamond Forged: {self.process_path.name}/{safe_name}_Green_Final.fit")
                return True
            else:
                logger.error(f"❌ Siril CLI Error:\n{result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Pipeline Engine Failure: {e}")
            return False

if __name__ == "__main__":
    processor = ScienceProcessor()
    # Test against the mock data we generated
    processor.process_green_stack("CH_Cyg")
