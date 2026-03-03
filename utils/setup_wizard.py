#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: utils/setup_wizard.py
Version: 1.5.2 (Monkel/Discovery Grade)
Objective: Automates hardware discovery using the alpacadiscovery1 handshake.
"""

import socket
import requests
import json
from pathlib import Path
from datetime import datetime

def discover_seestar(timeout=5):
    """Broadcasts 'alpacadiscovery1' to find the telescope."""
    print("📡 Broadcasting Alpaca discovery signal...")
    msg = "alpacadiscovery1"
    port = 32227
    
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(timeout)
        s.sendto(msg.encode(), ('<broadcast>', port))
        
        try:
            data, addr = s.recvfrom(1024)
            resp = json.loads(data.decode())
            print(f"🤝 Handshake Success! Found Seestar at {addr[0]}:{resp['AlpacaPort']}")
            return addr[0], resp['AlpacaPort']
        except socket.timeout:
            print("⚠️ No response. Ensure Seestar is powered on and Alpaca is enabled.")
            return None, None

def run_wizard():
    root = Path(__file__).resolve().parents[1]
    output_path = root / "config.toml"

    print("\n🔭 S30-PRO FEDERATION: MONKEL SETUP WIZARD")
    print("="*45)

    # 1. Automated Hardware Discovery
    ip, alp_port = discover_seestar()
    if not ip:
        ip = input("Enter Seestar IP manually [192.168.178.55]: ") or "192.168.178.55"
        alp_port = 5555

    # 2. Identity & AAVSO Requirements
    user_name = input("Enter Observer Name (e.g., Ed): ")
    obscode  = input("Enter AAVSO Observer Code (e.g., PE5ED): ")
    web_token = input("Enter AAVSO WebObs Token (Private): ")

    # 3. Secure Config Generation
    config_content = f"""# S30-PRO Federation: Garmt v1.2.0 Baseline

[identity]
observer_name = "{user_name}"
aavso_obscode = "{obscode}"

[network]
ip_address = "{ip}"
port = {alp_port}

[aavso]
observer_code = "{obscode}"
webobs_token = "{web_token}"

[hardware]
model = "S30-PRO"
sensor = "IMX585"
default_gain = 80

[science]
saturation_adu = 60000
fwhm_threshold = 4.5
magzero = 20.5
"""

    with open(output_path, 'w') as f:
        f.write(config_content)
    
    print(f"\n✅ Configuration Locked: {output_path}")

if __name__ == "__main__":
    run_wizard()
