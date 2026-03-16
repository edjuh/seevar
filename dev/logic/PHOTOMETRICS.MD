# PHOTOMETRICS.MD
# SeeVar Differential Photometry — Decisions, Rationale & Roadmap
# Location: logic/PHOTOMETRICS.MD
# Last updated: 2026-03-13

---

## Current Implementation (v2.0.0)

### Channel Selection
- Science channel: **G** (Bayer GRBG pattern, IMX585)
- AAVSO filter tag: **TG** (transformed green)
- Rationale: G pixels are 2× denser than R or B in the Bayer matrix,
  giving better SNR and sampling. No debayering — direct channel extraction.

### Aperture Photometry
- Engine: `bayer_photometry.aperture_flux()`
- Aperture: **dynamic** — 1.7 × Moffat PSF FWHM (from `psf_models.fit_psf()`)
- Fallback: fixed 8px radius if PSF fit fails or does not converge
- Sky annulus: r_in = max(r_sky_in, r_ap + 4), r_out = max(r_sky_out, r_ap + 10)
  Annulus expands with aperture to stay clean
- Saturation ceiling: **60000 ADU** (IMX585 16-bit linear limit)
- Centroid: peak-pixel in 10px search box on luminance (all channels)
- Comp stars measured at **same aperture radius as target** for consistency

### PSF Model
- Production model: **Moffat** profile (`psf_models.fit_moffat()`)
- Fallback: Gaussian (13% FWHM overestimate vs Moffat — acceptable for aperture sizing)
- Moffat recovers FWHM to within 0.006px on synthetic stars
- Pixel scale: 3.75"/px (IMX585 on S30-Pro, from CDELT header)

### Zero-Point Ensemble
- Method: **SNR²-weighted mean** of all valid comp star ZPs
- Weight: `w_i = SNR_i²` — high-SNR comps dominate, low-SNR suppressed
- Minimum comp SNR: 5.0 (hard gate before inclusion)
- Comp stars: Gaia DR3 via `gaia_resolver.py`, cached per field
- Expected zp_std on real flat-fielded frames: **0.05–0.15 mag**
- Synthetic test (126 targets × 2 runs): reproducibility excellent,
  zp_std ~1.17 with simple mean (dominated by synthetic noise floor)

### Error Budget
- Total error: `sqrt(zp_std² + snr_err²)`
- SNR noise term: `1.0857 / target_snr` (Pogson factor)
- Typical error on real frames mag 10–14: **~0.02–0.05 mag** (estimated)

### Quality Gates
- `MIN_SNR = 5.0` — target must exceed this in G channel
- `SATURATION_CEILING = 60000 ADU` — target and comps
- Out-of-frame rejection: target centroid must be > r_sky_out from edge
- Status vocabulary: `OBSERVED | FAILED_QC | FAILED_QC_LOW_SNR |`
  `FAILED_SATURATED | FAILED_NO_WCS | ERROR`

---

## Known Limitations

### Synthetic test anomalies (to investigate)
- **T Peg**: 4.5 mag jump between runs — likely synthetic generator bug,
  not a pipeline issue. Investigate `synthetic_fits_generator.py`.
- **eps Aur**: err ~13 — ZP ensemble unstable, crowded/extended field.
- **V0404 Cyg / V404 Cyg**: same object, two catalog entries — dedup needed.

### No colour transformation
- TG filter is not standard V. Colour term correction (Tv_tg) not yet applied.
- AAVSO accepts TG observations without transformation for LPV/Mira program.
- Future: add `(B-V)` colour term from Gaia BP-RP when needed for precision work.

### No airmass correction
- Differential photometry partially self-corrects if comps are close in az/alt.
- `nightly_planner.py` enforces minimum altitude (horizon mask) which limits
  worst-case extinction. No explicit X·k correction applied yet.

---

## Roadmap — Photometry Improvements

### Next: Sigma clipping on ZP ensemble
**Priority: HIGH**
Add iterative sigma clipping before weighted mean:
1. Compute weighted mean ZP
2. Reject comps > 2.5σ from mean
3. Recompute with survivors
4. Repeat until stable (typically 2–3 iterations)

Removes genuine outliers: misidentified stars, galaxies, unresolved doubles.
Even high SNR won't save a misidentified comp — sigma clipping catches them.
File: `core/postflight/bayer_photometry.py` → `differential_magnitude()`

### After that: Ensemble photometry (Honeycutt 1992)
**Priority: MEDIUM — requires multi-night data**
Solve simultaneously for all star magnitudes and nightly extinction coefficient.
Standard approach in professional differential photometry pipelines.
What AAVSO's own VPHOT does internally.

Algorithm:
- Build matrix of all pairwise magnitude differences across all frames
- Solve least-squares system for best-fit magnitudes + nightly ZP + extinction
- Iterate until convergence

Requires: multiple frames per field per night (currently 1 frame per target).
Becomes worthwhile when S30-Pro is doing repeat visits on campaign targets.
Reference: Honeycutt R.K. 1992, PASP 104, 435.

### Colour transformation
**Priority: LOW — AAVSO TG program does not require it**
Apply standard AAVSO transformation equation:
  `V = TG + Tv_tg × (B-V)`
where `Tv_tg` is the nightly transformation coefficient.
Requires: observations of standard fields (Landolt) on photometric nights.
Bortle 8 Haarlem — photometric nights are rare, low priority.

### PSF photometry (replace aperture)
**Priority: LOW — aperture is adequate for uncrowded LPV fields**
Fit PSF simultaneously to target + all comps in the field.
Better than aperture for crowded fields or poor seeing.
Overkill for Mira/SR program in uncrowded fields.
Consider if crowded-field targets are added to campaign.

---

## Data Flow Summary

```
FITS (GRBG uint16, IMX585)
  → BayerFITS.load()
  → BayerFITS.measure_star()
      → _fit_aperture()  [Moffat PSF → dynamic r_ap]
      → aperture_flux()  [G channel, sky-subtracted]
  → differential_magnitude()
      → measure_star() per comp [same r_ap]
      → SNR²-weighted ZP ensemble
      → mag ± err
  → calibration_engine.calibrate()
      → gaia_resolver (Gaia DR3 comps, cached)
      → returns {mag, err, snr, zp, zp_std, n_comps, filter, peak_adu}
  → accountant.py
      → ledger.json schema v2026.2
  → aavso_reporter.py  [AAVSO Extended Format]
```

---

## Hardware Constants (IMX585 on S30-Pro)
| Parameter | Value | Source |
|-----------|-------|--------|
| Bayer pattern | GRBG | confirmed pilot.py |
| Pixel scale | 3.75"/px | CDELT header |
| Saturation | 60000 ADU | pastinakel_math.py |
| Read noise | 1.6 e⁻ | IMX585 datasheet |
| Dark current | 0.005 e⁻/px/s | IMX585 datasheet |
| Bit depth | 16-bit unsigned (>u2) | BITPIX header |
| Frame size | 3840×2160 | NAXIS1/2 |
| Science filter | TG (green Bayer) | AAVSO convention |
