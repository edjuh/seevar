#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/postflight/deferred_dark_runner.py
Version: 1.1.0
Objective: Reacquire queued dark sequences only when the current camera temperature
is thermally compatible with the queued science frames, then restore affected raws
and rerun postflight accounting.
"""

import json
import logging
import shutil
from pathlib import Path

import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.flight.dark_library import DarkLibrary, TEMP_BIN_SIZE, dark_temp_tolerance_c
from core.flight.pilot import AlpacaCamera, AlpacaTelescope, TelemetryBlock
from core.postflight.accountant import process_buffer


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("DeferredDarkRunner")

DATA_DIR = PROJECT_ROOT / "data"
MISSING_DARKS_FILE = DATA_DIR / "missing_darks.json"
ARCHIVE_DIR = DATA_DIR / "archive"
LOCAL_BUFFER = DATA_DIR / "local_buffer"


# Convert a live camera temperature to the rounded calibration-library bin.
def _temp_bin(temp_c: float) -> int:
    return int(round(temp_c / TEMP_BIN_SIZE) * TEMP_BIN_SIZE)


# Load and normalize queued dark requirements from the accountant sidecar file.
def load_requirements() -> list[dict]:
    if not MISSING_DARKS_FILE.exists():
        return []

    payload = json.loads(MISSING_DARKS_FILE.read_text())
    requirements = payload.get("requirements", [])
    if not isinstance(requirements, list):
        raise RuntimeError("missing_darks.json has invalid requirements payload")

    cleaned = []
    for req in requirements:
        if not isinstance(req, dict):
            continue
        exp_ms = req.get("exp_ms")
        gain = req.get("gain")
        if exp_ms in (None, "") or gain in (None, ""):
            continue
        cleaned.append(req)

    return cleaned


# Collapse per-target requirements into unique exposure/gain dark sequences.
def collect_sequences(requirements: list[dict]) -> list[tuple[int, int]]:
    seen = set()
    sequences = []
    for req in requirements:
        sequence = (int(req["exp_ms"]), int(req["gain"]))
        if sequence in seen:
            continue
        seen.add(sequence)
        sequences.append(sequence)
    return sequences


# Read current telescope/camera telemetry before deciding which darks are safe.
def read_live_telemetry() -> TelemetryBlock:
    telescope = AlpacaTelescope()
    camera = AlpacaCamera()
    connect_errors = []

    for device in (telescope, camera):
        try:
            device.connect()
        except Exception as exc:
            connect_errors.append(f"{device.base}: {exc}")

    telemetry = TelemetryBlock.from_alpaca(telescope, camera)

    for device in (camera, telescope):
        try:
            device.disconnect()
        except Exception:
            pass

    if connect_errors:
        raise RuntimeError("Alpaca connect failed: " + " | ".join(connect_errors))
    if telemetry.parse_error:
        raise RuntimeError(telemetry.parse_error)
    if telemetry.temp_c is None:
        raise RuntimeError("Live camera temperature unavailable; refusing to bin darks blindly")

    return telemetry


# Keep only queued darks whose required temperature bin matches current conditions.
def filter_thermally_compatible(requirements: list[dict], temp_c: float) -> tuple[list[dict], int, float]:
    current_bin = _temp_bin(temp_c)
    tolerance_c = dark_temp_tolerance_c()
    compatible = []

    for req in requirements:
        req_bin = req.get("temp_bin")
        if req_bin is None:
            compatible.append(req)
            continue
        if abs(int(req_bin) - current_bin) <= tolerance_c:
            compatible.append(req)

    return compatible, current_bin, tolerance_c


# Extract successfully acquired exposure/gain pairs from DarkLibrary results.
def _ok_sequences_from_results(dark_results: dict) -> set[tuple[int, int]]:
    ok_sequences = set()
    for key, result in dark_results.items():
        if not (isinstance(result, dict) and result.get("status") == "ok"):
            continue

        exp_ms = gain = None
        for part in str(key).split("_"):
            if part.startswith("e"):
                exp_ms = int(part[1:])
            elif part.startswith("g"):
                gain = int(part[1:])

        if exp_ms is not None and gain is not None:
            ok_sequences.add((exp_ms, gain))

    return ok_sequences


# Restore archived raw frames that now have matching darks for accountant replay.
def restore_capture_paths(requirements: list[dict], dark_results: dict) -> list[Path]:
    LOCAL_BUFFER.mkdir(parents=True, exist_ok=True)
    restored = []
    ok_sequences = _ok_sequences_from_results(dark_results)

    for req in requirements:
        sequence = (int(req["exp_ms"]), int(req["gain"]))
        if sequence not in ok_sequences:
            continue

        for name in req.get("capture_paths", []):
            src = ARCHIVE_DIR / name
            dst = LOCAL_BUFFER / name
            if not src.exists():
                log.warning("Missing archived capture for replay: %s", src)
                continue
            if dst.exists():
                log.info("Replay frame already staged: %s", dst.name)
                restored.append(dst)
                continue
            shutil.copy2(src, dst)
            restored.append(dst)
            log.info("Restored %s for reprocessing", dst.name)

    return restored


# Acquire queued darks, restore matching raws, and rerun postflight accounting.
def run_deferred_dark_recovery() -> int:
    requirements = load_requirements()
    if not requirements:
        log.info("No queued dark requirements found.")
        return 0

    telemetry = read_live_telemetry()
    log.info("Live telemetry for deferred darks: %s", telemetry.summary())

    compatible, current_bin, tolerance_c = filter_thermally_compatible(requirements, telemetry.temp_c)
    skipped = [req for req in requirements if req not in compatible]

    if skipped:
        for req in skipped:
            log.warning(
                "Skipping queued dark e%s g%s: required temp bin %+dC, current bin %+dC exceeds tolerance %.1fC",
                req.get("exp_ms"),
                req.get("gain"),
                int(req.get("temp_bin")),
                current_bin,
                tolerance_c,
            )

    if not compatible:
        log.info("No thermally compatible queued dark requirements at current temperature; nothing to replay.")
        return 0

    sequences = collect_sequences(compatible)
    log.info("Thermally compatible dark sequences: %s", sequences)

    library = DarkLibrary()
    dark_results = library.acquire_darks(sequences, telemetry=telemetry)

    for key, result in dark_results.items():
        log.info("Dark result %s -> %s", key, result)

    restored = restore_capture_paths(compatible, dark_results)
    if restored:
        log.info("Restored %d raw frame(s) for accountant replay.", len(restored))
        process_buffer()
    else:
        log.info("No archived raws restored; skipping accountant replay.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run_deferred_dark_recovery())
    except Exception as exc:
        log.error("Deferred dark recovery failed: %s", exc)
        raise SystemExit(1) from None
