#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/utils/gps_monitor.py
Version: 1.5.0
Objective: Continuous native GPSD socket monitor with full resource safety,
           atomic writes, SIGTERM handling, Null Island guard, and --once mode.

Canonical location: Filename: core/utils/gps_monitor.py
Replaces:          core/preflight/gps_monitor.py (stale v1.3.0 duplicate — retire with git rm)

Changes vs 1.4.1:
  - FIXED: PROJECT_ROOT now derived from __file__ (was hardcoded /home/ed/seevar)
  - ADDED: atomic write — write to .tmp then os.replace() to avoid torn reads
  - ADDED: SIGTERM handler — clean shutdown on systemd stop / kill signal
  - ADDED: Null Island guard — lat==0.0 and lon==0.0 rejected as invalid fix
  - ADDED: --once flag — single-shot mode for preflight/oneshot callers (no daemon loop)
  - RETAINED: socket timeout (30 s), context-manager socket close
  - RETAINED: logging throughout (no bare print())
  - RETAINED: seevar namespace (no seestar_organizer references)
"""

import argparse
import json
import logging
import os
import signal
import socket
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Project root — dynamic so the file can be deployed without path surgery
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.env_loader import ENV_STATUS          # noqa: E402
from core.utils.observer_math import get_maidenhead_6char  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("GPSMonitor")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GPSD_HOST     = "127.0.0.1"
GPSD_PORT     = 2947
LOOP_INTERVAL = 60          # seconds between daemon polls
SOCKET_TIMEOUT = 30.0       # seconds to wait for a TPV reply

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
_shutdown_requested = False


def _handle_sigterm(signum, frame):
    global _shutdown_requested
    log.info("Shutdown signal received — stopping GPS monitor.")
    _shutdown_requested = True


signal.signal(signal.SIGTERM, _handle_sigterm)
signal.signal(signal.SIGINT,  _handle_sigterm)


# ---------------------------------------------------------------------------
# Core update function
# ---------------------------------------------------------------------------
def update_status() -> bool:
    """
    Connect to gpsd, wait for a 3-D fix, and atomically update ENV_STATUS.

    Returns:
        True  — valid fix written to ENV_STATUS
        False — no fix obtained (timeout, connection failure, Null Island, etc.)
    """
    status: dict = {"profile": "FIELD", "gps_status": "WAITING"}
    if ENV_STATUS.exists():
        try:
            with open(ENV_STATUS, "r") as fh:
                status.update(json.load(fh))
        except (json.JSONDecodeError, OSError) as exc:
            log.debug("Could not read existing ENV_STATUS: %s", exc)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(SOCKET_TIMEOUT)
            sock.connect((GPSD_HOST, GPSD_PORT))
            sock.sendall(b'?WATCH={"enable":true,"json":true}\n')

            with sock.makefile("r") as fobj:
                for line in fobj:
                    try:
                        report = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if report.get("class") != "TPV":
                        continue
                    if report.get("mode", 0) < 3:
                        continue

                    lat = round(report.get("lat", 0.0), 5)
                    lon = round(report.get("lon", 0.0), 5)

                    # Null Island guard
                    if lat == 0.0 and lon == 0.0:
                        log.debug("Null Island fix rejected (0.0, 0.0) — waiting for real fix.")
                        continue

                    status["gps_status"] = "FIXED"
                    status["lat"]         = lat
                    status["lon"]         = lon
                    status["maidenhead"]  = get_maidenhead_6char(lat, lon)
                    status["last_update"] = time.time()

                    # Atomic write
                    tmp_path = Path(str(ENV_STATUS) + ".tmp")
                    try:
                        with open(tmp_path, "w") as fh:
                            json.dump(status, fh)
                        os.replace(tmp_path, ENV_STATUS)
                    except OSError as exc:
                        log.error("Atomic write failed: %s", exc)
                        tmp_path.unlink(missing_ok=True)
                        return False

                    log.info("Fix acquired: %s  (%.5f, %.5f)", status["maidenhead"], lat, lon)
                    return True

    except socket.timeout:
        log.warning("Socket read timed out after %.0f s — no TPV received.", SOCKET_TIMEOUT)
    except ConnectionRefusedError:
        log.error("gpsd is not running or unreachable on %s:%s.", GPSD_HOST, GPSD_PORT)
    except OSError as exc:
        log.error("GPS monitor socket error: %s", exc)

    return False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="SeeVar GPS monitor — writes fix data to ENV_STATUS RAM file."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help=(
            "Single-shot mode: attempt one fix, write result, then exit. "
            "Used by preflight and oneshot systemd units. "
            "Without --once the monitor runs as a continuous daemon."
        ),
    )
    args = parser.parse_args()

    if args.once:
        log.info("gps_monitor --once: single-shot preflight mode.")
        success = update_status()
        sys.exit(0 if success else 1)

    log.info("Starting continuous GPS monitoring daemon (interval=%ds).", LOOP_INTERVAL)
    while not _shutdown_requested:
        update_status()
        for _ in range(LOOP_INTERVAL):
            if _shutdown_requested:
                break
            time.sleep(1)

    log.info("GPS monitor stopped.")


if __name__ == "__main__":
    main()
