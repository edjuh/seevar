#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/utils/env_loader.py
Version: 1.1.0
Objective: Single source of truth for SeeVar environment paths and TOML configuration loading.
"""

import tomllib
import logging
from pathlib import Path

log = logging.getLogger("EnvLoader")

# ---------------------------------------------------------------------------
# Centralized Sovereign Paths
# Derived from __file__ — never hardcoded. Works regardless of install location.
# core/utils/env_loader.py → parents[0]=utils, parents[1]=core, parents[2]=project root
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH  = PROJECT_ROOT / "config.toml"
DATA_DIR     = PROJECT_ROOT / "data"
ENV_STATUS   = Path("/dev/shm/env_status.json")

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
