#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/preflight/vsx_catalog.py
Version: 2.0.0
Objective: Fetch magnitude ranges from AAVSO VSX for all campaign targets.
           Populates data/vsx_catalog.json — consumed by exposure_planner.

CLI usage:
    python3 vsx_catalog.py                  # fetch all missing
    python3 vsx_catalog.py R And W Cyg      # fetch specific targets
    python3 vsx_catalog.py --refresh        # re-fetch everything
    python3 vsx_catalog.py --debug R And    # dump raw VSX JSON for inspection
    python3 vsx_catalog.py --summary        # print cached catalog table
"""

import json
import logging
import re
import sys
import time
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("VSXCatalog")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR  = PROJECT_ROOT / "catalogs"
DATA_DIR     = PROJECT_ROOT / "data"
MASTER_FILE  = CATALOG_DIR / "campaign_targets.json"
VSX_CACHE    = DATA_DIR / "vsx_catalog.json"

POLL_DELAY_S = 31.4
VSX_URL      = "https://www.aavso.org/vsx/index.php"
TIMEOUT_S    = 15
DEFAULT_MAG  = 12.0


# ---------------------------------------------------------------------------
# Magnitude string parser
# ---------------------------------------------------------------------------
def _clean_mag(s) -> float | None:
    """
    Robust VSX magnitude string parser.

    VSX returns MaxMag/MinMag as strings with many quirks:
        "5.8"       normal
        "(5.8)"     uncertain
        "<5.8"      upper limit
        "5.8:"      uncertain
        "5.8B"      band suffix
        "14.9p"     photographic band
        "[14.9]"    brackets
        "0.0"       VSX sentinel for 'not defined' — treat as None
        ""  / None  missing

    Strategy: extract first numeric token, reject 0.0 and out-of-range.
    """
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    m = re.search(r'(\d+\.?\d*)', s)
    if not m:
        return None
    val = float(m.group(1))
    # 0.0 is VSX's sentinel for undefined; reject physically implausible values
    if val <= 0.0 or val > 25.0:
        return None
    return val


# ---------------------------------------------------------------------------
# VSX query
# ---------------------------------------------------------------------------
def _query_vsx_raw(star_name: str) -> dict:
    """Return raw VSX JSON dict for a star, or {}."""
    try:
        resp = requests.get(
            VSX_URL,
            params={"view": "api.object", "format": "json", "ident": star_name, "caller": "REDA"},
            timeout=TIMEOUT_S,
        )
        if resp.status_code != 200:
            log.warning("VSX HTTP %d for %s", resp.status_code, star_name)
            return {}
        return resp.json()
    except Exception as e:
        log.error("VSX request failed for %s: %s", star_name, e)
        return {}


def _parse_vsx(star_name: str, raw: dict) -> dict:
    """
    Parse a raw VSX API response into a normalised magnitude record.

    VSX field notes:
        MaxMag  — bright limit (small number for Miras, e.g. 5.8)
        MinMag  — faint limit  (large number, e.g. 14.9)
        MagBand — photometric band of the range (V, R, B, p, ...)

    Some variable types (UGSS, ZAND, symbiotic novae) have poorly defined
    or missing magnitude ranges in VSX — these return mag_mid=None and fall
    back to DEFAULT_MAG in get_target_mag().
    """
    obj = raw.get("VSXObject", {})
    if not obj:
        return {"name": star_name, "max_mag": None, "min_mag": None,
                "mag_mid": None, "var_type": "UNKNOWN", "error": "vsx_empty"}

    max_mag = _clean_mag(obj.get("MaxMag"))
    min_mag = _clean_mag(obj.get("MinMag"))

    # VSX convention: MaxMag = bright end (smaller number)
    # Guard: swap if inverted
    if max_mag is not None and min_mag is not None:
        if max_mag > min_mag:
            max_mag, min_mag = min_mag, max_mag
        mag_mid = round((max_mag + min_mag) / 2.0, 2)
    elif max_mag is not None:
        mag_mid = max_mag
    elif min_mag is not None:
        mag_mid = min_mag
    else:
        mag_mid = None

    return {
        "name":     obj.get("Name", star_name),
        "auid":     obj.get("AUID", ""),
        "var_type": obj.get("VariabilityType", ""),
        "period":   obj.get("Period") or None,
        "max_mag":  max_mag,
        "min_mag":  min_mag,
        "mag_mid":  mag_mid,
        "mag_band": obj.get("MagBand", "V"),
        "ra":       obj.get("RA2000"),
        "dec":      obj.get("Declination2000"),
    }


def _query_vsx(star_name: str) -> dict:
    raw = _query_vsx_raw(star_name)
    if not raw:
        return {"name": star_name, "max_mag": None, "min_mag": None,
                "mag_mid": None, "var_type": "UNKNOWN", "error": "vsx_no_response"}
    return _parse_vsx(star_name, raw)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
def _load_cache() -> dict:
    if VSX_CACHE.exists():
        try:
            with open(VSX_CACHE, "r") as f:
                return json.load(f).get("stars", {})
        except Exception:
            pass
    return {}


def _save_cache(stars: dict):
    import datetime
    VSX_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(VSX_CACHE, "w") as f:
        json.dump({
            "#objective": "AAVSO VSX magnitude ranges for campaign targets",
            "updated":    datetime.datetime.utcnow().isoformat() + "Z",
            "stars":      stars,
        }, f, indent=4)


def _load_target_names() -> list:
    if not MASTER_FILE.exists():
        log.error("campaign_targets.json not found: %s", MASTER_FILE)
        return []
    with open(MASTER_FILE, "r") as f:
        data = json.load(f)
    targets = data.get("targets", []) if isinstance(data, dict) else data
    return [t["name"] for t in targets if "name" in t]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def fetch_vsx_catalog(target_list: list = None, force_refresh: bool = False) -> dict:
    """
    Fetch VSX data for all campaign targets. Cache-first unless force_refresh.
    Returns the full stars dict.
    """
    names  = target_list or _load_target_names()
    stars  = _load_cache()
    hits = misses = 0

    for name in names:
        key = name.strip()
        if key in stars and not force_refresh:
            continue

        if hits + misses > 0:
            log.info("Throttling %.1fs...", POLL_DELAY_S)
            time.sleep(POLL_DELAY_S)

        log.info("Querying VSX: %s", key)
        result = _query_vsx(key)
        stars[key] = result
        _save_cache(stars)  # incremental — survives kill

        if result.get("mag_mid") is not None:
            log.info("  ✅ %s — type=%-6s max=%-5s min=%-5s mid=%.1f",
                     key, result.get("var_type","?"),
                     result.get("max_mag"), result.get("min_mag"),
                     result["mag_mid"])
            hits += 1
        else:
            log.warning("  ⚠️  %s — type=%-6s no usable magnitude (max=%s min=%s)",
                        key, result.get("var_type","?"),
                        result.get("max_mag"), result.get("min_mag"))
            misses += 1

    _save_cache(stars)
    log.info("VSX catalog: %d with magnitude, %d without, %d total cached.",
             hits, misses, len(stars))
    return stars


def get_target_mag(star_name: str, phase: str = "mid") -> float:
    """
    Return planning magnitude for a target.

    phase: 'mid' (default) | 'bright' | 'faint'
    Falls back to DEFAULT_MAG if not cached or magnitude undefined.
    """
    entry = _load_cache().get(star_name.strip(), {})
    mag = {
        "bright": entry.get("max_mag"),
        "faint":  entry.get("min_mag"),
        "mid":    entry.get("mag_mid"),
    }.get(phase)

    if mag is None:
        log.debug("No VSX mag for %s phase=%s — using default %.1f",
                  star_name, phase, DEFAULT_MAG)
        return DEFAULT_MAG
    return float(mag)


def catalog_summary() -> None:
    stars = _load_cache()
    if not stars:
        print("VSX catalog empty — run: python3 core/preflight/vsx_catalog.py")
        return
    no_mag = sum(1 for s in stars.values() if s.get("mag_mid") is None)
    print(f"\nVSX Catalog — {len(stars)} targets  ({no_mag} without usable magnitude)")
    print(f"{'Name':<26} {'Type':<8} {'Max':>5} {'Min':>6} {'Mid':>6} {'Period':>9}")
    print("-" * 66)
    for name, s in sorted(stars.items()):
        vtype  = (s.get("var_type") or "?")[:7]
        maxm   = f"{s['max_mag']:.1f}"  if s.get("max_mag")  is not None else "  —  "
        minm   = f"{s['min_mag']:.1f}"  if s.get("min_mag")  is not None else "   —  "
        midm   = f"{s['mag_mid']:.1f}"  if s.get("mag_mid")  is not None else "   —  "
        try:
            period = f"{float(re.sub(r'[^0-9.]', '', str(s['period']))):.1f}d" if s.get("period") else "       —"
        except (ValueError, TypeError):
            period = str(s.get("period","—"))[:9]
        print(f"{name:<26} {vtype:<8} {maxm:>5} {minm:>6} {midm:>6} {period:>9}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    args = sys.argv[1:]

    # --debug R And  → dump raw VSX JSON, no cache write
    if "--debug" in args:
        names = [a for a in args if not a.startswith("--")]
        if not names:
            print("Usage: vsx_catalog.py --debug <star name>")
            sys.exit(1)
        star = " ".join(names)
        print(f"\nRaw VSX response for: {star}")
        print("-" * 50)
        raw = _query_vsx_raw(star)
        print(json.dumps(raw, indent=2))
        print("-" * 50)
        parsed = _parse_vsx(star, raw)
        print("Parsed:", json.dumps(parsed, indent=2))
        sys.exit(0)

    if "--summary" in args:
        catalog_summary()
        sys.exit(0)

    force   = "--refresh" in args
    names   = [a for a in args if not a.startswith("--")] or None
    fetch_vsx_catalog(target_list=names, force_refresh=force)
    catalog_summary()
