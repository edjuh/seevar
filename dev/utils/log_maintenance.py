#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/utils/log_maintenance.py
Version: 1.0.0
Objective: Rotate SeeVar application logs without relying on root logrotate.
"""

from __future__ import annotations

import argparse
import gzip
import shutil
from datetime import datetime, timezone
from pathlib import Path


# Move old rotated files up one slot and discard files beyond retention.
def _shift_rotations(path: Path, keep: int) -> None:
    oldest = path.with_name(f"{path.name}.{keep}.gz")
    oldest.unlink(missing_ok=True)

    for idx in range(keep - 1, 0, -1):
        src = path.with_name(f"{path.name}.{idx}.gz")
        dest = path.with_name(f"{path.name}.{idx + 1}.gz")
        if src.exists():
            src.replace(dest)


# Copy the live log into a compressed rotation and truncate the original.
def _rotate_log(path: Path, keep: int) -> dict[str, object]:
    before = path.stat().st_size
    _shift_rotations(path, keep)
    rotated = path.with_name(f"{path.name}.1.gz")
    with path.open("rb") as src, gzip.open(rotated, "wb") as dest:
        shutil.copyfileobj(src, dest)
    with path.open("w", encoding="utf-8"):
        pass
    return {"path": str(path), "bytes_before": before, "rotated_to": str(rotated)}


# Rotate logs exceeding the configured byte threshold.
def run(log_dir: Path, max_bytes: int, keep: int, force: bool = False) -> dict[str, object]:
    log_dir = log_dir.expanduser()
    rotated = []
    skipped = []
    for path in sorted(log_dir.glob("*.log")):
        try:
            size = path.stat().st_size
        except OSError as exc:
            skipped.append({"path": str(path), "error": str(exc)})
            continue
        if force or size >= max_bytes:
            rotated.append(_rotate_log(path, keep))
        else:
            skipped.append({"path": str(path), "bytes": size})

    return {
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "log_dir": str(log_dir),
        "max_bytes": max_bytes,
        "keep": keep,
        "rotated": rotated,
        "skipped_count": len(skipped),
    }


# Parse CLI flags for manual and systemd timer use.
def main() -> int:
    parser = argparse.ArgumentParser(description="Rotate SeeVar application logs.")
    parser.add_argument("--log-dir", type=Path, default=Path.home() / "seevar" / "logs")
    parser.add_argument("--max-mb", type=float, default=10.0)
    parser.add_argument("--keep", type=int, default=14)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = run(
        args.log_dir,
        max_bytes=max(1, int(args.max_mb * 1024 * 1024)),
        keep=max(1, int(args.keep)),
        force=args.force,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
