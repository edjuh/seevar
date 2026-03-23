#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/vsx_catalog.py
Version: 2.0.2
Objective: Fetch magnitude ranges from AAVSO VSX for all campaign targets.
           Iteratively saves data/vsx_catalog.json after every successful fetch to prevent data loss.
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

POLL_DELAY_S = 188.4  # SeeVar-vsx-throttle-188: Pi-Minute per CONTRIBUTING.md

def _query_vsx_raw(star_name: str) -> dict:
    url = "https://aavso.org/vsx/index.php"
    params = {
        "view": "api.object",
        "ident": star_name,
        "format": "json"
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning("VSX fetch failed for %s: %s", star_name, e)
        return {}

def _parse_vsx(star_name: str, raw: dict) -> dict:
    vsobj = raw.get("VSXObject", {})
    if not vsobj:
        return {}

    max_mag = vsobj.get("maxMag")
    min_mag = vsobj.get("minMag")
    var_type = vsobj.get("Type")
    period = vsobj.get("Period")

    def _clean_mag(m) -> float | None:
        if not m: return None
        m_str = str(m).replace("<", "").replace(">", "").strip()
        m_str = re.sub(r"[A-Za-z:()]", "", m_str)
        try:
            return float(m_str)
        except ValueError:
            return None

    c_max = _clean_mag(max_mag)
    c_min = _clean_mag(min_mag)

    mag_mid = None
    if c_max is not None and c_min is not None:
        mag_mid = round((c_max + c_min) / 2.0, 2)
    elif c_max is not None:
        mag_mid = c_max

    return {
        "max_mag": c_max,
        "min_mag": c_min,
        "mag_mid": mag_mid,
        "type": var_type,
        "period": period,
    }

def update_vsx_catalog(force_refresh: bool = False):
    if not MASTER_FILE.exists():
        log.error("No campaign targets found. Run aavso_fetcher first.")
        return

    with open(MASTER_FILE, "r") as f:
        master = json.load(f)

    targets = master.get("targets", []) if isinstance(master, dict) else master

    cache = {}
    if VSX_CACHE.exists() and not force_refresh:
        try:
            with open(VSX_CACHE, "r") as f:
                c = json.load(f)
                cache = c.get("stars", {})
        except json.JSONDecodeError:
            pass

    updated = 0
    total = len(targets)

    for i, t in enumerate(targets, 1):
        name = t.get("name")
        if not name: continue

        if name in cache and not force_refresh:
            log.info("[%d/%d] Skipping %s (Already in cache)", i, total, name)
            continue

        log.info("[%d/%d] Fetching VSX for %s...", i, total, name)
        raw = _query_vsx_raw(name)
        parsed = _parse_vsx(name, raw)

        if parsed:
            cache[name] = parsed
            updated += 1
            log.debug("  -> %s", parsed)
            
            # --- ITERATIVE SAVE (The Fix) ---
            out = {
                "#objective": "AAVSO VSX magnitude ranges for dynamic exposure planning.",
                "stars": cache,
            }
            with open(VSX_CACHE, "w") as f:
                json.dump(out, f, indent=4)
        else:
            log.warning("  -> No VSX match.")

        time.sleep(POLL_DELAY_S)

    log.info("✅ VSX Catalog run complete. %d new records added.", updated)

def get_target_mag(target_name: str) -> float | None:
    if not VSX_CACHE.exists(): return None
    try:
        with open(VSX_CACHE, "r") as f:
            data = json.load(f)
        star = data.get("stars", {}).get(target_name, {})
        return star.get("mag_mid")
    except Exception:
        return None

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--debug" in args:
        names = [a for a in args if not a.startswith("--")]
        if not names:
            print("Usage: vsx_catalog.py --debug <star name>")
            sys.exit(1)
        star = " ".join(names)
        print(f"\nRaw VSX response for: {star}")
        raw = _query_vsx_raw(star)
        print(json.dumps(raw, indent=2))
        parsed = _parse_vsx(star, raw)
        print(f"\nParsed dict: {parsed}\n")
        sys.exit(0)

    if "--refresh" in args:
        update_vsx_catalog(force_refresh=True)
    elif "--summary" in args:
        if not VSX_CACHE.exists():
            print("No cache found.")
            sys.exit(0)
        with open(VSX_CACHE, "r") as f:
            c = json.load(f)
        stars = c.get("stars", {})
        print(f"\nVSX Cached Stars: {len(stars)}")
        print(f"{'Name':<26} {'Type':<8} {'Max':>5} {'Min':>6} {'Mid':>6} {'Period':>9}")
        for name, s in sorted(stars.items()):
            vtype  = str(s.get("type",""))[:8]
            maxm   = f"{s['max_mag']:.1f}"  if s.get("max_mag")  is not None else "   — "
            minm   = f"{s['min_mag']:.1f}"  if s.get("min_mag")  is not None else "   —  "
            midm   = f"{s['mag_mid']:.1f}"  if s.get("mag_mid")  is not None else "   —  "
            try:
                period = f"{float(re.sub(r'[^0-9.]', '', str(s['period']))):.1f}d" if s.get("period") else "       —"
            except (ValueError, TypeError):
                period = str(s.get("period","—"))[:9]
            print(f"{name:<26} {vtype:<8} {maxm:>5} {minm:>6} {midm:>6} {period:>9}")
    elif len(args) > 0:
        star = " ".join(args)
        log.info("Fetching single target: %s", star)
        r = _query_vsx_raw(star)
        p = _parse_vsx(star, r)
        if p:
            if VSX_CACHE.exists():
                with open(VSX_CACHE, "r") as f:
                    data = json.load(f)
            else:
                data = {"stars": {}}
            data["stars"][star] = p
            with open(VSX_CACHE, "w") as f:
                json.dump(data, f, indent=4)
            log.info("Updated %s: %s", star, p)
        else:
            log.error("Failed to parse %s", star)
    else:
        update_vsx_catalog()
