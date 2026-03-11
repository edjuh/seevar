#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/flight/pilot.py
Version: 3.0.1
Objective: Executive control of the S30-PRO, handling direct RPC pulses. (IP safely locked to 127.0.0.1)
"""

import io
import time
import json
import requests
import logging
from pathlib import Path
from astropy.io import fits

PROJECT_ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.append(str(PROJECT_ROOT))

from core.flight.vault_manager import VaultManager
from core.flight.fsm import SovereignFSM

logger = logging.getLogger("Pilot")

class Pilot:
    def __init__(self, sim_mode=False):
        self.sim_mode = sim_mode
        self.fsm = SovereignFSM()
        self.vault = VaultManager()
        self.observer_code = self.vault.get_observer_config().get("observer_id", "UNKNOWN")
        
        # FIXED: Enforce local bridge routing per alpaca_bridge.md
        self.alp_url = "http://127.0.0.1:5555/api/v1/telescope/1/action"
        
        mode = "SIMULATION" if self.sim_mode else "HARDWARE"
        logger.info(f"🔭 Pilot initialized in {mode} mode on Local Bridge (127.0.0.1).")

    def pulse(self, method, params=None):
        payload = {
            "Action": "method_sync",
            "Parameters": json.dumps({"method": method, **(params or {})}),
            "ClientID": "1",
            "ClientTransactionID": str(int(time.time() * 1000))
        }
        try:
            res = requests.put(self.alp_url, json=payload, timeout=10)
            return res.json().get("Value", {}).get("result", {})
        except Exception as e:
            logger.error(f"RPC Pulse Error ({method}): {e}")
            return None

    def capture_and_stamp(self, target_name, ra, dec, exp_ms):
        safe_name = target_name.replace(" ", "_").upper()
        output_dir = PROJECT_ROOT / "data" / "local_buffer"
        output_dir.mkdir(parents=True, exist_ok=True)
        final_path = output_dir / f"{safe_name}_Raw.fits"

        if self.sim_mode:
            logger.info(f"🧪 [SIM] Stamping Mock FITS for {safe_name}...")
            with open(final_path, 'wb') as f: f.write(b"MOCK_FITS_DATA")
            return final_path

        logger.info(f"📸 Triggering {exp_ms}ms RAW exposure for {target_name}...")
        self.pulse("start_exposure", {"type": "light", "stack": False, "exp_ms": exp_ms, "count": 1})

        while True:
            status = self.pulse("get_exp_status")
            if status in ["Idle", "Complete", "idle"]: break
            time.sleep(1.0)
            
        time.sleep(2) 
        
        logger.info(f"📥 Harvesting binary stream via get_stacked_img...")
        pull_payload = {
            "Action": "method_sync",
            "Parameters": json.dumps({"method": "get_stacked_img"}),
            "ClientID": "1"
        }
        
        try:
            res = requests.put(self.alp_url, json=pull_payload, timeout=20)
            if res.status_code == 200:
                mem_file = io.BytesIO(res.content)
                logger.info(f"🧬 Applying Sovereign Stamp to {safe_name} FITS Header...")
                with fits.open(mem_file, mode='update') as hdul:
                    header = hdul[0].header
                    header['OBJECT'] = (target_name, "Sovereign Target Override")
                    header['OBJCTRA'] = (ra, "Commanded RA (DecDeg)")
                    header['OBJCTDEC'] = (dec, "Commanded DEC (DecDeg)")
                    header['OBSERVER'] = (self.observer_code, "AAVSO Observer Code")
                    hdul.flush()

                with open(final_path, 'wb') as f:
                    f.write(mem_file.getvalue())
                logger.info(f"💾 {final_path.name} written to secure disk -> Added AAVSO Tags.")
                return final_path
            else:
                logger.error(f"❌ Failed to download FITS payload. HTTP {res.status_code}")
                return None
        except Exception as e:
            logger.error(f"❌ FITS Interception failed: {e}")
            return None
