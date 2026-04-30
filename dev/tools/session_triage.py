#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/session_triage.py
Objective: Summarise the last SeeVar observing session from logs, ledger, plan,
           and data buffers without touching telescope state.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


STATUS_ORDER = {
    "OBSERVED": 0,
    "FAILED_QC": 1,
    "FAILED_QC_LOW_SNR": 2,
    "FAILED_SATURATED": 3,
    "FAILED_NO_WCS": 4,
    "FAILED_NO_DARK": 5,
    "CAPTURED_RAW": 6,
    "PENDING": 7,
}


@dataclass
class GroupSummary:
    name: str
    raw_frames: int = 0
    dark_failures: int = 0
    solve_failures: int = 0
    photometry_failures: list[str] = field(default_factory=list)
    ok_lines: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# Parse an ISO-ish timestamp into a timezone-aware UTC datetime.
def parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), timezone.utc)
    try:
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


# Load JSON safely and return a caller-provided default on failure.
def load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default


# Infer a useful session start from the current plan metadata or recent time.
def infer_since(root: Path, explicit: str | None) -> datetime:
    if explicit:
        parsed = parse_dt(explicit)
        if parsed:
            return parsed
        raise SystemExit(f"Could not parse --since value: {explicit}")

    plan = load_json(root / "data" / "tonights_plan.json", {})
    if isinstance(plan, dict):
        meta = plan.get("metadata", {})
        parsed = parse_dt(meta.get("planning_start_utc") or meta.get("generated"))
        if parsed:
            return parsed - timedelta(minutes=10)

    return datetime.now(timezone.utc) - timedelta(hours=18)


# Return the most relevant observation timestamp carried by a ledger entry.
def ledger_timestamp(entry: dict[str, Any]) -> datetime | None:
    for key in ("last_obs_utc", "last_capture_utc", "last_success"):
        parsed = parse_dt(entry.get(key))
        if parsed:
            return parsed
    return None


# Extract ledger rows updated during or after the requested session window.
def collect_ledger_rows(root: Path, since: datetime) -> list[tuple[datetime, str, dict[str, Any]]]:
    data = load_json(root / "data" / "ledger.json", {})
    entries = data.get("entries", data) if isinstance(data, dict) else {}
    rows: list[tuple[datetime, str, dict[str, Any]]] = []
    for name, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        ts = ledger_timestamp(entry)
        if ts and ts >= since:
            rows.append((ts, str(name), entry))
    return sorted(rows, key=lambda item: item[0])


# Read a text log into timestamped lines, keeping only lines after session start.
def read_log_since(path: Path, since: datetime) -> list[str]:
    if not path.exists():
        return []

    lines: list[str] = []
    current_year = datetime.now(timezone.utc).year
    for line in path.read_text(errors="replace").splitlines():
        timestamp = None
        match_full = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
        match_time = re.match(r"^(\d{2}:\d{2}:\d{2})", line)
        if match_full:
            timestamp = parse_dt(match_full.group(1).replace(" ", "T"))
        elif match_time:
            candidate = datetime.fromisoformat(f"{current_year}-{since.month:02d}-{since.day:02d}T{match_time.group(1)}")
            timestamp = candidate.replace(tzinfo=timezone.utc)
            if timestamp < since - timedelta(hours=3):
                timestamp += timedelta(days=1)

        if timestamp is None or timestamp >= since:
            lines.append(line)
    return lines


# Collapse accountant log lines into per-target postflight results.
def parse_accountant_groups(lines: list[str]) -> tuple[dict[str, GroupSummary], str | None]:
    groups: dict[str, GroupSummary] = {}
    current: GroupSummary | None = None
    audit_complete = None

    for line in lines:
        group_match = re.search(r"Processing group: (.+) \((\d+) raw frame", line)
        if group_match:
            name = group_match.group(1)
            current = groups.setdefault(name, GroupSummary(name=name))
            current.raw_frames += int(group_match.group(2))
            continue

        if "Audit complete." in line:
            audit_complete = line

        if current is None:
            continue

        if "dark calibration failed" in line:
            current.dark_failures += 1
        elif "solve failed" in line or "Plate solve failed" in line:
            current.solve_failures += 1
        elif "Photometry failed" in line:
            reason = line.split("Photometry failed", 1)[-1].strip(" :")
            current.photometry_failures.append(reason or line)
        elif re.search(r"\sOK\s", line):
            current.ok_lines.append(line)
        elif "has no dark-calibrated" in line or "failed QC" in line:
            current.notes.append(line)

    return groups, audit_complete


