#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/postflight/report_pipeline.py
Objective: Stage postflight reports, mirror them to the NAS, and optionally
           submit the AAVSO report without manual operator steering.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.postflight.aavso_submitter import AAVSOWebObsSubmitter
from core.utils.env_loader import DATA_DIR, load_config

log = logging.getLogger("PostflightReports")

REPORT_DIR = DATA_DIR / "reports"
DEFAULT_MIRROR_DIR = Path("/mnt/astronas/reports")


# Locate the newest accountant summary for this completed postflight run.
def latest_summary(report_dir: Path = REPORT_DIR) -> Path:
    candidates = sorted(report_dir.glob("postflight_summary_*.json"))
    if not candidates:
        raise FileNotFoundError(f"No postflight summary JSON found in {report_dir}")
    return candidates[-1]


# Keep an accepted WebObs upload tied to one accountant summary.
def submit_marker_path(summary_path: Path) -> Path:
    return summary_path.with_name(f"{summary_path.stem}.aavso_submit.json")


# Read the marker and return True only for already accepted submissions.
def already_accepted(summary_path: Path) -> bool:
    marker = submit_marker_path(summary_path)
    if not marker.exists():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        return bool((payload.get("aavso_submit") or {}).get("accepted"))
    except Exception:
        return False


# Read the marker and return a previous WebObs submission attempt if present.
def previous_submission(summary_path: Path) -> dict[str, Any] | None:
    marker = submit_marker_path(summary_path)
    if not marker.exists():
        return None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        submit = payload.get("aavso_submit") or {}
        if submit.get("submitted_utc") or submit.get("accepted") is not None:
            return payload
    except Exception:
        return None
    return None


# Decide whether automatic WebObs submission is enabled for this install.
def auto_submit_enabled(cfg: dict[str, Any], override: bool | None) -> bool:
    if override is not None:
        return bool(override)

    aavso_cfg = cfg.get("aavso", {}) if isinstance(cfg, dict) else {}
    explicit = aavso_cfg.get("auto_submit")
    if explicit is not None:
        return bool(explicit)

    cookie = (
        str(aavso_cfg.get("webobs_session_cookie", "")).strip()
        or str(aavso_cfg.get("webobs_token", "")).strip()
    )
    return bool(cookie)


# Pull the generated AAVSO Extended report out of the staged report set.
def aavso_report_from_outputs(outputs: list[Path]) -> Path | None:
    candidates = [
        path for path in outputs
        if path.name.startswith("AAVSO_") and path.suffix.lower() == ".txt"
    ]
    return candidates[-1] if candidates else None


# Write a durable marker with enough context to audit postflight publication.
def write_marker(summary_path: Path, payload: dict[str, Any]) -> Path:
    marker = submit_marker_path(summary_path)
    marker.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return marker


# Run the complete publication path: stage, mirror, and optionally submit.
def run_postflight_report_pipeline(
    summary_path: Path | None = None,
    *,
    submit_aavso: bool | None = None,
    mirror_dir: Path | None = DEFAULT_MIRROR_DIR,
) -> dict[str, Any]:
    from dev.tools.reports.stage_reports_from_summary import _mirror_outputs, stage_reports

    cfg = load_config()
    postflight_cfg = cfg.get("postflight", {}) if isinstance(cfg, dict) else {}
    if postflight_cfg.get("auto_stage_reports") is False:
        return {
            "checked_utc": datetime.now(timezone.utc).isoformat(),
            "staged": False,
            "skipped": "postflight.auto_stage_reports=false",
        }

    summary = Path(summary_path).expanduser().resolve() if summary_path else latest_summary()
    previous = previous_submission(summary)
    if previous is not None:
        submit = previous.get("aavso_submit") or {}
        reason = "already_accepted" if submit.get("accepted") else "already_attempted"
        return {
            "checked_utc": datetime.now(timezone.utc).isoformat(),
            "summary_path": str(summary),
            "staged": False,
            "aavso_submit": {"skipped": reason},
            "aavso_submit_marker": str(submit_marker_path(summary)),
        }

    configured_mirror = postflight_cfg.get("report_mirror_dir")
    effective_mirror = Path(configured_mirror).expanduser() if configured_mirror else mirror_dir

    outputs = stage_reports(summary)
    mirrored = _mirror_outputs(outputs, effective_mirror)
    aavso_report = aavso_report_from_outputs(outputs)

    result: dict[str, Any] = {
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "summary_path": str(summary),
        "staged": True,
        "outputs": [str(path) for path in outputs],
        "mirrored": [str(path) for path in mirrored],
        "aavso_report": str(aavso_report) if aavso_report else None,
        "auto_submit_enabled": auto_submit_enabled(cfg, submit_aavso),
    }

    if not result["auto_submit_enabled"]:
        result["aavso_submit"] = {"skipped": "auto_submit_disabled_or_no_cookie"}
        write_marker(summary, result)
        return result

    if aavso_report is None:
        result["aavso_submit"] = {"accepted": False, "error": "No AAVSO report staged"}
        write_marker(summary, result)
        return result

    try:
        submission = AAVSOWebObsSubmitter().submit(aavso_report)
    except Exception as exc:
        submission = {"accepted": False, "error": str(exc)}

    result["aavso_submit"] = submission
    marker = write_marker(summary, result)
    result["aavso_submit_marker"] = str(marker)
    return result
