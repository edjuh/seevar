#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: core/hardware/fleet_mapper.py
# Version: 1.4.17 (Infrastructure Baseline)
# Objective: Dynamically reads upstream ALP config, verifies the 'seestar.service', and maps hardware indices to a static schema.
# -----------------------------------------------------------------------------
import os
import sys
import json
import subprocess
import urllib.request

# Python 3.13.5 includes tomllib natively for safe TOML parsing
import tomllib 

# Resolve project paths dynamically
PROJECT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SCHEMA_FILE = os.path.join(PROJECT_DIR, 'data', 'fleet_schema.json')

# Upstream seestar_alp paths (based on your system audit)
ALP_DIR = os.path.expanduser("~/seestar_alp")
ALP_CONFIG = os.path.join(ALP_DIR, "config.toml")

def verify_alp_service():
    """Queries systemd to guarantee the bridge is actually running before network calls."""
    print("[BLOCK 2] Verifying 'seestar.service' via systemd...")
    try:
        # Corrected service name based on system audit
        result = subprocess.run(["systemctl", "is-active", "seestar.service"], capture_output=True, text=True)
        if result.stdout.strip() != "active":
            print(f"[FATAL] seestar.service is not active. Status: '{result.stdout.strip()}'")
            return False
        print("[OK] systemd confirms seestar.service is active.")
        return True
    except FileNotFoundError:
        print("[FATAL] systemctl not found. OS environment corrupted.")
        return False

def get_alpaca_endpoint():
    """Reads the upstream config.toml to find the true listening port."""
    port = 5555 # Fallback standard
    host = "127.0.0.1" # Safe internal loopback
    
    print(f"[BLOCK 2] Reading upstream config: {ALP_CONFIG}")
    if os.path.exists(ALP_CONFIG):
        try:
            with open(ALP_CONFIG, "rb") as f:
                config = tomllib.load(f)
                if "server" in config and "port" in config["server"]:
                    port = config["server"]["port"]
                elif "port" in config:
                    port = config["port"]
                print(f"[OK] Parsed port {port} from upstream config.toml.")
        except Exception as e:
            print(f"[WARNING] Could not parse {ALP_CONFIG}. Falling back to port {port}. Error: {e}")
    else:
        print(f"[WARNING] Upstream config {ALP_CONFIG} not found. Falling back to port {port}.")
        
    return f"http://{host}:{port}"

def map_fleet():
    if not verify_alp_service():
        sys.exit(1)
        
    base_url = get_alpaca_endpoint()
    print(f"[BLOCK 2] Polling Alpaca Management API at {base_url}...")
    
    try:
        req = urllib.request.urlopen(f"{base_url}/management/v1/configureddevices", timeout=3.0)
        devices = json.loads(req.read().decode())['Value']
    except Exception as e:
        print(f"[FATAL] ALP bridge unreachable at {base_url}: {e}")
        print("[BLOCK 2] Fleet mapping failed. Halting.")
        sys.exit(1)

    fleet_schema = {
        "bridge_url": base_url,
        "telescopes": {}
    }

    mapped_count = 0
    for dev in devices:
        if dev.get("DeviceType") == "Telescope":
            name = dev.get("DeviceName", "Unknown")
            idx = dev.get("DeviceNumber")
            
            # Identify units without assuming their index
            identity = "unknown_unit"
            if "Alpha" in name or "S30" in name: identity = "williamina_s30"
            elif "Annie" in name: identity = "annie_s50"
            elif "Henrietta" in name: identity = "henrietta_s50"
            
            fleet_schema["telescopes"][identity] = {
                "name": name,
                "device_number": idx,
                "endpoints": {
                    "base": f"/api/v1/telescope/{idx}",
                    "ra": f"/api/v1/telescope/{idx}/rightascension",
                    "dec": f"/api/v1/telescope/{idx}/declination",
                    "slewing": f"/api/v1/telescope/{idx}/slewing",
                    "tracking": f"/api/v1/telescope/{idx}/tracking",
                    "action": f"/api/v1/telescope/{idx}/action"
                }
            }
            mapped_count += 1
            print(f"[OK] Locked: {identity} ('{name}') -> DeviceNumber {idx}")

    os.makedirs(os.path.dirname(SCHEMA_FILE), exist_ok=True)

    with open(SCHEMA_FILE, 'w') as f:
        json.dump(fleet_schema, f, indent=4)
    
    print(f"[SUCCESS] Block 2: Schema written to {SCHEMA_FILE} with {mapped_count} device(s).")

if __name__ == "__main__":
    map_fleet()
