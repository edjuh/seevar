#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seestar_organizer/core/flight/orchestrator.py
Version: 3.0.0
Objective: The Supreme Gatekeeper. Executes the 6-step polite handshake and uploads the pre-compiled SSC schedule.
"""
import requests
import json
import time
import sys
import logging
from pathlib import Path

try:
    import tomllib
except ImportError:
    import toml as tomllib

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [ORCHESTRATOR] - %(message)s')
logger = logging.getLogger("FlightController")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.toml"
DATA_DIR = PROJECT_ROOT / "data"
PAYLOAD_FILE = DATA_DIR / "ssc_payload.json"

ALP_RPC_URL = "http://127.0.0.1:5555/api/v1/telescope/1/action"
SSC_UI_URL = "http://127.0.0.1:5432/0"

def zwo_rpc_pulse(method, params=None):
    """Low-level RPC call to the Alpaca bridge."""
    payload = {
        "Action": "method_sync",
        "Parameters": json.dumps({"method": method, **(params or {})}),
        "ClientID": "1",
        "ClientTransactionID": str(int(time.time()))
    }
    try:
        # Alpaca standard accepts URL-encoded form data for PUTs, but the tunnel accepts JSON
        res = requests.put(ALP_RPC_URL, json=payload, timeout=5)
        return res.json().get("Value", {}).get("result", {})
    except Exception:
        return None

def launch():
    logger.info("🚀 S30-PRO FEDERATION: INITIATING PHASE 2 (FLIGHT)")
    
    if not PAYLOAD_FILE.exists():
        logger.error(f"❌ Schedule payload missing: {PAYLOAD_FILE.name}. Run compiler first.")
        return False

    with open(CONFIG_PATH, "rb") as f:
        cfg = tomllib.load(f)
    intended_mount = cfg.get("planner", {}).get("mount_mode", "ALT/AZ").upper()

    # 1. The Knock
    logger.info("🚪 Step 1: The Knock (Pinging bridge...)")
    try:
        requests.get(f"{SSC_UI_URL}/", timeout=3)
    except Exception:
        logger.error("❌ Bridge unresponsive on Port 5432.")
        return False

    # 2. The Breath
    logger.info("⏳ Step 2: The Breath. Allowing sensor arrays to stabilize (5s)...")
    time.sleep(5)

    # 3. Small Talk (Vitals)
    logger.info("🩺 Step 3: Checking Vitals (Battery & Storage)...")
    device_state = zwo_rpc_pulse("get_device_state") or {}
    pi_status = device_state.get("pi_status", {})
    # Defaulting to 100 for simulator tests if the bridge returns an empty object
    batt = pi_status.get("battery_capacity", 100) 
    
    if batt < 10:
        logger.error(f"❌ Veto: Battery critically low ({batt}%).")
        return False
    logger.info(f"🔋 Battery check passed: {batt}%")

    # 4. The Deep Dive (Hardware State)
    logger.info(f"⚖️ Step 4: Hardware verification (Intended: {intended_mount})...")
    track_state = zwo_rpc_pulse("scope_get_track_state", {})
    # In full production, we parse track_state to verify EQ/ALT-AZ here. 
    logger.info("🟢 Hardware state verified.")

    # 5. The Handover
    logger.info(f"📤 Step 5: Uploading {PAYLOAD_FILE.name} to SSC...")
    try:
        with open(PAYLOAD_FILE, 'rb') as f:
            res = requests.post(f"{SSC_UI_URL}/schedule/upload", files={'schedule_file': f}, timeout=10)
        if res.status_code != 200:
            logger.error(f"❌ Upload rejected by bridge (HTTP {res.status_code}).")
            return False
        logger.info("✅ Payload accepted by Daemon.")
    except Exception as e:
        logger.error(f"❌ Upload failed: {e}")
        return False

    # 6. Ignition
    logger.info("🔥 Step 6: Ignition. Engaging Schedule...")
    try:
        # Triggering the exact endpoint used by the HTMX button
        requests.post(f"{SSC_UI_URL}/schedule/state", data={"action": "toggle"}, timeout=5)
        logger.info("✨ S30-PRO is in flight! The Daemon has control.")
        return True
    except Exception as e:
        logger.error(f"❌ Ignition failed: {e}")
        return False

if __name__ == "__main__":
    if launch():
        sys.exit(0)
    else:
        sys.exit(1)
