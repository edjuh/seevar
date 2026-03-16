# 🧬 AAVSO LOGIC

> **Objective:** Rules for scientific targeting, cadence, photometry
> channel selection, and AAVSO report formatting.
> **Version:** 2.0.0 (Praw)
> **Path:** `logic/AAVSO_LOGIC.MD`

Hardware acquisition: `API_PROTOCOL.MD`.
Data file ownership: `DATA_DICTIONARY.MD`.
Cadence implementation: `core/preflight/audit.py`.

---

## 🎯 Target Selection

SeeVar monitors four variable star classes for AAVSO:

| Class | Types | Programme |
|-------|-------|-----------|
| Long Period Variables | M, LPV, Mira | LPV Section |
| Semi-regulars | SR, SRC | LPV Section |
| Cataclysmic Variables | CV, UG, UGSS | CVnet Alert Corps |
| RR Lyrae | RR | RR Lyrae Section |

Source: AAVSO TargetTool (`www.aavso.org/apps/target/`).
Harvest script: `core/preflight/aavso_fetcher.py`.

## ⏳ Cadence Rules

Per-type minimum observation interval, applied by `audit.py` and
`ledger_manager.py` against `data/ledger.json`:

| Type | Cadence |
|------|---------|
| M / LPV / Mira | 7 days |
| SR | 4 days |
| SRC | 5 days |
| CV / UG / UGSS / RR | 1 day |
| Default (fallback) | 3 days |

Resolution order per target:
1. `recommended_cadence_days` in catalog entry
2. Type lookup in table above
3. Default 3 days

A target is `cadence_due = True` when:
`now - last_success >= cadence_days`

## 🔭 Photometry Channel

The IMX585 sensor produces raw uint16 Bayer frames with pattern **GRBG**
(not RGGB — confirmed from seestar_alp source and wire protocol).

For AAVSO Johnson V approximation, the **green channel** is extracted:

```
GRBG layout (pixel positions in 2×2 Bayer cell):
  G  R
  B  G

Green pixels occupy positions [0,0] and [1,1].
Extraction: array[0::2, 0::2] and array[1::2, 1::2], averaged.
```

- Filter designation for AAVSO reports: `CV` (Clear/V-proxy)
- FITS header keyword: `FILTER = 'CV'`
- Science processor: `core/postflight/science_processor.py`
- Output: `*_Green.fits` — single-channel float32, sky-subtracted

**Acquisition** is via `DiamondSequence.acquire()` in `core/flight/pilot.py`
over direct TCP to port 4801. `start_exposure` is not a confirmed method
and is never used. See `API_PROTOCOL.MD`.

Sub-exposure range: 30s – 60s single RAW frames per target visit.

## 🔗 VSP API — Comparison Star Sequences

Comparison star sequences are fetched from the AAVSO Variable Star
Plotter (VSP) API before the observing run.

| Parameter | Value |
|-----------|-------|
| Host | `apps.aavso.org` |
| Endpoint | `/vsp/api/chart/` |
| Auth | HTTP Basic |
| Username | `TARGET_KEY` (from `config.toml`) |
| Password | `api_token` (from `config.toml`) |
| FOV | `300` arcmin — matches S30-Pro 4.6° field |
| Format | JSON |

Fetch script: `core/preflight/chart_fetcher.py`.
Output: `catalogs/reference_stars/{TARGET}.json`.

### Pi-Sleep (Throttling)

A mandatory **31.4 second delay** between VSP API calls is enforced to
avoid IP lockout from `apps.aavso.org`. This is not optional.

## 📋 AAVSO Report Format

SeeVar submits via **AAVSO WebObs extended format** (not REDA).

Required fields per observation:

| Field | Source | Example |
|-------|--------|---------|
| `NAME` | `AcquisitionTarget.name` | `SS CYG` |
| `DATE` | `DATE-OBS` FITS header (JD) | `2460413.394` |
| `MAG` | `PhotometryPipeline` differential result | `11.42` |
| `MAGERR` | photometry SNR-derived | `0.05` |
| `FILT` | `FILTER` FITS header | `CV` |
| `TRANS` | always `NO` (no transform applied) | `NO` |
| `MTYPE` | always `STD` (standard ensemble) | `STD` |
| `CNAME` | ensemble comp star AUIDs | `000-BCB-641` |
| `CMAG` | comp star V mag | `9.9` |
| `OBSCODE` | `AcquisitionTarget.observer_code` | `REDA` |
| `AFFIL` | observer affiliation | optional |

Submission endpoint: `https://www.aavso.org/webobs/`.

## 🆔 AUID Format

All targets must carry an AAVSO Unique Identifier (AUID):

```
Format: NNN-NNN-NNN  (e.g. 000-BCB-641 for SS Cyg)
Stored: AcquisitionTarget.auid
FITS:   AUID keyword in sovereign_stamp()
```

Targets without a confirmed AUID should not be submitted to AAVSO.
They may still be observed for pipeline testing.
