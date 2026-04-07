#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/schedule_compiler.py
Version: 1.1.1
Objective: Translates canonical tonights_plan.json into a native SSC JSON payload while preserving planner ordering and metadata.
"""

import json
import uuid
import sys
import logging
from pathlib import Path

try:
    import tomllib
except ImportError:
    import toml as tomllib

from astropy.coordinates import SkyCoord
import astropy.units as u

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger("Compiler")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.toml"
DATA_DIR = PROJECT_ROOT / "data"
TONIGHTS_PLAN = DATA_DIR / "tonights_plan.json"
OUTPUT_PAYLOAD = DATA_DIR / "ssc_payload.json"


def convert_to_seestar_coords(ra_deg, dec_deg):
    coord = SkyCoord(ra=float(ra_deg) * u.deg, dec=float(dec_deg) * u.deg, frame="icrs")
    ra_str = coord.ra.to_string(unit=u.hour, sep=("h", "m", "s"), precision=1, pad=True)
    dec_str = coord.dec.to_string(sep=("d", "m", "s"), precision=1, alwayssign=True, pad=True)
    return ra_str, dec_str


def _load_config():
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def _select_exp_time(planner_cfg):
    mount_mode = planner_cfg.get("mount_mode", "ALT/AZ").upper()
    dithering = bool(planner_cfg.get("dithering", False))

    logger.info("Compiling for Intended State: %s | Dithering: %s", mount_mode, dithering)

    if mount_mode == "ALT/AZ":
        return mount_mode, dithering, 60
    if mount_mode == "EQ" and not dithering:
        return mount_mode, dithering, 300
    if mount_mode == "EQ" and dithering:
        return mount_mode, dithering, 60
    return mount_mode, dithering, 60


def _load_plan():
    if not TONIGHTS_PLAN.exists():
        logger.error("%s not found.", TONIGHTS_PLAN.name)
        sys.exit(1)

    with open(TONIGHTS_PLAN, "r") as f:
        plan = json.load(f)

    targets = plan.get("targets", []) if isinstance(plan, dict) else plan
    metadata = plan.get("metadata", {}) if isinstance(plan, dict) else {}
    objective = plan.get("#objective") if isinstance(plan, dict) else None
    return objective, metadata, targets


def _sorted_targets(targets):
    if not targets:
        return []

    if any("recommended_order" in t for t in targets):
        ordered = sorted(
            targets,
            key=lambda t: (
                int(t.get("recommended_order", 999999)),
                -float(t.get("efficiency_score", 0.0)),
                t.get("name", ""),
            ),
        )
        logger.info("Using recommended_order from nightly planner.")
        return ordered

    logger.info("No recommended_order present; preserving existing plan order.")
    return list(targets)


def _build_startup_item(mount_mode):
    return {
        "action": "start_up_sequence",
        "params": {
            "auto_focus": True,
            "dark_frames": True,
            "3ppa": (mount_mode == "EQ"),
        },
        "schedule_item_id": str(uuid.uuid4()),
    }


def _build_target_item(target, exp_time):
    ra_str, dec_str = convert_to_seestar_coords(target["ra"], target["dec"])
    duration = int(round(float(target.get("integration_sec") or target.get("duration") or 600)))
    frame_exp = int(round(float(target.get("exp_ms", exp_time * 1000)) / 1000.0))
    frame_exp = max(1, frame_exp)
    name = target.get("name", target.get("target_name", "unnamed"))

    compiler_notes = {
        "recommended_order": target.get("recommended_order"),
        "best_start_utc": target.get("best_start_utc"),
        "best_end_utc": target.get("best_end_utc"),
        "window_minutes": target.get("window_minutes"),
        "min_clearance_deg": target.get("min_clearance_deg"),
        "max_alt_deg": target.get("max_alt_deg"),
        "efficiency_score": target.get("efficiency_score"),
        "estimated_slew_cost_deg": target.get("estimated_slew_cost_deg"),
        "exp_ms": target.get("exp_ms"),
        "n_frames": target.get("n_frames"),
        "integration_sec": target.get("integration_sec"),
        "planner_mag": target.get("planner_mag"),
        "planner_bright_mag": target.get("planner_bright_mag"),
        "exposure_note": target.get("exposure_note"),
    }

    return {
        "action": "start_mosaic",
        "params": {
            "target_name": name,
            "is_j2000": True,
            "ra": ra_str,
            "dec": dec_str,
            "is_use_lp_filter": False,
            "panel_time_sec": duration,
            "ra_num": 1,
            "dec_num": 1,
            "panel_overlap_percent": 0,
            "selected_panels": "1",
            "gain": 80,
            "exp_time": frame_exp,
            "is_use_autofocus": True,
            "num_tries": 3,
            "retry_wait_s": 15,
        },
        "compiler_notes": compiler_notes,
        "source_target": {
            "name": name,
            "ra_deg": float(target["ra"]),
            "dec_deg": float(target["dec"]),
        },
        "schedule_item_id": str(uuid.uuid4()),
    }


def compile_schedule():
    cfg = _load_config()
    planner_cfg = cfg.get("planner", {})
    mount_mode, dithering, exp_time = _select_exp_time(planner_cfg)

    plan_objective, plan_metadata, targets = _load_plan()
    targets = _sorted_targets(targets)

    if not targets:
        logger.warning("No targets in plan. Aborting compilation.")
        return

    payload = {
        "#objective": "Compiled native SSC JSON payload for Seestar execution.",
        "version": 1.1,
        "Event": "Scheduler",
        "schedule_id": str(uuid.uuid4()),
        "state": "stopped",
        "source_plan": {
            "objective": plan_objective,
            "metadata": plan_metadata,
            "target_count": len(targets),
        },
        "compiler_settings": {
            "mount_mode": mount_mode,
            "dithering": dithering,
            "exp_time": exp_time,
        },
        "list": [],
    }

    payload["list"].append(_build_startup_item(mount_mode))

    for target in targets:
        payload["list"].append(_build_target_item(target, exp_time))

    payload["list"].append({
        "action": "scope_park",
        "params": {},
        "schedule_item_id": str(uuid.uuid4()),
    })
    payload["list"].append({
        "action": "shutdown",
        "params": {},
        "schedule_item_id": str(uuid.uuid4()),
    })

    with open(OUTPUT_PAYLOAD, "w") as f:
        json.dump(payload, f, indent=4)

    logger.info("Compilation Complete. Generated %d targets into %s", len(targets), OUTPUT_PAYLOAD.name)

    preview = targets[:10]
    if preview:
        logger.info("First compiled targets:")
        for t in preview:
            logger.info(
                "  #%s %s | score=%s | window=%s",
                t.get("recommended_order", "-"),
                t.get("name", t.get("target_name", "unnamed")),
                t.get("efficiency_score", "-"),
                t.get("window_minutes", "-"),
            )


if __name__ == "__main__":
    compile_schedule()
