#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/aavso_fetcher.py
Version: 1.7.0
Objective: Haul AAVSO Target Tool campaign targets and write the SeeVar seed catalog.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger("AAVSO_Step1")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.toml"
CATALOG_DIR = PROJECT_ROOT / "catalogs"
MASTER_HAUL_FILE = CATALOG_DIR / "campaign_targets.json"
RAW_HAUL_FILE = CATALOG_DIR / "aavso_targettool_raw.json"

MAG_LIMIT = 15.0
MIN_DEC = -7.62
TARGET_TOOL_URL = "https://targettool.aavso.org/TargetTool/api/v1/targets"
DEFAULT_SECTION = "ac"
PAGE_LIMIT = 1000


# Resolve the Target Tool API key without ever echoing it into logs.
def get_aavso_key(explicit_key: str | None = None) -> str:
    if explicit_key:
        return explicit_key

    env_key = os.environ.get("AAVSO_TARGET_TOOL_API_KEY", "").strip()
    if env_key:
        return env_key

    try:
        with open(CONFIG_PATH, "rb") as f:
            cfg = tomllib.load(f)
        aavso_cfg = cfg.get("aavso", {})
        key = (
            aavso_cfg.get("target_tool_api_key")
            or aavso_cfg.get("target_key")
            or ""
        )
        if not key or key == "":
            logger.error("❌ AAVSO Target Tool key is empty in config.toml")
            logger.error("   Add [aavso] target_tool_api_key = \"...\" or export AAVSO_TARGET_TOOL_API_KEY")
            sys.exit(1)
        return key
    except Exception:
        logger.error("❌ Could not find [aavso] Target Tool API key in config.toml")
        sys.exit(1)


# Return the list payload regardless of whether the API wraps it in a top-level key.
def _extract_targets(payload) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("targets", "data", "results"):
            items = payload.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
        if "star_name" in payload or "name" in payload:
            return [payload]
    logger.error("❌ API returned an unexpected payload:\n%s", json.dumps(payload, indent=2)[:4000])
    sys.exit(1)


# Read common coordinate forms from Target Tool and legacy seed files.
def _coerce_float(value, default=None):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


# Pull RA/Dec from either direct fields or the Target Tool nested coordinates object.
def _coords_deg(target: dict) -> tuple[float | None, float | None]:
    coords = target.get("coordinates")
    if isinstance(coords, dict):
        ra = (
            coords.get("ra")
            or coords.get("raDeg")
            or coords.get("rightAscension")
            or coords.get("rightAscensionDeg")
        )
        dec = (
            coords.get("dec")
            or coords.get("decDeg")
            or coords.get("declination")
            or coords.get("declinationDeg")
        )
    else:
        ra = target.get("ra") or target.get("raDeg") or target.get("rightAscension")
        dec = target.get("dec") or target.get("decDeg") or target.get("declination")
    return _coerce_float(ra), _coerce_float(dec)


# Pick the best available magnitude-like field for SeeVar's planning filters.
def _max_mag(target: dict) -> float | None:
    for key in ("max_mag", "maxMag", "maximumMagnitude", "magnitude", "mag"):
        mag = _coerce_float(target.get(key))
        if mag is not None:
            return mag
    return None


# Convert Target Tool cadence fields into the catalog cadence SeeVar already uses.
def _cadence_days(target: dict, var_type: str) -> float:
    value = _coerce_float(
        target.get("recommended_cadence_days")
        or target.get("cadence")
        or target.get("obs_cadence")
        or target.get("recommendedCadence")
    )
    unit = str(target.get("cadenceUnit") or target.get("recommendedCadenceUnit") or "day").lower()
    if value is not None:
        if unit.startswith("hour"):
            return max(0.1, value / 24.0)
        if unit.startswith("week"):
            return value * 7.0
        return value
    return 1.0 if any(x in var_type for x in ['CV', 'UG', 'RR', 'NA', 'ZAND', 'NL']) else 3.0


# Convert friendly section names to the Target Tool obs_section codes.
def _section_param(section: str) -> list[str]:
    aliases = {
        "alerts": "ac",
        "alerts & campaigns": "ac",
        "alerts | campaigns": "ac",
        "campaigns": "ac",
        "all": "all",
    }
    parts = [part.strip() for part in str(section or DEFAULT_SECTION).split(",") if part.strip()]
    return [aliases.get(part.lower(), part) for part in parts] or [DEFAULT_SECTION]


# Fetch AAVSO Target Tool rows using documented Basic Auth and obs_section codes.
def fetch_targettool_targets(
    api_key: str,
    *,
    observing_section: str = DEFAULT_SECTION,
    limit: int = 0,
    timeout: float = 20.0,
) -> list[dict]:
    params = {"obs_section": _section_param(observing_section)}
    logger.info("📡 Fetching AAVSO Target Tool obs_section=%s", ",".join(params["obs_section"]))
    response = requests.get(
        TARGET_TOOL_URL,
        auth=(api_key, "api_token"),
        params=params,
        timeout=timeout,
    )
    if response.status_code != 200:
        logger.error("❌ AAVSO Target Tool returned HTTP %s: %s", response.status_code, response.text[:1000])
        sys.exit(1)

    targets = _extract_targets(response.json())
    limit = int(limit or 0)
    return targets[:limit] if limit > 0 else targets


