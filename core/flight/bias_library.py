#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/bias_library.py
Version: 1.0.0
Objective: Capture short dark-filter frames as reusable master bias assets.
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
from core.postflight.calibration_assets import BIAS_LIBRARY_DIR, ensure_calibration_dirs, upsert_calibration_asset

logger = logging.getLogger("seevar.bias_library")

N_BIAS_FRAMES = 9
BIAS_EXPOSURE_MS = 1
BIAS_SETTLE_S = 1.0


class BiasLibrary:
    def __init__(self, host: str | None = None, port: int = ALPACA_PORT):
        cfg = load_config()
        self._scope = selected_scope(cfg)
        self.host = host or str(self._scope.get("host") or self._scope.get("ip") or selected_scope_host(cfg)[0])
        self.port = port
        ensure_calibration_dirs()
        BIAS_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

    def acquire_bias(self, gain: int, telemetry: Optional[TelemetryBlock] = None, n_frames: int = N_BIAS_FRAMES) -> dict:
        temp_c = telemetry.temp_c if telemetry and telemetry.temp_c is not None else None
        camera = AlpacaCamera(self.host, self.port)
        filterwheel = AlpacaFilterWheel(self.host, self.port)
        frames = []

        try:
            camera.connect()
            filterwheel.connect()
            filterwheel.set_position(AlpacaFilterWheel.DARK)
            time.sleep(BIAS_SETTLE_S)
            camera.set_gain(int(gain))

            exp_sec = max(0.001, float(BIAS_EXPOSURE_MS) / 1000.0)
            for idx in range(max(1, int(n_frames))):
                camera.start_exposure(exp_sec, light=False)
                if not camera.wait_for_image(exp_sec, timeout=5.0):
                    logger.warning("Bias frame %d/%d timed out", idx + 1, n_frames)
                    continue
                frame = camera.download_image().astype(np.float32)
                frames.append(frame)
                logger.info("Bias frame %d/%d downloaded (%s)", idx + 1, n_frames, frame.shape)
        except Exception as e:
            logger.error("Bias acquisition failed: %s", e)
            return {"status": "failed", "error": str(e), "n_frames": len(frames)}
        finally:
            try:
                camera.disconnect()
                filterwheel.disconnect()
            except Exception:
                pass

        if not frames:
            return {"status": "failed", "error": "no_frames", "n_frames": 0}

        master = np.median(np.stack(frames, axis=0), axis=0).astype(np.float32)
        key = f"bias_g{int(gain)}"
        out_path = BIAS_LIBRARY_DIR / f"{key}_master.fits"

        hdr = fits.Header()
        hdr["IMAGETYP"] = "MASTER BIAS"
        hdr["EXPMS"] = int(BIAS_EXPOSURE_MS)
        hdr["EXPTIME"] = float(BIAS_EXPOSURE_MS) / 1000.0
        hdr["GAIN"] = int(gain)
        hdr["NFRAMES"] = len(frames)
        hdr["SOURCE"] = "SeeVar bias_library"
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
            "gain": int(gain),
            "exp_ms": int(BIAS_EXPOSURE_MS),
            "n_frames": len(frames),
            "master_path": str(out_path),
            "scope_id": self._scope.get("scope_id"),
            "scope_name": self._scope.get("scope_name"),
            "scope_ip": self._scope.get("ip"),
            "source": "alpaca_bias_dark_filter",
        }
        upsert_calibration_asset("bias", key, entry)
        return {"status": "ok", "master_path": str(out_path), "n_frames": len(frames), "key": key}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    import argparse

    parser = argparse.ArgumentParser(description="Capture a master bias for the active scope.")
    parser.add_argument("--gain", type=int, default=80)
    parser.add_argument("--frames", type=int, default=N_BIAS_FRAMES)
    args = parser.parse_args()

    lib = BiasLibrary()
    result = lib.acquire_bias(gain=args.gain, n_frames=args.frames)
    print(result)
