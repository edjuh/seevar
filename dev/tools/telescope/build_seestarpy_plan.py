#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/telescope/build_seestarpy_plan.py
Version: 1.0.0
Objective: Convert SeeVar nightly or SSC payloads into seestarpy observation plans.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = PROJECT_ROOT / "data" / "tonights_plan.json"


# Function: _load_json
def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


# Function: _parse_plan_date
def _parse_plan_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


# Function: _parse_iso_dt
def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


# Function: _parse_clock_minute
def _parse_clock_minute(value: str) -> int:
    hour_text, minute_text = str(value).split(":", 1)
    return int(hour_text) * 60 + int(minute_text)


# Function: _target_id
def _target_id(name: str, ra_hours: float, dec_deg: float) -> int:
    raw = f"{name}|{ra_hours:.7f}|{dec_deg:.7f}".encode("utf-8")
    return 100_000_000 + (int(hashlib.sha1(raw).hexdigest()[:8], 16) % 900_000_000)


# Function: _duration_min
def _duration_min(target: dict[str, Any]) -> int:
    for key in ("duration_min", "block_minutes", "window_minutes"):
        if target.get(key) is not None:
            return max(1, int(math.ceil(float(target[key]))))
    for key in ("integration_sec", "duration", "panel_time_sec"):
        if target.get(key) is not None:
            return max(1, int(math.ceil(float(target[key]) / 60.0)))
    return 10


# Function: _start_min
def _start_min(target: dict[str, Any], timezone_name: str, plan_date: date, fallback: int) -> int:
    if target.get("start_min") is not None:
        return int(target["start_min"])
    if target.get("start_time"):
        return _parse_clock_minute(str(target["start_time"]))

    dt = _parse_iso_dt(target.get("best_start_utc"))
    if dt is None:
        return fallback

    local = dt.astimezone(ZoneInfo(timezone_name))
    day_offset = max(0, (local.date() - plan_date).days)
    return day_offset * 1440 + local.hour * 60 + local.minute


# Function: _plan_date
def _plan_date(targets: list[dict[str, Any]], timezone_name: str, explicit: str | None) -> date:
    parsed = _parse_plan_date(explicit)
    if parsed is not None:
        return parsed
    for target in targets:
        dt = _parse_iso_dt(target.get("best_start_utc"))
        if dt is not None:
            return dt.astimezone(ZoneInfo(timezone_name)).date()
    return datetime.now(ZoneInfo(timezone_name)).date()


# Function: _ra_hours_dec_deg
def _ra_hours_dec_deg(target: dict[str, Any]) -> tuple[float, float]:
    if target.get("ra_hours") is not None:
        return float(target["ra_hours"]), float(target["dec_deg"])
    if target.get("ra_deg") is not None:
        return float(target["ra_deg"]) / 15.0, float(target["dec_deg"])
    return float(target["ra"]) / 15.0, float(target["dec"])


# Function: _from_ssc_item
def _from_ssc_item(item: dict[str, Any]) -> dict[str, Any] | None:
    if item.get("action") != "start_mosaic":
        return None
    params = item.get("params") or {}
    source = item.get("source_target") or {}
    notes = item.get("compiler_notes") or {}
    name = str(params.get("target_name") or source.get("name") or "SeeVar Target")
    return {
        "name": name,
        "alias_name": source.get("alias_name") or name,
        "ra_deg": source.get("ra_deg"),
        "dec_deg": source.get("dec_deg"),
        "panel_time_sec": params.get("panel_time_sec"),
        "best_start_utc": notes.get("best_start_utc"),
        "lp_filter": bool(params.get("is_use_lp_filter", False)),
    }


# Function: _source_targets
def _source_targets(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("list"), list):
        items = [_from_ssc_item(item) for item in payload["list"]]
        return [item for item in items if item is not None]
    if isinstance(payload, dict):
        targets = payload.get("targets", payload.get("data", []))
    else:
        targets = payload
    if not isinstance(targets, list):
        raise ValueError("input does not contain a target list")
    return [dict(target) for target in targets]


# Function: _sorted_targets
def _sorted_targets(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if any("recommended_order" in target for target in targets):
        return sorted(targets, key=lambda target: int(target.get("recommended_order", 999999)))
    return targets


# Function: build_seestarpy_plan
def build_seestarpy_plan(
    input_path: Path,
    timezone_name: str,
    plan_name: str,
    plan_date: str | None = None,
    default_start: str = "21:00",
) -> dict[str, Any]:
    targets = _sorted_targets(_source_targets(_load_json(input_path)))
    local_plan_date = _plan_date(targets, timezone_name, plan_date)
    fallback_start = _parse_clock_minute(default_start)
    output_targets = []

    for target in targets:
        name = str(target.get("name") or target.get("target_name") or "SeeVar Target")
        ra_hours, dec_deg = _ra_hours_dec_deg(target)
        duration = _duration_min(target)
        start = _start_min(target, timezone_name, local_plan_date, fallback_start)
        fallback_start = start + duration
        output_targets.append(
            {
                "target_id": _target_id(name, ra_hours, dec_deg),
                "target_name": name,
                "alias_name": str(target.get("alias_name") or name),
                "target_ra_dec": [round(ra_hours % 24.0, 6), round(dec_deg, 6)],
                "lp_filter": bool(target.get("lp_filter", False)),
                "start_min": start,
                "duration_min": duration,
            }
        )

    return {
        "plan_name": plan_name,
        "update_time_seestar": local_plan_date.strftime("%Y.%m.%d"),
        "list": output_targets,
    }


# Function: submit_seestarpy_plan
def submit_seestarpy_plan(plan_payload: dict[str, Any]) -> None:
    from seestarpy import plan

    plan.set_view_plan(plan_payload)


# Function: main
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timezone", default="Europe/Amsterdam")
    parser.add_argument("--name", default="SeeVar")
    parser.add_argument("--plan-date", help="Local observing date, YYYY-MM-DD.")
    parser.add_argument("--default-start", default="21:00")
    parser.add_argument("--submit", action="store_true", help="Submit with seestarpy.plan.set_view_plan after writing.")
    args = parser.parse_args()

    payload = build_seestarpy_plan(
        args.input.expanduser().resolve(),
        args.timezone,
        args.name,
        args.plan_date,
        args.default_start,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if args.submit:
        submit_seestarpy_plan(payload)
    print(f"wrote {args.output} ({len(payload['list'])} target(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
