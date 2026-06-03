#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tests/tools/test_build_seestarpy_plan.py
Version: 1.0.0
Objective: Verify SeeVar plans convert into seestarpy observation-plan dictionaries.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from dev.tools.telescope import build_seestarpy_plan


# Function: _write_json
def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# Function: test_tonights_plan_converts_with_midnight_wrap
def test_tonights_plan_converts_with_midnight_wrap(tmp_path):
    plan_path = _write_json(
        tmp_path / "tonights_plan.json",
        {
            "targets": [
                {
                    "name": "ST Boo",
                    "ra": 224.44,
                    "dec": 40.73,
                    "integration_sec": 600,
                    "best_start_utc": "2026-05-25T19:00:00Z",
                    "recommended_order": 2,
                },
                {
                    "name": "TT Boo",
                    "ra": 224.60,
                    "dec": 40.90,
                    "integration_sec": 900,
                    "best_start_utc": "2026-05-25T22:30:00Z",
                    "recommended_order": 3,
                },
            ],
        },
    )

    output = build_seestarpy_plan.build_seestarpy_plan(
        plan_path,
        "Europe/Amsterdam",
        "SeeVar Test",
        plan_date="2026-05-25",
    )

    assert output["plan_name"] == "SeeVar Test"
    assert output["update_time_seestar"] == "2026.05.25"
    assert output["list"][0]["target_name"] == "ST Boo"
    assert output["list"][0]["target_ra_dec"] == [14.962667, 40.73]
    assert output["list"][0]["start_min"] == 1260
    assert output["list"][0]["duration_min"] == 10
    assert output["list"][1]["start_min"] == 1470
    assert output["list"][1]["duration_min"] == 15


# Function: test_ssc_payload_converts_start_mosaic_items_only
def test_ssc_payload_converts_start_mosaic_items_only(tmp_path):
    plan_path = _write_json(
        tmp_path / "ssc_payload.json",
        {
            "list": [
                {"action": "start_up_sequence", "params": {}},
                {
                    "action": "start_mosaic",
                    "params": {
                        "target_name": "M 51",
                        "panel_time_sec": 3600,
                        "is_use_lp_filter": True,
                    },
                    "compiler_notes": {"best_start_utc": "2026-05-25T20:15:00Z"},
                    "source_target": {"name": "M 51", "ra_deg": 202.4696, "dec_deg": 47.1952},
                },
                {"action": "scope_park", "params": {}},
            ],
        },
    )

    output = build_seestarpy_plan.build_seestarpy_plan(
        plan_path,
        "Europe/Amsterdam",
        "SSC Test",
        plan_date="2026-05-25",
    )

    assert len(output["list"]) == 1
    target = output["list"][0]
    assert target["target_name"] == "M 51"
    assert target["target_ra_dec"] == [13.497973, 47.1952]
    assert target["lp_filter"] is True
    assert target["start_min"] == 1335
    assert target["duration_min"] == 60
