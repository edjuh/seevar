#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/postflight/aavso_reporter.py
Version: 1.1.0
Objective: Generate AAVSO Extended Format reports in the dedicated data/reports/ directory.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))

from core.flight.vault_manager import VaultManager

class AAVSOReporter:
    def __init__(self):
        self.vault = VaultManager()
        self.report_dir = PROJECT_ROOT / "data" / "reports"
        self.report_dir.mkdir(parents=True, exist_ok=True)
        
        # Pulling from config.toml via VaultManager
        conf = self.vault.get_observer_config()
        self.obs_code = conf.get("observer_code", "REDA")

    def finalize_report(self, observations):
        """
        Saves the AAVSO report to the reports/ landing zone.
        observations: List of dicts [target, jd, mag, err, filter, comp]
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"AAVSO_{self.obs_code}_{timestamp}.txt"
        save_path = self.report_dir / filename

        lines = [
            "#TYPE=EXTENDED",
            f"#OBSCODE={self.obs_code}",
            "#SOFTWARE=SeeVar_Federation_v1.1",
            "#DELIM=,",
            "#DATE=JD",
            "#OBSTYPE=CCD",
            "#STARDATA"
        ]

        for obs in observations:
            # Standard AAVSO CSV-style format
            line = f"{obs['target']},{obs['jd']:.5f},{obs['mag']:.3f},{obs['err']:.3f},{obs['filter']},NO,STD,{obs['comp']}"
            lines.append(line)

        with open(save_path, "w") as f:
            f.write("\n".join(lines))
        
        return save_path

if __name__ == "__main__":
    rep = AAVSOReporter()
    print(f"✅ AAVSO Reporter initialized. Landing zone: {rep.report_dir}")
