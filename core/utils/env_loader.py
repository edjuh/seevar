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
import time
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
_LIVE_SCOPE_CACHE = {
    "timestamp": 0.0,
    "signature": (),
    "scopes": [],
}

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


def selected_scope_host(
    cfg: dict | None = None,
    scope_id: str | None = None,
    *,
    fallback: str = "10.0.0.1",
) -> tuple[str, str]:
    cfg = cfg if isinstance(cfg, dict) else load_config()

    alpaca_cfg = cfg.get("alpaca", {}) if isinstance(cfg, dict) else {}
    alpaca_host = str(alpaca_cfg.get("host", "")).strip()
    if alpaca_host and alpaca_host != "TBD":
        return alpaca_host, "config.alpaca.host"

    scope = selected_scope(cfg, scope_id)
    if scope:
        for key in ("host", "ip"):
            value = str(scope.get(key, "")).strip()
            if value and value != "TBD":
                scope_ref = scope.get("scope_id") or scope.get("scope_name") or "scope"
                return value, f"config.{scope_ref}.{key}"

    return fallback, "fallback.default"


def live_available_scopes(cfg: dict | None = None, *, cache_ttl: float = 5.0) -> list[dict]:
    cfg = cfg if isinstance(cfg, dict) else load_config()
    scopes = configured_scopes(cfg, active_only=True)
    signature = tuple((scope.get("scope_id"), scope.get("ip")) for scope in scopes)
    now = time.time()

    if (
        _LIVE_SCOPE_CACHE["signature"] == signature
        and now - float(_LIVE_SCOPE_CACHE["timestamp"]) <= float(cache_ttl)
    ):
        return [dict(scope) for scope in _LIVE_SCOPE_CACHE["scopes"]]

    available = []
    try:
        from core.hardware.live_scope_status import poll_scope_status
    except Exception as e:
        log.warning("Could not import live scope polling: %s", e)
        return scopes

    for scope in scopes:
        status = poll_scope_status(scope.get("ip", ""))
        if status.get("link_status") == "ONLINE":
            enriched = dict(scope)
            enriched["live_status"] = status
            available.append(enriched)

    _LIVE_SCOPE_CACHE["timestamp"] = now
    _LIVE_SCOPE_CACHE["signature"] = signature
    _LIVE_SCOPE_CACHE["scopes"] = [dict(scope) for scope in available]
    return [dict(scope) for scope in available]


def effective_fleet_mode(cfg: dict | None = None) -> str:
    cfg = cfg if isinstance(cfg, dict) else load_config()
    requested = str(cfg.get("planner", {}).get("fleet_mode", "single")).strip().lower()
    active_count = len(live_available_scopes(cfg))

    if requested == "auto":
        return "split" if active_count >= 2 else "single"
    if requested == "split":
        return "split" if active_count >= 2 else "single"
    return "single"


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

    for scope in live_available_scopes(cfg):
        ip = str(scope.get("ip", "")).strip()
        if ip and ip != "TBD":
            return scope

    for scope in scopes:
        ip = str(scope.get("ip", "")).strip()
        if ip and ip != "TBD":
            return scope

    return scopes[0] if scopes else {}


def scope_file_tag(scope: dict | None = None, *, fallback: str = "scope") -> str:
    scope = scope if isinstance(scope, dict) else {}

    for candidate in (
        scope.get("scope_id"),
        scope.get("scope_name"),
        scope.get("name"),
    ):
        token = _norm_scope_token(candidate or "")
        if token:
            return token

    return _norm_scope_token(fallback) or "scope"
