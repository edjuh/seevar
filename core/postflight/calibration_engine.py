#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/postflight/calibration_engine.py
Version: 2.0.0
Objective: Orchestrates differential photometry for a single FITS frame.
           Resolves comparison stars from Gaia DR3 (cached), measures all
           stars on raw Bayer pixels, and returns a calibrated magnitude
           ready for aavso_reporter.py.
           No Siril. No debayer. No external photometry packages.
"""

import logging
from pathlib import Path
from typing import Optional

from core.postflight.bayer_photometry import BayerFITS, differential_magnitude
from core.postflight.gaia_resolver import get_comp_stars

logger = logging.getLogger("seevar.calibration_engine")

# Bayer channel used for AAVSO submission.
# G channel = TG (transformed green) — closest AAVSO standard for Seestar CV filter.
SCIENCE_CHANNEL = "G"

# Minimum comp stars before we trust the result
MIN_COMPS = 3

# Minimum target SNR before we trust the measurement
MIN_SNR = 5.0


class CalibrationEngine:
    """
    End-to-end calibration for one FITS frame → one magnitude measurement.

    Usage:
        engine = CalibrationEngine()
        result = engine.calibrate(fits_path, target_ra, target_dec, target_name)
        # result["mag"], result["err"], result["filter"] ready for AAVSOReporter
    """

    def calibrate(
        self,
        fits_path:   Path,
        target_ra:   float,
        target_dec:  float,
        target_name: str = "",
        channel:     str = SCIENCE_CHANNEL,
        force_gaia_refresh: bool = False,
    ) -> dict:
        """
        Full pipeline for one frame:
          1. Load raw Bayer FITS
          2. Fetch Gaia comp stars (cache-first)
          3. Run differential photometry
          4. Validate result quality

        Returns dict with keys:
            mag, err, filter, n_comps, zero_point, target_snr,
            fits_path, target_name, channel
        On failure, returns {"error": "<reason>"}
        """
        fits_path = Path(fits_path)

        # 1 — Load FITS
        frame = BayerFITS(fits_path)
        if not frame.load():
            return {"error": f"failed_to_load_fits: {fits_path.name}"}

        logger.info("Calibrating %s  target=%s  channel=%s",
                    fits_path.name, target_name or "unnamed", channel)

        # 2 — Gaia comp stars for this field
        comp_stars = get_comp_stars(target_ra, target_dec, force_refresh=force_gaia_refresh)
        if len(comp_stars) < MIN_COMPS:
            return {"error": f"insufficient_comp_stars: got {len(comp_stars)}, need {MIN_COMPS}"}

        # 3 — Differential photometry
        result = differential_magnitude(
            fits_file  = frame,
            target_ra  = target_ra,
            target_dec = target_dec,
            comp_stars = comp_stars,
            channel    = channel,
        )

        if "error" in result:
            logger.warning("Photometry failed for %s: %s", target_name, result["error"])
            return result

        # 4 — Quality gates
        snr = result.get("target_snr", 0)
        if snr < MIN_SNR:
            logger.warning("Target SNR %.1f below minimum %.1f — rejecting.", snr, MIN_SNR)
            return {"error": f"snr_too_low: {snr:.1f}"}

        n_comps = result.get("n_comps", 0)
        if n_comps < MIN_COMPS:
            logger.warning("Only %d comp stars passed QC — rejecting.", n_comps)
            return {"error": f"insufficient_valid_comps: {n_comps}"}

        # Annotate with context for aavso_reporter
        result["fits_path"]    = str(fits_path)
        result["target_name"]  = target_name
        # AAVSO filter code: G channel on CV filter = TG
        result["filter"]       = "TG" if channel == "G" else channel
        # Use the brightest valid comp as the check star label (first in list by Gmag)
        if comp_stars:
            brightest = min(comp_stars, key=lambda s: s.get("gmag", 99))
            result["comp_label"] = brightest.get("source_id", "GAIA")

        logger.info(
            "✅ %s  mag=%.3f ± %.3f  SNR=%.1f  comps=%d  ZP=%.4f",
            target_name, result["mag"], result["err"],
            snr, n_comps, result["zero_point"]
        )

        return result


# Module-level singleton — import and call directly
calibration_engine = CalibrationEngine()


if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)-28s  %(levelname)-8s  %(message)s"
    )

    if len(sys.argv) < 4:
        print("Usage: calibration_engine.py <fits_path> <ra_deg> <dec_deg> [target_name]")
        sys.exit(1)

    fits_arg   = Path(sys.argv[1])
    ra_arg     = float(sys.argv[2])
    dec_arg    = float(sys.argv[3])
    name_arg   = sys.argv[4] if len(sys.argv) > 4 else fits_arg.stem

    out = calibration_engine.calibrate(fits_arg, ra_arg, dec_arg, name_arg)

    if "error" in out:
        print(f"\n❌ Calibration failed: {out['error']}")
        sys.exit(1)

    print(f"\n✅ {out['target_name']}")
    print(f"   Magnitude : {out['mag']:.3f} ± {out['err']:.3f}  [{out['filter']}]")
    print(f"   SNR       : {out['target_snr']:.1f}")
    print(f"   Comp stars: {out['n_comps']}")
    print(f"   Zero-point: {out['zero_point']:.4f}  (σ={out['zp_std']:.4f})")
