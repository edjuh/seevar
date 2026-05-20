#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/telescope/build_seestar_view_plan.py
Objective: Convert a SeeVar SSC payload into the Seestar app view_plan.json
           shape used on the telescope under ~/.ZWO/view_plan.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import astropy.units as u
from astropy.coordinates import FK5, SkyCoord
from astropy.time import Time


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PAYLOAD = PROJECT_ROOT / "data" / "ssc_payload.json"


def _load_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or not isinstance(payload.get("list"), list):
        raise ValueError(f"{path} is not an SSC payload")
    return payload


def _target_id(name: str, ra_hours: float, dec_deg: float) -> int:
    raw = f"{name}|{ra_hours:.7f}|{dec_deg:.7f}".encode("utf-8")
    return int(hashlib.sha1(raw).hexdigest()[:8], 16)


def _to_seestar_epoch(ra_deg: float, dec_deg: float, epoch: str) -> tuple[float, float]:
    if epoch == "j2000":
        return ra_deg / 15.0, dec_deg
    if epoch != "jnow":
        raise ValueError(f"unsupported coordinate epoch: {epoch}")

    coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")
    jnow = coord.transform_to(FK5(equinox=Time.now()))
    return float(jnow.ra.hour), float(jnow.dec.deg)


def _local_minute(value: str | None, timezone_name: str, fallback: int) -> int:
    if not value:
        return fallback
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    local = dt.astimezone(ZoneInfo(timezone_name))
    return local.hour * 60 + local.minute


def _build_target(
    item: dict[str, Any],
    timezone_name: str,
    fallback_start_min: int,
    coordinate_epoch: str,
) -> tuple[dict[str, Any], int]:
    params = item.get("params") or {}
    source = item.get("source_target") or {}
    notes = item.get("compiler_notes") or {}

    name = str(params.get("target_name") or source.get("name") or "SeeVar Target")
    ra_hours, dec_deg = _to_seestar_epoch(float(source["ra_deg"]), float(source["dec_deg"]), coordinate_epoch)
    duration_min = max(1, int(math.ceil(float(params.get("panel_time_sec", 60)) / 60.0)))
    window_start_min = _local_minute(notes.get("best_start_utc"), timezone_name, fallback_start_min)
    start_min = max(window_start_min, fallback_start_min)

    target = {
        "target_ra_dec": [round(ra_hours, 6), round(dec_deg, 6)],
        "target_name": name,
        "lp_filter": bool(params.get("is_use_lp_filter", False)),
        "state": "waiting",
        "lapse_ms": 0,
        "target_id": _target_id(name, ra_hours, dec_deg),
        "output_file": {"path": f"MyWorks/{name}", "files": []},
        "stack_total_sec": 0.0,
        "start_min": start_min,
        "duration_min": duration_min,
        "skip": False,
        "alias_name": name,
        "coordinate_epoch": coordinate_epoch.upper(),
    }
    return target, start_min + duration_min


def build_view_plan(payload_path: Path, timezone_name: str, plan_name: str, coordinate_epoch: str) -> dict[str, Any]:
    payload = _load_payload(payload_path)
    targets = []
    fallback_start_min = 0

    for item in payload["list"]:
        if item.get("action") != "start_mosaic":
            continue
        target, fallback_start_min = _build_target(item, timezone_name, fallback_start_min, coordinate_epoch)
        targets.append(target)

    return {
        "state": "waiting",
        "lapse_ms": 0,
        "plan": {
            "update_time_seestar": datetime.now(ZoneInfo(timezone_name)).strftime("%Y.%m.%d"),
            "plan_name": plan_name,
            "coordinate_epoch": coordinate_epoch.upper(),
            "list": targets,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, default=DEFAULT_PAYLOAD)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timezone", default="Europe/Amsterdam")
    parser.add_argument("--name", default="SeeVar")
    parser.add_argument(
        "--coordinate-epoch",
        choices=("jnow", "j2000"),
        default="jnow",
        help="Seestar app plans appear to operate in JNOW; keep jnow unless validating firmware behavior.",
    )
    args = parser.parse_args()

    plan = build_view_plan(args.payload.expanduser().resolve(), args.timezone, args.name, args.coordinate_epoch)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {args.output} ({len(plan['plan']['list'])} target(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
