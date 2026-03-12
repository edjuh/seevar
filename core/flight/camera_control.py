#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/camera_control.py
Version: 2.0.0
Objective: Hardware status interface for ZWO S30-Pro via Sovereign TCP.

Replaces the v1.0.0 stub (capture() -> True).
Primary role: preflight hardware gate in orchestrator._run_preflight().

Protocol:
  Port 4700  JSON-RPC control  (text, \\r\\n terminated)
  Method: get_device_state  — returns device health dict
  Method: iscope_stop_view  — safe park before session start

Only imports from core.flight.pilot so there is a single wire-protocol
source of truth (ControlSocket lives there).
"""

import logging
from typing import Optional

from core.flight.pilot import ControlSocket, SEESTAR_HOST, CTRL_PORT

log = logging.getLogger("seevar.camera_control")


class CameraControl:
    """
    Thin wrapper around the S30-Pro control socket.
    Used by orchestrator preflight to verify hardware is alive.
    """

    def __init__(self, host: str = SEESTAR_HOST, port: int = CTRL_PORT,
                 timeout: float = 10.0):
        self.host    = host
        self.port    = port
        self.timeout = timeout

    def get_view_status(self) -> bool:
        """
        Send get_device_state, expect a response dict.
        Returns True if the device responds with any result payload.
        Returns False on connection failure or timeout.

        This is the preflight hardware gate — any valid JSON response
        means the device is alive and accepting commands.
        """
        try:
            with ControlSocket(self.host, self.port, self.timeout) as ctrl:
                sent = ctrl.send("get_device_state")
                if not sent:
                    log.error("get_view_status: send failed")
                    return False
                resp = ctrl.recv_response()
                if resp is None:
                    log.error("get_view_status: no response")
                    return False
                # Any valid JSON response means the device is alive.
                # Log what we got for visibility.
                result = resp.get("result") or resp.get("params") or resp
                log.info("get_device_state response: %s", result)
                return True
        except Exception as e:
            log.error("get_view_status: exception: %s", e)
            return False

    def safe_stop(self) -> bool:
        """
        Send iscope_stop_view — call before starting a new session
        to clear any lingering exposure state.
        Returns True if command was sent (not acknowledged — fire and forget).
        """
        try:
            with ControlSocket(self.host, self.port, self.timeout) as ctrl:
                return ctrl.send("iscope_stop_view")
        except Exception as e:
            log.error("safe_stop: exception: %s", e)
            return False
