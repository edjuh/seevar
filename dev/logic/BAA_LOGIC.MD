# 🇬🇧 BAA LOGIC

> **Objective:** Rules for SeeVar export to BAA VSSDB formats, including the
> BAA-modified AAVSO Extended variant and the richer CCD/CMOS layout.
> **Version:** 1.0.0
> **Path:** `logic/BAA_LOGIC.MD`

Primary AAVSO science logic remains in `AAVSO_LOGIC.MD`.

---

## 📦 Supported BAA Output Paths

SeeVar currently supports two BAA-facing export shapes:

1. **BAA-supported modified AAVSO Extended**
2. **BAA CCD/CMOS tabular format**

Implemented in:
- `core/postflight/aavso_reporter.py`

Test driver:
- `dev/tools/aavso_reporter_test.py`

---

## 🔭 Observation Method

For Seestar output, the observation method is:

- `CMOS`

It is not `DSLR`.

---

## 🎨 Filter Semantics

For SeeVar Bayer-green photometry, the exported filter is:

- `TG`

This is preferred over `CV` for the current Seestar pipeline, because the
measurement is derived from the green channel rather than from an unfiltered
full-chip clear measurement.

---

## 🧪 Saturation Policy

SeeVar explicitly checks for saturation during photometry.

Current saturation ceiling:

- `60000 ADU`

Behavior:
- saturated **targets** are rejected from export
- saturated **comparison stars** are excluded from the ensemble
- accepted BAA exports carry an explicit saturation note

Examples of export notes:
- `SATCHECK=PASS SATLIM=60000 PEAKADU=42112.0`
- `SATCHECK=FAIL SATLIM=60000 PEAKADU=61234.0`

---

## 📝 BAA-Modified AAVSO Extended

This variant emits:

- `#TYPE=AAVSO EXT BAA V1.00`
- `#LOCATION=...`
- `#TELESCOPE=...`
- `#CAMERA=...`
- tab-delimited rows

Per-row `NOTES` now include the saturation statement when available.

---

## 📊 BAA CCD/CMOS Layout

This richer format is intended for one variable per file and preserves:

- calculated magnitude and error
- instrumental target magnitude and error
- repeated comparison-star columns
- comparison reference mag / error
- comparison instrumental mag / error

The file-level `Comment` field carries the saturation summary for exported rows.

---

## ⚙️ Current Seestar Defaults

- Observation method: `CMOS`
- Filter: `TG`
- Camera: `Integrated CMOS`
- Telescope string: `name / model / mount` when available

---

## 🚧 Remaining Work

- wire BAA export directly from accepted real-night postflight results
- decide whether saturation should also become a dedicated BAA column if the
  BAA side prefers that over notes/comment metadata
- validate final parser acceptance with BAA VSS maintainers
