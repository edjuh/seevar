# 🌑 POSTFLIGHT

> **Version:** 1.9.0
> **Objective:** Define the sovereign postflight science chain from raw FITS custody to ledger verdict and AAVSO-ready output.
> **Path:** `dev/logic/POSTFLIGHT.MD`

The telescope has parked. Flight is over.
Postflight is where raw frames are turned into defensible science.

This phase must protect three truths:

- detector truth
- astrometric truth
- photometric truth

Flight only proves that a frame was captured.
Postflight decides whether the frame is scientifically usable.

**Entry condition:** FLIGHT complete, raw FITS present in `data/local_buffer/`
**Exit condition:** Ledger stamped, archive updated, report products staged

---

## The Sovereign Postflight Sequence (P1-P8)

Each science frame must pass one deterministic postflight chain.
A frame may fail without invalidating the rest of the night.

### P1 — Ingest

Take custody of the raw science FITS.

Validate:
- file exists
- FITS is readable
- required header fields are present
- target identity can be recovered
- observation timestamp can be recovered

This is the file-integrity gate.

**Inputs:**
- `data/local_buffer/*.fits`

**Outputs:**
- frame accepted for processing
- or immediate failure status if corrupt/unreadable

---

### P2 — Calibration Match

Locate the best available detector calibration assets for the frame.

Current priority:
- dark frames matched by exposure time, gain, and temperature bin

Future priority:
- flats matched by filter/channel and optical state

Missing calibration assets must be recorded explicitly.
Silently skipping calibration is not acceptable long-term.

**Inputs:**
- science FITS header
- dark library index
- future flat library index

**Outputs:**
- matched calibration set
- or explicit "calibration missing" condition

---

### P3 — Calibration Apply

Apply detector calibration to the raw frame.

Order:
1. dark subtraction
2. flat correction when implemented

Rules:
- raw FITS remains untouched
- calibrated products are derived artifacts
- calibrated products must be traceable to the raw source frame

This is where detector truth begins.

**Outputs:**
- calibrated working frame for analysis
- provenance metadata linking raw + calibration assets

---

### P4 — Astrometric Solve

Produce a real solved WCS for the frame.

This must be an actual astrometric solution.
Header guesses such as `CRVAL`, `CRPIX`, and `CDELT` are not by themselves sufficient scientific truth.

Solve products should include:
- solved WCS
- center RA/Dec
- solve success/failure
- residual/confidence if available

Without a real solve, comparison-star placement is not trustworthy.

**Outputs:**
- solved frame
- or `FAILED_NO_WCS`

---

### P5 — Source Measurement

Measure the target and candidate comparison stars on the calibrated frame using the solved WCS.

This includes:
- target localization
- centroid refinement
- PSF / FWHM estimation
- dynamic aperture selection
- Bayer-aware per-channel flux extraction

No debayering is required.
SeeVar uses direct Bayer-aware photometry on the raw sensor mosaic.

**Outputs:**
- target fluxes and SNR
- comp-star fluxes and SNR
- aperture geometry
- peak ADU / saturation flags

---

### P6 — Ensemble Calibration

Convert source measurements into a differential magnitude.

This step owns:
- comparison-star selection
- magnitude-window filtering
- SNR filtering
- zero-point solution
- sigma clipping of bad comparison stars
- photometric error estimate

Current science channel:
- `G` Bayer channel
- reported as `TG`

This is the core photometric science step.

**Outputs:**
- magnitude
- magnitude error
- target SNR
- comparison count
- zero point
- zero-point scatter

---

### P7 — Quality Verdict

Apply scientific acceptance gates and assign the final frame verdict.

Minimum gates:
- readable FITS
- calibration state known
- real solved WCS present
- target not saturated
- target flux positive
- target SNR above threshold
- sufficient valid comparison stars
- zero-point scatter within acceptable tolerance

Possible verdicts include:
- `OBSERVED`
- `FAILED_QC`
- `FAILED_QC_LOW_SNR`
- `FAILED_SATURATED`
- `FAILED_NO_WCS`
- `ERROR`

This is the authoritative scientific pass/fail step.

---

### P8 — Commit And Report

Write durable outputs and publication products.

This includes:
- update `data/ledger.json`
- move or copy final custody products into archive
- write QC/report artifacts
- stage AAVSO output products

Only at this step is a frame considered postflight-complete.

**Outputs:**
- stamped ledger
- archived frame custody
- report-ready science products

---

## Current Scientific Law

### What postflight must prove

Postflight must prove all three:

- the detector data is trustworthy
- the sky position is trustworthy
- the photometry is trustworthy

If any one of those is unproven, the frame is not science-grade.

### What is not enough anymore

The following are not enough on their own:
- unsolved header coordinates
- raw CRVAL-based pixel estimates
- uncalibrated detector data
- weighted comp-star ensembles without outlier rejection

---

## Current implementation status

### Implemented or partial
- FITS ingestion and basic header parsing
- Bayer-aware channel extraction
- PSF-driven dynamic aperture selection
- Gaia comparison star lookup and cache
- weighted zero-point ensemble
- ledger stamping and archive movement
- AAVSO report formatter

### Under scientific upgrade
- real solved WCS as a hard postflight dependency
- dark matching and dark subtraction
- flat-field support
- sigma clipping on comparison stars
- fully wired AAVSO report generation from accepted ledger entries

---

## Roadmap 1.9.x — Postflight Hardening

### 1.9.0 — Doctrine freeze
- Freeze the canonical `P1-P8` sequence
- Align docs and code ownership to that sequence

### 1.9.1 — Astrometric truth
- Require real solved WCS in postflight
- Replace header-only coordinate assumptions for source placement

### 1.9.2 — Detector truth
- Match and apply dark frames before photometry
- Preserve raw FITS and produce calibrated working products

### 1.9.3 — Ensemble robustness
- Add sigma clipping to comparison-star zero-point estimation
- Record rejected comps and final survivor count

### 1.9.4 — Publication path
- Wire accepted ledger entries into AAVSO report generation
- Stage report output as a deterministic postflight product

Future:
- flat-field support
- color transformation when scientifically justified
- optional multi-band reporting once the AAVSO/STWG path is ready

---

## Data products

| File | Role |
|------|------|
| `data/local_buffer/*.fits` | raw science custody from flight |
| `data/dark_library/` | dark library and index |
| `data/gaia_cache/*.json` | Gaia comparison-star cache |
| `data/ledger.json` | authoritative observation ledger |
| `data/archive/*.fits` | archived processed custody |
| `data/reports/*.txt` | AAVSO-ready report outputs |

---

## Scientific boundary

Flight ends at:
- trustworthy raw frame captured and committed

Postflight ends at:
- trustworthy calibrated, solved, measured, and judged science result committed

That boundary must remain clean.

<!-- SeeVar-POSTFLIGHT-v1.9.0 -->
