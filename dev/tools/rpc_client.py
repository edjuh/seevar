#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: dev/tools/rpc_client.py
Version: 2.0.1
Objective: Interactive JSON-RPC client for Seestar port 4700 using pre-built sovereign payloads.
"""

import socket
import json
import sys
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

class SeestarRPCClient:
    def __init__(self, host, port=4700):
        self.host = host
        self.port = port
        self.msg_id = 10000

    def _send(self, method, params=None):
        payload = {
            "id": self.msg_id,
            "method": method
        }
        if params is not None:
            payload["params"] = params
            
        self.msg_id += 1
        wire = (json.dumps(payload) + "\r\n").encode("utf-8")
        
        try:
            with socket.create_connection((self.host, self.port), timeout=5) as sock:
                sock.sendall(wire)
                response = sock.recv(4096)
                if not response:
                    return {"error": "Empty response from device"}
                return json.loads(response.decode("utf-8"))
        except Exception as e:
            return {"error": str(e)}

    def check_health(self):
        """Method: get_device_state"""
        return self._send("get_device_state")

    def stop_all(self):
        """Method: iscope_stop_view"""
        return self._send("iscope_stop_view")

    def goto(self, ra, dec):
        """Method: scope_goto [ra_hours, dec_deg]"""
        return self._send("scope_goto", [ra, dec])

    def autofocus(self):
        """Method: start_auto_focuse (Note firmware typo)"""
        return self._send("start_auto_focuse")

if __name__ == "__main__":
    telescope_ip = get_telescope_ip()
    client = SeestarRPCClient(telescope_ip)
    
    print(f"--- Probing Seestar at {telescope_ip} ---")
    state = client.check_health()
    print(json.dumps(state, indent=2))
