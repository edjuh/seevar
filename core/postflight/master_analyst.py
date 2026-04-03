#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/postflight/master_analyst.py
Version: 2.1.0
Objective: High-level plate-solving coordinator executing astrometry.net's solve-field and returning real WCS products for postflight science use.
"""

import logging
import subprocess
import warnings
from pathlib import Path

import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.utils.exceptions import AstropyWarning
from astropy.wcs import WCS

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [ANALYST] - %(message)s")
logger = logging.getLogger("MasterAnalyst")

warnings.filterwarnings("ignore", category=AstropyWarning, append=True)


class MasterAnalyst:
    def __init__(self):
        self.solve_available = False
        try:
            subprocess.run(["solve-field", "--version"], capture_output=True, check=True)
            self.solve_available = True
        except Exception:
            logger.error("solve-field is not installed or not in PATH.")

    def _extract_hints(self, header) -> tuple[str, float | None, float | None]:
        target_name = str(header.get("OBJECT", "Unknown")).strip() or "Unknown"

        ra_deg = dec_deg = None

        ra_val = header.get("RA")
        dec_val = header.get("DEC")
        if ra_val is not None and dec_val is not None:
            try:
                ra_deg = float(ra_val)
                dec_deg = float(dec_val)
                return target_name, ra_deg, dec_deg
            except Exception:
                pass

        ra_str = header.get("OBJCTRA")
        dec_str = header.get("OBJCTDEC")
        if ra_str and dec_str:
            try:
                coord = SkyCoord(f"{ra_str} {dec_str}", unit=(u.hourangle, u.deg))
                ra_deg = float(coord.ra.deg)
                dec_deg = float(coord.dec.deg)
                return target_name, ra_deg, dec_deg
            except Exception:
                pass

        if header.get("CRVAL1") is not None and header.get("CRVAL2") is not None:
            try:
                ra_deg = float(header["CRVAL1"])
                dec_deg = float(header["CRVAL2"])
            except Exception:
                pass

        return target_name, ra_deg, dec_deg

    def solve_frame(self, fits_path_str) -> dict:
        fits_file = Path(fits_path_str)
        wcs_file = fits_file.with_suffix(".wcs")

        if not fits_file.exists():
            return {"ok": False, "error": f"file_not_found: {fits_file}"}

        try:
            with fits.open(fits_file) as hdul:
                hdr = hdul[0].header
                target_name, ra_deg, dec_deg = self._extract_hints(hdr)
        except Exception as e:
            return {"ok": False, "error": f"header_read_failed: {e}"}

        if ra_deg is None or dec_deg is None:
            return {"ok": False, "error": "no_header_coordinates"}

        if not wcs_file.exists():
            if not self.solve_available:
                return {"ok": False, "error": "solve_field_unavailable"}

            logger.info("Initiating plate solve for %s (%s)", fits_file.name, target_name)

            cmd = [
                "solve-field",
                str(fits_file),
                "--dir", str(fits_file.parent),
                "--ra", str(ra_deg),
                "--dec", str(dec_deg),
                "--radius", "2",
                "--downsample", "2",
                "--no-plots",
                "--overwrite",
                "--tweak-order", "1",
                "--cpulimit", "45",
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            if not wcs_file.exists():
                stderr_tail = (result.stderr or "").strip()[-300:]
                logger.error("Plate solve failed for %s", fits_file.name)
                return {
                    "ok": False,
                    "error": "plate_solve_failed",
                    "stderr": stderr_tail,
                    "returncode": result.returncode,
                }

            logger.info("Plate solve successful for %s", fits_file.name)
        else:
            logger.info("WCS already exists for %s, skipping solve", fits_file.name)

        try:
            w = WCS(str(wcs_file))
            px, py = w.all_world2pix(ra_deg, dec_deg, 0)
            solved_hdr = fits.getheader(wcs_file, 0)

            return {
                "ok": True,
                "target_name": target_name,
                "fits_path": str(fits_file),
                "wcs_path": str(wcs_file),
                "target_ra_deg": ra_deg,
                "target_dec_deg": dec_deg,
                "target_px": float(px),
                "target_py": float(py),
                "solved_ra_deg": float(solved_hdr.get("CRVAL1", ra_deg)),
                "solved_dec_deg": float(solved_hdr.get("CRVAL2", dec_deg)),
            }
        except Exception as e:
            return {"ok": False, "error": f"wcs_read_failed: {e}"}

    def solve_and_locate(self, fits_path_str):
        result = self.solve_frame(fits_path_str)
        if not result.get("ok"):
            logger.error("solve_and_locate failed: %s", result.get("error", "unknown"))
            return None, None
        logger.info(
            "Target %s located at pixel X=%.2f Y=%.2f",
            result["target_name"],
            result["target_px"],
            result["target_py"],
        )
        return result["target_px"], result["target_py"]


if __name__ == "__main__":
    import sys

    analyst = MasterAnalyst()
    if len(sys.argv) != 2:
        print("Usage: master_analyst.py <fits_path>")
        raise SystemExit(1)

    out = analyst.solve_frame(sys.argv[1])
    if not out.get("ok"):
        print(f"FAIL: {out.get('error')}")
        raise SystemExit(1)

    print(f"OK: {out['target_name']}")
    print(f"    WCS: {out['wcs_path']}")
    print(f"    PX : {out['target_px']:.2f}")
    print(f"    PY : {out['target_py']:.2f}")
