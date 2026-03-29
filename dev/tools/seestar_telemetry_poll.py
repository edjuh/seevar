#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/seestar_telemetry_poll.py
Version: 1.0.0
Objective: Standalone diagnostic tool to poll real-time JSON-RPC 2.0 telemetry and status data directly from the Seestar on port 4700.
"""

import socket
import json
import time
import sys
from pathlib import Path

# Fallback defaults
HOST = "192.168.178.251"
PORT = 4700

def load_ip():
    """Extract Seestar IP dynamically from config.toml."""
    config_path = Path.home() / "seevar" / "config.toml"
    if not config_path.exists():
        return HOST
    try:
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            import tomli as tomllib
            
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
            return config.get("network", {}).get("seestar_ip", HOST)
    except Exception:
        return HOST

def rpc_call(sock: socket.socket, method: str, cmd_id: int, params: list = None, timeout: float = 5.0) -> dict:
    """Send a command and return the ID-matched response, ignoring unsolicited Events."""
    msg = {"jsonrpc": "2.0", "id": cmd_id, "method": method}
    if params:
        msg["params"] = params
        
    try:
        sock.sendall((json.dumps(msg) + "\r\n").encode("utf-8"))
    except Exception as e:
        return {"error": f"Transmission failed: {e}"}

    buf = b""
    deadline = time.monotonic() + timeout
    
    while time.monotonic() < deadline:
        try:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
            
            while b"\r\n" in buf:
                line, buf = buf.split(b"\r\n", 1)
                if not line:
                    continue
                try:
                    response = json.loads(line.decode("utf-8"))
                    # Drop unsolicited telemetry events
                    if "Event" in response:
                        continue
                    # Match the exact ID
                    if response.get("id") == cmd_id:
                        return response
                except json.JSONDecodeError:
                    continue
        except socket.timeout:
            continue
            
    return {"error": "Timeout waiting for matching response ID."}

def main():
    target_ip = load_ip()
    print(f"📡 Connecting to Seestar Sovereign API at {target_ip}:{PORT}...\n")
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((target_ip, PORT))
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        sys.exit(1)

    commands = [
        ("get_device_state", "Hardware Health"),
        ("get_camera_state", "Camera Status"),
        ("scope_get_equ_coord", "Mount Coordinates"),
        ("get_user_location", "GPS Location")
    ]

    cmd_id = 1000
    for method, title in commands:
        cmd_id += 1
        print(f"--- {title} (`{method}`) ---")
        
        response = rpc_call(sock, method, cmd_id)
        
        if "error" in response:
            print(f"⚠️ Error: {response['error']}\n")
        elif "result" in response:
            # Format output nicely
            print(json.dumps(response["result"], indent=2))
            print()
        else:
            print(f"⚠️ Unexpected payload: {response}\n")
            
        time.sleep(0.2) # Slight pause between commands to respect the SOC

    sock.close()
    print("🔌 Socket closed. Polling complete.")

if __name__ == "__main__":
    main()
