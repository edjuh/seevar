# 🌑 POSTFLIGHT

> **Version:** 1.0.0
> **Path:** `logic/POSTFLIGHT.MD`

The telescope has parked. The night's work is done. What remains is
turning raw photons into science that AAVSO can use.

Postflight runs entirely on the Pi, without the telescope. The S30-Pro
can be powered down. Everything in this phase works on the FITS files
that landed in `data/local_buffer/` during flight.

**Entry condition:** FLIGHT complete — target list exhausted or dawn
**Exit condition:** Accountant finished, ledger stamped → PARKED

---

## What was captured

Each raw FITS file in `data/local_buffer/` is a single uint16 Bayer
GRBG frame from the IMX585 sensor. It contains:

- Raw pixel values — no demosaicing, no stacking, no processing
- A complete AAVSO-compliant header written by `sovereign_stamp()`
- Target name, AUID, observer code REDA, GPS-accurate DATE-OBS
- Airmass, moon phase, moon altitude calculated at time of exposure

This is the science frame. Everything downstream derives from it.

---

## Phase 1 — Dark frames

Before science processing, the sensor's thermal noise is characterised.
The S30-Pro has an internal dark field filter — no lens cap needed.
The firmware handles the mechanical switching.

For each unique combination of exposure time and gain used tonight,
`dark_library.py` requests a dark frame from the telescope firmware
using `start_create_dark`. The firmware is polled via `get_event_state`
until the DarkLibrary reports complete or fail.

Dark acquisition is skipped in simulation mode.

```
Command:  start_create_dark
Poll:     get_event_state → DarkLibrary.state == "complete" | "fail"
Output:   data/local_buffer/*_Dark.fits
          data/local_buffer/index.json
```

---

## Phase 2 — Aperture photometry

This is not traditional debayering. SeeVar uses direct Bayer-matrix
channel extraction — the same approach being developed by the AAVSO
Smart Telescope Working Group (STWG) for OSC CMOS sensors.

The core principle: stars are measured directly on the raw Bayer pixels
without interpolation. Apertures are placed once on the full-resolution
array and the same pixel coordinates are applied to every channel.
This guarantees identical partial-pixel fractions across R/G/B/L —
the noise source that debayering introduces is eliminated entirely.

### PSF fitting and dynamic aperture

`psf_models.py` fits a 2D Moffat profile to the target star on the G
channel. The Moffat model correctly captures the power-law wings of
real stellar profiles under atmospheric seeing — it outperforms the
Gaussian model for ground-based photometry.

The fitted FWHM determines the aperture radius: r_ap = 1.7 × FWHM.
This aperture is then used for every star in the field — target and
comparison stars alike. Consistent aperture placement is what makes
the differential measurement valid.

```
Model:    2D Moffat  (fallback: 2D Gaussian)
Aperture: 1.7 × FWHM_pixels  (clipped to 4–20px)
Channels: G, R, B, L all extracted at identical aperture positions
```

### Four-channel extraction

`bayer_photometry.py` extracts flux from all four Bayer channels at
every star position using the same aperture radius:

| Channel | Bayer pixels used | Purpose |
|---------|------------------|---------|
| G | Even/Even + Odd/Odd positions | Primary science channel (TG) |
| R | Even row, Odd col | Red — future multi-band |
| B | Odd row, Even col | Blue — future multi-band |
| L | All pixels | Luminance — highest SNR |

Currently AAVSO submission uses the G channel (reported as filter TG).
R and B extraction is implemented and available for future multi-band
reporting when the AAVSO starlist format is finalised by the STWG.

### Gaia DR3 comparison stars

`gaia_resolver.py` provides comparison stars from Gaia DR3 via VizieR.
Results are cached to `data/gaia_cache/` on RAID1 — first call queries
VizieR online, every subsequent call is fully offline.

The cache key snaps RA/Dec to a 0.1° grid so nearby pointings share
a cache entry. Gaia G magnitudes are converted to approximate Johnson V
using the Jordi (2010) polynomial transformation.