# Normalize raw Target Tool rows into the legacy campaign_targets.json schema.
def normalize_targets(target_list: list[dict], *, source_label: str) -> list[dict]:
    logger.info("📥 Processing %s raw entries...", len(target_list))

    targets_dict = {}

    for t in target_list:
        if not isinstance(t, dict):
            continue

        target_name = t.get('star_name') or t.get('name') or t.get("primaryName")
        if not target_name:
            continue

        try:
            ra, dec = _coords_deg(t)
            mag = _max_mag(t)
            if mag is None or ra is None or dec is None:
                continue
            if mag > MAG_LIMIT or dec < MIN_DEC:
                continue

            var_type = str(t.get('var_type') or t.get("targetType") or t.get("type") or "").upper()
            rec_cadence = _cadence_days(t, var_type)
            raw_priority = t.get("priority")
            priority = 1 if raw_priority is True or str(raw_priority).lower() == "true" else 2

            canon_name = re.sub(r' V0+(\d)', r'V \1', str(target_name))

            if canon_name not in targets_dict or mag < targets_dict[canon_name]['max_mag']:
                targets_dict[canon_name] = {
                    "name": canon_name,
                    "ra": float(ra),
                    "dec": float(dec),
                    "type": var_type,
                    "max_mag": mag,
                    "recommended_cadence_days": rec_cadence,
                    "priority": priority,
                    "duration": 600,
                    "source": source_label,
                    "target_class": "AAVSO_CAMPAIGN",
                }
                min_mag = _coerce_float(t.get("min_mag") or t.get("minMag") or t.get("minimumMagnitude"))
                period = _coerce_float(t.get("period") or t.get("period_days"))
                if min_mag is not None:
                    targets_dict[canon_name]["min_mag"] = min_mag
                if period is not None:
                    targets_dict[canon_name]["period_days"] = period
                if t.get("auid"):
                    targets_dict[canon_name]["auid"] = t.get("auid")
                recommended_filter = t.get("recommendedFilter") or t.get("filter")
                if recommended_filter:
                    targets_dict[canon_name]["recommended_filter"] = recommended_filter
                if t.get("observingPrograms"):
                    targets_dict[canon_name]["observing_programs"] = t.get("observingPrograms")
                if t.get("other_info"):
                    targets_dict[canon_name]["campaign_notes"] = t.get("other_info")
        except (ValueError, TypeError):
            continue

    return list(targets_dict.values())


# Write both raw audit data and the filtered catalog consumed by the existing pipeline.
def haul_and_filter(
    api_key: str,
    *,
    observing_section: str = DEFAULT_SECTION,
    limit: int = 0,
    output_path: Path = MASTER_HAUL_FILE,
    raw_output_path: Path = RAW_HAUL_FILE,
) -> list[dict]:
    raw_targets = fetch_targettool_targets(api_key, observing_section=observing_section, limit=limit)
    final_targets = normalize_targets(raw_targets, source_label=f"AAVSO Target Tool: {observing_section}")

    if not final_targets:
        logger.error("❌ No valid targets remained after filtering.")
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    raw_output_path.parent.mkdir(parents=True, exist_ok=True)
    generated_utc = datetime.now(timezone.utc).isoformat()

    raw_output_data = {
        "#objective": "Raw AAVSO Target Tool response retained for audit and future secondary-target curation.",
        "metadata": {
            "generated_utc": generated_utc,
            "source": TARGET_TOOL_URL,
            "observing_section": observing_section,
            "raw_count": len(raw_targets),
        },
        "targets": raw_targets,
    }
    with open(raw_output_path, "w") as f:
        json.dump(raw_output_data, f, indent=4)

    output_data = {
        "#objective": "Filtered AAVSO campaign targets usable by SeeVar preflight tooling.",
        "metadata": {
            "generated_utc": generated_utc,
            "source": TARGET_TOOL_URL,
            "observing_section": observing_section,
            "raw_target_count": len(raw_targets),
            "target_count": len(final_targets)
        },
        "targets": final_targets
    }

    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=4)

    logger.info("✅ Success: %s unique targets saved to %s", len(final_targets), output_path)
    logger.info("🧾 Raw haul retained at %s", raw_output_path)
    return final_targets


# Keep the script usable from cron, bootstrap, or manual beta runs.
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch AAVSO Target Tool campaign targets.")
    parser.add_argument("--api-key", default=None, help="AAVSO Target Tool API key. Prefer config/env for normal use.")
    parser.add_argument("--section", default=DEFAULT_SECTION, help="Target Tool obs_section code or alias. Default: ac (Alerts & Campaigns).")
    parser.add_argument("--limit", type=int, default=0, help="Maximum raw targets to keep; 0 keeps the full API response.")
    parser.add_argument("--output", type=Path, default=MASTER_HAUL_FILE, help="Filtered SeeVar catalog output path.")
    parser.add_argument("--raw-output", type=Path, default=RAW_HAUL_FILE, help="Raw Target Tool audit output path.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    key = get_aavso_key(args.api_key)
    haul_and_filter(
        key,
        observing_section=args.section,
        limit=args.limit,
        output_path=args.output,
        raw_output_path=args.raw_output,
    )
