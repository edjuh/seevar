#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/hardware/wilhelmina_monitor.py
Version:  1.0.2
Objective: Persistent event stream listener for ZWO Seestar port 4700.
           Connects to the telescope, parses broadcast JSON events, and
           writes a live state snapshot to /dev/shm/wilhelmina_state.json.
           Reconnects automatically after 2s on disconnect.

           Event vocabulary (observed on S30-Pro firmware 7.18):
             PiStatus           -> battery_capacity, temp
             ScopeGoto          -> state, lapse_ms, close
             ScopeTrack         -> state, tracking, manual
             BalanceSensor      -> data.x, data.y, data.z, data.angle
             Demonstrate        -> demo mode active
             CompassCalibration -> compass cal state
             ScopeHome          -> homing sequence
             SelectCamera       -> camera selection
             GoPixel            -> mount positioning
             RTSP               -> video stream
             View               -> viewing state
             WheelMove          -> filter wheel
             Setting            -> settings changes
             SecondView         -> secondary view
             FocuserMove        -> autofocus
             ScanSun            -> sun scan
             SaveImage          -> image saved
"""

import json
import logging
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.env_loader import load_config

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "telescope.log", mode="a"),
    ],
)
log = logging.getLogger("WilhelminaMonitor")

CTRL_PORT       = 4700
STATE_PATH      = Path("/dev/shm/wilhelmina_state.json")
RECONNECT_DELAY = 2
RECV_TIMEOUT    = 5.0
SILENCE_LIMIT   = 60


def _get_seestar_ip() -> str:
    try:
        cfg = load_config()
        seestars = cfg.get("seestars", [{}])
        ip = seestars[0].get("ip", "TBD")
        if ip in ("TBD", "", "10.0.0.1"):
            return "10.0.0.1"
        return ip
    except Exception:
        return "10.0.0.1"


class TelescopeState:
    def __init__(self):
        self.link_status     = "WAITING"
        self.battery_pct     = None
        self.temp_c          = None
        self.tracking        = False
        self.slewing         = False
        self.slew_state      = None
        self.level_angle     = None
        self.level_ok        = True
        self.demo_mode       = False
        self.compass_cal     = None
        self.homing          = False
        self.last_event      = None
        self.last_event_ts   = None
        self.connected_since = None
        self.event_counts    = {}

    def apply_event(self, msg: dict):
        event = msg.get("Event")
        if not event:
            return
        self.last_event    = event
        self.last_event_ts = datetime.now(timezone.utc).isoformat()
        self.event_counts[event] = self.event_counts.get(event, 0) + 1

        if event == "PiStatus":
            if "battery_capacity" in msg:
                self.battery_pct = msg["battery_capacity"]
            if "temp" in msg:
                self.temp_c = round(msg["temp"], 1)

        elif event == "ScopeTrack":
            self.tracking = msg.get("tracking", False)

        elif event == "ScopeGoto":
            state = msg.get("state", "")
            self.slew_state = state
            self.slewing    = state == "working"

        elif event == "BalanceSensor":
            data = msg.get("data", {})
            self.level_angle = data.get("angle")
            self.level_ok    = self.level_angle is not None and self.level_angle < 1.5

        elif event == "Demonstrate":
            self.demo_mode = msg.get("state", "") not in ("complete", "off", "")

        elif event == "CompassCalibration":
            self.compass_cal = msg.get("state")

        elif event == "ScopeHome":
            self.homing = msg.get("state", "") == "working"

    def to_dict(self) -> dict:
        return {
            "#objective":      "Live Seestar telemetry from port 4700 event stream.",
            "timestamp":       datetime.now(timezone.utc).isoformat(),
            "link_status":     self.link_status,
            "battery_pct":     self.battery_pct,
            "temp_c":          self.temp_c,
            "tracking":        self.tracking,
            "slewing":         self.slewing,
            "slew_state":      self.slew_state,
            "level_angle":     self.level_angle,
            "level_ok":        self.level_ok,
            "demo_mode":       self.demo_mode,
            "compass_cal":     self.compass_cal,
            "homing":          self.homing,
            "last_event":      self.last_event,
            "last_event_ts":   self.last_event_ts,
            "connected_since": self.connected_since,
            "event_counts":    self.event_counts,
        }


def write_state(state: TelescopeState):
    try:
        STATE_PATH.write_text(json.dumps(state.to_dict(), indent=2))
    except OSError as e:
        log.warning("Failed to write state: %s", e)


def monitor(host: str):
    state = TelescopeState()
    while True:
        log.info("Connecting to %s:%d ...", host, CTRL_PORT)
        state.link_status = "CONNECTING"
        write_state(state)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(RECV_TIMEOUT)
            sock.connect((host, CTRL_PORT))
        except (socket.error, OSError) as e:
            log.warning("Connection failed: %s — retrying in %ds", e, RECONNECT_DELAY)
            state.link_status = "OFFLINE"
            state.battery_pct = None
            state.temp_c      = None
            write_state(state)
            time.sleep(RECONNECT_DELAY)
            continue

        log.info("Connected to Wilhelmina @ %s:%d", host, CTRL_PORT)
        state.link_status     = "ONLINE"
        state.connected_since = datetime.now(timezone.utc).isoformat()
        write_state(state)

        buf          = b""
        last_data_ts = time.monotonic()

        try:
            while True:
                if time.monotonic() - last_data_ts > SILENCE_LIMIT:
                    log.warning("No data for %ds — assuming disconnect.", SILENCE_LIMIT)
                    break
                try:
                    chunk = sock.recv(4096)
                    if not chunk:
                        log.info("Connection closed by telescope.")
                        break
                    buf          += chunk
                    last_data_ts  = time.monotonic()
                    while b"\r\n" in buf:
                        line, buf = buf.split(b"\r\n", 1)
                        if not line:
                            continue
                        try:
                            msg   = json.loads(line.decode("utf-8"))
                            event = msg.get("Event", "Response")
                            state.apply_event(msg)
                            write_state(state)
                            if state.event_counts.get(event, 0) == 1:
                                log.info("NEW EVENT TYPE: %s — %s", event, msg)
                        except json.JSONDecodeError:
                            log.debug("Non-JSON line: %r", line)
                except socket.timeout:
                    continue
                except socket.error as e:
                    log.warning("Socket error: %s", e)
                    break
        finally:
            sock.close()
            state.link_status = "OFFLINE"
            state.battery_pct = None
            state.temp_c      = None
            write_state(state)
            log.info("Disconnected. Reconnecting in %ds ...", RECONNECT_DELAY)
            time.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    host = _get_seestar_ip()
    log.info("WilhelminaMonitor v1.0.2 starting — target: %s:%d", host, CTRL_PORT)
    log.info("State file: %s", STATE_PATH)
    try:
        monitor(host)
    except KeyboardInterrupt:
        log.info("Interrupted — exiting.")
