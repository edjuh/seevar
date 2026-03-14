#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/librarian.py
Version: 4.3.0
Objective: The Single Source of Truth. Parses raw AAVSO haul, checks for VSP charts, and writes the Federation Catalog.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger("Librarian")

# Fixed Sovereign Path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = PROJECT_ROOT / "catalogs"
RAW_HARVEST = CATALOG_DIR / "campaign_targets.json"
REF_DIR = CATALOG_DIR / "reference_stars"
VALIDATED_CATALOG = CATALOG_DIR / "federation_catalog.json"
VSX_CATALOG   = PROJECT_ROOT / "data" / "vsx_catalog.json"

def inject_metadata(data, objective):
    return {
        "#objective": objective,
        "metadata": {
            "generated": datetime.now().isoformat(),
            "schema_version": "2026.1"
        },
        "data": data
    }

def process_library():
    logger.info("📚 Librarian: Commencing library audit...")

    if not RAW_HARVEST.exists():
        logger.error("❌ No harvest found.")
        return

    with open(RAW_HARVEST, 'r') as f:
        raw_data = json.load(f)
        targets = raw_data.get("targets", []) if isinstance(raw_data, dict) else raw_data

    # Deduplicate while preserving all fields
    unique_map = {t['name']: t for t in targets if 'name' in t}
    valid_targets = []

    # vsx_enrichment — load VSX cache for min_mag + period enrichment
    vsx_stars = {}
    if VSX_CATALOG.exists():
        try:
            vsx_raw = json.load(open(VSX_CATALOG, 'r'))
            vsx_stars = vsx_raw.get("stars", {})
            logger.info(f"📡 VSX cache loaded: {len(vsx_stars)} entries available for enrichment")
        except Exception as e:
            logger.warning(f"⚠️  VSX cache load failed: {e} — proceeding without enrichment")
    else:
        logger.warning("⚠️  VSX catalog not found — min_mag and period will be null")

    enriched = skipped = 0

    for name, target in unique_map.items():
        # multi_name_match — check all three naming conventions
        clean_lower = name.lower().replace(' ', '_').replace('-', '_')
        clean_upper = name.upper().replace(' ', '_').replace('-', '_')
        has_ref = (
            (REF_DIR / f"{clean_lower}.json").exists() or
            (REF_DIR / f"{clean_upper}_comps.json").exists() or
            (REF_DIR / f"{clean_upper}.json").exists()
        )
        if not has_ref:
            continue

        # Enrich with VSX fields if available
        vsx = vsx_stars.get(name, {})
        if vsx:
            # min_mag
            raw_min = vsx.get("min_mag")
            try:
                target["min_mag"] = float(raw_min) if raw_min is not None else None
            except (ValueError, TypeError):
                target["min_mag"] = None

            # period in days
            raw_period = vsx.get("period")
            try:
                target["period_days"] = float(raw_period) if raw_period is not None else None
            except (ValueError, TypeError):
                target["period_days"] = None

            enriched += 1
        else:
            target["min_mag"]     = None
            target["period_days"] = None
            skipped += 1

        valid_targets.append(target)

    logger.info(f"✨ VSX enrichment: {enriched} targets enriched, {skipped} without VSX match")

    federated_data = inject_metadata(valid_targets, "Validated and deduplicated target list ready for Auditing.")
    
    with open(VALIDATED_CATALOG, 'w') as f:
        json.dump(federated_data, f, indent=4)

    logger.info(f"✅ Librarian: {len(valid_targets)} targets federated with full metadata.")

if __name__ == "__main__":
    process_library()
