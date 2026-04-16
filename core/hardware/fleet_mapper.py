#!/usr/bin/env python3
# Filename: core/hardware/fleet_mapper.py
# Version:  2.0.0
# Objective: Read [[seestars]] from config.toml, load hardware constants
#            from core/hardware/models/<model>.json, and produce
#            data/fleet_schema.json for use by pilot.py and orchestrator.py.
#            Sovereign TCP path only. No Alpaca. No port 5555.

import json
import sys
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE  = PROJECT_ROOT / "config.toml"
MODELS_DIR   = PROJECT_ROOT / "core" / "hardware" / "models"
SCHEMA_FILE  = PROJECT_ROOT / "data" / "fleet_schema.json"


def load_model(model_name: str) -> dict:
    """Load hardware constants from core/hardware/models/<model>.json."""
    path = MODELS_DIR / f"{model_name}.json"
    if not path.exists():
        print(f"[ERROR] Model file not found: {path}")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def map_fleet() -> dict:
    """Build fleet schema from config.toml [[seestars]] entries."""
    if not CONFIG_FILE.exists():
        print(f"[FATAL] config.toml not found: {CONFIG_FILE}")
        sys.exit(1)

    with open(CONFIG_FILE, "rb") as f:
        config = tomllib.load(f)

    seestars = config.get("seestars", [])
    if not seestars:
        print("[WARNING] No [[seestars]] entries found in config.toml.")
        return {"telescopes": {}}

    fleet = {"telescopes": {}}

    for entry in seestars:
        name  = entry.get("name")
        model = entry.get("model")
        ip    = entry.get("ip", "TBD")
        mount = entry.get("mount", "altaz")

        if not name or not model:
            print(f"[WARNING] Skipping incomplete entry: {entry}")
            continue

        hw = load_model(model)

        fleet["telescopes"][name] = {
            "name":         name,
            "model":        model,
            "ip":           ip,
            "ctrl_port":    4700,
            "alpaca_port":  32323,
            "img_port":     4801,
            "mount":        mount,
            "telescope":    hw["telescope"],
            "instrument":   hw["instrument"],
            "sensor_w":     hw["sensor_w"],
            "sensor_h":     hw["sensor_h"],
            "focallen_mm":  hw["focallen_mm"],
            "aperture_mm":  hw["aperture_mm"],
            "pixscale":     hw["pixscale"],
            "bayer":        hw["bayer"],
            "gain_default": hw["gain_default"],
            "filter":       hw["filter"],
            "veto_temp_c":  hw["veto_temp_c"],
            "veto_battery": hw["veto_battery"],
            "settle_s":     hw["settle_s"],
            "frame_timeout_s": hw["frame_timeout_s"],
        }
        print(f"[OK] Mapped: {name} ({model}) @ {ip}")

    SCHEMA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SCHEMA_FILE, "w") as f:
        json.dump(fleet, f, indent=4)

    print(f"[SUCCESS] Fleet schema written: {SCHEMA_FILE}")
    print(f"          {len(fleet['telescopes'])} telescope(s) mapped.")
    return fleet


if __name__ == "__main__":
    map_fleet()
