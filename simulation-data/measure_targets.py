#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: simulation-data/measure_targets.py
Version: 2.0.0
Objective: Batch photometric reduction of all synthetic FITS frames using the
           real bayer_photometry + gaia_resolver pipeline.
           Produces simulation_measurements.csv with calibrated magnitudes,
           SNRs, comp star counts, and zero-point statistics.
           This is a true dry run of the postflight calibration pipeline.
"""

import sys
import csv
import logging
from pathlib import Path

# Allow imports from both simulation-data/ and the seevar package
SIM_DIR     = Path(__file__).resolve().parent
SEEVAR_ROOT = SIM_DIR.parent
sys.path.insert(0, str(SIM_DIR))
sys.path.insert(0, str(SEEVAR_ROOT))

from bayer_photometry import BayerFITS, differential_magnitude
from gaia_resolver import get_comp_stars

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-24s  %(levelname)-8s  %(message)s"
)
logger = logging.getLogger("measure_targets")

BUFFER_DIR      = SIM_DIR / "data" / "local_buffer"
OUTPUT_CSV      = SIM_DIR / "simulation_measurements.csv"
SCIENCE_CHANNEL = "G"

CSV_FIELDS = [
    "target", "fits_file",
    "mag", "err", "filter",
    "n_comps", "zero_point", "zp_std",
    "target_snr", "peak_adu",
    "status", "error"
]


def measure_one(fits_path: Path) -> dict:
    """
    Full pipeline for one synthetic FITS frame.
    Returns a result dict ready for CSV writing.
    """
    frame = BayerFITS(fits_path)
    if not frame.load():
        return {"fits_file": fits_path.name, "status": "FAIL", "error": "fits_load_failed"}

    h      = frame.header
    target = str(h.get("OBJECT", fits_path.stem))
    ra     = float(h.get("CRVAL1", 0))
    dec    = float(h.get("CRVAL2", 0))

    if ra == 0 and dec == 0:
        return {"target": target, "fits_file": fits_path.name,
                "status": "FAIL", "error": "missing_wcs"}

    # Gaia comp stars — cache-first, one VizieR query per field ever
    comps = get_comp_stars(ra, dec)
    if len(comps) < 3:
        return {"target": target, "fits_file": fits_path.name,
                "status": "FAIL", "error": f"insufficient_comps_{len(comps)}"}

    # Differential photometry on G channel
    result = differential_magnitude(frame, ra, dec, comps, channel=SCIENCE_CHANNEL)

    if "error" in result:
        return {"target": target, "fits_file": fits_path.name,
                "status": "FAIL", "error": result["error"]}

    # Grab peak ADU from a direct measure_star call
    star = frame.measure_star(ra, dec)
    peak = star.get("peak", 0)

    return {
        "target":     target,
        "fits_file":  fits_path.name,
        "mag":        result["mag"],
        "err":        result["err"],
        "filter":     "TG",
        "n_comps":    result["n_comps"],
        "zero_point": result["zero_point"],
        "zp_std":     result["zp_std"],
        "target_snr": result["target_snr"],
        "peak_adu":   round(peak, 0),
        "status":     "OK",
        "error":      "",
    }


def run_batch():
    fits_files = sorted(BUFFER_DIR.glob("*.fit")) + sorted(BUFFER_DIR.glob("*.fits"))

    if not fits_files:
        logger.error("No FITS files found in %s", BUFFER_DIR)
        sys.exit(1)

    logger.info("Starting batch reduction -- %d frames in %s", len(fits_files), BUFFER_DIR)

    results    = []
    ok_count   = 0
    fail_count = 0

    for i, fpath in enumerate(fits_files, 1):
        logger.info("[%d/%d] %s", i, len(fits_files), fpath.name)
        row = measure_one(fpath)
        results.append(row)
        if row.get("status") == "OK":
            ok_count += 1
            logger.info("  OK  mag=%.3f +/- %.3f  SNR=%.1f  comps=%d",
                        row["mag"], row["err"], row["target_snr"], row["n_comps"])
        else:
            fail_count += 1
            logger.warning("  FAIL  %s", row.get("error", "unknown"))

    # Write CSV
    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    logger.info("-" * 60)
    logger.info("Batch complete.  OK: %d  FAIL: %d  -> %s", ok_count, fail_count, OUTPUT_CSV)

    # Summary table to stdout
    print(f"\n{'Target':<25} {'Mag':>7} {'Err':>6} {'SNR':>6} {'Comps':>6}  Status")
    print("-" * 65)
    for r in results:
        if r.get("status") == "OK":
            print(f"{r['target']:<25} {r['mag']:>7.3f} {r['err']:>6.3f} "
                  f"{r['target_snr']:>6.1f} {r['n_comps']:>6}  OK")
        else:
            print(f"{r.get('target', '?'):<25} {'--':>7} {'--':>6} {'--':>6} {'--':>6}  FAIL: {r['error']}")


if __name__ == "__main__":
    run_batch()