Comparison stars are filtered to a magnitude window around the target
(±3 mag) and the IMX585 linear range (G 9.5–14.5).

```
Catalog:  Gaia DR3 via VizieR
Cache:    data/gaia_cache/*.json  (offline after first query)
Grid:     0.1° — nearby fields share cache
Bright:   G > 9.5  (IMX585 saturation limit)
Faint:    G < 14.5
```

### SNR²-weighted zero-point ensemble

Each comparison star contributes a zero-point estimate:
ZP = v_mag + 2.5 × log10(flux). The ensemble zero-point is the
SNR²-weighted mean of all valid comp stars — high-SNR stars contribute
more weight, suppressing outliers and reducing scatter.

The photometric error is the quadrature sum of the weighted zero-point
scatter and the SNR noise term: err = sqrt(zp_std² + (1.0857/SNR)²)

Minimum 3 comp stars required. Minimum target SNR 5.0 required.

---

## Phase 3 — Accountant

`accountant.py` is the quality gate and ledger authority. It sweeps
`data/local_buffer/`, runs the full calibration pipeline on each frame,
and stamps the result into `data/ledger.json` after every frame —
a power loss mid-run loses nothing already processed.

For each frame it records:

| Field | Content |
|-------|---------|
| `status` | OBSERVED / FAILED_QC / FAILED_QC_LOW_SNR / FAILED_SATURATED / FAILED_NO_WCS / ERROR |
| `last_mag` | Differential magnitude |
| `last_err` | Photometric error |
| `last_snr` | Target SNR |
| `last_filter` | TG (G channel on CV filter) |
| `last_comps` | Comparison stars used |
| `last_zp` | Ensemble zero point |
| `last_zp_std` | Zero point scatter — photometric quality indicator |
| `last_peak_adu` | Peak pixel ADU — saturation check |
| `last_obs_utc` | DATE-OBS from FITS header |

Processed frames are moved to `data/archive/` after stamping.

```
Input:    data/local_buffer/*.fits
Output:   data/ledger.json  (stamped, incremental — survives power loss)
          data/archive/*.fits
QC gate:  SNR >= 5.0, no saturation, WCS present
```

---

## Phase 4 — AAVSO report (pending first light)

`aavso_reporter.py` generates a submission in AAVSO WebObs extended
format. Observer code: REDA.

The AAVSO STWG is developing a JSON starlist format for direct robotic
telescope submission — smaller files, same measurement content, designed
specifically for OSC CMOS smart scopes. SeeVar's four-channel extraction
with identical aperture positions is already aligned with this format.
When the STWG publishes, integration will be straightforward.

```
Input:    data/ledger.json  (OBSERVED entries since dusk)
Output:   data/reports/REDA_{date}.txt
Format:   AAVSO WebObs extended
Status:   pending first light validation
```

---

## Data files written this phase

| File | Written by | Purpose |
|------|-----------|---------|
| `data/local_buffer/*_Dark.fits` | `dark_library.py` | Dark calibration frames |
| `data/local_buffer/index.json` | `dark_library.py` | Dark frame index |
| `data/gaia_cache/*.json` | `gaia_resolver.py` | Gaia comp star cache (RAID1) |
| `data/ledger.json` | `accountant.py` | Photometry results, incremental |
| `data/archive/*.fits` | `accountant.py` | Processed frame custody |
| `data/reports/REDA_{date}.txt` | `aavso_reporter.py` | AAVSO submission |

---

## First light actions

- Confirm Moffat PSF convergence on real IMX585 frames — synthetic
  simulation frames use random noise; real stellar profiles will
  exercise the PSF fitter for the first time.
- Validate Gaia comp star cache for first target fields — first call
  queries VizieR, subsequent calls are offline.
- Validate TG magnitude against known AAVSO standards before
  submitting as REDA.
- Consider R and B channel submission once AAVSO STWG starlist
  format is published.

<!-- SeeVar-POSTFLIGHT-v1.0.0 -->
