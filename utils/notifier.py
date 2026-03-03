#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: utils/notifier.py
Version: 1.2.0 (Pee Pastinakel)
Objective: Outbound notification manager that generates morning reports and sends mission summaries via Telegram.
"""

import os
import json
import requests
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/seestar_organizer/.env"))

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Failed to send Telegram: {e}")
        return False

def generate_morning_report():
    report_path = os.path.expanduser("~/seestar_organizer/core/postflight/data/qc_report.json")
    if not os.path.exists(report_path):
        return

    with open(report_path, 'r') as f:
        data = json.load(f)

    passed = [r for r in data if r.get('status') == "PASS"]
    
    msg = "☕ *S30-PRO Morning Report*\n"
    msg += "---------------------------\n"
    msg += f"✅ Successful Observations: {len(passed)}\n"
    msg += f"❌ Failed/Low SNR: {len(data) - len(passed)}\n\n"
    
    if passed:
        msg += "*Key Science Collected:*\n"
        for r in passed[:8]:
            msg += f"• {r.get('target', 'Unknown')}: SNR {r.get('snr', 0.0)}\n"
    
    msg += "\n🔭 _Federation Status: {} Parked".format(self.obs.get("maidenhead"))_"
    send_telegram(msg)

if __name__ == "__main__":
    generate_morning_report()
