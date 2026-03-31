#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/camera_control.py
Version: 3.0.0
Objective: Hardware status interface for ZWO S30-Pro via Alpaca REST.
           Replaces TCP port 4700 health check with Alpaca management API.
"""

import logging
import requests
from typing import Optional

from core.flight.pilot import SEESTAR_HOST, ALPACA_PORT

log = logging.getLogger("seevar.camera_control")


class CameraControl:
    """
    Thin Alpaca wrapper for preflight hardware gate.
    Replaces TCP ControlSocket with HTTP management API ping.
    """

    def __init__(self, host: str = SEESTAR_HOST, port: int = ALPACA_PORT,
                 timeout: float = 10.0):
        self.host    = host
        self.port    = port
        self.timeout = timeout
        self._base   = f"http://{host}:{port}"

    def get_view_status(self) -> bool:
        """
        Ping Alpaca management API. Returns True if device responds.
        This is the preflight hardware gate.
        """
        try:
            r = requests.get(
                f"{self._base}/management/v1/configureddevices",
                timeout=self.timeout)
            if r.status_code == 200:
                devices = r.json().get("Value", [])
                log.info("Alpaca alive: %d devices on %s:%d",
                         len(devices), self.host, self.port)
                return True
            log.error("Alpaca returned status %d", r.status_code)
            return False
        except Exception as e:
            log.error("get_view_status: %s", e)
            return False

    def safe_stop(self) -> bool:
        """
        Park telescope via Alpaca — replaces iscope_stop_view.
        Returns True if park command accepted.
        """
        try:
            r = requests.put(
                f"{self._base}/api/v1/telescope/0/park",
                data={"ClientID": 42, "ClientTransactionID": 1},
                timeout=self.timeout)
            data = r.json()
            err = data.get("ErrorNumber", 0)
            if err:
                log.warning("safe_stop park error %d: %s",
                            err, data.get("ErrorMessage", ""))
                return False
            return True
        except Exception as e:
            log.error("safe_stop: %s", e)
            return False
