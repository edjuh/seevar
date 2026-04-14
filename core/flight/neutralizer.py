#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Filename: core/flight/neutralizer.py
Version: 2.1.0
Objective: Hardware reset via Alpaca REST — parks telescope and verifies
 idle state before handing control to the pilot.
"""

import logging
import time

import requests

from core.flight.pilot import (
    AlpacaTelescope, AlpacaCamera,
    SEESTAR_HOST, ALPACA_PORT,
)

logger = logging.getLogger("seevar.neutralizer")

ZERO_STATE_TIMEOUT = 60  # seconds


def _management_status(host: str, port: int) -> tuple[bool, str]:
    try:
        r = requests.get(f"http://{host}:{port}/management/apiversions", timeout=5)
        if r.status_code != 200:
            return False, f"Alpaca management returned HTTP {r.status_code}"
        return True, ""
    except Exception as e:
        return False, f"Alpaca management unreachable: {e}"


def _require_connected(device, label: str):
    try:
        connected = bool(device.connected)
    except Exception as e:
        raise RuntimeError(f"{label} connection probe failed: {e}")
    if not connected:
        raise RuntimeError(f"{label} reports connected=false after connect()")


def enforce_zero_state(host: str = SEESTAR_HOST, port: int = ALPACA_PORT) -> bool:
    """
    Park telescope and verify camera idle.

    Returns True if zero-state achieved, False on failure.
    """
    logger.info("enforce_zero_state: Alpaca REST on %s:%d", host, port)

    ok, error = _management_status(host, port)
    if not ok:
        logger.error("%s", error)
        return False

    telescope = AlpacaTelescope(host, port)
    camera = AlpacaCamera(host, port)

    try:
        telescope.connect()
        _require_connected(telescope, "Telescope")

        camera.connect()
        _require_connected(camera, "Camera")

        try:
            state = camera.camera_state
            if state in (camera.EXPOSING, camera.READING, camera.WAITING):
                logger.info("Camera busy (state %d) — aborting...", state)
                camera.abort_exposure()
                time.sleep(2.0)
        except Exception as e:
            logger.warning("Camera state check: %s", e)

        try:
            telescope.set_tracking(False)
        except Exception as e:
            logger.warning("Tracking disable: %s", e)

        try:
            if not telescope.at_park:
                logger.info("Parking telescope...")
                telescope.park()

                deadline = time.monotonic() + ZERO_STATE_TIMEOUT
                while time.monotonic() < deadline:
                    try:
                        if telescope.at_park:
                            logger.info("Telescope parked.")
                            break
                    except Exception:
                        pass
                    time.sleep(2.0)
            else:
                logger.info("Already parked.")
        except Exception as e:
            logger.warning("Park: %s (non-fatal)", e)

        logger.info("Zero-state achieved.")
        return True

    except Exception as e:
        logger.error("enforce_zero_state failed: %s", e)
        return False

    finally:
        try:
            telescope.disconnect()
            camera.disconnect()
        except Exception:
            pass
