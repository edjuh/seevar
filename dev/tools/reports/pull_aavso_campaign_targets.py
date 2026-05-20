#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/reports/pull_aavso_campaign_targets.py
Version: 1.0.0
Objective: Pull AAVSO Target Tool campaign targets as secondary candidates without replacing the main SeeVar catalog.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.preflight.aavso_fetcher import DEFAULT_SECTION, get_aavso_key, haul_and_filter
from core.utils.env_loader import DATA_DIR

SECONDARY_DIR = DATA_DIR / "secondary_targets"
DEFAULT_OUTPUT = SECONDARY_DIR / "aavso_campaign_targets.json"
DEFAULT_RAW_OUTPUT = SECONDARY_DIR / "aavso_targettool_raw.json"


# Parse a small operator-friendly CLI for beta/manual target harvesting.
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pull AAVSO Target Tool campaign targets into data/secondary_targets/."
    )
    parser.add_argument("--api-key", default=None, help="AAVSO Target Tool API key. Prefer config/env for normal use.")
    parser.add_argument("--section", default=DEFAULT_SECTION, help="Target Tool obs_section code or alias. Default: ac (Alerts & Campaigns).")
    parser.add_argument("--limit", type=int, default=0, help="Maximum raw targets to keep; 0 keeps the full API response.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Filtered secondary catalog output.")
    parser.add_argument("--raw-output", type=Path, default=DEFAULT_RAW_OUTPUT, help="Raw Target Tool audit output.")
    return parser.parse_args(argv)


# Fetch and annotate the secondary-target catalog so the planner can treat it cautiously later.
def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    api_key = get_aavso_key(args.api_key)
    targets = haul_and_filter(
        api_key,
        observing_section=args.section,
        limit=args.limit,
        output_path=args.output,
        raw_output_path=args.raw_output,
    )

    with open(args.output, "r") as f:
        payload = json.load(f)

    payload["#objective"] = (
        "AAVSO Target Tool campaign targets staged as secondary SeeVar candidates. "
        "These are not automatically scheduled until planner policy enables them."
    )
    payload.setdefault("metadata", {})
    payload["metadata"]["secondary_catalog"] = True
    payload["metadata"]["staged_utc"] = datetime.now(timezone.utc).isoformat()
    for target in payload.get("targets", []):
        if isinstance(target, dict):
            target["target_class"] = "SECONDARY_AAVSO_CAMPAIGN"
            target["priority"] = min(int(target.get("priority", 2)), 3)

    with open(args.output, "w") as f:
        json.dump(payload, f, indent=4)

    print(f"Secondary AAVSO campaign targets: {len(targets)}")
    print(args.output)
    print(args.raw_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
