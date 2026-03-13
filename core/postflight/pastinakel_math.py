#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/postflight/pastinakel_math.py
Version: 1.1.1
Objective: Logic for saturation detection and dynamic aperture scaling.
"""

def check_saturation(pixel_data, ceiling=60000):
    """
    Returns True if any pixel exceeds the safety ceiling.
    Standard 16-bit FITS usually caps at 65535.
    We set 60000 to stay in the linear range of the sensor.
    """
    max_val = pixel_data.max()
    is_saturated = max_val >= ceiling
    return is_saturated, max_val

def calculate_dynamic_aperture(fwhm):
    """
    Standard Photometric Rule: Aperture radius should be ~1.5 to 2.0 x FWHM.
    This ensures we capture the 'wings' of the star profile.
    """
    multiplier = 1.7
    return round(fwhm * multiplier, 2)

if __name__ == "__main__":
    import numpy as np
    mock_star = np.array([100, 500, 62000, 500, 100])
    saturated, val = check_saturation(mock_star)
    print(f"🔬 Saturation Test: {'⚠️ FAILED' if saturated else '✅ OK'} (Peak: {val})")
