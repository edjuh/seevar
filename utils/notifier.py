#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/utils/notifier.py
Version: 1.3.0
Objective: Outbound notification manager realigned for SeeVar paths.
"""

import os
import json
import requests
from dotenv import load_dotenv

# Realigned to SeeVar root
load_dotenv(os.path.expanduser("~/seevar/.env"))

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Failed to send Telegram: {e}")
        return False

if __name__ == "__main__":
    # Test message
    if TOKEN and CHAT_ID:
        send_telegram("🚀 *SeeVar System Online*: Diamond Revision confirmed and services active.")
    else:
        print("❌ Error: Telegram credentials not found in ~/seevar/.env")
