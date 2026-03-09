#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seestar_organizer/core/flight/neutralizer.py
Version: 2.6.1
Objective: Optimized hardware reset (Neutralizer) locked to local Alpaca bridge.
"""

import requests
import json
import time
import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger("Neutralizer")

# FIXED: Reverted to strict local bridge
ALP_URL = "http://127.0.0.1:5555/api/v1/telescope/1/action"

def zwo_rpc_pulse(method, params=None):
    payload = {
        "Action": "method_sync",
        "Parameters": json.dumps({"method": method, **(params or {})}),
        "ClientID": "1",
        "ClientTransactionID": str(int(time.time()))
    }
    try:
        response = requests.put(ALP_URL, json=payload, timeout=3)
        return response.json().get("Value", {}).get("result", {})
    except:
        return None

def ping_engine():
    try:
        requests.get("http://127.0.0.1:5555/management/apiversions", timeout=2)
        return True
    except:
        return False

def enforce_zero_state():
    logger.info("🧠 STEP 1: Stopping all active tasks and commanding PARK...")
    try:
        requests.post("http://127.0.0.1:5432/1/schedule/state", data={"action": "toggle"}, timeout=3)
    except: pass
        
    zwo_rpc_pulse("iscope_stop_view")
    time.sleep(1)
    zwo_rpc_pulse("scope_park")

    logger.info("🔌 STEP 2: Waiting for engine pulse (Smart Poll)...")
    max_wait = 180
    start_time = time.time()
    is_alive = False
    
    while (time.time() - start_time) < max_wait:
        if ping_engine():
            logger.info(f"✅ Heartbeat detected after {int(time.time() - start_time)}s.")
            is_alive = True
            break
        time.sleep(5)
        
    if not is_alive:
        logger.error("❌ Flatline: The telescope did not respond within the timeout.")
        return False

    logger.info("📡 STEP 3: Verifying Zero-State (Parked & Idle)...")
    state_timeout = time.time() + 60
    while time.time() < state_timeout:
        state = zwo_rpc_pulse("iscope_get_app_state")
        if isinstance(state, dict):
            is_parked = state.get("parked", False)
            app_status = state.get("state", "unknown")
            if is_parked and app_status == "idle":
                logger.info("🟢 S30-PRO Zero-State SECURED. Mount is Parked and Idle.")
                return True
        time.sleep(5)
    
    logger.warning("⚠️ Zero-State verification timed out, but engine is alive.")
    return True

if __name__ == "__main__":
    if enforce_zero_state(): sys.exit(0)
    else: sys.exit(1)
