#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/install_horizon_mask.py
Objective: Install a candidate horizon_mask.json into the SeeVar runtime data dir
with a timestamped backup of any existing mask.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
TARGET_MASK = DATA_DIR / "horizon_mask.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install a candidate SeeVar horizon mask.")
    parser.add_argument("source", help="Path to the candidate horizon_mask.json")
    return parser.parse_args()


def summarize(mask_path: Path) -> str:
    payload = json.loads(mask_path.read_text())
    profile = {int(k): float(v) for k, v in payload["profile"].items()}
    vals = list(profile.values())
    return (
        f"points={len(profile)} min={min(vals):.1f} max={max(vals):.1f} "
        f"mean={sum(vals)/len(vals):.1f} source={payload.get('source','unknown')}"
    )


def main() -> int:
    args = parse_args()
    source = Path(args.source).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"Source not found: {source}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if TARGET_MASK.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = DATA_DIR / f"horizon_mask.{stamp}.bak.json"
        shutil.copy2(TARGET_MASK, backup)
        print(f"Backed up existing mask to {backup}")

    shutil.copy2(source, TARGET_MASK)
    print(f"Installed {source} -> {TARGET_MASK}")
    print(summarize(TARGET_MASK))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
