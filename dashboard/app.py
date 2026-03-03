#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# S30-PRO Federation Dashboard (v2.2.0 - Clean Bridge)
import json, os, sys
from flask import Flask, render_template, jsonify
from pathlib import Path

# Absolute Pathing
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parents[0]
TEMPLATE_DIR = BASE_DIR / "templates"
DATA_FILE = PROJECT_ROOT / "data" / "targets.json"

sys.path.append(str(PROJECT_ROOT))
from core.flight.vault_manager import VaultManager

app = Flask(__name__, template_folder=str(TEMPLATE_DIR))
vault = VaultManager()

@app.route('/')
def index():
    # Load targets safely to inject into the HTML
    targets = []
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, 'r') as f:
                targets = json.load(f)
        except Exception as e:
            print(f"Data read error: {e}")
            
    if not targets:
        targets = [{"name": "AWAITING MISSION", "priority": "NORMAL"}]

    # Pass the targets directly into the Jinja template
    return render_template('index.html', target_data=targets)

@app.route('/telemetry')
def telemetry():
    obs = vault.get_observer_config()
    return jsonify({
        "maidenhead": obs.get("maidenhead", "SEARCHING"),
        "status": "EXTERNAL_BRIDGE_UP"
    })

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5050, debug=False)
