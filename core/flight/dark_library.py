#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/dark_library.py
Version: 2.1.0
Objective: Post-session dark frame acquisition via Alpaca REST.
           Captures downloadable dark frames, combines them into a master dark,
           and stores reusable calibration assets for postflight subtraction.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from astropy.io import fits

import sys
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.env_loader import DATA_DIR
from core.flight.pilot import (
    AlpacaCamera, AlpacaFilterWheel, TelemetryBlock,
    SEESTAR_HOST, ALPACA_PORT, GAIN, EXPOSE_TIMEOUT,
)

logger = logging.getLogger("seevar.dark_library")

DARK_LIBRARY_DIR = DATA_DIR / "dark_library"
TEMP_BIN_SIZE = 5
TEMP_BIN_TOLS = 10
N_DARK_FRAMES = 5
DARK_SETTLE_S = 2


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
        self.host = host
        self.port = port
        self._index = _load_index()
        DARK_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

    def acquire_darks(self, sequences: list, telemetry: Optional[TelemetryBlock] = None) -> dict:
        """
        Acquire master darks for each (exp_ms, gain) pair.
        Each set is downloaded, median-combined, written to disk, and indexed.
        """
        temp_c = telemetry.temp_c if telemetry and telemetry.temp_c is not None else 0.0
        if temp_c == 0.0:
            logger.warning("acquire_darks: no temp_c — using bin 0")

        tb = _temp_bin(temp_c)
        logger.info("acquire_darks: temp=%.1fC -> bin=%+dC", temp_c, tb)

        results = {}
        camera = AlpacaCamera(self.host, self.port)
        fw = AlpacaFilterWheel(self.host, self.port)

        try:
            camera.connect()
            fw.connect()

            logger.info("Setting filter to Dark (position 0)...")
            fw.set_position(AlpacaFilterWheel.DARK)
            time.sleep(DARK_SETTLE_S)

            for exp_ms, gain in sequences:
                key = _key(tb, exp_ms, gain)
                logger.info("Acquiring dark: %s", key)

                status = self._capture_dark_set(camera, exp_ms, gain, tb, temp_c)
                results[key] = status

                if status["status"] == "ok":
                    self._index[key] = {
                        "temp_bin": tb,
                        "exp_ms": exp_ms,
                        "gain": gain,
                        "n_frames": status["n_frames"],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "temp_c_actual": round(temp_c, 1),
                        "source": "alpaca_dark_filter",
                        "master_path": status["master_path"],
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

    def _capture_dark_set(self, camera: AlpacaCamera, exp_ms: int, gain: int, temp_bin: int, temp_c: float) -> dict:
        """Capture N dark frames, download them, median-combine into a master dark."""
        exp_sec = exp_ms / 1000.0
        frames = []

        try:
            camera.set_gain(gain)
        except Exception as e:
            logger.warning("Dark gain set: %s", e)

        for i in range(N_DARK_FRAMES):
            try:
                camera.start_exposure(exp_sec, light=False)
                if camera.wait_for_image(exp_sec, timeout=exp_sec + EXPOSE_TIMEOUT):
                    img = camera.download_image()
                    frames.append(img.astype(np.float32))
                    logger.info("  Dark frame %d/%d downloaded (%s)", i + 1, N_DARK_FRAMES, img.shape)
                else:
                    logger.error("  Dark frame %d/%d timeout", i + 1, N_DARK_FRAMES)
            except Exception as e:
                logger.error("  Dark frame %d/%d error: %s", i + 1, N_DARK_FRAMES, e)

        if not frames:
            return {"status": "failed", "n_frames": 0}

        master = np.median(np.stack(frames, axis=0), axis=0).astype(np.float32)
        key = _key(temp_bin, exp_ms, gain)
        out_path = DARK_LIBRARY_DIR / f"{key}_master.fits"

        hdr = fits.Header()
        hdr["IMAGETYP"] = "MASTER DARK"
        hdr["EXPTIME"] = exp_sec
        hdr["EXPMS"] = int(exp_ms)
        hdr["GAIN"] = int(gain)
        hdr["TEMPBIN"] = int(temp_bin)
        hdr["TEMPCACT"] = round(float(temp_c), 1)
        hdr["NFRAMES"] = len(frames)
        hdr["SOURCE"] = "SeeVar dark_library"
        hdr["DATE"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

        fits.PrimaryHDU(data=master, header=hdr).writeto(out_path, overwrite=True)

        return {
            "status": "ok",
            "n_frames": len(frames),
            "master_path": str(out_path),
        }

    def best_dark(self, temp_c: float, exp_ms: int, gain: int) -> tuple[bool, Optional[dict], str]:
        """
        Resolve the best available master dark.
        Returns (ok, entry, message).
        """
        tb = _temp_bin(temp_c)
        key = _key(tb, exp_ms, gain)

        if key in self._index:
            entry = self._index[key]
            master_path = Path(entry.get("master_path", ""))
            if master_path.exists():
                return True, entry, f"dark confirmed: {key}"

        candidates = []
        for k, entry in self._index.items():
            if entry.get("exp_ms") == exp_ms and entry.get("gain") == gain:
                master_path = Path(entry.get("master_path", ""))
                if not master_path.exists():
                    continue
                delta = abs(int(entry.get("temp_bin", 0)) - tb)
                if delta <= TEMP_BIN_TOLS:
                    candidates.append((delta, entry))

        if candidates:
            candidates.sort(key=lambda x: x[0])
            delta, entry = candidates[0]
            return True, entry, f"dark fallback: delta {delta}C"

        return False, None, f"no dark for exp_ms={exp_ms} gain={gain} temp_bin={tb:+d}C"

    def is_dark_current(self, temp_c: float, exp_ms: int, gain: int) -> tuple:
        ok, entry, msg = self.best_dark(temp_c, exp_ms, gain)
        return ok, msg


if __name__ == "__main__":
    pass
