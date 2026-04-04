# PHOTOMETRICS.MD
# SeeVar Differential Photometry — Decisions, Standards & Roadmap
# Location: dev/logic/PHOTOMETRICS.MD
# Version: 1.9.0
# Last updated: 2026-04-02

---

## Purpose

This document defines the scientific rules for SeeVar photometry.

It exists to protect one outcome:
a trustworthy differential magnitude that can be defended scientifically.

Photometry is not just aperture math.
It depends on three upstream truths:

- detector truth
- astrometric truth
- photometric truth

These correspond directly to the postflight chain:
- `P3` detector calibration
- `P4` astrometric solve
- `P5-P6` photometric measurement and ensemble calibration

If one of those is weak, the final magnitude is weak.

---

### Current science status

SeeVar currently produces:

- raw Bayer-mosaic photometry
- green-channel science measurements
- untransformed `TG` output
- dark-calibrated working frames before science photometry
- sigma-clipped comparison-star ensembles

This is the active and accepted science path.

### Detector calibration status

Dark calibration is now enforced in postflight.

Current detector-calibration rule:
- raw science FITS are preserved unchanged
- a calibrated working derivative is created for science measurement
- dark matching is performed by exposure, gain, and temperature bin

Flat correction remains future work.

### Ensemble status

Comparison stars are no longer accepted by weighted averaging alone.

Current ensemble rule:
- measure candidate comparison stars on the same Bayer-aware aperture basis
- compute provisional zero points
- reject zero-point outliers by sigma clipping
- recompute the final ensemble zero point from survivors

This is the active `1.9.3` behavior.

### Reporting honesty

SeeVar does **not** currently claim true Johnson `V`.

Current reporting stance:
- reported code: `TG`
- measurement type: raw Bayer green, untransformed
- comparison reference magnitudes may come from `V`, but the reported science product remains `TG`

Transformed `V` is future work and requires explicit instrument calibration.


### Why not naive debayering

Debayering interpolates pixel values and alters the native noise model.
For scientific photometry, that is undesirable unless there is a strong reason.

SeeVar therefore measures directly on the Bayer mosaic where possible.

### Current science channel

- Science channel: `G`
- Bayer pattern: `GRBG`
- AAVSO reporting code: `TG`

Reason:
- the green channel has the densest sampling on the IMX585 Bayer matrix
- it gives the strongest balance of resolution and SNR
- it is the best current proxy for TG-style reporting

---

## Core Measurement Law

### 1. Source placement must come from solved astrometry

Header estimates alone are not enough.

`CRVAL`, `CRPIX`, and `CDELT` may be useful hints, but they are not a substitute for a real solved WCS.
Comparison-star placement must ultimately be based on astrometric truth.

This means:

- header-only world-to-pixel mapping is provisional
- postflight science-grade photometry must use a real solved WCS
- unsolved frames cannot be accepted as `OBSERVED`

### 2. Detector calibration must happen before science photometry

Photometry on untreated raw frames is acceptable only as engineering or diagnostic output.

Science-grade postflight requires:
- dark matching
- dark subtraction
- flat correction when flats exist

Raw custody must remain untouched.
Calibration products must be explicit derived artifacts.

### 3. Differential photometry is an ensemble problem

A single comparison star is not strong enough by default.

The working model is:
- multiple valid comparison stars
- weighted ensemble zero point
- outlier rejection
- final magnitude from the ensemble, not from a single comp

### 4. A high-SNR wrong star is still wrong

High SNR is not enough.

If comparison-star identification is wrong, or if a comp is variable, blended, saturated, or poorly placed, weighting alone will not save the result.

This is why sigma clipping and comparison vetting are mandatory next steps.

---

## Current Implementation Standard

### Channel handling

- Bayer pattern: `GRBG`
- Channels measured:
  - `G`
  - `R`
  - `B`
  - `ALL` / luminance
- Current reporting channel:
  - `G` -> `TG`

### Aperture model

- Primary PSF model: Moffat
- Fallback PSF model: Gaussian
- Aperture radius rule:
  - `r_ap = 1.7 × FWHM`
- Hard clipping:
  - minimum aperture: `4 px`
  - maximum aperture: `20 px`

### Sky annulus

The sky annulus must expand with aperture size so it remains outside the stellar core:

- `r_sky_in = max(default_in, r_ap + 4)`
- `r_sky_out = max(default_out, r_ap + 10)`

### Saturation guard

- Saturation ceiling: `60000 ADU`

Any saturated target frame must not be accepted for science output.

### Minimum acceptance gates

Current hard gates:

- target flux must be positive
- target SNR must be at least `5.0`
- minimum valid comparison stars: `3`
- frame must not be saturated
- frame must have a real solved WCS
- detector calibration state must be known

