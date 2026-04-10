#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/vsx_catalog.py
Version: 2.4.0
Objective: Fetch magnitude ranges from AAVSO VSX for all campaign targets,
           cache them safely, and serve target magnitudes efficiently at runtime.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import requests

try:
    import fcntl
except ImportError:
    fcntl = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("VSXCatalog")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = PROJECT_ROOT / "catalogs"
DATA_DIR = PROJECT_ROOT / "data"
MASTER_FILE = CATALOG_DIR / "campaign_targets.json"
VSX_CACHE = DATA_DIR / "vsx_catalog.json"
VSX_LOCK = DATA_DIR / "vsx_catalog.lock"

POLL_DELAY_S = 88.4
SAVE_EVERY_N = 10
HTTP_RETRIES = 2
HTTP_BACKOFF_S = 2.0

STATUS_OK = "ok"
STATUS_NO_MATCH = "no_match"

_MAG_CACHE: dict[str, dict] = {}
_MAG_CACHE_MTIME: float | None = None


@contextmanager
def _file_lock():
    VSX_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(VSX_LOCK, "w") as lockf:
        if fcntl is not None:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_cache_from_disk() -> dict:
    if not VSX_CACHE.exists():
        return {"stars": {}}
    try:
        with open(VSX_CACHE, "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("stars", {})
            stars = data.get("stars", {})
            migrated = False
            if isinstance(stars, dict):
                for name, entry in list(stars.items()):
                    if not isinstance(entry, dict):
                        entry = {}
                    if "status" not in entry:
                        enriched = (
                            entry.get("mag_mid") is not None
                            or bool(entry.get("type"))
                            or entry.get("period") is not None
                            or entry.get("max_mag") is not None
                            or entry.get("min_mag") is not None
                        )
                        entry["status"] = STATUS_OK if enriched else STATUS_NO_MATCH
                        entry.setdefault("checked_utc", _now_utc())
                        stars[name] = entry
                        migrated = True
            if migrated:
                data["stars"] = stars
                _save_cache(stars)
            return data
    except json.JSONDecodeError:
        log.warning("VSX cache unreadable; starting with empty cache.")
    except Exception as exc:
        log.warning("VSX cache read failed: %s", exc)
    return {"stars": {}}


def _save_cache(stars: dict):
    VSX_CACHE.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "#objective": "AAVSO VSX magnitude ranges for dynamic exposure planning.",
        "stars": stars,
    }
    tmp = VSX_CACHE.with_suffix(".json.tmp")
    with _file_lock():
        with open(tmp, "w") as f:
            json.dump(out, f, indent=4)
        tmp.replace(VSX_CACHE)


def _refresh_mag_cache():
    global _MAG_CACHE, _MAG_CACHE_MTIME

    if not VSX_CACHE.exists():
        _MAG_CACHE = {}
        _MAG_CACHE_MTIME = None
        return

    try:
        mtime = VSX_CACHE.stat().st_mtime
    except Exception:
        return

    if _MAG_CACHE_MTIME is not None and mtime == _MAG_CACHE_MTIME:
        return

    data = _load_cache_from_disk()
    _MAG_CACHE = data.get("stars", {})
    _MAG_CACHE_MTIME = mtime


def _extract_band(value) -> str | None:
    if not value:
        return None
    m = re.search(r"([A-Za-z]+)\s*$", str(value).strip())
    return m.group(1) if m else None


def _clean_mag(value) -> float | None:
    if not value:
        return None
    m_str = str(value).replace("<", "").replace(">", "").strip()
    m_str = re.sub(r"[A-Za-z:()]", "", m_str)
    try:
        return float(m_str)
    except ValueError:
        return None


def _clean_period(value) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        cleaned = re.sub(r"[^0-9.]+", "", str(value))
        return float(cleaned) if cleaned else None
    except Exception:
        return None


def _stamp_entry(entry: dict, status: str) -> dict:
    stamped = dict(entry)
    stamped["status"] = status
    stamped["checked_utc"] = _now_utc()
    return stamped


def _negative_cache_entry() -> dict:
    return _stamp_entry(
        {
            "max_mag": None,
            "min_mag": None,
            "mag_mid": None,
            "type": None,
            "period": None,
            "max_band": None,
            "min_band": None,
        },
        STATUS_NO_MATCH,
    )


def _is_cached_success(entry: dict) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("status") == STATUS_OK:
        return True
    return (
        entry.get("mag_mid") is not None
        or bool(entry.get("type"))
        or entry.get("period") is not None
        or entry.get("max_mag") is not None
        or entry.get("min_mag") is not None
    )


def _is_cached_no_match(entry: dict) -> bool:
    return isinstance(entry, dict) and entry.get("status") == STATUS_NO_MATCH


def _query_vsx_raw(star_name: str) -> dict:
    url = "https://aavso.org/vsx/index.php"
    params = {
        "view": "api.object",
        "ident": star_name,
        "format": "json",
    }

    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            if attempt >= HTTP_RETRIES:
                log.warning("VSX fetch failed for %s after %d attempt(s): %s", star_name, attempt, exc)
                return {}
            log.warning(
                "VSX fetch failed for %s (attempt %d/%d): %s; retrying...",
                star_name, attempt, HTTP_RETRIES, exc
            )
            time.sleep(HTTP_BACKOFF_S)

    return {}


