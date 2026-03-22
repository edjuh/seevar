#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/utils/notifier.py
Version: 1.4.0
Objective: Outbound alert management via Telegram and system bell.
           Single authoritative notifier for all SeeVar pipeline components.

Canonical location: Filename: core/utils/notifier.py
Replaces:          utils/notifier.py (retired — top-level utils/ is not a Python package)

Changes vs 1.3.0 / 1.1.0:
  - Single canonical file. utils/notifier.py is retired.
  - FIXED: sys.path seestar_organizer → seevar
  - FIXED: bare except → specific exception types
  - FIXED: Telegram token/chat_id read from config.toml [telegram] section
  - ADDED: send_telegram() returns bool (success/failure)
  - ADDED: notify() unified entry point — Telegram + bell in one call
  - ADDED: bell() respects SEEVAR_NO_BELL env var
  - RETAINED: graceful degradation — Telegram failure does not raise, just logs
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Notifier")

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Config loading — lazy, cached
# ---------------------------------------------------------------------------

_telegram_cfg: Optional[dict] = None

def _load_telegram_cfg() -> dict:
    global _telegram_cfg
    if _telegram_cfg is not None:
        return _telegram_cfg

    try:
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore

        config_path = PROJECT_ROOT / "config.toml"
        with open(config_path, "rb") as f:
            cfg = tomllib.load(f)
        _telegram_cfg = cfg.get("telegram", {})
    except Exception as e:
        logger.debug(f"Could not load telegram config: {e}")
        _telegram_cfg = {}

    return _telegram_cfg


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def send_telegram(message: str) -> bool:
    """
    Send a Telegram message using credentials from config.toml [telegram].
    Returns True on success, False on any failure (never raises).
    """
    try:
        import requests
    except ImportError:
        logger.warning("requests not installed — Telegram notifications unavailable.")
        return False

    cfg     = _load_telegram_cfg()
    token   = cfg.get("token", "").strip()
    chat_id = cfg.get("chat_id", "").strip()

    if not token or not chat_id:
        logger.debug("Telegram token/chat_id not configured — skipping notification.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.debug(f"Telegram sent: {message[:60]}")
            return True
        else:
            logger.warning(f"Telegram API returned {resp.status_code}: {resp.text[:120]}")
            return False
    except requests.RequestException as e:
        logger.warning(f"Telegram send failed: {e}")
        return False


# ---------------------------------------------------------------------------
# System bell
# ---------------------------------------------------------------------------

def bell(times: int = 1) -> None:
    """Ring system bell. Silenced by SEEVAR_NO_BELL=1."""
    if os.environ.get("SEEVAR_NO_BELL", "0") == "1":
        return
    try:
        for _ in range(times):
            print("\a", end="", flush=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------

def notify(
    message: str,
    telegram: bool = True,
    ring: bool = False,
    bell_times: int = 1,
) -> None:
    """Unified notification entry point."""
    logger.info(f"NOTIFY: {message}")
    if telegram:
        send_telegram(message)
    if ring:
        bell(bell_times)


# ---------------------------------------------------------------------------
# Convenience shorthands
# ---------------------------------------------------------------------------

def alert(message: str) -> None:
    """High-priority alert — Telegram + bell x3."""
    notify(message, telegram=True, ring=True, bell_times=3)

def info(message: str) -> None:
    """Informational — Telegram only, no bell."""
    notify(message, telegram=True, ring=False)

def silent_log(message: str) -> None:
    """Log only — no Telegram, no bell."""
    logger.info(f"NOTIFY(silent): {message}")


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Testing notifier...")
    bell(2)
    result = send_telegram("🔭 SeeVar notifier self-test.")
    print(f"Telegram: {'sent' if result else 'skipped (not configured or unavailable)'}")
    print("Done.")
