#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: /home/ed/seevar/core/utils/env_loader.py
Version: 1.0.0
Objective: Single source of truth for SeeVar environment paths and TOML configuration loading.
"""

import os
import tomllib
import logging
from pathlib import Path

log = logging.getLogger("EnvLoader")

# ---------------------------------------------------------------------------
# Centralized Sovereign Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path("/home/ed/seevar")
CONFIG_PATH = PROJECT_ROOT / "config.toml"
DATA_DIR = PROJECT_ROOT / "data"
ENV_STATUS = Path("/dev/shm/env_status.json")

# ---------------------------------------------------------------------------
# Centralized Configuration Loader
# ---------------------------------------------------------------------------
def load_config() -> dict:
    """Safely loads config.toml, returning an empty dict on failure with logging."""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "rb") as f:
                return tomllib.load(f)
        except (tomllib.TOMLDecodeError, OSError) as e:
            log.warning("load_config failed for %s: %s", CONFIG_PATH, e)
    else:
        log.warning("Config file not found at %s", CONFIG_PATH)
    return {}
