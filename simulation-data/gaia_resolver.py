#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/postflight/gaia_resolver.py
Version: 1.0.0
Objective: Resolve Gaia DR3 comparison stars for a given field.
           Queries VizieR once per field, caches results to data/gaia_cache/
           on RAID1. Subsequent calls are fully offline.
           Returns star list compatible with bayer_photometry.differential_magnitude().
"""

import json
import logging
import math
from pathlib import Path
from typing import Optional

logger = logging.getLogger("seevar.gaia_resolver")

# Cache lives on RAID1 data/ — persists across reboots, survives power loss
from core.utils.env_loader import DATA_DIR
GAIA_CACHE_DIR = DATA_DIR / "gaia_cache"

# VizieR / Gaia DR3 catalog identifier
GAIA_CATALOG   = "I/355/gaiadr3"
GAIA_COLUMNS   = ["RA_ICRS", "DE_ICRS", "Gmag", "BPmag", "RPmag", "Source"]

# Field of view for the Seestar S30-Pro (degrees)
FOV_RA_DEG     = 1.28
FOV_DEC_DEG    = 0.72

# Grid quantisation for cache key — 0.1° grid means fields within ~6' share a cache entry
GRID_DEG       = 0.1

# Faint limit — no point fetching stars the IMX585 cannot measure cleanly
GMAG_FAINT     = 14.5

# Minimum stars required before we consider the cache valid
MIN_STARS      = 5


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------

def _cache_key(ra: float, dec: float) -> str:
    """
    Snap RA/Dec to a coarse grid so nearby pointings share a cache file.
    Returns a filesystem-safe string: e.g. 'ra083.4_dec+45.2'
    """
    ra_snap  = round(round(ra  / GRID_DEG) * GRID_DEG, 2)
    dec_snap = round(round(dec / GRID_DEG) * GRID_DEG, 2)
    sign     = "+" if dec_snap >= 0 else ""
    return f"ra{ra_snap:07.3f}_dec{sign}{dec_snap:+.3f}".replace("+", "p").replace("-", "m")


def _cache_path(ra: float, dec: float) -> Path:
    return GAIA_CACHE_DIR / f"{_cache_key(ra, dec)}.json"


# ---------------------------------------------------------------------------
# Gaia magnitude → approximate V magnitude conversion
# Jordi et al. (2010) transformation for solar-type stars — good to ~0.05 mag
# ---------------------------------------------------------------------------

def _gaia_to_v(gmag: float, bp_rp: Optional[float]) -> float:
    """
    Convert Gaia G magnitude to approximate Johnson V.
    Falls back to G mag directly if colour unavailable.
    """
    if bp_rp is None or math.isnan(bp_rp):
        return gmag
    # Jordi 2010 polynomial: V = G - (-0.01760 - 0.006860*x - 0.1732*x^2) where x = BP-RP
    x = bp_rp
    correction = -0.01760 - 0.006860 * x - 0.1732 * x**2
    return gmag - correction


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

def _query_vizier(ra: float, dec: float) -> list:
    """
    Hit VizieR for Gaia DR3 stars in the Seestar FOV centred on ra/dec.
    Returns list of dicts ready for caching.
    """
    try:
        from astroquery.vizier import Vizier
        from astropy.coordinates import SkyCoord
        import astropy.units as u
    except ImportError:
        logger.error("astroquery not available — cannot query Gaia. Install: pip install astroquery")
        return []

    logger.info("Querying Gaia DR3 via VizieR at RA=%.4f Dec=%.4f ...", ra, dec)

    v = Vizier(columns=GAIA_COLUMNS, column_filters={"Gmag": f"<{GMAG_FAINT}"})
    v.ROW_LIMIT = -1

    coord  = SkyCoord(ra=ra, dec=dec, unit=("deg", "deg"), frame="icrs")

    try:
        result = v.query_region(
            coord,
            width=FOV_RA_DEG   * u.deg,
            height=FOV_DEC_DEG * u.deg,
            catalog=GAIA_CATALOG
        )
    except Exception as e:
        logger.error("VizieR query failed: %s", e)
        return []

    if not result or len(result) == 0:
        logger.warning("VizieR returned no stars for this field.")
        return []

    table  = result[0]
    stars  = []

    for row in table:
        try:
            gmag  = float(row["Gmag"])
            bpmag = float(row["BPmag"]) if not hasattr(row["BPmag"], "mask") else None
            rpmag = float(row["RPmag"]) if not hasattr(row["RPmag"], "mask") else None
            bp_rp = (bpmag - rpmag) if (bpmag and rpmag) else None
            v_mag = _gaia_to_v(gmag, bp_rp)

            stars.append({
                "source_id": str(row["Source"]),
                "ra":        float(row["RA_ICRS"]),
                "dec":       float(row["DE_ICRS"]),
                "gmag":      round(gmag, 4),
                "v_mag":     round(v_mag, 4),
                "bp_rp":     round(bp_rp, 4) if bp_rp else None,
                # bands list matches the format expected by differential_magnitude()
                "bands": [{"band": "V", "mag": round(v_mag, 4)}],
            })
        except Exception:
            continue

    logger.info("Gaia query returned %d usable stars (G < %.1f).", len(stars), GMAG_FAINT)
    return stars


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_comp_stars(ra: float, dec: float, force_refresh: bool = False) -> list:
    """
    Return a list of comparison stars for the field centred on ra/dec.

    On first call: queries Gaia DR3, writes cache to data/gaia_cache/.
    On subsequent calls: loads from cache (fully offline).
    force_refresh=True: re-queries even if cache exists.

    Each star dict contains:
        source_id, ra, dec, gmag, v_mag, bp_rp, bands
    Compatible with bayer_photometry.differential_magnitude(comp_stars=...).
    """
    GAIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = _cache_path(ra, dec)

    if cache.exists() and not force_refresh:
        try:
            with open(cache, "r") as f:
                data = json.load(f)
            stars = data.get("stars", [])
            if len(stars) >= MIN_STARS:
                logger.info("Gaia cache hit: %s (%d stars)", cache.name, len(stars))
                return stars
            else:
                logger.warning("Cache exists but only %d stars — refreshing.", len(stars))
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Cache read failed (%s) — re-querying.", e)

    # Cache miss or stale — go to VizieR
    stars = _query_vizier(ra, dec)

    if len(stars) >= MIN_STARS:
        payload = {
            "ra":    ra,
            "dec":   dec,
            "n":     len(stars),
            "stars": stars,
        }
        try:
            with open(cache, "w") as f:
                json.dump(payload, f, indent=2)
            logger.info("Gaia cache written: %s (%d stars)", cache.name, len(stars))
        except OSError as e:
            logger.error("Failed to write Gaia cache: %s", e)
    else:
        logger.error("Insufficient stars returned (%d < %d). Cache not written.", len(stars), MIN_STARS)

    return stars


def invalidate_cache(ra: float, dec: float):
    """Remove the cache file for this field — next call will re-query."""
    p = _cache_path(ra, dec)
    if p.exists():
        p.unlink()
        logger.info("Gaia cache invalidated: %s", p.name)


def cache_stats() -> dict:
    """Return a summary of the current Gaia cache."""
    GAIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    files  = list(GAIA_CACHE_DIR.glob("*.json"))
    total  = 0
    for f in files:
        try:
            with open(f) as fh:
                d = json.load(fh)
            total += d.get("n", 0)
        except Exception:
            pass
    return {"fields_cached": len(files), "total_stars": total, "cache_dir": str(GAIA_CACHE_DIR)}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(name)-24s  %(levelname)-8s  %(message)s")

    # Quick smoke test — SS Cyg: RA 314.753, Dec +43.586
    ra_test, dec_test = 314.753, 43.586
    if len(sys.argv) == 3:
        ra_test, dec_test = float(sys.argv[1]), float(sys.argv[2])

    stars = get_comp_stars(ra_test, dec_test)
    print(f"\n{len(stars)} comparison stars retrieved.")
    for s in stars[:5]:
        print(f"  {s['source_id']}  RA={s['ra']:.4f}  Dec={s['dec']:.4f}  G={s['gmag']:.2f}  V≈{s['v_mag']:.2f}")

    print(f"\nCache stats: {cache_stats()}")
