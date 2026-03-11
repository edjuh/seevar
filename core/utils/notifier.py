#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/utils/notifier.py
Version: 1.1.0
Objective: Outbound alert management via Telegram and system bells.
"""

import requests
from core.env_loader import cfg
from core.logger import log_event

class Notifier:
    def __init__(self):
        self.token = cfg("TELEGRAM_BOT_TOKEN")
        self.chat_id = cfg("TELEGRAM_CHAT_ID")

    def send_alert(self, message):
        log_event(f"Notification Sent: {message}")
        if not self.token or not self.chat_id:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            requests.post(url, data={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"})
        except Exception as e:
            log_event(f"Failed to send Telegram: {e}", level="error")

notifier = Notifier()
