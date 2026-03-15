#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/dark_library.py
Version: 1.0.0
Objective: Post-session dark frame acquisition via firmware start_create_dark.
           Polls port 4700 event stream for DarkLibrary completion.
           Firmware owns filter engagement, capture and master stacking.
           Stores confirmation records in data/dark_library/index.json only —
           no numpy arrays, no port 4801 involvement.
"""

import json
import logging
import socket
import time
from pathlib import Path
from typing import Optional

import sys
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.env_loader import DATA_DIR
from core.flight.pilot import (
    ControlSocket, TelemetryBlock,
    SEESTAR_HOST, GAIN, CTRL_PORT,
)

logger = logging.getLogger("seevar.dark_library")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DARK_LIBRARY_DIR  = DATA_DIR / "dark_library"
TEMP_BIN_SIZE     = 5      # °C bin width
TEMP_BIN_TOLS     = 10     # ±°C fallback tolerance
# Timeout: firmware captures and stacks its own dark frames internally.
# No N_DARK_FRAMES constant here — firmware decides how many it needs.
# Ceiling: 5 minutes is generous for any exposure time.
DARK_TIMEOUT_S    = 300    # seconds — poll ceiling for DarkLibrary complete
DARK_POLL_SLEEP_S = 1      # seconds between event poll attempts
# seestar_alp _try_dark_frame: sleep 1s between stop_view and start_create_dark
DARK_PRE_SLEEP_S  = 1


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

def _temp_bin(temp_c: float) -> int:
    """Round temperature to nearest TEMP_BIN_SIZE °C bin."""
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
        except Exception as e:
            logger.warning("dark_library: index load failed: %s", e)
    return {}


def _save_index(index: dict) -> None:
    try:
        _index_path().parent.mkdir(parents=True, exist_ok=True)
        _index_path().write_text(json.dumps(index, indent=2))
    except Exception as e:
        logger.error("dark_library: index save failed: %s", e)


# ---------------------------------------------------------------------------
# Event stream poller
# ---------------------------------------------------------------------------

def _poll_dark_complete(ctrl: ControlSocket, timeout_s: float) -> bool:
    """Poll port 4700 event stream for DarkLibrary state complete or fail.

    The firmware sends unsolicited JSON events on the control socket:
        {"Event": "DarkLibrary", "state": "complete"}
        {"Event": "DarkLibrary", "state": "fail"}

    Mirrors seestar_alp wait_end_op("DarkLibrary") — seestar_device.py:2342:
        while event_state["DarkLibrary"]["state"] not in ("complete", "fail"):
            time.sleep(1)

    Returns True on complete, False on fail or timeout.
    """
    deadline = time.monotonic() + timeout_s
    logger.info("_poll_dark_complete: polling for DarkLibrary event (timeout=%ds)", timeout_s)

    while time.monotonic() < deadline:
        response = ctrl.recv_response()
        if response is None:
            time.sleep(DARK_POLL_SLEEP_S)
            continue

        # Unsolicited firmware event — seestar_device.py:393
        # event_name = parsed_data["Event"]
        # event_state[event_name] = parsed_data
        event = response.get("Event", "")
        state = response.get("state", "")

        if event == "DarkLibrary":
            if state == "complete":
                logger.info("_poll_dark_complete: DarkLibrary complete")
                return True
            elif state == "fail":
                logger.error("_poll_dark_complete: DarkLibrary failed")
                return False
            else:
                logger.debug("_poll_dark_complete: DarkLibrary state=%s — continuing", state)

        time.sleep(DARK_POLL_SLEEP_S)

    logger.error("_poll_dark_complete: timeout after %ds", timeout_s)
    return False


# ---------------------------------------------------------------------------
# DarkLibrary
# ---------------------------------------------------------------------------

class DarkLibrary:
    """
    Post-session dark frame manager — firmware-delegated.

    The S30-Pro has a built-in dark field filter. start_create_dark engages
    it automatically — no lens cap, no filter wheel command needed.
    The firmware captures and median-stacks its own dark master internally.
    It applies the master automatically during subsequent stacking sessions.

    Our role:
      1. Trigger start_create_dark with correct exp_ms after science session.
      2. Poll for DarkLibrary complete event on port 4700.
      3. Record confirmation in index.json for session auditing.
      4. is_dark_current() lets preflight warn if no dark exists for tonight's
         parameters — never a hard veto, always a logged advisory.

    Acquisition sequence (confirmed from seestar_alp _try_dark_frame):
      S1. iscope_stop_view
      S2. sleep(1)                    ← autofocus state side-effect guard
      S3. set_setting exp_ms          ← match tonight's science exposure
      S4. start_create_dark           ← firmware owns all dark acquisition
      S5. set_control_value gain      ← set immediately after, per alp source
      S6. poll event stream           ← wait for DarkLibrary complete|fail
      S7. iscope_stop_view stage=Stack
      S8. sleep(1)
    """

    def __init__(self, host: str = SEESTAR_HOST):
        self.host   = host
        self._index = _load_index()
        DARK_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Acquisition                                                          #
    # ------------------------------------------------------------------ #

    def acquire_darks(
        self,
        sequences: list,
        telemetry: Optional[TelemetryBlock] = None,
    ) -> dict:
        """Trigger firmware dark acquisition for each (exp_ms, gain) pair.

        Args:
            sequences: list of (exp_ms: int, gain: int) tuples — tonight's
                       unique science exposure parameters.
            telemetry: TelemetryBlock from last get_device_state. Used for
                       temp_bin keying. None = temp_bin 0 (flagged).

        Returns:
            dict mapping key → {"status": "ok"|"failed", "event": str}
        """
        temp_c = (telemetry.temp_c
                  if telemetry and telemetry.temp_c is not None
                  else None)
        if temp_c is None:
            logger.warning("acquire_darks: no temp_c — using bin 0 (unconfirmed)")
            temp_c = 0.0

        tb = _temp_bin(temp_c)
        logger.info("acquire_darks: temp_c=%.1f°C → temp_bin=%+d°C", temp_c, tb)

        results = {}

        for exp_ms, gain in sequences:
            key = _key(tb, exp_ms, gain)
            logger.info("acquire_darks: starting firmware dark for %s", key)

            status = self._run_dark_sequence(exp_ms, gain)
            results[key] = status

            if status["status"] == "ok":
                self._index[key] = {
                    "temp_bin":      tb,
                    "exp_ms":        exp_ms,
                    "gain":          gain,
                    "timestamp":     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "temp_c_actual": round(temp_c, 1),
                    "source":        "firmware_start_create_dark",
                }
                _save_index(self._index)
                logger.info("acquire_darks: confirmed and indexed %s", key)
            else:
                logger.error("acquire_darks: failed for %s: %s",
                             key, status.get("event", "unknown"))

        return results

    def _run_dark_sequence(self, exp_ms: int, gain: int) -> dict:
        """Execute S1-S8 dark acquisition sequence on sovereign TCP.

        Returns {"status": "ok"|"failed", "event": str}
        """
        ctrl = ControlSocket(host=self.host)
        if not ctrl.connect():
            return {"status": "failed", "event": "control_socket_connect_failed"}

        try:
            # S1 — clear any active session
            logger.info("[dark S1] iscope_stop_view")
            ctrl.send("iscope_stop_view")

            # S2 — sleep: autofocus state side-effect guard (per alp source)
            logger.info("[dark S2] sleep %ds", DARK_PRE_SLEEP_S)
            time.sleep(DARK_PRE_SLEEP_S)

            # S3 — set exposure to match science frames
            logger.info("[dark S3] set_setting exp_ms=%d", exp_ms)
            ctrl.send("set_setting", {"exp_ms": {"stack_l": exp_ms}})

            # S4 — trigger firmware dark acquisition
            logger.info("[dark S4] start_create_dark")
            resp = ctrl.send_and_recv("start_create_dark")
            if resp and "error" in resp:
                logger.error("[dark S4] start_create_dark error: %s", resp)
                return {"status": "failed", "event": f"start_create_dark_error: {resp}"}

            # S5 — set gain immediately after (per alp _try_dark_frame)
            logger.info("[dark S5] set_control_value gain=%d", gain)
            ctrl.send("set_control_value", ["gain", gain])

            # S6 — poll event stream for DarkLibrary complete
            logger.info("[dark S6] polling for DarkLibrary complete...")
            completed = _poll_dark_complete(ctrl, DARK_TIMEOUT_S)
            if not completed:
                return {"status": "failed", "event": "DarkLibrary_timeout_or_fail"}

            # S7 — stop stack (per alp _try_dark_frame post-dark cleanup)
            logger.info("[dark S7] iscope_stop_view stage=Stack")
            ctrl.send("iscope_stop_view", {"stage": "Stack"})

            # S8 — settle
            time.sleep(DARK_PRE_SLEEP_S)

            return {"status": "ok", "event": "DarkLibrary_complete"}

        except Exception as e:
            logger.error("_run_dark_sequence: exception: %s", e)
            return {"status": "failed", "event": str(e)}
        finally:
            ctrl.disconnect()

    # ------------------------------------------------------------------ #
    # Advisory lookup — never a hard veto                                  #
    # ------------------------------------------------------------------ #

    def is_dark_current(
        self,
        temp_c: float,
        exp_ms: int,
        gain:   int,
    ) -> tuple:
        """Check if a valid dark exists for given parameters.

        Returns (found: bool, message: str).
        Nearest bin ±TEMP_BIN_TOLS°C fallback — same tolerance as original design.
        Advisory only — caller logs warning, never vetoes science acquisition.
        """
        tb = _temp_bin(temp_c)
        key = _key(tb, exp_ms, gain)

        # Exact match
        if key in self._index:
            entry = self._index[key]
            return True, f"dark confirmed: {key} ({entry['timestamp']})"

        # Nearest bin fallback
        candidates = []
        for k, entry in self._index.items():
            if entry["exp_ms"] == exp_ms and entry["gain"] == gain:
                delta = abs(entry["temp_bin"] - tb)
                if delta <= TEMP_BIN_TOLS:
                    candidates.append((delta, k, entry))

        if candidates:
            candidates.sort(key=lambda x: x[0])
            delta, k, entry = candidates[0]
            return True, (f"dark fallback: {k} (Δ{delta}°C, {entry['timestamp']})")

        return False, (
            f"no dark for exp_ms={exp_ms} gain={gain} "
            f"temp_bin={tb:+d}°C (±{TEMP_BIN_TOLS}°C) — "
            f"science frame will be uncalibrated"
        )


# SeeVar-v5-M4-DarkLibrary
if __name__ == "__main__":
    pass
