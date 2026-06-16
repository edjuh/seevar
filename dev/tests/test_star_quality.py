#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tests/test_star_quality.py
Version: 1.0.0
Objective: Verify lightweight star-shape QC accepts round fields and rejects trailed fields.
"""

import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.flight.star_quality import measure_star_shape


# Function: _synthetic_field
def _synthetic_field(*, trailed: bool) -> np.ndarray:
    rng = np.random.default_rng(42)
    image = rng.normal(1000.0, 6.0, size=(512, 512)).astype(np.float32)
    yy, xx = np.indices(image.shape, dtype=np.float32)
    for y, x in [(80, 80), (110, 210), (150, 350), (220, 120), (260, 260), (300, 410), (380, 170), (430, 340)]:
        sigma_x = 1.5 if not trailed else 1.2
        sigma_y = 1.5 if not trailed else 13.0
        image += 2500.0 * np.exp(-0.5 * (((xx - x) / sigma_x) ** 2 + ((yy - y) / sigma_y) ** 2))
    return image


# Function: test_round_star_field_passes_shape_qc
def test_round_star_field_passes_shape_qc():
    metrics = measure_star_shape(_synthetic_field(trailed=False), max_sources=20)
    assert metrics.acceptance_error(max_elongation=6.0, max_major_axis_px=18.0, min_sources=6) is None


# Function: test_trailed_star_field_fails_shape_qc
def test_trailed_star_field_fails_shape_qc():
    metrics = measure_star_shape(_synthetic_field(trailed=True), max_sources=20)
    assert metrics.acceptance_error(max_elongation=6.0, max_major_axis_px=18.0, min_sources=6) is not None
