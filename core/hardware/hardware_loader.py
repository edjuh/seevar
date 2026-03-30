#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/hardware/hardware_loader.py
Version: 1.2.0
Objective: Auto-detect Seestar hardware via Alpaca UDP discovery beacon (port 32227), fingerprint sensor via HTTP Alpaca API, load the matching hardware profile.
"""

import json
import select
import socket
import logging
import tomllib
import requests
from pathlib import Path
from typing import Optional

log = logging.getLogger("hardware_loader")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR   = PROJECT_ROOT / "core" / "hardware" / "models"
CONFIG_PATH  = PROJECT_ROOT / "config.toml"

ALPACA_DISCOVERY_PORT = 32227
ALPACA_DISCOVERY_MSG  = bytes.fromhex("616c70616361646973636f7665727931")
ALPACA_CLIENT_PARAMS  = {"ClientID": 1, "ClientTransactionID": 42}


# =============================================================================
# STEP 1 — UDP DISCOVERY
# =============================================================================

def discover_seestar(timeout: float = 3.0) -> list:
    """
    Broadcast Alpaca discovery and collect all responding Seestars.
    Returns list of {"ip": "x.x.x.x", "port": 4700}
    Empty list if none found within timeout.
    """
    devices = []
    
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(False)

        try:
            sock.sendto(ALPACA_DISCOVERY_MSG, ("<broadcast>", ALPACA_DISCOVERY_PORT))
            log.debug("Alpaca discovery broadcast sent → port %d", ALPACA_DISCOVERY_PORT)

            while True:
                ready = select.select([sock], [], [], timeout)
                if not ready[0]:
                    break
                data, addr = sock.recvfrom(1024)
                if not data:
                    continue
                try:
                    response = json.loads(data.decode("utf-8"))
                    if "AlpacaPort" in response:
                        devices.append({
                            "ip":   addr[0],
                            "port": response["AlpacaPort"],
                        })
                        log.info("Seestar found: %s port %s", addr[0], response["AlpacaPort"])
                except json.JSONDecodeError:
                    continue
        except socket.error as e:
            log.error("UDP broadcast failed: %s", e)

    return devices


# =============================================================================
# STEP 2 — HTTP ALPACA FINGERPRINT
# =============================================================================

def get_sensor_fingerprint(ip: str, port: int = 4700) -> dict:
    """
    Identify Seestar model via Alpaca HTTP API.
    Primary: cameraxsize (sensor width)
    Secondary: description (S30 vs S50 disambiguation)
    """
    base = f"http://{ip}:{port}/api/v1/camera/0"

    try:
        r = requests.get(f"{base}/cameraxsize",
                         params=ALPACA_CLIENT_PARAMS, timeout=3)
        r.raise_for_status()
        width = r.json().get("Value")
        log.debug("Sensor width from %s: %s", ip, width)

        if width == 3840:
            return {"model": "S30-Pro", "instrument": "IMX585", "sensor_w": 3840}

        if width == 1920:
            try:
                rd = requests.get(f"{base}/description",
                                  params=ALPACA_CLIENT_PARAMS, timeout=3)
                desc = rd.json().get("Value", "").upper()
                log.debug("Description from %s: %s", ip, desc)

                if "S50" in desc or "IMX462" in desc:
                    return {"model": "S50",  "instrument": "IMX462", "sensor_w": 1920}
                else:
                    return {"model": "S30",  "instrument": "IMX662", "sensor_w": 1920}

            except requests.exceptions.RequestException as e:
                log.warning("Description query failed: %s — assuming S30", e)
                return {"model": "S30", "instrument": "IMX662", "sensor_w": 1920}

        log.warning("Unexpected sensor width %s from %s", width, ip)
        return {}

    except requests.exceptions.RequestException as e:
        log.warning("Alpaca fingerprint network call failed for %s: %s", ip, e)
        return {}


# =============================================================================
# CONFIG FALLBACK
# =============================================================================

def _from_config(key: str, name: Optional[str] = None) -> Optional[str]:
    """Read model or ip from config.toml [[seestars]]."""
    try:
        with open(CONFIG_PATH, "rb") as f:
            config = tomllib.load(f)
        seestars = config.get("seestars", [])
        if not seestars:
            return None
        if name:
            for s in seestars:
                if s.get("name") == name:
                    val = s.get(key)
                    return None if val == "TBD" else val
        val = seestars[0].get(key)
        return None if val == "TBD" else val
    except Exception:
        return None


# =============================================================================
# MAIN LOADER
# =============================================================================

def load_hardware_profile(
    model_hint: Optional[str] = None,
    name_hint:  Optional[str] = None,
    use_udp:    bool = True,
) -> dict:
    """
    Load hardware profile with auto-detection.

    Priority:
      1. model_hint  — explicit override
      2. UDP discovery + HTTP Alpaca fingerprint
      3. config.toml [[seestars]] model field
      4. S30-Pro default (primary target)

    Returns merged hardware constants dict.
    """
    detected_ip    = None
    detected_model = None

    if model_hint:
        detected_model = model_hint
        log.info("Using explicit model hint: %s", model_hint)

    if not detected_model and use_udp:
        units = discover_seestar(timeout=3.0)
        if units:
            target = units[0]
            detected_ip = target["ip"]
            fp = get_sensor_fingerprint(detected_ip, target["port"])
            detected_model = fp.get("model")
            if detected_model:
                log.info("Auto-detected: %s @ %s", detected_model, detected_ip)

    if not detected_model:
        detected_model = _from_config("model", name_hint)
        if detected_model:
            log.info("Using config.toml model: %s", detected_model)

    if not detected_model:
        detected_model = "S30-Pro"
        log.warning("Detection failed — defaulting to S30-Pro")

    profile_path = MODELS_DIR / f"{detected_model}.json"
    if not profile_path.exists():
        log.error("Model file not found: %s — falling back to S30-Pro", profile_path)
        detected_model = "S30-Pro"
        profile_path   = MODELS_DIR / "S30-Pro.json"

    with open(profile_path, encoding="utf-8") as f:
        profile = json.load(f)

    if detected_ip:
        profile["detected_ip"] = detected_ip

    log.info(
        "Profile loaded: %s — %s %.2f\"/px sensor %s",
        detected_model,
        profile.get("telescope", "?"),
        profile.get("pixscale", 0),
        profile.get("instrument", "?"),
    )
    return profile


# =============================================================================
# STANDALONE TEST
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    print(r"""
   ___  ___  ___ 
  / __|| __|| __|
  \__ \| _| | _| 
  |___/|___||___|
  __   __ _  ___ 
  \ \ / // \| _ \
   \ V // _ \   /
    \_//_/ \_\_|_\
    """)
    print("🔭 SeeVar Hardware Loader v1.2.0")
    print("=" * 50)

    print("\nStep 1 — UDP Alpaca discovery (3s)...")
    units = discover_seestar(timeout=3.0)
    if units:
        for u in units:
            print(f"  Found: {u['ip']}:{u['port']}")
            fp = get_sensor_fingerprint(u["ip"], u["port"])
            print(f"  Fingerprint: {fp}")
    else:
        print("  No Seestar on network — expected before first light")

    print("\nStep 2 — Loading hardware profile...")
    hw = load_hardware_profile()
    print(f"\n  Model      : {hw.get('model')}")
    print(f"  Telescope  : {hw.get('telescope')}")
    print(f"  Instrument : {hw.get('instrument')}")
    print(f"  Sensor     : {hw.get('sensor_w')}x{hw.get('sensor_h')}")
    print(f"  Pixscale   : {hw.get('pixscale')}\"/px")
    print(f"  Focal len  : {hw.get('focallen_mm')}mm")
    if hw.get("detected_ip"):
        print(f"  Detected IP: {hw['detected_ip']}")
    print()
    print("# FIRST LIGHT REQUIRED:")
    print("  - Log raw UDP response for payload confirmation")
    print("  - Log description field for S30 vs S50 disambiguation")
    print("  - Confirm ClientID/ClientTransactionID requirements")
