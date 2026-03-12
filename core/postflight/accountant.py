#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/postflight/accountant.py
Version: 1.1.0
Objective: Sweeps local_buffer, performs resilient QC photometry with historical header fallbacks, and stamps Ledger.
"""

import json
import logging
import shutil
from pathlib import Path
from datetime import datetime, timezone

from astropy.coordinates import SkyCoord
import astropy.units as u

import sys
PROJECT_ROOT = Path("/home/ed/seevar")
sys.path.insert(0, str(PROJECT_ROOT))

# Import the centralized science extraction engine
from core.flight.pilot import PhotometryPipeline

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger("Accountant")

DATA_DIR = PROJECT_ROOT / "data"
LOCAL_BUFFER = DATA_DIR / "local_buffer"
ARCHIVE_DIR = DATA_DIR / "archive"
LEDGER_FILE = DATA_DIR / "ledger.json"

def load_ledger() -> dict:
    if LEDGER_FILE.exists():
        try:
            with open(LEDGER_FILE, 'r') as f:
                data = json.load(f)
                return data.get("entries", {}) if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            logger.warning("Ledger unreadable. Starting fresh.")
    return {}

def save_ledger(entries: dict):
    output = {
        "#objective": "Master Observational Register and Status Ledger",
        "metadata": {
            "last_updated": datetime.now().isoformat(),
            "schema_version": "2026.1"
        },
        "entries": entries
    }
    with open(LEDGER_FILE, 'w') as f:
        json.dump(output, f, indent=4)

def process_buffer():
    logger.info("🧾 Accountant: Auditing local buffer for completed observations...")

    if not LOCAL_BUFFER.exists():
        logger.info("Local buffer empty or missing. Nothing to do.")
        return

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    ledger = load_ledger()
    
    fits_files = list(LOCAL_BUFFER.glob("*.fits"))
    if not fits_files:
        logger.info("No FITS files found in buffer.")
        return

    processed = 0
    successes = 0

    for fpath in fits_files:
        logger.info(f"Processing: {fpath.name}")
        pipe = PhotometryPipeline(fpath)
        
        if not pipe.load():
            logger.error(f"  ❌ Corrupt or invalid FITS: {fpath.name}")
            continue

        h = pipe.header
        
        # 1. Resilient Target Name Parsing
        target_name = h.get("OBJECT")
        if not target_name or str(target_name).strip() == "":
            target_name = fpath.stem.split("_")[0]
            
        safe_name = str(target_name).replace(" ", "_").upper()

        # 2. Resilient Date-Obs Parsing
        date_obs = h.get("DATE-OBS")
        if not date_obs:
            date_obs = datetime.fromtimestamp(fpath.stat().st_mtime, tz=timezone.utc).isoformat()

        # 3. Resilient Coordinate Parsing (Try Sovereign strings, fallback to standard CRVAL floats)
        ra_str = h.get("OBJCTRA")
        dec_str = h.get("OBJCTDEC")
        ra_deg, dec_deg = None, None

        if ra_str and dec_str:
            try:
                coord = SkyCoord(f"{ra_str} {dec_str}", unit=(u.hourangle, u.deg))
                ra_deg = coord.ra.deg
                dec_deg = coord.dec.deg
            except Exception:
                pass
                
        if ra_deg is None or dec_deg is None:
            if "CRVAL1" in h and "CRVAL2" in h:
                ra_deg = float(h["CRVAL1"])
                dec_deg = float(h["CRVAL2"])

        # Ledger Management
        if safe_name not in ledger:
            ledger[safe_name] = {
                "status": "PENDING",
                "last_success": None,
                "attempts": 0,
                "priority": "NORMAL"
            }

        ledger[safe_name]["attempts"] += 1

        if ra_deg is None or dec_deg is None:
            logger.error("  ❌ Missing all WCS spatial data. Marking attempt, skipping photometry.")
            ledger[safe_name]["status"] = "FAILED_QC"
        else:
            try:
                # Extract QC Photometry
                measure = pipe.measure(ra_deg, dec_deg)
                
                if "error" in measure:
                    logger.warning(f"  ⚠️ Target not found in frame or extraction error: {measure['error']}")
                    ledger[safe_name]["status"] = "FAILED_QC"
                else:
                    snr = measure["snr"]
                    if snr > 3.0:
                        logger.info(f"  ✅ SUCCESS: SNR={snr:.1f}. Stamping ledger.")
                        # Ensure UTC Z suffix for strict ISO8601 parsing by the Auditor
                        ledger[safe_name]["last_success"] = str(date_obs) + "Z" if not str(date_obs).endswith("Z") else str(date_obs)
                        ledger[safe_name]["status"] = "OBSERVED"
                        successes += 1
                    else:
                        logger.warning(f"  ⚠️ POOR SIGNAL: SNR={snr:.1f}. Minimum is 3.0.")
                        ledger[safe_name]["status"] = "FAILED_QC_LOW_SNR"
                        
            except Exception as e:
                logger.error(f"  ❌ Photometry crash: {e}")
                ledger[safe_name]["status"] = "ERROR"

        # Archive the file
        try:
            shutil.move(str(fpath), str(ARCHIVE_DIR / fpath.name))
        except Exception as e:
            logger.error(f"  ❌ Failed to archive {fpath.name}: {e}")

        processed += 1

    save_ledger(ledger)
    logger.info(f"🧾 Audit Complete. Processed {processed} frames. Ledger updated with {successes} successful observations.")

if __name__ == "__main__":
    process_buffer()
