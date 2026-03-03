#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# S30-PRO Federation Dashboard (v2.2.1 - The 500 Killer)
import json, os, sys
from flask import Flask, render_template, jsonify
from pathlib import Path

# Absolute Pathing to the core directories
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parents[1]
TEMPLATE_DIR = BASE_DIR / "templates"
DATA_FILE = PROJECT_ROOT / "data" / "targets.json"

sys.path.append(str(PROJECT_ROOT))
from core.flight.vault_manager import VaultManager

app = Flask(__name__, template_folder=str(TEMPLATE_DIR))
vault = VaultManager()

@app.route('/')
def index():
    # Safely load the RAID targets to pass to the frontend
    targets = []
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, 'r') as f:
                targets = json.load(f)
        except Exception as e:
            print(f"JSON Error: {e}")
            
    # Fallback if the RAID is acting up
    if not targets:
        targets = [{"name": "AWAITING MISSION", "priority": "NORMAL"}]

    # INJECT the data into the HTML (This kills the 500 error)
    return render_template('index.html', target_data=targets)

@app.route('/telemetry')
def telemetry():
    obs = vault.get_observer_config()
    return jsonify({
        "maidenhead": obs.get("maidenhead", "JO22hj"),
        "status": "EXTERNAL_BRIDGE_UP"
    })

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5050, debug=False)