def _parse_vsx(star_name: str, raw: dict) -> dict:
    vsobj = raw.get("VSXObject", {})
    if not vsobj:
        return {}

    max_mag_raw = vsobj.get("MaxMag") or vsobj.get("maxMag")
    min_mag_raw = vsobj.get("MinMag") or vsobj.get("minMag")
    var_type = vsobj.get("VariabilityType") or vsobj.get("Type")
    period = _clean_period(vsobj.get("Period"))

    max_band = _extract_band(max_mag_raw)
    min_band = _extract_band(min_mag_raw)

    c_max = _clean_mag(max_mag_raw)
    c_min = _clean_mag(min_mag_raw)

    if max_band and min_band and max_band != min_band:
        log.warning(
            "VSX band mismatch for %s: max=%s (%s) min=%s (%s)",
            star_name, max_mag_raw, max_band, min_mag_raw, min_band
        )

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
        "max_band": max_band,
        "min_band": min_band,
    }


def update_vsx_catalog(force_refresh: bool = False):
    if not MASTER_FILE.exists():
        log.error("No campaign targets found. Run aavso_fetcher first.")
        return

    with open(MASTER_FILE, "r") as f:
        master = json.load(f)

    targets = master.get("targets", []) if isinstance(master, dict) else master

    cache_data = _load_cache_from_disk() if VSX_CACHE.exists() and not force_refresh else {"stars": {}}
    cache = cache_data.get("stars", {})

    updated = 0
    no_match_cached = 0
    since_save = 0
    total = len(targets)

    try:
        for i, t in enumerate(targets, 1):
            name = t.get("name")
            if not name:
                continue

            if name in cache and not force_refresh:
                existing = cache.get(name, {})
                if _is_cached_success(existing) or _is_cached_no_match(existing):
                    continue

            log.info("[%d/%d] Fetching VSX for %s...", i, total, name)
            raw = _query_vsx_raw(name)
            parsed = _parse_vsx(name, raw)

            if parsed:
                cache[name] = _stamp_entry(parsed, STATUS_OK)
                updated += 1
                since_save += 1
                log.debug("  -> %s", parsed)
            else:
                cache[name] = _negative_cache_entry()
                no_match_cached += 1
                since_save += 1
                log.warning("  -> No VSX match; cached as no_match.")

            if since_save >= SAVE_EVERY_N:
                _save_cache(cache)
                since_save = 0

            time.sleep(POLL_DELAY_S)
    finally:
        if updated > 0 or no_match_cached > 0 or force_refresh:
            _save_cache(cache)
            _refresh_mag_cache()

    if updated > 0 or no_match_cached > 0 or force_refresh:
        log.info(
            "✅ VSX Catalog updated. %d enriched, %d cached as no_match.",
            updated,
            no_match_cached,
        )
    else:
        log.info("✅ VSX Catalog up to date. No API calls made.")


def get_target_mag(target_name: str) -> float | None:
    _refresh_mag_cache()
    star = _MAG_CACHE.get(target_name, {})
    return star.get("mag_mid")


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
        positive = {name: s for name, s in stars.items() if not _is_cached_no_match(s)}
        misses = sum(1 for s in stars.values() if _is_cached_no_match(s))

        print(f"\nVSX Cached Stars: {len(stars)} ({len(positive)} enriched, {misses} no_match)")
        print(f"{'Name':<26} {'Type':<8} {'Max':>5} {'Min':>6} {'Mid':>6} {'Period':>9}")
        for name, s in sorted(positive.items()):
            vtype = str(s.get("type", ""))[:8]
            maxm = f"{s['max_mag']:.1f}" if s.get("max_mag") is not None else "   — "
            minm = f"{s['min_mag']:.1f}" if s.get("min_mag") is not None else "   —  "
            midm = f"{s['mag_mid']:.1f}" if s.get("mag_mid") is not None else "   —  "
            period_val = s.get("period")
            period = f"{period_val:.1f}d" if isinstance(period_val, (int, float)) else "       —"
            print(f"{name:<26} {vtype:<8} {maxm:>5} {minm:>6} {midm:>6} {period:>9}")
    elif len(args) > 0:
        star = " ".join(args)
        log.info("Fetching single target: %s", star)
        r = _query_vsx_raw(star)
        p = _parse_vsx(star, r)
        data = _load_cache_from_disk()
        data.setdefault("stars", {})
        if p:
            data["stars"][star] = _stamp_entry(p, STATUS_OK)
            _save_cache(data["stars"])
            _refresh_mag_cache()
            log.info("Updated %s: %s", star, p)
        else:
            data["stars"][star] = _negative_cache_entry()
            _save_cache(data["stars"])
            _refresh_mag_cache()
            log.warning("Cached %s as no_match", star)
    else:
        update_vsx_catalog()
