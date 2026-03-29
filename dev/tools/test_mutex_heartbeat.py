#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/test_mutex_heartbeat.py
Version: 1.0.0
Objective: Verify that ControlSocket's background heartbeat keeps port 4700 alive during a 60s+ simulated exposure without corrupting the command stream.
"""

import time
import sys
import logging
from core.flight.pilot import ControlSocket

# Enable debug logging temporarily to watch the unsolicited telemetry drops
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")

def run_test():
    print("🚀 Starting Mutex & Heartbeat validation test...")
    
    with ControlSocket(timeout=20.0) as ctrl:
        if not ctrl._sock:
            print("❌ Failed to connect to Seestar. Check your IP and network connection.")
            sys.exit(1)
            
        print("✅ Connected to Port 4700. Firing initial command...")
        
        # Test 1: Standard send_and_recv
        resp = ctrl.send_and_recv("get_device_state")
        if resp and "result" in resp:
            fw = resp.get("result", {}).get("device", {}).get("firmware_ver_int", "Unknown")
            print(f"📡 Initial state received. Firmware: {fw}")
        else:
            print("❌ Failed to get initial state.")
            sys.exit(1)
            
        print("\n⏳ Simulating 65-second exposure wait...")
        print("   The background thread is currently sending heartbeat ID: 99999 every 5 seconds.")
        print("   You should see debug logs if the Seestar pushes unsolicited Event telemetry.")
        
        # Block the main thread, ticking every 5 seconds for visibility
        for i in range(13):
            time.sleep(5)
            print(f"   ... {i * 5 + 5}s elapsed")

        print("\n📸 Exposure wait complete. Testing if socket survived...")
        
        # Test 2: Prove the socket wasn't dropped and stream isn't corrupted
        t_start = time.monotonic()
        resp2 = ctrl.send_and_recv("scope_get_equ_coord")
        t_elapsed = time.monotonic() - t_start
        
        if resp2 and "result" in resp2:
            print(f"✅ SUCCESS: Socket survived the 65-second wait! (Response in {t_elapsed:.2f}s)")
            print(f"   Coordinates: {resp2['result']}")
        else:
            print("❌ FAILURE: Socket dropped or JSON stream was corrupted by the heartbeat.")

if __name__ == "__main__":
    run_test()
