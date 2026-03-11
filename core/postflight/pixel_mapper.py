#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/postflight/pixel_mapper.py
Version: 1.0.1
Objective: Converts celestial WCS coordinates to local sensor pixel X/Y coordinates.
"""

import warnings
from astropy.wcs import WCS
from astropy.utils.exceptions import AstropyWarning

def get_pixel_coords(wcs_file, ra, dec):
    """
    Translates RA/Dec to Pixel X/Y with noise suppression.
    """
    warnings.filterwarnings('ignore', category=AstropyWarning, append=True)
    
    try:
        w = WCS(wcs_file)
        # origin=0 for 0-indexed pixels (numpy style)
        px, py = w.all_world2pix(ra, dec, 0)
        return float(px), float(py)
    except Exception:
        return None, None
