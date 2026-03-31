#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/dark_library.py
Version: 2.0.0
Objective: Post-session dark frame acquisition via Alpaca REST.
           Uses FilterWheel position 0 (Dark) + Camera StartExposure.
           Replaces TCP firmware start_create_dark with direct Alpaca control.
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

import sys
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.env_loader import DATA_DIR
from core.flight.pilot import (
    AlpacaCamera, AlpacaFilterWheel, TelemetryBlock,
    SEESTAR_HOST, ALPACA_PORT, GAIN, EXPOSE_TIMEOUT,
)

logger = logging.getLogger("seevar.dark_library")

DARK_LIBRARY_DIR  = DATA_DIR / "dark_library"
TEMP_BIN_SIZE     = 5
TEMP_BIN_TOLS     = 10
N_DARK_FRAMES     = 5       # Number of dark frames to capture per sequence
DARK_SETTLE_S     = 2       # Settle after filter change


def _temp_bin(temp_c: float) -> int:
    return int(round(temp_c / TEMP_BIN_SIZE) * TEMP_BIN_SIZE)

def _key(temp_bin: int, exp_ms: int, gain: int) -> str:
    return f"dark_tb{temp_bin:+d}_e{exp_ms}_g{gain}"

def _index_path() -> Path:
    return DARK_LIBRARY_DIR / "index.json"

def _load_index() -> dict:
    p = _index_path()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}

def _save_index(index: dict) -> None:
    try:
        _index_path().parent.mkdir(parents=True, exist_ok=True)
        _index_path().write_text(json.dumps(index, indent=2))
    except Exception as e:
        logger.error("dark_library: index save failed: %s", e)


class DarkLibrary:
    """Post-session dark frame acquisition via Alpaca FilterWheel + Camera."""

    def __init__(self, host: str = SEESTAR_HOST, port: int = ALPACA_PORT):
        self.host   = host
        self.port   = port
        self._index = _load_index()
        DARK_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

    def acquire_darks(self, sequences: list,
                      telemetry: Optional[TelemetryBlock] = None) -> dict:
        """Acquire dark frames for each (exp_ms, gain) pair."""
        temp_c = (telemetry.temp_c
                  if telemetry and telemetry.temp_c is not None
                  else 0.0)
        if temp_c == 0.0:
            logger.warning("acquire_darks: no temp_c — using bin 0")

        tb = _temp_bin(temp_c)
        logger.info("acquire_darks: temp=%.1f°C → bin=%+d°C", temp_c, tb)

        results = {}
        camera = AlpacaCamera(self.host, self.port)
        fw     = AlpacaFilterWheel(self.host, self.port)

        try:
            camera.connect()
            fw.connect()

            # Switch to Dark filter
            logger.info("Setting filter to Dark (position 0)...")
            fw.set_position(AlpacaFilterWheel.DARK)
            time.sleep(DARK_SETTLE_S)

            for exp_ms, gain in sequences:
                key = _key(tb, exp_ms, gain)
                logger.info("Acquiring dark: %s", key)

                status = self._capture_dark_set(camera, exp_ms, gain)
                results[key] = status

                if status["status"] == "ok":
                    self._index[key] = {
                        "temp_bin":      tb,
                        "exp_ms":        exp_ms,
                        "gain":          gain,
                        "n_frames":      status["n_frames"],
                        "timestamp":     time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                       time.gmtime()),
                        "temp_c_actual": round(temp_c, 1),
                        "source":        "alpaca_dark_filter",
                    }
                    _save_index(self._index)

        except Exception as e:
            logger.error("acquire_darks: %s", e)
        finally:
            try:
                camera.disconnect()
                fw.disconnect()
            except Exception:
                pass

        return results

    def _capture_dark_set(self, camera: AlpacaCamera,
                          exp_ms: int, gain: int) -> dict:
        """Capture N_DARK_FRAMES dark frames at given parameters."""
        exp_sec = exp_ms / 1000.0
        completed = 0

        try:
            camera.set_gain(gain)
        except Exception as e:
            logger.warning("Dark gain set: %s", e)

        for i in range(N_DARK_FRAMES):
            try:
                camera.start_exposure(exp_sec, light=False)  # dark = light=False
                if camera.wait_for_image(exp_sec, timeout=exp_sec + EXPOSE_TIMEOUT):
                    # We don't need to download — firmware stores internally
                    # But we confirm the exposure completed
                    completed += 1
                    logger.info("  Dark frame %d/%d complete", i + 1, N_DARK_FRAMES)
                else:
                    logger.error("  Dark frame %d/%d timeout", i + 1, N_DARK_FRAMES)
            except Exception as e:
                logger.error("  Dark frame %d/%d error: %s", i + 1, N_DARK_FRAMES, e)

        if completed > 0:
            return {"status": "ok", "n_frames": completed}
        return {"status": "failed", "n_frames": 0}

    def is_dark_current(self, temp_c: float, exp_ms: int, gain: int) -> tuple:
        """Check if a valid dark exists. Advisory only."""
        tb = _temp_bin(temp_c)
        key = _key(tb, exp_ms, gain)

        if key in self._index:
            entry = self._index[key]
            return True, f"dark confirmed: {key} ({entry['timestamp']})"

        candidates = []
        for k, entry in self._index.items():
            if entry["exp_ms"] == exp_ms and entry["gain"] == gain:
                delta = abs(entry["temp_bin"] - tb)
                if delta <= TEMP_BIN_TOLS:
                    candidates.append((delta, k, entry))

        if candidates:
            candidates.sort(key=lambda x: x[0])
            delta, k, entry = candidates[0]
            return True, f"dark fallback: {k} (delta {delta}°C)"

        return False, (f"no dark for exp_ms={exp_ms} gain={gain} "
                       f"temp_bin={tb:+d}°C")


if __name__ == "__main__":
    pass
