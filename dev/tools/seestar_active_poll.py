#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/seestar_active_poll.py
Version: 1.3.0
Objective: Actively poll the Seestar Sovereign telemetry by first breaking the session lock (S1).
"""

import socket
import json
import sys
import time
from pathlib import Path
import tomllib

def get_telescope_ip():
    config_path = Path.home() / "seevar" / "config.toml"
    if not config_path.exists():
        print(f"Error: Could not find {config_path}")
        sys.exit(1)
    
    with open(config_path, "rb") as f:
        config = tomllib.load(f)
        
    try:
        return config["seestars"][0]["ip"]
    except (KeyError, IndexError):
        print("Error: Could not parse [[seestars]] ip from config.toml")
        sys.exit(1)

def send_command(sock, method, msg_id, params=None):
    payload = {"id": msg_id, "method": method}
    if params is not None:
        payload["params"] = params
        
    wire = (json.dumps(payload) + "\r\n").encode("utf-8")
    
    try:
        sock.sendall(wire)
        # Use makefile to safely read the \r\n terminated JSON-RPC stream
        f = sock.makefile('rb')
        line = f.readline()
        
        if not line:
            return {"error": "0 bytes - Connection silently dropped"}
            
        return json.loads(line.decode("utf-8").strip())
        
    except socket.timeout:
        return {"error": f"Timeout - Seestar ignored '{method}'"}
    except Exception as e:
        return {"error": str(e)}

def poll_seestar():
    ip = get_telescope_ip()
    port = 4700
    msg_id = 10000
    
    print(f"[*] Connecting to Sovereign TCP at {ip}:{port}...")
    
    try:
        # We use a longer timeout in case the Seestar is busy resetting its state
        sock = socket.create_connection((ip, port), timeout=10)
        print("[+] Connected.")
        
        # --- S1: BREAK THE GHOST LOCK ---
        print("\n[*] S1: Sending 'iscope_stop_view' to clear session lock...")
        reset_resp = send_command(sock, "iscope_stop_view", msg_id)
        msg_id += 1
        print(f"    Response: {reset_resp.get('method', 'Error or ignored')}")
        
        # Give the firmware a moment to clear the buffers
        time.sleep(0.5)

        # --- S4: GET DEVICE STATE ---
        print("\n[*] S4: Requesting telemetry (get_device_state)...")
        state_resp = send_command(sock, "get_device_state", msg_id)
        msg_id += 1
        
        if "error" in state_resp:
            print(f"    [!] Failed: {state_resp['error']}")
        else:
            print("    [+] Success! Telemetry Block received:")
            print(json.dumps(state_resp, indent=2))

        # --- GET MOUNT STATE ---
        print("\n[*] Requesting mount coordinates (scope_get_ra_dec)...")
        radec_resp = send_command(sock, "scope_get_ra_dec", msg_id)
        msg_id += 1
        print(json.dumps(radec_resp, indent=2))

    except ConnectionRefusedError:
        print("[!] Connection Refused. Is the Seestar turned on and connected to the Wi-Fi?")
    except Exception as e:
        print(f"[!] Unexpected error: {e}")
    finally:
        if 'sock' in locals():
            sock.close()
            print("\n[*] Socket closed.")

if __name__ == "__main__":
    poll_seestar()
