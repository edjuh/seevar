#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: utils/astro.py
Version: 1.2.0 (Pee Pastinakel)
Objective: Core library for RA/Dec parsing, sidereal time, and coordinate math.
"""

def ra_to_decimal(ra_str):
    if isinstance(ra_str, (int, float)): return float(ra_str)
    parts = ra_str.replace(" ", ":").split(":")
    h, m, s = float(parts), float(parts), float(parts)
    return round((h + (m / 60.0) + (s / 3600.0)) * 15.0, 5)

def dec_to_decimal(dec_str):
    if isinstance(dec_str, (int, float)): return float(dec_str)
    parts = dec_str.replace(" ", ":").split(":")
    d, m, s = float(parts), float(parts), float(parts)
    sign = -1 if d < 0 or str(parts).startswith('-') else 1
    return round((abs(d) + (m / 60.0) + (s / 3600.0)) * sign, 5)

def decimal_to_ra_hms(decimal_ra):
    ra_hours = float(decimal_ra) / 15.0
    h = int(ra_hours)
    m = int((ra_hours - h) * 60)
    s = ((ra_hours - h) * 60 - m) * 60
    return f"{h}h{m}m{s:.1f}s"

def decimal_to_dec_dms(decimal_dec):
    sign = "+" if decimal_dec >= 0 else "-"
    abs_dec = abs(float(decimal_dec))
    d = int(abs_dec)
    m = int((abs_dec - d) * 60)
    s = ((abs_dec - d) * 60 - m) * 60
    return f"{sign}{d}d{m}m{s:.1f}s"
