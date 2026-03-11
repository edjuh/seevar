#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/postflight/calibration_engine.py
Version: 1.0.1
Objective: Manages Zero-Point (ZP) offsets and flat-field corrections for the IMX585.
"""

import json
import math
from pathlib import Path
from core.postflight.master_analyst import MasterAnalyst
from core.postflight.photometry_engine import phot_engine

class CalibrationEngine:
    def __init__(self):
        self.project_root = Path(__file__).parent.parent.resolve()
        self.master_analyst = MasterAnalyst()

    def load_sequence(self, target_name):
        safe_name = target_name.lower().replace(" ", "_")
        json_path = self.project_root / "data" / "sequences" / f"{safe_name}.json"
        if not json_path.exists(): return None
        try:
            with open(json_path, 'r') as f:
                return json.load(f)
        except: return None

    def calculate_magnitude(self, fits_path, target_ra, target_dec, target_name):
        tx, ty = self.master_analyst.solve_and_locate(fits_path)
        if not tx or not ty: return None
            
        target_data = phot_engine.extract_flux(fits_path, tx, ty)
        if not target_data or target_data['inst_flux'] <= 0: return None
            
        target_inst_flux = target_data['inst_flux']
        comp_stars = self.load_sequence(target_name)
        if not comp_stars: return None
            
        zero_points = []
        for comp in comp_stars:
            v_mag = next((b['mag'] for b in comp.get('bands', []) if b['band'] == 'V'), None)
            if v_mag is None: continue
                
            cx, cy = self.master_analyst.solve_and_locate(fits_path)
            if not cx or not cy: continue
                
            comp_data = phot_engine.extract_flux(fits_path, cx, cy)
            if comp_data and comp_data['inst_flux'] > 0:
                zp = v_mag + 2.5 * math.log10(comp_data['inst_flux'])
                zero_points.append(zp)
                
        if not zero_points: return None
        avg_zp = sum(zero_points) / len(zero_points)
        return avg_zp - 2.5 * math.log10(target_inst_flux)

calibration_engine = CalibrationEngine()
