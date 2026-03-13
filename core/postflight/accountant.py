#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/postflight/accountant.py
Version: 2.0.0
Objective: Sweeps local_buffer, runs full Bayer differential photometry via
           calibration_engine, and stamps complete results into the ledger.

Ledger schema v2 per target:
    status          : PENDING | OBSERVED | FAILED_QC | FAILED_QC_LOW_SNR |
                      FAILED_SATURATED | FAILED_NO_WCS | ERROR
    last_success    : ISO8601 UTC timestamp of last successful observation
    attempts        : total attempts including failures
    priority        : NORMAL | HIGH | URGENT (set externally by planner)
    last_mag        : differential magnitude (float)
    last_err        : magnitude error (float)
    last_snr        : target SNR (float)
    last_filter     : photometric filter string e.g. "TG"
    last_comps      : number of comparison stars used (int)
    last_zp         : ensemble zero point (float)
    last_zp_std     : zero point scatter (float)
    last_obs_utc    : DATE-OBS from FITS header (ISO8601)
    last_peak_adu   : peak pixel ADU of target
"""

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from astropy.coordinates import SkyCoord
import astropy.units as u

import sys
PROJECT_ROOT = Path("/home/ed/seevar")
sys.path.insert(0, str(PROJECT_ROOT))

from core.postflight.calibration_engine import CalibrationEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("Accountant")

DATA_DIR     = PROJECT_ROOT / "data"
LOCAL_BUFFER = DATA_DIR / "local_buffer"
ARCHIVE_DIR  = DATA_DIR / "archive"
LEDGER_FILE  = DATA_DIR / "ledger.json"

# Minimum SNR gate — below this, observation is flagged FAILED_QC_LOW_SNR
MIN_SNR = 5.0

# Singleton calibration engine
_engine = CalibrationEngine()


# ---------------------------------------------------------------------------
# Ledger I/O
# ---------------------------------------------------------------------------
def load_ledger() -> dict:
    if LEDGER_FILE.exists():
        try:
            with open(LEDGER_FILE, "r") as f:
                data = json.load(f)
                return data.get("entries", {}) if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            log.warning("Ledger unreadable — starting fresh.")
    return {}


def save_ledger(entries: dict):
    output = {
        "#objective": "Master Observational Register and Status Ledger",
        "metadata": {
            "last_updated":   datetime.now(timezone.utc).isoformat(),
            "schema_version": "2026.2",
        },
        "entries": entries,
    }
    LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_FILE, "w") as f:
        json.dump(output, f, indent=4)


def _blank_entry() -> dict:
    return {
        "status":       "PENDING",
        "last_success": None,
        "attempts":     0,
        "priority":     "NORMAL",
        "last_mag":     None,
        "last_err":     None,
        "last_snr":     None,
        "last_filter":  None,
        "last_comps":   None,
        "last_zp":      None,
        "last_zp_std":  None,
        "last_obs_utc": None,
        "last_peak_adu": None,
    }


# ---------------------------------------------------------------------------
# FITS header parsing — kept resilient from v1.1.0
# ---------------------------------------------------------------------------
def _parse_header(fpath: Path, header: dict) -> tuple:
    """
    Extract (target_name, date_obs, ra_deg, dec_deg) from FITS header.
    Falls back gracefully at each step.
    Returns (name: str, date_obs: str, ra_deg: float|None, dec_deg: float|None)
    """
    # Target name
    target_name = header.get("OBJECT", "")
    if not str(target_name).strip():
        target_name = fpath.stem.split("_")[0]
    target_name = str(target_name).strip()

    # Date-Obs
    date_obs = header.get("DATE-OBS")
    if not date_obs:
        date_obs = datetime.fromtimestamp(
            fpath.stat().st_mtime, tz=timezone.utc
        ).isoformat()

    # Coordinates — try OBJCTRA/OBJCTDEC strings first, then CRVAL floats
    ra_deg = dec_deg = None
    ra_str  = header.get("OBJCTRA")
    dec_str = header.get("OBJCTDEC")

    if ra_str and dec_str:
        try:
            coord   = SkyCoord(f"{ra_str} {dec_str}", unit=(u.hourangle, u.deg))
            ra_deg  = float(coord.ra.deg)
            dec_deg = float(coord.dec.deg)
        except Exception:
            pass

    if ra_deg is None and "CRVAL1" in header and "CRVAL2" in header:
        try:
            ra_deg  = float(header["CRVAL1"])
            dec_deg = float(header["CRVAL2"])
        except Exception:
            pass

    return target_name, date_obs, ra_deg, dec_deg


# ---------------------------------------------------------------------------
# Main buffer processor
# ---------------------------------------------------------------------------
def process_buffer():
    log.info("Accountant: auditing local buffer...")

    if not LOCAL_BUFFER.exists():
        log.info("Local buffer empty or missing — nothing to do.")
        return

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    ledger    = load_ledger()
    fits_files = sorted(LOCAL_BUFFER.glob("*.fit")) + \
                 sorted(LOCAL_BUFFER.glob("*.fits"))

    if not fits_files:
        log.info("No FITS files in buffer.")
        return

    processed = successes = 0

    for fpath in fits_files:
        log.info("Processing: %s", fpath.name)

        # --- Parse header first to get coordinates and name ---
        from core.postflight.bayer_photometry import BayerFITS
        frame = BayerFITS(fpath)
        if not frame.load():
            log.error("  ❌ Corrupt or invalid FITS: %s", fpath.name)
            continue

        target_name, date_obs, ra_deg, dec_deg = _parse_header(fpath, frame.header)

        if ra_deg is None or dec_deg is None:
            log.error("  ❌ %s  no WCS data — skipping photometry", target_name)
            key = target_name
            if key not in ledger:
                ledger[key] = _blank_entry()
            ledger[key]["attempts"] += 1
            ledger[key]["status"] = "FAILED_NO_WCS"
            try:
                shutil.move(str(fpath), str(ARCHIVE_DIR / fpath.name))
            except Exception as e:
                log.error("  ❌ Archive failed: %s", e)
            processed += 1
            continue

        # --- Run full Bayer differential photometry ---
        result = _engine.calibrate(str(fpath), ra_deg, dec_deg, target_name)

        # Ensure UTC Z suffix
        if date_obs and not str(date_obs).endswith("Z"):
            date_obs = str(date_obs) + "Z"

        # Normalise key — ledger uses original target name as key
        key = target_name

        # Initialise ledger entry if new
        if key not in ledger:
            ledger[key] = _blank_entry()

        ledger[key]["attempts"] += 1

        # --- Interpret result ---
        status = result.get("status", "error")
        error  = result.get("error", "")

        if status == "ok":
            snr = result.get("target_snr", 0.0)

            if snr >= MIN_SNR:
                log.info("  ✅ %s  mag=%.3f ± %.3f  SNR=%.1f  comps=%d  filter=%s",
                         key,
                         result.get("mag", 0),
                         result.get("err", 0),
                         snr,
                         result.get("n_comps", 0),
                         result.get("filter", "?"))

                ledger[key].update({
                    "status":        "OBSERVED",
                    "last_success":  date_obs,
                    "last_mag":      result.get("mag"),
                    "last_err":      result.get("err"),
                    "last_snr":      round(snr, 1),
                    "last_filter":   result.get("filter"),
                    "last_comps":    result.get("n_comps"),
                    "last_zp":       result.get("zero_point"),
                    "last_zp_std":   result.get("zp_std"),
                    "last_obs_utc":  date_obs,
                    "last_peak_adu": result.get("peak_adu"),
                })
                successes += 1

            else:
                log.warning("  ⚠️  %s  poor SNR=%.1f (min %.1f)", key, snr, MIN_SNR)
                ledger[key]["status"] = "FAILED_QC_LOW_SNR"

        elif status == "fail":
            if "saturated" in error:
                log.warning("  ⚠️  %s  SATURATED (peak_adu=%s)", key, result.get("peak_adu"))
                ledger[key]["status"] = "FAILED_SATURATED"
            elif "no_wcs" in error or "wcs" in error.lower():
                log.error("  ❌ %s  no WCS data", key)
                ledger[key]["status"] = "FAILED_NO_WCS"
            elif "flux" in error:
                log.warning("  ⚠️  %s  zero/negative flux — target below detection limit", key)
                ledger[key]["status"] = "FAILED_QC"
            else:
                log.warning("  ⚠️  %s  failed: %s", key, error)
                ledger[key]["status"] = "FAILED_QC"

        else:
            log.error("  ❌ %s  calibration error: %s", key, error)
            ledger[key]["status"] = "ERROR"

        # --- Archive FITS ---
        try:
            shutil.move(str(fpath), str(ARCHIVE_DIR / fpath.name))
        except Exception as e:
            log.error("  ❌ Archive failed for %s: %s", fpath.name, e)

        processed += 1

    save_ledger(ledger)
    log.info("Audit complete. %d frames processed, %d successful observations stamped.",
             processed, successes)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    process_buffer()
