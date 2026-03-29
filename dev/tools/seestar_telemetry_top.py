#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/seestar_telemetry_top.py
Version: 1.0.0
Objective: Live, continuous CLI dashboard (like 'top') for Seestar Sovereign telemetry via JSON-RPC 2.0 on port 4700.
"""

import socket
import json
import time
import sys
import os
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

def rpc_call(sock: socket.socket, method: str, cmd_id: int, params: list = None, timeout: float = 2.0) -> dict:
    """Send a command and return the ID-matched result payload."""
    msg = {"jsonrpc": "2.0", "id": cmd_id, "method": method}
    if params:
        msg["params"] = params
        
    try:
        sock.sendall((json.dumps(msg) + "\r\n").encode("utf-8"))
    except Exception:
        return None

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
                    # Match the exact ID and return just the 'result' block
                    if response.get("id") == cmd_id:
                        return response.get("result")
                except json.JSONDecodeError:
                    continue
        except socket.timeout:
            continue
            
    return None

def main():
    target_ip = load_ip()
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((target_ip, PORT))
    except Exception as e:
        print(f"❌ Connection to {target_ip}:{PORT} failed: {e}")
        sys.exit(1)

    cmd_id = 10000

    try:
        while True:
            # 1. Fetch data
            cmd_id += 1
            device_state = rpc_call(sock, "get_device_state", cmd_id)
            
            cmd_id += 1
            coords = rpc_call(sock, "scope_get_equ_coord", cmd_id)
            
            cmd_id += 1
            camera_state = rpc_call(sock, "get_camera_state", cmd_id)
            
            # 2. Clear terminal screen
            os.system('cls' if os.name == 'nt' else 'clear')
            
            # 3. Paint the UI
            print("=" * 55)
            print(f" 🔭 SEESTAR SOVEREIGN TELEMETRY ('TOP' MODE)")
            print(f" 📡 Target: {target_ip}:{PORT}")
            print("=" * 55)
            
            if device_state:
                dev = device_state.get('device', {})
                pi = device_state.get('pi_status', {})
                print("\n [ SYSTEM HEALTH ]")
                print(f"   Name:     {dev.get('name', 'Unknown')}")
                print(f"   Firmware: {dev.get('firmware_ver_int', 'Unknown')}")
                print(f"   Battery:  {pi.get('battery_capacity', '--')}% ({pi.get('charger_status', 'Unknown')})")
                print(f"   Temp:     {pi.get('temp', '--')} °C")
            else:
                print("\n [ SYSTEM HEALTH ]\n   ⚠️ Timeout / No Data")

            if coords:
                print("\n [ MOUNT POSITION ]")
                ra = coords.get('ra')
                dec = coords.get('dec')
                print(f"   RA:       {ra:.4f} h" if isinstance(ra, (int, float)) else f"   RA:       {ra}")
                print(f"   DEC:      {dec:.4f} °" if isinstance(dec, (int, float)) else f"   DEC:      {dec}")
            else:
                print("\n [ MOUNT POSITION ]\n   ⚠️ Timeout / No Data")

            if camera_state:
                print("\n [ CAMERA STATUS ]")
                print(f"   State:    {camera_state.get('state', '--')}")
                print(f"   Lapse ms: {camera_state.get('lapse_ms', '--')}")
            else:
                print("\n [ CAMERA STATUS ]\n   ⚠️ Timeout / No Data")

            print("\n" + "=" * 55)
            print(" Press Ctrl+C to exit.")
            
            # 4. Sleep before next cycle (1 Hz refresh rate)
            time.sleep(1.0) 

    except KeyboardInterrupt:
        print("\n🔌 Disconnecting...")
    finally:
        sock.close()

if __name__ == "__main__":
    main()
