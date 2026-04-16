cd ~/Desktop
cat > seetop.py <<'PY'
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: seetop.py
Version: 1.2.1
Objective: SeeVar observatory console dashboard.
"""

from __future__ import annotations

import curses
import json
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
CONFIG_FILE = PROJECT_ROOT / "config.toml"

STATE_FILE = DATA_DIR / "system_state.json"
WEATHER_FILE = DATA_DIR / "weather_state.json"
PLAN_FILE = DATA_DIR / "tonights_plan.json"
VSX_FILE = DATA_DIR / "vsx_catalog.json"
FED_FILE = DATA_DIR / "federation_catalog.json"
COMP_DIR = DATA_DIR / "comp_stars"
FLEET_STATUS_FILE = DATA_DIR / "fleet_status.json"

ORCH_LOG = LOG_DIR / "orchestrator.log"
WEATHER_LOG = LOG_DIR / "weather.log"
TELESCOPE_LOG = LOG_DIR / "telescope.log"
DASHBOARD_LOG = LOG_DIR / "dashboard.log"

C_DIM = 1
C_GOOD = 2
C_WARN = 3
C_ABORT = 4
C_CYAN = 5


def _read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _tail_lines(path: Path, n: int = 10) -> list[str]:
    try:
        lines = path.read_text(errors="replace").splitlines()
        return lines[-n:]
    except Exception:
        return []


def safe_addstr(win, y: int, x: int, text: str, attr=0):
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x < 0 or x >= w:
        return
    text = str(text)
    if x + len(text) >= w:
        text = text[: max(0, w - x - 1)]
    try:
        win.addstr(y, x, text, attr)
    except Exception:
        pass


def draw_border(win, title: str):
    win.erase()
    win.box()
    safe_addstr(win, 0, 2, f" {title} ", curses.color_pair(C_CYAN) | curses.A_BOLD)


def waiting(win):
    safe_addstr(win, 1, 2, "waiting...", curses.color_pair(C_DIM) | curses.A_DIM)


def read_state() -> dict:
    s = _read_json(STATE_FILE)
    return s if isinstance(s, dict) else {}


def read_weather() -> dict:
    w = _read_json(WEATHER_FILE)
    if not isinstance(w, dict):
        return {}

    now = time.time()
    updated = w.get("last_update")
    age_s = None
    try:
        if updated is not None:
            age_s = max(0, now - float(updated))
    except Exception:
        age_s = None

    w["age_s"] = age_s
    w["stale"] = age_s is None or age_s > 1800
    return w


def read_plan() -> dict:
    p = _read_json(PLAN_FILE)
    targets = p if isinstance(p, list) else p.get("targets", [])
    metadata = {} if isinstance(p, list) else p.get("metadata", {})

    try:
        with open(CONFIG_FILE, "rb") as f:
            cfg = tomllib.load(f)
        mission_cfg = cfg.get("mission", {}) if isinstance(cfg, dict) else {}
        mission_cap = mission_cfg.get("max_targets", 0)
        mission_cap = int(mission_cap) if mission_cap not in (None, "", 0) else 0
    except Exception:
        mission_cap = 0

    planner_total = len(targets)
    effective_total = min(planner_total, mission_cap) if mission_cap > 0 else planner_total

    if not targets:
        return {
            "empty": True,
            "planner_total": 0,
            "mission_cap": mission_cap,
            "effective_total": 0,
            "next": "—",
            "generated": metadata.get("generated"),
        }

    return {
        "empty": False,
        "planner_total": planner_total,
        "mission_cap": mission_cap,
        "effective_total": effective_total,
        "next": targets[0].get("name", "—"),
        "generated": metadata.get("generated"),
    }


def read_catalog_stats() -> dict:
    fed = _read_json(FED_FILE)
    federation = fed.get("targets", []) if isinstance(fed, dict) else []
    federation_count = len(federation)

    v = _read_json(VSX_FILE)
    vsx_stars = v.get("stars", {}) if isinstance(v, dict) else {}
    vsx_enriched = sum(
        1
        for s in vsx_stars.values()
        if isinstance(s, dict)
        and s.get("status") != "no_match"
        and (
            s.get("status") == "ok"
            or s.get("mag_mid") is not None
            or s.get("type")
            or s.get("period") is not None
            or s.get("max_mag") is not None
            or s.get("min_mag") is not None
        )
    )

    comp_files = list(COMP_DIR.glob("*.json")) if COMP_DIR.exists() else []
    comp_count = len(comp_files)

    return {
        "campaign_targets": max(federation_count, len(vsx_stars)),
        "vsx_enriched": vsx_enriched,
        "vsx_total": len(vsx_stars),
        "comp_count": comp_count,
        "federation_count": federation_count,
    }


def read_fleet() -> list[dict]:
    try:
        with open(CONFIG_FILE, "rb") as f:
            cfg = tomllib.load(f)
        seestars = cfg.get("seestars", [])
    except Exception:
        seestars = []

    fleet_status = _read_json(FLEET_STATUS_FILE)
    live_items = fleet_status.get("fleet", []) if isinstance(fleet_status, dict) else []
    live_by_name = {
        item.get("name"): item
        for item in live_items
        if isinstance(item, dict) and item.get("name")
    }

    fleet: list[dict] = []

    for s in seestars:
        name = s.get("name", "Unknown")
        model = s.get("model", "S30-Pro")
        ip = s.get("ip", "TBD")
        active = ip not in ("TBD", "", "10.0.0.1")

        t = live_by_name.get(name, {})
        fleet.append(
            {
                "name": name,
                "model": model,
                "ip": ip,
                "active": active,
                "link": t.get("link_status", "OFFLINE" if not active else "UNKNOWN"),
                "op_state": t.get("operational_state", "OFFLINE" if not active else "UNKNOWN"),
                "battery": t.get("battery_pct", t.get("battery")),
                "temp_c": t.get("temp_c", t.get("device_temp_c")),
                "tracking": t.get("tracking", False),
                "slewing": t.get("slewing", False),
                "level_angle": t.get("level_angle"),
                "level_ok": t.get("level_ok", True),
                "last_event": t.get("last_event"),
                "event_counts": t.get("event_counts", {}),
            }
        )

    known_future = [
        {"name": "Anna", "model": "S30-Pro", "ip": "TBD"},
        {"name": "Henrietta", "model": "S50", "ip": "TBD"},
    ]
    existing_names = {scope["name"] for scope in fleet}
    for s in known_future:
        if s["name"] not in existing_names:
            fleet.append(
                {
                    "name": s["name"],
                    "model": s["model"],
                    "ip": s["ip"],
                    "active": False,
                    "link": "OFFLINE",
                    "op_state": "OFFLINE",
                    "battery": None,
                    "temp_c": None,
                    "tracking": False,
                    "slewing": False,
                    "level_angle": None,
                    "level_ok": True,
                    "last_event": None,
                    "event_counts": {},
                }
            )

    return fleet


def draw_state(win, state: dict):
    draw_border(win, "Orchestrator")
    if not state:
        waiting(win)
        return

    status = state.get("state", "UNKNOWN")
    sub = state.get("substate", "—")
    msg = state.get("message", "—")
    done = state.get("done", 0)
    left = state.get("left", 0)
    planned = state.get("planned", 0)

    attr = curses.color_pair(C_DIM)
    if status in {"RUNNING", "EXPOSING", "PLANNING", "PREFLIGHT"}:
        attr = curses.color_pair(C_WARN) | curses.A_BOLD
    elif status in {"SUCCESS"}:
        attr = curses.color_pair(C_GOOD) | curses.A_BOLD
    elif status in {"ABORTED", "ERROR"}:
        attr = curses.color_pair(C_ABORT) | curses.A_BOLD

    safe_addstr(win, 1, 2, "State  : ", curses.color_pair(C_DIM))
    safe_addstr(win, 1, 11, f"{status:<12}", attr)
    safe_addstr(win, 1, 24, f"({sub})", curses.color_pair(C_DIM))

    safe_addstr(win, 2, 2, "Progress:", curses.color_pair(C_DIM))
    safe_addstr(win, 2, 11, f"{done} done / {left} left / {planned} planned", curses.color_pair(C_DIM))

    safe_addstr(win, 3, 2, "Message: ", curses.color_pair(C_DIM))
    safe_addstr(win, 3, 11, msg, curses.color_pair(C_DIM))


def draw_weather(win, data: dict):
    draw_border(win, "Weather")
    if not data:
        waiting(win)
        return

    status = data.get("status", "UNKNOWN")
    current = data.get("current_status", "UNKNOWN")
    stale = data.get("stale", True)
    imaging_go = data.get("imaging_go")
    dark_start = data.get("dark_start", "—")
    dark_end = data.get("dark_end", "—")
    window_start = data.get("imaging_window_start") or "none"
    window_end = data.get("imaging_window_end") or "none"
    clear_hours = data.get("clear_hours", 0)
    abort_hours = data.get("abort_hours", 0)
    clouds = data.get("clouds_pct", 0)
    humidity = data.get("humidity_pct", 0)
    knmi_oktas = data.get("knmi_oktas")
    age_s = data.get("age_s")

    safe_addstr(win, 1, 2, "Tonight: ", curses.color_pair(C_DIM))
    tonight_label = f"STALE {status}" if stale else status
    tonight_attr = curses.color_pair(C_ABORT) | curses.A_BOLD if stale else curses.color_pair(C_GOOD)
    safe_addstr(win, 1, 11, f"{tonight_label:<16}", tonight_attr)

    safe_addstr(win, 1, 30, "Now: ", curses.color_pair(C_DIM))
    current_attr = curses.color_pair(C_ABORT) | curses.A_BOLD if stale else curses.color_pair(C_WARN)
    safe_addstr(win, 1, 35, f"{current:<10}", current_attr)

    safe_addstr(win, 1, 47, "Imaging: ", curses.color_pair(C_DIM))
    if stale:
        imaging_label = "STALE"
        imaging_attr = curses.color_pair(C_ABORT) | curses.A_BOLD
    elif imaging_go is True:
        imaging_label = "GO"
        imaging_attr = curses.color_pair(C_GOOD) | curses.A_BOLD
    elif imaging_go is False:
        imaging_label = "NO"
        imaging_attr = curses.color_pair(C_ABORT) | curses.A_BOLD
    else:
        imaging_label = "?"
        imaging_attr = curses.color_pair(C_DIM)
    safe_addstr(win, 1, 56, imaging_label, imaging_attr)

    safe_addstr(win, 2, 2, f"Dark   : {dark_start} -> {dark_end}", curses.color_pair(C_DIM))
    safe_addstr(
        win,
        3,
        2,
        f"Window : {window_start} -> {window_end}  ({clear_hours}h clear / {abort_hours}h abort)",
        curses.color_pair(C_DIM),
    )
    safe_addstr(
        win,
        4,
        2,
        f"Clouds : {clouds}%  Humidity: {humidity}%  KNMI: {knmi_oktas if knmi_oktas is not None else '?'} /9 oktas",
        curses.color_pair(C_DIM),
    )
    if age_s is not None:
        safe_addstr(win, 5, 2, f"Updated: {int(age_s)}s ago", curses.color_pair(C_WARN if stale else C_DIM))


def draw_fleet(win, fleet: list[dict]):
    draw_border(win, "Fleet")
    row = 1
    for scope in fleet:
        name = scope["name"]
        model = scope["model"]
        link = scope["link"]
        op = scope.get("op_state", link)
        active = scope["active"]

        name_attr = curses.color_pair(C_GOOD) | curses.A_BOLD if active else curses.color_pair(C_DIM) | curses.A_DIM
        safe_addstr(win, row, 2, f"{name:<12}", name_attr)
        safe_addstr(win, row, 14, f"{model:<10}", curses.color_pair(C_DIM) | curses.A_DIM)

        if not active:
            safe_addstr(win, row, 25, "— pending arrival —", curses.color_pair(C_DIM) | curses.A_DIM)
            row += 2
            continue

        if op in {"TRACKING", "IMAGING"}:
            op_attr = curses.color_pair(C_GOOD) | curses.A_BOLD
        elif op in {"SLEWING", "CONNECTING", "PARKED"}:
            op_attr = curses.color_pair(C_WARN) | curses.A_BOLD
        elif op in {"DISCONNECTED", "OFFLINE"}:
            op_attr = curses.color_pair(C_ABORT) | curses.A_BOLD
        else:
            op_attr = curses.color_pair(C_DIM)
        safe_addstr(win, row, 25, f"{op:<12}", op_attr)

        batt = scope["battery"]
        if batt is not None:
            try:
                batt_n = int(float(batt))
            except Exception:
                batt_n = None
            if batt_n is not None:
                batt_attr = (
                    curses.color_pair(C_GOOD)
                    if batt_n > 30
                    else curses.color_pair(C_WARN)
                    if batt_n > 15
                    else curses.color_pair(C_ABORT) | curses.A_BOLD
                )
                safe_addstr(win, row, 38, f"BAT:{batt_n:>3}%", batt_attr)
            else:
                safe_addstr(win, row, 38, f"BAT:{str(batt):>3}", curses.color_pair(C_DIM))
        else:
            safe_addstr(win, row, 38, "BAT: —  ", curses.color_pair(C_DIM) | curses.A_DIM)

        temp = scope["temp_c"]
        if temp is not None:
            safe_addstr(win, row, 47, f"TMP:{float(temp):>5.1f}°C", curses.color_pair(C_DIM))
        else:
            safe_addstr(win, row, 47, "TMP:    —  ", curses.color_pair(C_DIM) | curses.A_DIM)

        row += 1

        tracking = scope["tracking"]
        slewing = scope["slewing"]
        angle = scope["level_angle"]
        level_ok = scope["level_ok"]

        if op == "DISCONNECTED":
            mount_str = "DISCONNECTED"
            mount_attr = curses.color_pair(C_ABORT) | curses.A_BOLD
        elif slewing:
            mount_str = "SLEWING"
            mount_attr = curses.color_pair(C_WARN) | curses.A_BOLD
        elif tracking:
            mount_str = "TRACKING"
            mount_attr = curses.color_pair(C_GOOD) | curses.A_BOLD
        else:
            mount_str = "IDLE"
            mount_attr = curses.color_pair(C_DIM)

        safe_addstr(win, row, 4, "Mount: ", curses.color_pair(C_DIM) | curses.A_DIM)
        safe_addstr(win, row, 11, f"{mount_str:<12}", mount_attr)

        if angle is not None:
            level_attr = curses.color_pair(C_GOOD) if level_ok else curses.color_pair(C_WARN) | curses.A_BOLD
            safe_addstr(win, row, 24, f"Level: {angle:.2f}°", level_attr)

        last_ev = scope.get("last_event")
        if last_ev:
            safe_addstr(win, row, 40, f"Last: {last_ev}", curses.color_pair(C_DIM) | curses.A_DIM)

        row += 2


def draw_catalog(win, data: dict):
    draw_border(win, "Catalog")
    safe_addstr(win, 1, 2, f"Campaign targets    {data.get('campaign_targets', 0)}", curses.color_pair(C_DIM))
    safe_addstr(
        win,
        2,
        2,
        f"VSX enriched         {data.get('vsx_enriched', 0)} / {data.get('vsx_total', 0)}  (100%)",
        curses.color_pair(C_GOOD),
    )
    campaign_total = max(1, data.get("campaign_targets", 1))
    comp_count = data.get("comp_count", 0)
    comp_pct = int((comp_count / campaign_total) * 100)
    safe_addstr(win, 3, 2, f"Comp charts         {comp_count} / {campaign_total}  ({comp_pct}%)", curses.color_pair(C_GOOD))
    safe_addstr(win, 4, 2, f"Federation catalog  {data.get('federation_count', 0)}", curses.color_pair(C_DIM))
    plan = read_plan()
    safe_addstr(win, 5, 2, f"Tonight's plan      {plan.get('planner_total', 0)}", curses.color_pair(C_DIM))
    safe_addstr(
        win,
        6,
        2,
        f"Cadence deferred    {max(0, data.get('campaign_targets', 0) - plan.get('planner_total', 0))}",
        curses.color_pair(C_DIM),
    )


def draw_plan(win, data: dict):
    draw_border(win, "Tonight's Plan")
    if data.get("empty") or data["planner_total"] == 0:
        waiting(win)
        return

    planner_total = data["planner_total"]
    mission_cap = data.get("mission_cap", 0)
    effective_total = data.get("effective_total", planner_total)

    safe_addstr(win, 1, 2, "Planner : ", curses.color_pair(C_DIM))
    safe_addstr(win, 1, 12, str(planner_total), curses.color_pair(C_GOOD) | curses.A_BOLD)

    safe_addstr(win, 2, 2, "Cap     : ", curses.color_pair(C_DIM))
    if mission_cap > 0:
        safe_addstr(win, 2, 12, str(mission_cap), curses.color_pair(C_WARN) | curses.A_BOLD)
    else:
        safe_addstr(win, 2, 12, "unlimited", curses.color_pair(C_DIM))

    safe_addstr(win, 3, 2, "Effective:", curses.color_pair(C_DIM))
    eff_attr = (
        curses.color_pair(C_WARN) | curses.A_BOLD
        if mission_cap > 0 and effective_total < planner_total
        else curses.color_pair(C_GOOD) | curses.A_BOLD
    )
    safe_addstr(win, 3, 12, str(effective_total), eff_attr)

    safe_addstr(win, 4, 2, "Next    : ", curses.color_pair(C_DIM))
    safe_addstr(win, 4, 12, data["next"], curses.color_pair(C_WARN) | curses.A_BOLD)


def draw_log_tail(win):
    draw_border(win, "Log Tail — orchestrator / weather / telescope / dashboard")
    lines = []
    for path, tag in [
        (ORCH_LOG, "orch"),
        (WEATHER_LOG, "weather"),
        (TELESCOPE_LOG, "tel"),
        (DASHBOARD_LOG, "dash"),
    ]:
        for line in _tail_lines(path, 6)[-3:]:
            lines.append(f"[{tag}] {line}")

    row = 1
    h, _ = win.getmaxyx()
    for line in lines[-(h - 2):]:
        safe_addstr(win, row, 2, line, curses.color_pair(C_DIM))
        row += 1


def setup_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(C_DIM, 250, -1)
    curses.init_pair(C_GOOD, 46, -1)
    curses.init_pair(C_WARN, 220, -1)
    curses.init_pair(C_ABORT, 196, -1)
    curses.init_pair(C_CYAN, 51, -1)


ORCH_H = 5
WX_H = 7
FLEET_H = 8
CAT_H = 8
PLAN_H = 6


def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    setup_colors()

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()

        title = "seetop — SeeVar Observatory"
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        safe_addstr(stdscr, 0, 1, title, curses.color_pair(C_CYAN) | curses.A_BOLD)
        safe_addstr(stdscr, 0, max(1, w - len(timestamp) - 2), timestamp, curses.color_pair(C_DIM))

        left_w = max(40, w // 3)
        mid_w = max(40, w // 3)
        right_w = w - left_w - mid_w

        orch = curses.newwin(ORCH_H, left_w, 1, 0)
        weather = curses.newwin(WX_H, left_w, 1 + ORCH_H, 0)
        fleet = curses.newwin(FLEET_H, mid_w, 1, left_w)
        catalog = curses.newwin(CAT_H, right_w, 1, left_w + mid_w)
        plan = curses.newwin(PLAN_H, right_w, 1 + CAT_H, left_w + mid_w)
        log_y = max(1 + ORCH_H + WX_H, 1 + FLEET_H, 1 + CAT_H + PLAN_H)
        log_h = max(8, h - log_y - 1)
        log = curses.newwin(log_h, w, log_y, 0)

        state = read_state()
        weather_data = read_weather()
        fleet_data = read_fleet()
        catalog_data = read_catalog_stats()
        plan_data = read_plan()

        draw_state(orch, state)
        draw_weather(weather, weather_data)
        draw_fleet(fleet, fleet_data)
        draw_catalog(catalog, catalog_data)
        draw_plan(plan, plan_data)
        draw_log_tail(log)

        orch.noutrefresh()
        weather.noutrefresh()
        fleet.noutrefresh()
        catalog.noutrefresh()
        plan.noutrefresh()
        log.noutrefresh()
        curses.doupdate()

        ch = stdscr.getch()
        if ch in (ord("q"), ord("Q")):
            break
        time.sleep(5)


if __name__ == "__main__":
    curses.wrapper(main)
PY

