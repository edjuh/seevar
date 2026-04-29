#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/postflight/calibration_engine.py
Version: 2.2.0
Objective: Orchestrate differential photometry for a single FITS frame using a real solved WCS,
Gaia/AAVSO-style comparison stars, and raw Bayer-green TG photometry.
"""

import logging
from pathlib import Path
from typing import Optional

from core.postflight.bayer_photometry import BayerFITS, differential_magnitude
from core.postflight.gaia_resolver import get_comp_stars

logger = logging.getLogger("seevar.calibration_engine")

SCIENCE_CHANNEL = "G"
SCIENCE_FILTER_LABEL = "TG"
MIN_COMPS = 3
MIN_SNR = 5.0


class CalibrationEngine:
    """
    End-to-end calibration for one FITS frame to one TG magnitude measurement.
    """

    def calibrate(
        self,
        fits_path: Path,
        target_ra: float,
        target_dec: float,
        target_name: str = "",
        channel: str = SCIENCE_CHANNEL,
        force_gaia_refresh: bool = False,
        target_mag: float = None,
        wcs_path: Optional[Path] = None,
        solve_result: Optional[dict] = None,
    ) -> dict:
        fits_path = Path(fits_path)

        frame = BayerFITS(fits_path)
        if not frame.load(wcs_path=wcs_path):
            return {"status": "fail", "error": f"failed_to_load_fits: {fits_path.name}"}

        if not frame.has_wcs:
            return {"status": "fail", "error": "no_wcs"}

        logger.info(
            "Calibrating %s  target=%s  channel=%s (%s)",
            fits_path.name,
            target_name or "unnamed",
            channel,
            SCIENCE_FILTER_LABEL,
        )

        comp_stars = get_comp_stars(
            target_ra,
            target_dec,
            force_refresh=force_gaia_refresh,
            target_mag=target_mag,
        )
        if len(comp_stars) < MIN_COMPS:
            return {
                "status": "fail",
                "error": f"insufficient_comp_stars: got {len(comp_stars)}, need {MIN_COMPS}",
            }

        result = differential_magnitude(
            fits_file=frame,
            target_ra=target_ra,
            target_dec=target_dec,
            comp_stars=comp_stars,
            channel=channel,
        )

        if result.get("status") != "ok":
            target_measurement = result.get("target_measurement") or {}
            if target_measurement:
                logger.warning(
                    "Photometry failed for %s: %s target_flux_G=%s target_snr_G=%s peak=%s xy=(%s,%s)",
                    target_name,
                    result.get("error"),
                    target_measurement.get("flux_G"),
                    target_measurement.get("snr_G"),
                    target_measurement.get("peak"),
                    target_measurement.get("cx"),
                    target_measurement.get("cy"),
                )
            else:
                logger.warning("Photometry failed for %s: %s", target_name, result.get("error"))
            return result

        snr = result.get("target_snr", 0)
        if snr < MIN_SNR:
            logger.warning("Target SNR %.1f below minimum %.1f, rejecting.", snr, MIN_SNR)
            return {"status": "fail", "error": f"snr_too_low: {snr:.1f}"}

        n_comps = result.get("n_comps", 0)
        if n_comps < MIN_COMPS:
            logger.warning("Only %d comp stars passed QC, rejecting.", n_comps)
            return {"status": "fail", "error": f"insufficient_valid_comps: {n_comps}"}

        result["fits_path"] = str(fits_path)
        result["target_name"] = target_name
        result["filter"] = SCIENCE_FILTER_LABEL
        result["photometric_system"] = "TG"
        result["measurement_kind"] = "raw_bayer_green_untransformed"
        result["wcs_path"] = str(wcs_path) if wcs_path else str(fits_path.with_suffix(".wcs"))

        if solve_result and solve_result.get("ok"):
            result["solved_ra_deg"] = solve_result.get("solved_ra_deg")
            result["solved_dec_deg"] = solve_result.get("solved_dec_deg")

        if comp_stars:
            brightest = min(comp_stars, key=lambda s: s.get("gmag", 99))
            result["comp_label"] = brightest.get("source_id", "GAIA")

        logger.info(
            "OK %s  TG=%.3f +/- %.3f  SNR=%.1f  comps=%d  ZP=%.4f",
            target_name,
            result["mag"],
            result["err"],
            snr,
            n_comps,
            result["zero_point"],
        )

        return result


calibration_engine = CalibrationEngine()


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)-28s  %(levelname)-8s  %(message)s",
    )

    if len(sys.argv) < 5:
        print("Usage: calibration_engine.py <fits_path> <wcs_path> <ra_deg> <dec_deg> [target_name]")
        raise SystemExit(1)

    fits_arg = Path(sys.argv[1])
    wcs_arg = Path(sys.argv[2])
    ra_arg = float(sys.argv[3])
    dec_arg = float(sys.argv[4])
    name_arg = sys.argv[5] if len(sys.argv) > 5 else fits_arg.stem

    out = calibration_engine.calibrate(
        fits_arg,
        ra_arg,
        dec_arg,
        name_arg,
        wcs_path=wcs_arg,
    )

    if out.get("status") != "ok":
        print(f"\nFAIL Calibration failed: {out.get('error')}")
        raise SystemExit(1)

    print(f"\nOK {out['target_name']}")
    print(f"   TG        : {out['mag']:.3f} +/- {out['err']:.3f}")
    print(f"   System    : {out['photometric_system']}")
    print(f"   SNR       : {out['target_snr']:.1f}")
    print(f"   Comp stars: {out['n_comps']}")
    print(f"   Zero-point: {out['zero_point']:.4f}  (sigma={out['zp_std']:.4f})")
