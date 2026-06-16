#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/seestar_alp_adapter.py
Objective: Optional seestar_alp-backed flight control adapter behind the SeeVar pilot interface.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Protocol

from core.flight.pilot import AcquisitionTarget, FrameResult, GAIN, TelemetryBlock
from core.utils.env_loader import load_config, selected_scope, selected_scope_host

logger = logging.getLogger("seevar.seestar_alp_adapter")


class SSalpClientProtocol(Protocol):
    # Function: SSalpClientProtocol.test_connection_sync
    def test_connection_sync(self) -> dict: ...

    # Function: SSalpClientProtocol.goto_target_sync
    def goto_target_sync(self, target_name: str, ra: float, dec: float, is_j2000: bool = True) -> dict: ...

    # Function: SSalpClientProtocol.scope_get_track_state_sync
    def scope_get_track_state_sync(self) -> dict: ...

    # Function: SSalpClientProtocol.scope_set_track_state_sync
    def scope_set_track_state_sync(self, enabled: bool) -> dict: ...

    # Function: SSalpClientProtocol.start_solve_sync
    def start_solve_sync(self) -> dict: ...

    # Function: SSalpClientProtocol.get_solve_result_sync
    def get_solve_result_sync(self) -> dict: ...

    # Function: SSalpClientProtocol.start_stack_sync
    def start_stack_sync(self, gain: int, restart: bool = True) -> dict: ...

    # Function: SSalpClientProtocol.get_last_image_sync
    def get_last_image_sync(self, is_subframe: bool = True, is_thumb: bool = False) -> dict: ...


# Function: _seestar_alp_cfg
def _seestar_alp_cfg() -> dict:
    cfg = load_config()
    return cfg.get("seestar_alp", {}) if isinstance(cfg, dict) else {}


# Function: _truthy
def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        for key in ("ok", "success", "solved", "tracking", "is_tracking", "state", "enabled", "Value"):
            if key in value:
                return _truthy(value[key])
    if isinstance(value, str):
        return value.strip().lower() in {"true", "on", "tracking", "solved", "ok", "success", "1"}
    return bool(value)


# Function: _extract_path
def _extract_path(value: Any) -> Path | None:
    if isinstance(value, (str, Path)):
        text = str(value).strip()
        return Path(text) if text else None
    if isinstance(value, dict):
        for key in ("path", "file", "file_path", "fits", "fits_path", "filename", "local_path"):
            if key in value:
                found = _extract_path(value[key])
                if found:
                    return found
        for child in value.values():
            found = _extract_path(child)
            if found:
                return found
    if isinstance(value, (list, tuple)):
        for child in value:
            found = _extract_path(child)
            if found:
                return found
    return None


class SeestarAlpSequence:
    # Function: SeestarAlpSequence.__init__
    def __init__(self, host: str | None = None, port: int | None = None, client: SSalpClientProtocol | None = None):
        cfg = load_config()
        scope = selected_scope(cfg if isinstance(cfg, dict) else {})
        resolved_host, source = selected_scope_host(cfg if isinstance(cfg, dict) else {}) if not host else (host, "explicit")
        alp_cfg = _seestar_alp_cfg()
        self.host = resolved_host
        self.port = int(port or alp_cfg.get("port") or alp_cfg.get("alpaca_port") or scope.get("alpaca_port") or 5555)
        self.base_url = str(alp_cfg.get("base_url") or f"http://{self.host}:{self.port}")
        self.host_source = source
        self.client = client or self._build_client()
        self._session_ready = False
        logger.info("SeestarAlpSequence endpoint: %s (%s)", self.base_url, self.host_source)

    # Function: SeestarAlpSequence._build_client
    def _build_client(self) -> SSalpClientProtocol:
        try:
            from ssalp_api_client import SSAlpApiClient
        except Exception as e:
            raise RuntimeError(f"ssalp_api_client unavailable: {e}") from e
        return SSAlpApiClient(base_url=self.base_url)

    # Function: SeestarAlpSequence.init_session
    def init_session(self, level_ok: bool = True) -> TelemetryBlock:
        try:
            response = self.client.test_connection_sync()
            tracking_state = self.client.scope_get_track_state_sync()
            telemetry = TelemetryBlock(
                raw={"connection": response, "tracking": tracking_state},
                tracking=_truthy(tracking_state),
                level_ok=level_ok,
            )
            self._session_ready = True
            return telemetry
        except Exception as e:
            self._session_ready = False
            return TelemetryBlock(parse_error=f"seestar_alp init_session failed: {e}", level_ok=level_ok)

    # Function: SeestarAlpSequence.prepare_target
    def prepare_target(self, target: AcquisitionTarget, telemetry: TelemetryBlock | None = None, notify=None) -> AcquisitionTarget:
        return target

    # Function: SeestarAlpSequence._notify
    def _notify(self, status_cb, step: str, msg: str) -> None:
        if status_cb:
            status_cb(f"[{step}] {msg}")
        logger.info("[%s] %s", step, msg)

    # Function: SeestarAlpSequence._ensure_tracking
    def _ensure_tracking(self) -> dict:
        state = self.client.scope_get_track_state_sync()
        if not _truthy(state):
            self.client.scope_set_track_state_sync(True)
            state = self.client.scope_get_track_state_sync()
        if not _truthy(state):
            raise RuntimeError("seestar_alp tracking did not enable")
        return state

    # Function: SeestarAlpSequence.acquire
    def acquire(
        self,
        target: AcquisitionTarget,
        status_cb=None,
        telemetry: TelemetryBlock | None = None,
        skip_pointing: bool = False,
        abort_callback=None,
    ) -> FrameResult:
        start = time.monotonic()
        try:
            if abort_callback and abort_callback():
                return FrameResult(success=False, error="operator_abort")

            if not skip_pointing:
                self._notify(status_cb, "A4", f"seestar_alp slew to {target.name}")
                self.client.goto_target_sync(target.name, float(target.ra_hours), float(target.dec_deg), True)
                self._notify(status_cb, "A7", "seestar_alp solve")
                self.client.start_solve_sync()
                solve = self.client.get_solve_result_sync()
                if not _truthy(solve):
                    return FrameResult(success=False, error=f"seestar_alp solve failed: {solve}")
                self._notify(status_cb, "A7", "Solve success")

            self._ensure_tracking()
            self._notify(status_cb, "A8", "Tracking proof accepted")

            self._notify(status_cb, "A10", f"seestar_alp stack exposure for {target.name}")
            self.client.start_stack_sync(gain=GAIN, restart=False)
            image = self.client.get_last_image_sync(is_subframe=False, is_thumb=False)
            path = _extract_path(image)
            if not path:
                return FrameResult(success=False, error=f"seestar_alp returned no image path: {image}")
            self._notify(status_cb, "A11", f"Frame accepted: {path}")
            return FrameResult(success=True, path=path, elapsed_s=time.monotonic() - start)
        except Exception as e:
            logger.exception("seestar_alp acquire failed: %s", e)
            return FrameResult(success=False, error=f"seestar_alp acquire failed: {e}", elapsed_s=time.monotonic() - start)

    # Function: SeestarAlpSequence.park
    def park(self):
        logger.info("seestar_alp park not implemented by adapter")

    # Function: SeestarAlpSequence.at_park
    def at_park(self) -> bool:
        return False

    # Function: SeestarAlpSequence.shutdown_scope
    def shutdown_scope(self):
        raise RuntimeError("seestar_alp shutdown not implemented by adapter")

    # Function: SeestarAlpSequence.disconnect_all
    def disconnect_all(self):
        return None
