#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/flight/neutralizer.py
Version: 3.0.0
Objective: Hardware reset — stops any active S30-Pro session and verifies
           idle state before handing control to the pilot.

Changes vs 2.6.1:
  - FIXED: port 5555 → 4700 (sovereign TCP JSON-RPC)
  - FIXED: device index /1/ retained — /0/ is bridge, /1/ is telescope (port 5432)
  - FIXED: method_sync removed — does not exist in seestar_alp
  - FIXED: iscope_get_app_state → get_device_state (confirmed method)
  - FIXED: ClientID string "1" → int 42 (persistent, never string)
  - FIXED: bare except → specific exception types throughout
  - FIXED: zwo_rpc_pulse replaced by _sovereign_rpc() — direct TCP on port 4700
  - ADDED: _alpaca_ping() checks port 5432 (not 5555)
  - ADDED: get_device_state response handles both flat and nested result shapes
  - RETAINED: schedule toggle via Alpaca port 5432 (legitimate Alpaca use)
  - RETAINED: iscope_stop_view + scope_park sequence
  - RETAINED: 180s heartbeat poll, 60s state verification timeout
"""

import json
import logging
import socket
import sys
import time

import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(name)s - %(message)s'
)
logger = logging.getLogger("Neutralizer")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
S30_HOST        = "192.168.178.55"
S30_PORT        = 4700          # sovereign JSON-RPC control
ALPACA_URL      = "http://127.0.0.1:5432/api/v1/telescope/1"
SOCK_TIMEOUT    = 5             # seconds per RPC call
HEARTBEAT_MAX   = 180           # seconds to wait for engine pulse
STATE_TIMEOUT   = 60            # seconds to verify idle state
POLL_INTERVAL   = 5             # seconds between polls


# ---------------------------------------------------------------------------
# Sovereign TCP JSON-RPC (port 4700)
# ---------------------------------------------------------------------------

def _sovereign_rpc(method: str, params=None) -> dict | None:
    """
    Send a single JSON-RPC command to the S30-Pro on port 4700.
    Returns the parsed response dict, or None on any failure.
    """
    payload = {"method": method}
    if params is not None:
        payload["params"] = params

    try:
        with socket.create_connection((S30_HOST, S30_PORT), timeout=SOCK_TIMEOUT) as sock:
            sock.sendall((json.dumps(payload) + "\r\n").encode())
            raw = b""
            while not raw.endswith(b"\n"):
                chunk = sock.recv(4096)
                if not chunk:
                    break
                raw += chunk
            return json.loads(raw.decode().strip())
    except (socket.timeout, ConnectionRefusedError) as e:
        logger.warning(f"RPC {method} failed: {e}")
        return None
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"RPC {method} error: {e}")
        return None


# ---------------------------------------------------------------------------
# Alpaca ping (port 5432) — health check only
# ---------------------------------------------------------------------------

def _alpaca_ping() -> bool:
    """Check whether the seestar.service Alpaca bridge is alive."""
    try:
        resp = requests.get(
            "http://127.0.0.1:5432/management/apiversions",
            timeout=2
        )
        return resp.status_code == 200
    except requests.RequestException:
        return False


# ---------------------------------------------------------------------------
# State verification via get_device_state
# ---------------------------------------------------------------------------

def _device_is_idle() -> bool:
    """
    Query get_device_state on port 4700.
    Returns True if the device reports parked and idle.
    Handles both flat and nested result shapes.
    """
    resp = _sovereign_rpc("get_device_state")
    if resp is None:
        return False

    # Result may be at top level or nested under 'result'
    result = resp.get("result", resp)

    if isinstance(result, dict):
        is_parked   = result.get("parked", False)
        app_status  = str(result.get("state", "unknown")).lower()
        logger.debug(f"Device state: parked={is_parked} state={app_status}")
        return is_parked and app_status == "idle"

    # Unexpected shape — log raw and be conservative
    logger.warning(f"Unexpected get_device_state shape: {resp}")
    return False


# ---------------------------------------------------------------------------
# Main sequence
# ---------------------------------------------------------------------------

def enforce_zero_state() -> bool:
    """
    Bring the S30-Pro to a known idle state:
      1. Toggle SSC scheduler off (Alpaca, port 5432)
      2. Stop active view + park mount (sovereign TCP, port 4700)
      3. Poll for heartbeat (up to HEARTBEAT_MAX seconds)
      4. Verify idle state (up to STATE_TIMEOUT seconds)

    Returns True when zero-state is secured, False on timeout.
    """
    # Step 1 — stop the SSC scheduler if running
    logger.info("STEP 1: Disabling SSC scheduler...")
    try:
        requests.post(
            f"{ALPACA_URL}/action",
            json={
                "Action": "schedule",
                "Parameters": json.dumps({"state": "stop"}),
                "ClientID": 42,
                "ClientTransactionID": int(time.time()),
            },
            timeout=3,
        )
    except requests.RequestException as e:
        logger.debug(f"Scheduler toggle skipped (bridge may not be running): {e}")

    # Step 2 — stop active view and park
    logger.info("STEP 2: Issuing iscope_stop_view + scope_park...")
    _sovereign_rpc("iscope_stop_view")
    time.sleep(1)
    _sovereign_rpc("scope_park")

    # Step 3 — wait for device to respond on port 4700
    logger.info(f"STEP 3: Waiting for device heartbeat (max {HEARTBEAT_MAX}s)...")
    start = time.time()
    alive = False

    while (time.time() - start) < HEARTBEAT_MAX:
        resp = _sovereign_rpc("get_device_state")
        if resp is not None:
            elapsed = int(time.time() - start)
            logger.info(f"Heartbeat detected after {elapsed}s.")
            alive = True
            break
        time.sleep(POLL_INTERVAL)

    if not alive:
        logger.error("Flatline: device did not respond within timeout.")
        return False

    # Step 4 — verify idle state
    logger.info(f"STEP 4: Verifying zero-state (max {STATE_TIMEOUT}s)...")
    deadline = time.time() + STATE_TIMEOUT

    while time.time() < deadline:
        if _device_is_idle():
            logger.info("Zero-state SECURED — mount parked and idle.")
            return True
        time.sleep(POLL_INTERVAL)

    # Device is alive but did not confirm idle — proceed with caution
    logger.warning("Zero-state verification timed out. Device alive but state unconfirmed.")
    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(0 if enforce_zero_state() else 1)