# Count files by target-ish prefix in a data directory after session start.
def count_files_since(directory: Path, since: datetime) -> Counter:
    counts: Counter = Counter()
    if not directory.exists():
        return counts
    for path in directory.iterdir():
        if not path.is_file():
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if mtime < since:
            continue
        stem = path.name
        target = stem.split("_scope", 1)[0].split("_20", 1)[0]
        counts[target.replace("_", " ")] += 1
    return counts


# Build a compact status line for one ledger row.
def format_ledger_row(ts: datetime, name: str, entry: dict[str, Any]) -> str:
    status = str(entry.get("status", "UNKNOWN"))
    mag = entry.get("last_mag")
    snr = entry.get("last_snr")
    mag_text = f" mag={mag}" if mag is not None else ""
    snr_text = f" snr={snr}" if snr is not None else ""
    return f"{ts.isoformat()}  {name:28} {status:15} attempts={entry.get('attempts', 0)}{mag_text}{snr_text}"


# Render the full human-readable triage report.
def build_report(root: Path, since: datetime, limit: int) -> str:
    rows = collect_ledger_rows(root, since)
    status_counts = Counter(str(entry.get("status", "UNKNOWN")) for _, _, entry in rows)

    accountant_lines = read_log_since(root / "logs" / "accountant.log", since)
    groups, audit_complete = parse_accountant_groups(accountant_lines)

    directory_counts = {
        "local_buffer": count_files_since(root / "data" / "local_buffer", since),
        "verify_buffer": count_files_since(root / "data" / "verify_buffer", since),
        "calibrated_buffer": count_files_since(root / "data" / "calibrated_buffer", since),
        "process": count_files_since(root / "data" / "process", since),
        "archive": count_files_since(root / "data" / "archive", since),
    }

    out: list[str] = []
    out.append("SeeVar Session Triage")
    out.append(f"root        : {root}")
    out.append(f"since UTC   : {since.isoformat()}")
    out.append("")

    out.append("Ledger outcome")
    if not rows:
        out.append("  no ledger entries changed in this window")
    else:
        for status, count in sorted(status_counts.items(), key=lambda item: (STATUS_ORDER.get(item[0], 99), item[0])):
            out.append(f"  {status:15} {count}")
        out.append("")
        for row in rows[-limit:]:
            out.append("  " + format_ledger_row(*row))

    out.append("")
    out.append("Postflight accountant")
    out.append(f"  {audit_complete or 'no audit completion line found'}")
    if groups:
        for name, group in sorted(groups.items(), key=lambda item: item[0])[-limit:]:
            failure_bits = []
            if group.dark_failures:
                failure_bits.append(f"dark_fail={group.dark_failures}")
            if group.solve_failures:
                failure_bits.append(f"solve_fail={group.solve_failures}")
            if group.photometry_failures:
                failure_bits.append(f"phot_fail={len(group.photometry_failures)}")
            if group.ok_lines:
                failure_bits.append(f"ok={len(group.ok_lines)}")
            status = ", ".join(failure_bits) if failure_bits else "no explicit failure"
            out.append(f"  {name:28} raw={group.raw_frames:<4} {status}")

    out.append("")
    out.append("Files changed since session start")
    for label, counts in directory_counts.items():
        total = sum(counts.values())
        top = ", ".join(f"{name}:{count}" for name, count in counts.most_common(5))
        out.append(f"  {label:17} {total:4}  {top or '-'}")

    out.append("")
    out.append("Next checks")
    if status_counts.get("FAILED_NO_DARK"):
        out.append("  - Build matching darks for the exposure/gain/temp combinations used by the plan.")
    if status_counts.get("FAILED_NO_WCS"):
        out.append("  - Inspect verify/science frames for those targets and tighten horizon/pointing gates.")
    if not (root / "logs" / "orchestrator.log").exists():
        out.append("  - Orchestrator log is missing; start through systemd after logging fix.")
    return "\n".join(out)


# Parse CLI arguments for the read-only triage command.
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarise the last SeeVar observing session.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2], help="SeeVar project root")
    parser.add_argument("--since", help="UTC/session start timestamp, e.g. 2026-04-29T21:50:00+00:00")
    parser.add_argument("--limit", type=int, default=30, help="Maximum rows per section")
    return parser.parse_args()


# Run the triage command and print the report.
def main() -> None:
    args = parse_args()
    root = args.root.expanduser().resolve()
    since = infer_since(root, args.since)
    print(build_report(root, since, max(1, args.limit)))


if __name__ == "__main__":
    main()
