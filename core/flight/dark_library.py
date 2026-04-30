#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/dark_library.py
Version: 2.2.0
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

from core.utils.env_loader import DATA_DIR, load_config, selected_scope, selected_scope_host
from core.flight.pilot import (
    AlpacaCamera, AlpacaFilterWheel, TelemetryBlock,
    ALPACA_PORT, EXPOSE_TIMEOUT,
)
from core.postflight.calibration_assets import (
    DARK_LIBRARY_DIR,
    ensure_calibration_dirs,
    upsert_calibration_asset,
)

logger = logging.getLogger("seevar.dark_library")

# Tighter temperature matching for more defensible dark current behavior.
TEMP_BIN_SIZE = 2
TEMP_BIN_TOLS = 4

N_DARK_FRAMES = 5
DARK_SETTLE_S = 2


# Convert a camera temperature to SeeVar's rounded dark-library bin.
def _temp_bin(temp_c: float) -> int:
    return int(round(temp_c / TEMP_BIN_SIZE) * TEMP_BIN_SIZE)


# Build the canonical dark-library key from temperature, exposure, and gain.
def _key(temp_bin: int, exp_ms: int, gain: int) -> str:
    return f"dark_tb{temp_bin:+d}_e{exp_ms}_g{gain}"


# Return the JSON index path for the reusable dark library.
def _index_path() -> Path:
    return DARK_LIBRARY_DIR / "index.json"


# Load the dark-library index, tolerating missing or damaged index files.
def _load_index() -> dict:
    p = _index_path()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


# Persist the dark-library index after adding or replacing a master dark.
def _save_index(index: dict) -> None:
    try:
        _index_path().parent.mkdir(parents=True, exist_ok=True)
        _index_path().write_text(json.dumps(index, indent=2))
    except Exception as e:
        logger.error("dark_library: index save failed: %s", e)


# Normalize telescope model names so equivalent S30-Pro units can share darks.
def _normalized_model(value: object) -> str:
    return str(value or "").strip().lower().replace(" ", "")


# Read the configured maximum dark/science temperature-bin mismatch.
def dark_temp_tolerance_c(cfg: dict | None = None) -> float:
    cfg = cfg if isinstance(cfg, dict) else load_config()
    value = cfg.get("calibration", {}).get("dark_temp_tolerance_c", TEMP_BIN_TOLS)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(TEMP_BIN_TOLS)


class DarkLibrary:
    """Fleet-shared dark acquisition via Alpaca, gated by model/temperature/exposure/gain."""

    # Select the active scope and load reusable dark-library metadata.
    def __init__(self, host: str | None = None, port: int = ALPACA_PORT):
        cfg = load_config()
        self._scope = selected_scope(cfg)
        self._temp_tolerance_c = dark_temp_tolerance_c(cfg)
        self.host = host or str(self._scope.get("host") or self._scope.get("ip") or selected_scope_host(cfg)[0])
        self.port = port
        self._index = _load_index()
        ensure_calibration_dirs()
        DARK_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

    # Reload the on-disk index so another process can add calibration assets.
    def _refresh_index(self):
        self._index = _load_index()

    # Capture master darks for the requested exposure/gain pairs at live temperature.
    def acquire_darks(self, sequences: list, telemetry: Optional[TelemetryBlock] = None) -> dict:
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
                    self._refresh_index()
                    self._index[key] = {
                        "temp_bin": tb,
                        "exp_ms": exp_ms,
                        "gain": gain,
                        "n_frames": status["n_frames"],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "temp_c_actual": round(temp_c, 1),
                        "source": "alpaca_dark_filter",
                        "master_path": status["master_path"],
                        "scope_id": self._scope.get("scope_id"),
                        "scope_name": self._scope.get("scope_name"),
                        "scope_model": self._scope.get("model"),
                        "scope_ip": self._scope.get("ip"),
                        "sharing_policy": "fleet_shared_model_and_temperature_gated",
                    }
                    _save_index(self._index)
                    upsert_calibration_asset("dark", key, self._index[key])

        except Exception as e:
            logger.error("acquire_darks: %s", e)
        finally:
            try:
                camera.disconnect()
                fw.disconnect()
            except Exception:
                pass

        return results

    # Capture one master dark from multiple camera dark exposures.
    def _capture_dark_set(self, camera: AlpacaCamera, exp_ms: int, gain: int, temp_bin: int, temp_c: float) -> dict:
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
        hdr["FILTER"] = "DARK"
        if self._scope.get("scope_id"):
            hdr["SCOPEID"] = str(self._scope["scope_id"])[:68]
        if self._scope.get("scope_name"):
            hdr["SCOPENAM"] = str(self._scope["scope_name"])[:68]
        if self._scope.get("model"):
            hdr["SCOPEMOD"] = str(self._scope["model"])[:68]
        if self._scope.get("ip"):
            hdr["SCOPEIP"] = str(self._scope["ip"])[:68]
        hdr["SHAREPOL"] = "MODEL_TEMP_GATE"
        hdr["DATE"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

        fits.PrimaryHDU(data=master, header=hdr).writeto(out_path, overwrite=True)

        return {
            "status": "ok",
            "n_frames": len(frames),
            "master_path": str(out_path),
        }

    # Check whether an indexed dark is compatible with the currently selected scope model.
    def _model_compatible(self, entry: dict) -> bool:
        active_model = _normalized_model(self._scope.get("model"))
        entry_model = _normalized_model(entry.get("scope_model"))
        return not active_model or not entry_model or active_model == entry_model

    # Find the best reusable dark for a science frame by exposure, gain, model, and temperature.
    def best_dark(self, temp_c: float, exp_ms: int, gain: int) -> tuple[bool, Optional[dict], str]:
        self._refresh_index()

        tb = _temp_bin(temp_c)
        key = _key(tb, exp_ms, gain)

        if key in self._index:
            entry = self._index[key]
            master_path = Path(entry.get("master_path", ""))
            if master_path.exists() and self._model_compatible(entry):
                return True, entry, f"dark confirmed: {key}"

        candidates = []
        for _, entry in self._index.items():
            if entry.get("exp_ms") == exp_ms and entry.get("gain") == gain:
                master_path = Path(entry.get("master_path", ""))
                if not master_path.exists():
                    continue
                if not self._model_compatible(entry):
                    continue
                delta = abs(int(entry.get("temp_bin", 0)) - tb)
                if delta <= self._temp_tolerance_c:
                    candidates.append((delta, entry))

        if candidates:
            candidates.sort(key=lambda x: x[0])
            delta, entry = candidates[0]
            return True, entry, f"dark fallback: delta {delta}C"

        return False, None, f"no dark for exp_ms={exp_ms} gain={gain} temp_bin={tb:+d}C"

    # Report whether a matching dark exists for preflight/postflight gating.
    def is_dark_current(self, temp_c: float, exp_ms: int, gain: int) -> tuple:
        ok, entry, msg = self.best_dark(temp_c, exp_ms, gain)
        return ok, msg


if __name__ == "__main__":
    pass
