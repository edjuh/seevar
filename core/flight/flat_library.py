#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/flat_library.py
Version: 1.0.0
Objective: Capture normalized master flat assets for a scope/filter pair and
mark whether they are ready for science use.
"""

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

from core.utils.env_loader import load_config, selected_scope, selected_scope_host
from core.flight.pilot import AlpacaCamera, AlpacaFilterWheel, TelemetryBlock, ALPACA_PORT
from core.flight.dark_library import DarkLibrary
from core.postflight.calibration_assets import (
    FLAT_LIBRARY_DIR,
    best_bias_asset,
    ensure_calibration_dirs,
    upsert_calibration_asset,
)

logger = logging.getLogger("seevar.flat_library")

N_FLAT_FRAMES = 9
FLAT_SETTLE_S = 1.0


def _load_master(path: str | Path) -> np.ndarray:
    with fits.open(path) as hdul:
        return hdul[0].data.astype(np.float32)


class FlatLibrary:
    def __init__(self, host: str | None = None, port: int = ALPACA_PORT):
        cfg = load_config()
        self._scope = selected_scope(cfg)
        self.host = host or str(self._scope.get("host") or self._scope.get("ip") or selected_scope_host(cfg)[0])
        self.port = port
        self._dark_library = DarkLibrary(host=self.host, port=port)
        ensure_calibration_dirs()
        FLAT_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

    def acquire_flats(
        self,
        exp_ms: int,
        gain: int,
        telemetry: Optional[TelemetryBlock] = None,
        n_frames: int = N_FLAT_FRAMES,
        filter_name: str = "TG",
        filter_position: int | None = None,
    ) -> dict:
        temp_c = telemetry.temp_c if telemetry and telemetry.temp_c is not None else None
        camera = AlpacaCamera(self.host, self.port)
        filterwheel = AlpacaFilterWheel(self.host, self.port)
        frames = []

        try:
            camera.connect()
            filterwheel.connect()
            if filter_position is not None:
                filterwheel.set_position(int(filter_position))
                time.sleep(FLAT_SETTLE_S)
            camera.set_gain(int(gain))

            exp_sec = max(0.001, float(exp_ms) / 1000.0)
            for idx in range(max(1, int(n_frames))):
                camera.start_exposure(exp_sec, light=True)
                if not camera.wait_for_image(exp_sec, timeout=exp_sec + 5.0):
                    logger.warning("Flat frame %d/%d timed out", idx + 1, n_frames)
                    continue
                frame = camera.download_image().astype(np.float32)
                frames.append(frame)
                logger.info("Flat frame %d/%d downloaded (%s)", idx + 1, n_frames, frame.shape)
        except Exception as e:
            logger.error("Flat acquisition failed: %s", e)
            return {"status": "failed", "error": str(e), "n_frames": len(frames)}
        finally:
            try:
                camera.disconnect()
                filterwheel.disconnect()
            except Exception:
                pass

        if not frames:
            return {"status": "failed", "error": "no_frames", "n_frames": 0}

        preprocess = "raw"
        dark_key = None
        bias_key = None
        if temp_c is not None:
            dark_ok, dark_entry, _ = self._dark_library.best_dark(float(temp_c), int(exp_ms), int(gain))
            if dark_ok and dark_entry:
                dark_data = _load_master(dark_entry["master_path"])
                frames = [np.clip(frame - dark_data, 0.0, None) for frame in frames]
                dark_key = dark_entry.get("key") or Path(dark_entry["master_path"]).stem
                preprocess = "dark_subtracted"

        if preprocess == "raw":
            bias_entry = best_bias_asset(int(gain))
            if bias_entry:
                bias_data = _load_master(bias_entry["master_path"])
                frames = [np.clip(frame - bias_data, 0.0, None) for frame in frames]
                bias_key = bias_entry.get("key") or Path(bias_entry["master_path"]).stem
                preprocess = "bias_subtracted"

        master = np.median(np.stack(frames, axis=0), axis=0).astype(np.float32)
        positive = master[master > 0.0]
        norm = float(np.median(positive)) if positive.size else 0.0
        if norm <= 0.0:
            return {"status": "failed", "error": "flat_normalization_failed", "n_frames": len(frames)}

        master /= norm
        master = np.clip(master, 0.1, 5.0).astype(np.float32)

        filter_token = str(filter_name or "TG").strip().upper()
        scope_id = self._scope.get("scope_id") or "scope"
        key = f"flat_{scope_id}_{filter_token}"
        out_path = FLAT_LIBRARY_DIR / f"{key}_master.fits"

        hdr = fits.Header()
        hdr["IMAGETYP"] = "MASTER FLAT"
        hdr["EXPMS"] = int(exp_ms)
        hdr["EXPTIME"] = float(exp_ms) / 1000.0
        hdr["GAIN"] = int(gain)
        hdr["FILTER"] = filter_token
        hdr["NFRAMES"] = len(frames)
        hdr["FLATNORM"] = round(norm, 3)
        hdr["FLATREADY"] = preprocess in {"dark_subtracted", "bias_subtracted"}
        hdr["FLATPREP"] = preprocess
        if dark_key:
            hdr["DARKKEY"] = str(dark_key)[:68]
        if bias_key:
            hdr["BIASKEY"] = str(bias_key)[:68]
        if temp_c is not None:
            hdr["TEMPCACT"] = round(float(temp_c), 1)
        if self._scope.get("scope_id"):
            hdr["SCOPEID"] = str(self._scope["scope_id"])[:68]
        if self._scope.get("scope_name"):
            hdr["SCOPENAM"] = str(self._scope["scope_name"])[:68]
        if self._scope.get("ip"):
            hdr["SCOPEIP"] = str(self._scope["ip"])[:68]
        hdr["DATE"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

        fits.PrimaryHDU(data=master, header=hdr).writeto(out_path, overwrite=True)

        entry = {
            "filter": filter_token,
            "gain": int(gain),
            "exp_ms": int(exp_ms),
            "n_frames": len(frames),
            "master_path": str(out_path),
            "scope_id": self._scope.get("scope_id"),
            "scope_name": self._scope.get("scope_name"),
            "scope_ip": self._scope.get("ip"),
            "flat_ready": preprocess in {"dark_subtracted", "bias_subtracted"},
            "preprocess": preprocess,
            "dark_key": dark_key,
            "bias_key": bias_key,
            "source": "alpaca_flat_panel",
        }
        upsert_calibration_asset("flat", key, entry)
        return {"status": "ok", "master_path": str(out_path), "n_frames": len(frames), "key": key, "flat_ready": entry["flat_ready"]}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    import argparse

    parser = argparse.ArgumentParser(description="Capture a master flat for the active scope.")
    parser.add_argument("--exp-ms", type=int, required=True)
    parser.add_argument("--gain", type=int, default=80)
    parser.add_argument("--frames", type=int, default=N_FLAT_FRAMES)
    parser.add_argument("--filter", default="TG")
    parser.add_argument("--filter-position", type=int)
    args = parser.parse_args()

    lib = FlatLibrary()
    result = lib.acquire_flats(
        exp_ms=args.exp_ms,
        gain=args.gain,
        n_frames=args.frames,
        filter_name=args.filter,
        filter_position=args.filter_position,
    )
    print(result)
