#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/postflight/analyst.py
Version: 1.0.0
Objective: Analyzes FITS image quality, FWHM, and basic observational metrics.
"""

import subprocess
import tomllib
from pathlib import Path
from core.logger import log_event

class Analyst:
    def __init__(self):
        self.solver_path = "/usr/bin/solve-field"
        self.project_root = Path(__file__).parent.parent.resolve()
        self.load_config()

    def load_config(self):
        config_file = self.project_root / "config.toml"
        try:
            with open(config_file, "rb") as f:
                data = tomllib.load(f)
                solver_cfg = data.get("solver", {})
                raw_config_path = solver_cfg.get("config_path", "/etc/astrometry.cfg")
                self.config_path = Path(raw_config_path).expanduser()
                self.scale_low = solver_cfg.get("scale_low", 3.5)
                self.scale_high = solver_cfg.get("scale_high", 4.0)
                self.search_radius = solver_cfg.get("search_radius", 5.0)
                self.downsample = solver_cfg.get("downsample", 2)
                self.timeout = solver_cfg.get("timeout", 45)
        except Exception as e:
            log_event(f"Analyst: Failed to read config.toml, using defaults. Error: {e}", level="error")
            self.config_path = Path("/etc/astrometry.cfg")
            self.scale_low, self.scale_high = 3.5, 4.0
            self.search_radius, self.downsample, self.timeout = 5.0, 2, 45

    def solve_image(self, fits_path, hint_ra=None, hint_dec=None):
        fits_path = Path(fits_path)
        if not fits_path.exists():
            log_event(f"Analyst: FITS file missing - {fits_path}", level="error")
            return None
        
        wcs_file = fits_path.with_suffix('.wcs')
        
        cmd = [
            self.solver_path,
            str(fits_path),
            "--config", str(self.config_path),
            "--scale-low", str(self.scale_low),
            "--scale-high", str(self.scale_high),
            "--downsample", str(self.downsample),
            "--overwrite",
            "--no-plots",
            "--cpulimit", str(self.timeout)
        ]
        
        if hint_ra is not None and hint_dec is not None:
            cmd.extend(["--ra", str(hint_ra), "--dec", str(hint_dec), "--radius", str(self.search_radius)])
            
        log_event(f"Analyst: Running solve-field on {fits_path.name}...")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if wcs_file.exists():
                log_event(f"Analyst: Plate solve successful -> {wcs_file.name}")
                return wcs_file
            else:
                log_event("Analyst: Plate solve failed.", level="error")
                return None
        except Exception as e:
            log_event(f"Analyst: Critical subprocess error: {e}", level="error")
            return None

analyst = Analyst()