These are minimums, not ideals.

---

## Current Weak Points

These are the places where the implementation is still behind the doctrine.

### 1. Header-based source placement is still too trusting

If photometry uses only header center and scale assumptions, then comp-star placement can be wrong even when the math looks clean.

This is currently under scientific upgrade.

### 2. Dark and flat calibration are not yet fully enforced

The postflight chain must not quietly skip detector calibration forever.
Dark calibration is the next required correction.
Flat correction comes after that.

### 3. No sigma clipping yet on the comparison ensemble

Weighted means alone are not enough.
Bad comps must be rejected explicitly.

This is the next live photometry improvement.

### 4. AAVSO report generation is formatter-ready, not fully science-integrated

The formatter exists, but the full chain from accepted postflight result to deterministic report staging is not yet complete.

---

## Accepted Error Model

Current total magnitude uncertainty should be modeled as:

`total_err = sqrt(zp_std^2 + snr_err^2)`

Where:

- `zp_std` = ensemble zero-point scatter
- `snr_err = 1.0857 / target_snr`

This is acceptable as the current working model.

Later additions may include:
- solve-quality contribution
- calibration-frame uncertainty contribution
- transformation uncertainty if color terms are introduced

---

## Comparison Star Policy

### Source

Comparison stars currently come from Gaia DR3.

### Current conversion

Gaia `G` magnitudes are converted to approximate Johnson `V` using a color-based approximation.

This is acceptable as a practical current step, but it is still an approximation.

### Selection rules

Comparison stars should be filtered by:

- valid coordinates
- valid magnitude
- non-saturation range
- sensible magnitude window around the target
- minimum SNR
- successful on-frame placement
- no saturation in the measured frame

### Future comparison-star hardening

The ensemble should later support:

- sigma clipping
- explicit rejection logging
- optional crowding rejection
- optional edge-distance rejection
- optional known-variable rejection if catalogs permit

---

## Roadmap 1.9.x

### 1.9.0 — Doctrine freeze
- freeze Bayer-aware photometry as the official direction
- align `POSTFLIGHT.MD` and `PHOTOMETRICS.MD`
- define the `P1-P8` postflight chain

### 1.9.1 — Real solved WCS
- require solved astrometry before final source measurement
- stop treating header geometry as scientific truth

### 1.9.2 — Dark-calibrated working frames
- match darks by exposure, gain, and temperature bin
- subtract dark before photometry
- preserve raw custody separately

### 1.9.3 — Sigma-clipped ensemble
- compute initial weighted zero point
- reject comparison stars outside tolerance
- recompute with survivors
- record survivor count and rejected comps

### 1.9.4 — Deterministic reporting
- accept only `P7`-passed frames into report staging
- wire accepted results into AAVSO output products

### Later
- flat-field support
- color transformation only if scientifically justified
- optional multi-band output when standards and workflow are ready

---

## Sigma Clipping Standard

This is the next required photometric upgrade.

Recommended first implementation:

1. measure all candidate comparison stars
2. build zero-point list from valid comps
3. compute weighted mean and scatter
4. reject comps beyond `2.5 sigma`
5. recompute
6. repeat until stable or max iterations reached
7. fail if survivors drop below minimum comp count

Suggested defaults:
- clip threshold: `2.5 sigma`
- max iterations: `3`

This should happen inside the ensemble calibration step, not later in reporting.

---

## Scientific Verdict Standard

A frame may be marked `OBSERVED` only if all of the following are true:

- detector calibration state is known
- astrometric solve is real and accepted
- target placement is valid
- target is not saturated
- target flux is positive
- target SNR meets threshold
- enough valid comps survive QC
- zero-point solution is stable enough for acceptance

If not, the frame must fail honestly.

Possible statuses include:

- `OBSERVED`
- `FAILED_QC`
- `FAILED_QC_LOW_SNR`
- `FAILED_SATURATED`
- `FAILED_NO_WCS`
- `ERROR`

---

## Architectural Boundary

Flight proves:
- a trustworthy raw frame was captured

Postflight proves:
- that frame can support trustworthy science

Photometry belongs to postflight, not flight.
Astrometric truth and detector truth must be established before a magnitude is believed.

---

## Summary

The direction is correct:

- Bayer-aware photometry is the right path
- green-channel TG reporting is the right current output
- dynamic apertures and ensemble calibration are the right basis

The next work is not changing philosophy.
It is finishing the scientific custody chain around that philosophy:

- solved WCS
- dark calibration
- sigma clipping
- report wiring

That is the `1.9.x` hardening chapter.

<!-- SeeVar-PHOTOMETRICS-v1.9.0 -->
