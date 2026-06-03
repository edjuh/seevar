#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/star_quality.py
Objective: Lightweight star-shape quality checks for rejecting trailed science frames.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class StarShapeMetrics:
    sources: int = 0
    median_elongation: float | None = None
    median_major_axis_px: float | None = None
    p90_major_axis_px: float | None = None
    error: str = ""

    # Function: StarShapeMetrics.acceptance_error
    def acceptance_error(self, *, max_elongation: float, max_major_axis_px: float, min_sources: int) -> str | None:
        if self.error:
            return self.error
        if self.sources < min_sources:
            return f"star_shape_sources_low:{self.sources}<{min_sources}"
        if self.median_elongation is not None and self.median_elongation > max_elongation:
            return f"star_elongation_high:{self.median_elongation:.2f}>{max_elongation:.2f}"
        if (
            self.p90_major_axis_px is not None
            and self.p90_major_axis_px > max_major_axis_px
            and self.median_elongation is not None
            and self.median_elongation > 2.0
        ):
            return f"star_trail_px_high:{self.p90_major_axis_px:.1f}>{max_major_axis_px:.1f}"
        return None

    # Function: StarShapeMetrics.write_header
    def write_header(self, header) -> None:
        header["STARSRC"] = (int(self.sources), "Star-shape QC sources")
        if self.median_elongation is not None:
            header["STARELON"] = (round(float(self.median_elongation), 3), "Median star elongation")
        if self.median_major_axis_px is not None:
            header["STARMED"] = (round(float(self.median_major_axis_px), 3), "Median major-axis length px")
        if self.p90_major_axis_px is not None:
            header["STARLEN"] = (round(float(self.p90_major_axis_px), 3), "P90 major-axis length px")
        if self.error:
            header["STARQERR"] = (self.error[:68], "Star-shape QC error")


# Function: _background_stats
def _background_stats(arr: np.ndarray) -> tuple[float, float]:
    vals = arr[np.isfinite(arr)]
    if vals.size == 0:
        return 0.0, 1.0
    med = float(np.median(vals))
    mad = float(np.median(np.abs(vals - med)))
    sigma = 1.4826 * mad if mad > 0 else float(np.std(vals))
    return med, max(sigma, 1e-6)


# Function: measure_star_shape
def measure_star_shape(
    data: np.ndarray,
    *,
    max_sources: int = 60,
    half_size: int = 32,
    min_separation_px: int = 24,
) -> StarShapeMetrics:
    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim > 2:
        arr = np.squeeze(arr)
    if arr.ndim != 2:
        return StarShapeMetrics(error="star_shape_not_2d")

    finite = np.isfinite(arr)
    vals = arr[finite]
    if vals.size < 1000:
        return StarShapeMetrics(error="star_shape_no_finite_data")

    med, sigma = _background_stats(arr)
    threshold = max(med + 8.0 * sigma, float(np.percentile(vals, 99.92)))
    yx = np.argwhere(finite & (arr > threshold))
    if yx.size == 0:
        return StarShapeMetrics(sources=0)

    values = arr[yx[:, 0], yx[:, 1]]
    top_n = min(values.size, max(500, max_sources * 80))
    top_idx = np.argpartition(values, -top_n)[-top_n:]
    top_idx = top_idx[np.argsort(values[top_idx])[::-1]]

    height, width = arr.shape
    used: list[tuple[int, int]] = []
    elongations: list[float] = []
    major_axes: list[float] = []
    yy, xx = np.indices((half_size * 2 + 1, half_size * 2 + 1), dtype=np.float32)

    for idx in top_idx:
        y, x = int(yx[idx, 0]), int(yx[idx, 1])
        if y < half_size or x < half_size or y >= height - half_size or x >= width - half_size:
            continue
        if any((y - uy) ** 2 + (x - ux) ** 2 < min_separation_px ** 2 for uy, ux in used):
            continue

        cutout = arr[y - half_size : y + half_size + 1, x - half_size : x + half_size + 1]
        weights = np.clip(np.where(np.isfinite(cutout), cutout, med) - (med + 3.0 * sigma), 0.0, None)
        if int(np.count_nonzero(weights)) < 6:
            continue
        flux = float(weights.sum())
        if flux <= 0:
            continue

        cx = float((xx * weights).sum() / flux)
        cy = float((yy * weights).sum() / flux)
        dx = xx - cx
        dy = yy - cy
        var_x = float((dx * dx * weights).sum() / flux)
        var_y = float((dy * dy * weights).sum() / flux)
        cov = float((dx * dy * weights).sum() / flux)
        disc = max((var_x - var_y) ** 2 + 4.0 * cov * cov, 0.0)
        major_var = max(0.5 * (var_x + var_y + float(np.sqrt(disc))), 1e-6)
        minor_var = max(0.5 * (var_x + var_y - float(np.sqrt(disc))), 1e-6)
        elongation = float(np.sqrt(major_var / minor_var))
        major_axis = float(4.0 * np.sqrt(major_var))
        if not np.isfinite(elongation) or not np.isfinite(major_axis):
            continue
        if major_axis < 1.0 or major_axis > float(half_size * 2):
            continue

        used.append((y, x))
        elongations.append(elongation)
        major_axes.append(major_axis)
        if len(elongations) >= max_sources:
            break

    if not elongations:
        return StarShapeMetrics(sources=0)

    return StarShapeMetrics(
        sources=len(elongations),
        median_elongation=float(np.median(elongations)),
        median_major_axis_px=float(np.median(major_axes)),
        p90_major_axis_px=float(np.percentile(major_axes, 90.0)),
    )
