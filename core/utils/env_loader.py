#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/utils/env_loader.py
Version: 1.1.0
Objective: Single source of truth for SeeVar environment paths and TOML configuration loading.
"""

import os
import tomllib
import logging
import re
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


def configured_scopes(cfg: dict | None = None, *, active_only: bool = False) -> list[dict]:
    cfg = cfg if isinstance(cfg, dict) else load_config()
    scopes = []

    for idx, entry in enumerate(cfg.get("seestars", [])):
        if not isinstance(entry, dict):
            continue

        ip = str(entry.get("ip", "")).strip()
        if active_only and (not ip or ip == "TBD"):
            continue

        name = str(entry.get("name", f"Scope-{idx + 1}")).strip() or f"Scope-{idx + 1}"
        enriched = dict(entry)
        enriched["scope_id"] = f"scope{idx + 1:02d}"
        enriched["scope_name"] = name
        scopes.append(enriched)

    return scopes


def _norm_scope_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).strip().lower())


def selected_scope_id() -> str | None:
    value = str(os.environ.get("SEEVAR_SCOPE_ID", "")).strip().lower()
    return value or None


def selected_scope(cfg: dict | None = None, scope_id: str | None = None) -> dict:
    cfg = cfg if isinstance(cfg, dict) else load_config()
    scope_id = (scope_id or selected_scope_id() or "").strip().lower()
    scope_token = _norm_scope_token(scope_id)
    scopes = configured_scopes(cfg, active_only=False)

    if scope_id:
        for scope in scopes:
            if str(scope.get("scope_id", "")).lower() == scope_id:
                return scope
            if _norm_scope_token(scope.get("scope_name", "")) == scope_token:
                return scope

    for scope in scopes:
        ip = str(scope.get("ip", "")).strip()
        if ip and ip != "TBD":
            return scope

    return scopes[0] if scopes else {}
