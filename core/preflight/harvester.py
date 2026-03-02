#!/usr/bin/env python3
import requests, json, tomllib
from pathlib import Path

def harvest():
    # Absolute Path Resolution
    root = Path(__file__).resolve().parents[2]
    config_path = root / "config.toml"
    output_path = root / "data/campaign_targets.json"

    with open(config_path, "rb") as f:
        cfg = tomllib.load(f).get('aavso', {})
    
    headers = {
        'X-Observer-Code': cfg.get("observer_code"),
        'X-Target-Key': cfg.get("target_key"),
        'X-Auth-Token': cfg.get("webobs_token"),
        'User-Agent': 'S30-Pro-Federation-v1.2.0'
    }

    # Verified 2026 Endpoint
    url = "https://apps.aavso.org/vsp/api/v1/targetlist/default/"
    
    response = requests.get(url, headers=headers, timeout=15, allow_redirects=False)
    if response.status_code == 200:
        with open(output_path, 'w') as f:
            json.dump(response.json(), f, indent=4)
        print(f"✅ Harvested {len(response.json())} targets to RAID.")
