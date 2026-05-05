#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Clean transient postflight solver products left in SeeVar data directories.

Default mode is a dry run. Use --apply after reviewing the candidate list.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

SOLVER_PATTERNS = (
    "*.axy",
    "*.corr",
    "*.match",
    "*.rdls",
    "*.solved",
    "*.new",
    "*.wcs",
    "*-indx.xyls",
)


def _iter_matches(root: Path, patterns: tuple[str, ...]) -> list[Path]:
    matches: list[Path] = []
    if not root.exists():
        return matches
    for pattern in patterns:
        matches.extend(root.glob(pattern))
    return sorted(set(path for path in matches if path.is_file()))


def _age_filtered(paths: list[Path], max_age_hours: float) -> list[Path]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    filtered = []
    for path in paths:
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if mtime <= cutoff:
            filtered.append(path)
    return filtered


def _size(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        try:
            total += path.stat().st_size
        except OSError:
            pass
    return total


def _fmt_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GiB"


def collect_candidates(data_dir: Path, include_verify: bool, verify_max_age_hours: float) -> list[Path]:
    candidates: list[Path] = []
    for dirname in ("calibrated_buffer", "process"):
        candidates.extend(_iter_matches(data_dir / dirname, SOLVER_PATTERNS))

    if include_verify:
        verify_files = []
        verify_dir = data_dir / "verify_buffer"
        if verify_dir.exists():
            verify_files = sorted(path for path in verify_dir.iterdir() if path.is_file())
        candidates.extend(_age_filtered(verify_files, verify_max_age_hours))

    return sorted(set(candidates))


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean transient SeeVar postflight remnants.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="SeeVar data directory")
    parser.add_argument("--include-verify", action="store_true", help="also clean old verify_buffer files")
    parser.add_argument("--verify-max-age-hours", type=float, default=24.0, help="minimum verify file age to clean")
    parser.add_argument("--apply", action="store_true", help="delete the listed files")
    args = parser.parse_args()

    data_dir = args.data_dir.expanduser().resolve()
    candidates = collect_candidates(data_dir, args.include_verify, args.verify_max_age_hours)

    print(f"Data dir : {data_dir}")
    print(f"Mode     : {'APPLY' if args.apply else 'DRY RUN'}")
    print(f"Files    : {len(candidates)}")
    print(f"Size     : {_fmt_size(_size(candidates))}")

    for path in candidates:
        print(path)

    if not args.apply:
        print("\nDry run only. Add --apply to delete these files.")
        return 0

    removed = 0
    for path in candidates:
        try:
            path.unlink()
            removed += 1
        except OSError as exc:
            print(f"FAILED {path}: {exc}")

    print(f"\nRemoved {removed}/{len(candidates)} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
