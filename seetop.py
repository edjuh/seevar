#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: seetop.py
Version: 1.2.0
Objective: Ncurses live dashboard for SeeVar — orchestrator state, weather
           consensus, full fleet telemetry (Wilhelmina + future Anna/Henrietta),
           catalog statistics, tonight's plan, and deduplicated log tail.
           Three-column layout. Atomic screen updates via doupdate.
           Refreshes every 5 seconds. Press q to quit.
Changes v1.2.0:
  - Fleet panel: reads all [[seestars]] from config.toml and shows live status
    from generic scope pollers
  - GPS row: lat/lon/maidenhead from /dev/shm/env_status.json
  - Log tail: deduplicates consecutive identical lines, adds telescope.log
  - 3-column layout
  - 5s refresh
"""

import curses
import json
import time
import tomllib
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from core.hardware.live_scope_status import poll_scope_status

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SEEVAR_ROOT   = Path(__file__).resolve().parent
DATA_DIR      = SEEVAR_ROOT / "data"
CATALOG_DIR   = SEEVAR_ROOT / "catalogs"
LOG_DIR       = SEEVAR_ROOT / "logs"

STATE_FILE       = DATA_DIR    / "system_state.json"
WEATHER_FILE     = DATA_DIR    / "weather_state.json"
PLAN_FILE        = DATA_DIR    / "tonights_plan.json"
VSX_FILE         = DATA_DIR    / "vsx_catalog.json"
CAMPAIGN_FILE    = CATALOG_DIR / "campaign_targets.json"
FED_FILE         = CATALOG_DIR / "federation_catalog.json"
CHARTS_DIR       = CATALOG_DIR / "reference_stars"
CONFIG_FILE      = SEEVAR_ROOT / "config.toml"
ENV_STATUS       = Path("/dev/shm/env_status.json")

LOG_FILES = [
    LOG_DIR / "orchestrator.log",
    LOG_DIR / "weather.log",
    LOG_DIR / "telescope.log",
    LOG_DIR / "dashboard.log",
]

REFRESH_S  = 5
LOG_LINES  = 10
VERSION    = "1.2.0"
WEATHER_STALE_SEC = 1800


# ---------------------------------------------------------------------------
# Data readers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict | list:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def read_orchestrator() -> dict:
    s = _read_json(STATE_FILE)
    if not isinstance(s, dict) or not s:
        return {"empty": True}
    return {
        "empty":     False,
        "state":     s.get("state", "UNKNOWN"),
        "sub":       s.get("sub", s.get("substate", "")),
        "msg":       s.get("msg", s.get("message", "")),
        "updated":   s.get("updated", s.get("updated_utc", "")),
        "done":      s.get("done_count", 0),
        "remaining": s.get("remaining_count", 0),
        "planned":   s.get("planned_count", 0),
    }


def read_weather() -> dict:
    w = _read_json(WEATHER_FILE)
    if not isinstance(w, dict) or not w:
        return {"empty": True}

    last_update = w.get("last_update", None)
    age = int(time.time() - last_update) if isinstance(last_update, (int, float)) else None
    stale = age is None or age > WEATHER_STALE_SEC

    return {
        "empty":        False,
        "status":       w.get("status", "UNKNOWN"),
        "current_status": w.get("current_status", w.get("status", "UNKNOWN")),
        "imaging_go":   None if stale else w.get("imaging_go", None),
        "win_start":    w.get("imaging_window_start", None),
        "win_end":      w.get("imaging_window_end", None),
        "clear_hours":  w.get("clear_hours", 0),
        "abort_hours":  w.get("abort_hours", 0),
        "clouds_pct":   w.get("clouds_pct", 0),
        "humidity_pct": w.get("humidity_pct", 0),
        "knmi_oktas":   w.get("knmi_oktas", None),
        "dark_start":   w.get("dark_start", "?"),
        "dark_end":     w.get("dark_end", "?"),
        "last_update":  last_update,
        "age_s":        age,
        "stale":        stale,
    }


def read_plan() -> dict:
    p = _read_json(PLAN_FILE)
    targets = p if isinstance(p, list) else p.get("targets", [])
    if not targets:
        return {"empty": True, "total": 0, "next": "—"}
    return {
        "empty": False,
        "total": len(targets),
        "next":  targets[0].get("name", "—"),
    }


def read_catalog_stats() -> dict:
    c = _read_json(CAMPAIGN_FILE)
    campaign_list  = c if isinstance(c, list) else c.get("targets", [])
    campaign_total = len(campaign_list)

    v = _read_json(VSX_FILE)
    vsx_stars    = v.get("stars", {}) if isinstance(v, dict) else {}
    vsx_enriched = len(vsx_stars)

    charts = len(list(CHARTS_DIR.glob("*.json"))) if CHARTS_DIR.exists() else 0

    f = _read_json(FED_FILE)
    fed_list  = f if isinstance(f, list) else f.get("data", f.get("targets", []))
    fed_total = len(fed_list)

    p = _read_json(PLAN_FILE)
    plan_list = p if isinstance(p, list) else p.get("targets", [])
    tonight   = len(plan_list)
    deferred  = max(0, fed_total - tonight)

    return {
        "campaign":  campaign_total,
        "vsx":       vsx_enriched,
        "charts":    charts,
        "fed":       fed_total,
        "tonight":   tonight,
        "deferred":  deferred,
    }


def read_fleet() -> list:
    """
    Read [[seestars]] from config.toml and merge with live telemetry
    from /dev/shm/wilhelmina_state.json (keyed by name).
    Returns list of dicts — one per telescope, present or future.
    """
    fleet = []

    # Load config
    try:
        with open(CONFIG_FILE, "rb") as f:
            cfg = tomllib.load(f)
        seestars = cfg.get("seestars", [])
    except Exception:
        seestars = []

    # No telescope-specific shm telemetry here.
    # Live truth should come from generic fleet sources, not hardcoded scope files.
    live_by_name = {}

    for s in seestars:
        name   = s.get("name",  "Unknown")
        model  = s.get("model", "S30-Pro")
        ip     = s.get("ip",    "TBD")
        active = ip not in ("TBD", "", "10.0.0.1")

        t = live_by_name.get(name, {})
        fleet.append({
            "name":        name,
            "model":       model,
            "ip":          ip,
            "active":      active,
            "link":        t.get("link_status",  "OFFLINE" if not active else "WAITING"),
            "battery":     t.get("battery_pct"),
            "temp_c":      t.get("temp_c"),
            "tracking":    t.get("tracking",     False),
            "slewing":     t.get("slewing",      False),
            "level_angle": t.get("level_angle"),
            "level_ok":    t.get("level_ok",     True),
            "last_event":  t.get("last_event"),
            "event_counts": t.get("event_counts", {}),
        })

    # Add placeholder entries for known future scopes if not in config
    known_future = [
        {"name": "Anna",      "model": "S30-Pro", "ip": "TBD"},
        {"name": "Henrietta", "model": "S50",     "ip": "TBD"},
    ]
    existing_names = {s["name"] for s in fleet}
    for f in known_future:
        if f["name"] not in existing_names:
            fleet.append({
                "name":        f["name"],
                "model":       f["model"],
                "ip":          "TBD",
                "active":      False,
                "link":        "—",
                "battery":     None,
                "temp_c":      None,
                "tracking":    False,
                "slewing":     False,
                "level_angle": None,
                "level_ok":    True,
                "last_event":  None,
                "event_counts": {},
            })

    return fleet


def read_gps() -> dict:
    e = _read_json(ENV_STATUS) if ENV_STATUS.exists() else {}
    if not e:
        return {"empty": True}
    return {
        "empty":      False,
        "status":     e.get("gps_status", "NO-DATA"),
        "mode":       e.get("gps_mode"),
        "lat":        e.get("lat"),
        "lon":        e.get("lon"),
        "maidenhead": e.get("maidenhead", "—"),
    }


def read_log_tail(n: int) -> list:
    """Read last n lines across all log files, deduplicate consecutive repeats."""
    lines = deque(maxlen=n * len(LOG_FILES))
    for lf in LOG_FILES:
        if not lf.exists():
            continue
        try:
            with open(lf, "r") as f:
                for line in f:
                    line = line.rstrip()
                    if line:
                        lines.append((lf.stem, line))
        except OSError:
            continue

    # Deduplicate consecutive identical log lines
    raw = list(lines)[-n * 2:]
    deduped = []
    prev_line = None
    repeat_count = 0
    for source, line in raw:
        # Strip timestamp prefix for comparison (first 25 chars)
        core = line[25:] if len(line) > 25 else line
        if core == prev_line:
            repeat_count += 1
        else:
            if repeat_count > 0:
                # Append repeat note to previous entry
                if deduped:
                    s, l = deduped[-1]
                    deduped[-1] = (s, f"{l}  [×{repeat_count + 1}]")
            repeat_count = 0
            prev_line = core
            deduped.append((source, line))

    # Filter pure Flask startup noise
    filtered = [(s, l) for s, l in deduped
                if not any(noise in l for noise in [
                    "Serving Flask app",
                    "Debug mode:",
                    "Running on http",
                    " * Restarting",
                ])]

    return filtered[-n:]


# ---------------------------------------------------------------------------
# Colour pairs
# ---------------------------------------------------------------------------
C_TITLE  = 1
C_GOOD   = 2
C_WARN   = 3
C_ABORT  = 4
C_DIM    = 5
C_BORDER = 6
C_CYAN   = 7


def init_colours():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(C_TITLE,  curses.COLOR_CYAN,    -1)
    curses.init_pair(C_GOOD,   curses.COLOR_GREEN,   -1)
    curses.init_pair(C_WARN,   curses.COLOR_YELLOW,  -1)
    curses.init_pair(C_ABORT,  curses.COLOR_RED,     -1)
    curses.init_pair(C_DIM,    curses.COLOR_WHITE,   -1)
    curses.init_pair(C_BORDER, curses.COLOR_BLUE,    -1)
    curses.init_pair(C_CYAN,   curses.COLOR_CYAN,    -1)


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def safe_addstr(win, y, x, text, attr=0):
    max_y, max_x = win.getmaxyx()
    if y < 0 or y >= max_y or x < 0 or x >= max_x:
        return
    max_len = max_x - x - 1
    if max_len <= 0:
        return
    try:
        win.addstr(y, x, str(text)[:max_len], attr)
    except curses.error:
        pass


def draw_border(win, title: str):
    try:
        win.box()
    except curses.error:
        pass
    safe_addstr(win, 0, 2, f" {title} ",
                curses.color_pair(C_TITLE) | curses.A_BOLD)


def waiting(win, row: int = 1):
    safe_addstr(win, row, 2, "waiting for data...",
                curses.color_pair(C_DIM) | curses.A_DIM)


def state_colour(state: str) -> int:
    s = state.upper()
    if s == "FLIGHT":     return curses.color_pair(C_GOOD)  | curses.A_BOLD
    if s == "PREFLIGHT":  return curses.color_pair(C_WARN)  | curses.A_BOLD
    if s == "POSTFLIGHT": return curses.color_pair(C_WARN)
    if s == "PARKED":     return curses.color_pair(C_ABORT) | curses.A_BOLD
    return curses.color_pair(C_DIM)


def weather_colour(status: str, imaging_go) -> int:
    if imaging_go is False:
        return curses.color_pair(C_ABORT) | curses.A_BOLD
    s = status.upper()
    if s == "CLEAR":                     return curses.color_pair(C_GOOD) | curses.A_BOLD
    if s in ("CLOUDY", "HAZY", "HUMID"): return curses.color_pair(C_WARN)
    return curses.color_pair(C_DIM)


def log_colour(source: str) -> int:
    if "orchestrator" in source: return curses.color_pair(C_GOOD)
    if "weather"      in source: return curses.color_pair(C_WARN)
    if "telescope"    in source: return curses.color_pair(C_CYAN)
    return curses.color_pair(C_DIM)


# ---------------------------------------------------------------------------
# Panel drawers
# ---------------------------------------------------------------------------

def draw_header(stdscr, cols: int, gps: dict):
    now   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    title = "seetop — SeeVar Observatory"
    safe_addstr(stdscr, 0, 0, "─" * cols, curses.color_pair(C_BORDER))
    safe_addstr(stdscr, 0, 2, f" {title} ",
                curses.color_pair(C_TITLE) | curses.A_BOLD)

    # GPS in header
    if not gps.get("empty"):
        status = gps["status"]
        locked = any(s in status for s in ("3D", "FIX", "LOCK", "FIXED"))
        gps_attr = curses.color_pair(C_GOOD) if locked else curses.color_pair(C_WARN)
        mh   = gps.get("maidenhead", "—")
        lat  = f"{gps['lat']:.4f}" if gps.get("lat") else "—"
        lon  = f"{gps['lon']:.4f}" if gps.get("lon") else "—"
        mode = gps.get("mode")
        mode_str = f"{mode}D" if mode in (2, 3) else status
        gps_str = f" GPS:{mh} {mode_str} ({lat},{lon}) "
        safe_addstr(stdscr, 0, len(title) + 5, gps_str, gps_attr)

    safe_addstr(stdscr, 0, cols - len(now) - 3, f" {now} ",
                curses.color_pair(C_DIM))


def draw_orchestrator(win, data: dict):
    draw_border(win, "Orchestrator")
    if data.get("empty"):
        waiting(win)
        return
    state = data["state"]
    safe_addstr(win, 1, 2,  "State  : ", curses.color_pair(C_DIM))
    safe_addstr(win, 1, 11, f"{state:<12}", state_colour(state))
    if data["sub"]:
        safe_addstr(win, 1, 24, f"({data['sub']})", curses.color_pair(C_DIM))
    safe_addstr(win, 2, 2,  "Progress:", curses.color_pair(C_DIM))
    safe_addstr(win, 2, 11, f"{data['done']} done / {data['remaining']} left / {data['planned']} planned", curses.color_pair(C_DIM))
    safe_addstr(win, 3, 2,  "Message: ", curses.color_pair(C_DIM))
    safe_addstr(win, 3, 11, data["msg"],  curses.color_pair(C_DIM))


def draw_weather(win, data: dict):
    draw_border(win, "Weather")
    if data.get("empty"):
        waiting(win)
        return

    status     = data["status"]
    current_status = data.get("current_status", status)
    imaging_go = data["imaging_go"]
    go_str  = "GO  ✓" if imaging_go else "NO-GO ✗" if imaging_go is False else "?"
    go_attr = (curses.color_pair(C_GOOD)  | curses.A_BOLD) if imaging_go \
         else (curses.color_pair(C_ABORT) | curses.A_BOLD) if imaging_go is False \
         else curses.color_pair(C_DIM)

    stale = data.get("stale", False)
    shown_status = f"STALE {status}" if stale else status

    safe_addstr(win, 1, 2,  "Tonight: ", curses.color_pair(C_DIM))
    safe_addstr(
        win, 1, 11, f"{shown_status:<16}",
        curses.color_pair(C_WARN) | curses.A_BOLD if stale else weather_colour(status, imaging_go)
    )
    safe_addstr(win, 1, 29, "Now: ", curses.color_pair(C_DIM))
    safe_addstr(win, 1, 34, f"{current_status:<10}", curses.color_pair(C_DIM))
    safe_addstr(win, 1, 46, "Imaging: ", curses.color_pair(C_DIM))
    safe_addstr(win, 1, 55, go_str, go_attr)
    safe_addstr(win, 2, 2,  "Dark   : ", curses.color_pair(C_DIM))
    safe_addstr(win, 2, 11, f"{data['dark_start']} -> {data['dark_end']}",
                curses.color_pair(C_DIM))

    if data["win_start"] and data["win_end"]:
        safe_addstr(win, 3, 2,  "Window : ", curses.color_pair(C_DIM))
        safe_addstr(win, 3, 11,
                    f"{data['win_start']} -> {data['win_end']}  "
                    f"({data['clear_hours']}h clear / {data['abort_hours']}h abort)",
                    curses.color_pair(C_GOOD))
    else:
        safe_addstr(win, 3, 2, "Window : no clear window tonight",
                    curses.color_pair(C_ABORT))

    oktas = f"{data['knmi_oktas']:.0f}" if data["knmi_oktas"] is not None else "?"
    safe_addstr(win, 4, 2,
                f"Clouds : {data['clouds_pct']}%  "
                f"Humidity: {data['humidity_pct']}%  "
                f"KNMI: {oktas}/9 oktas",
                curses.color_pair(C_DIM) | curses.A_DIM)

    if data["age_s"] is not None:
        age = int(data["age_s"])
        attr = curses.color_pair(C_WARN) | curses.A_BOLD if stale else curses.color_pair(C_DIM) | curses.A_DIM
        safe_addstr(win, 5, 2, f"Updated: {age}s ago", attr)


def draw_fleet(win, fleet: list):
    draw_border(win, "Fleet")
    row = 1
    for scope in fleet:
        name   = scope["name"]
        model  = scope["model"]
        link   = scope["link"]
        op     = scope.get("op_state", link)
        active = scope["active"]

        # Name + model
        name_attr = curses.color_pair(C_GOOD) | curses.A_BOLD if active \
                    else curses.color_pair(C_DIM) | curses.A_DIM
        safe_addstr(win, row, 2, f"{name:<12}", name_attr)
        safe_addstr(win, row, 14, f"{model:<10}", curses.color_pair(C_DIM) | curses.A_DIM)

        if not active:
            safe_addstr(win, row, 25, "— pending arrival —",
                        curses.color_pair(C_DIM) | curses.A_DIM)
            row += 2
            continue

        # Link status
        if link == "ONLINE":
            link_attr = curses.color_pair(C_GOOD)
        elif link == "CONNECTING":
            link_attr = curses.color_pair(C_WARN)
        else:
            link_attr = curses.color_pair(C_ABORT)
        safe_addstr(win, row, 25, f"{link:<12}", link_attr)

        # Battery
        batt = scope["battery"]
        if batt is not None:
            batt_attr = curses.color_pair(C_GOOD)  if batt > 30 \
                   else curses.color_pair(C_WARN)  if batt > 15 \
                   else curses.color_pair(C_ABORT) | curses.A_BOLD
            safe_addstr(win, row, 38, f"BAT:{batt:>3}%", batt_attr)
        else:
            safe_addstr(win, row, 38, "BAT: —  ", curses.color_pair(C_DIM) | curses.A_DIM)

        # Temperature
        temp = scope["temp_c"]
        if temp is not None:
            safe_addstr(win, row, 47, f"TMP:{temp:>5.1f}°C",
                        curses.color_pair(C_DIM))
        else:
            safe_addstr(win, row, 47, "TMP:    —  ",
                        curses.color_pair(C_DIM) | curses.A_DIM)

        row += 1

        # Mount state row
        tracking = scope["tracking"]
        slewing  = scope["slewing"]
        angle    = scope["level_angle"]
        level_ok = scope["level_ok"]

        if slewing:
            mount_str  = "SLEWING"
            mount_attr = curses.color_pair(C_WARN) | curses.A_BOLD
        elif tracking:
            mount_str  = "TRACKING"
            mount_attr = curses.color_pair(C_GOOD) | curses.A_BOLD
        else:
            mount_str  = "IDLE"
            mount_attr = curses.color_pair(C_DIM)

        safe_addstr(win, row, 4, f"Mount: ", curses.color_pair(C_DIM) | curses.A_DIM)
        safe_addstr(win, row, 11, f"{mount_str:<10}", mount_attr)

        if angle is not None:
            level_attr = curses.color_pair(C_GOOD) if level_ok \
                         else curses.color_pair(C_WARN) | curses.A_BOLD
            safe_addstr(win, row, 22, f"Level: {angle:.2f}°", level_attr)

        # Last event
        last_ev = scope.get("last_event")
        if last_ev:
            safe_addstr(win, row, 38, f"Last: {last_ev}",
                        curses.color_pair(C_DIM) | curses.A_DIM)

        row += 2


def draw_catalog(win, data: dict):
    draw_border(win, "Catalog")

    def stat_row(row, label, val, total=None, warn_zero=False):
        safe_addstr(win, row, 2, f"{label:<20}", curses.color_pair(C_DIM))
        if total is not None and total > 0:
            pct  = int(val / total * 100)
            attr = curses.color_pair(C_GOOD)  if pct >= 80 \
                   else curses.color_pair(C_WARN)  if pct >= 40 \
                   else curses.color_pair(C_ABORT)
            safe_addstr(win, row, 22, f"{val:>4} / {total:<4} ({pct:>3}%)", attr)
        else:
            attr = (curses.color_pair(C_ABORT) if warn_zero and val == 0
                    else curses.color_pair(C_GOOD) if val > 0
                    else curses.color_pair(C_DIM))
            safe_addstr(win, row, 22, str(val), attr)

    stat_row(1, "Campaign targets",   data["campaign"])
    stat_row(2, "VSX enriched",       data["vsx"],     data["campaign"])
    stat_row(3, "Comp charts",        data["charts"],  data["campaign"])
    stat_row(4, "Federation catalog", data["fed"])
    stat_row(5, "Tonight's plan",     data["tonight"], warn_zero=True)
    stat_row(6, "Cadence deferred",   data["deferred"])


def draw_plan(win, data: dict):
    draw_border(win, "Tonight's Plan")
    if data.get("empty") or data["total"] == 0:
        waiting(win)
        return
    safe_addstr(win, 1, 2,  "Targets: ", curses.color_pair(C_DIM))
    safe_addstr(win, 1, 11, str(data["total"]),
                curses.color_pair(C_GOOD) | curses.A_BOLD)
    safe_addstr(win, 2, 2,  "Next   : ", curses.color_pair(C_DIM))
    safe_addstr(win, 2, 11, data["next"],
                curses.color_pair(C_WARN) | curses.A_BOLD)


def draw_log_tail(win, lines: list):
    draw_border(win, "Log Tail — orchestrator / weather / telescope / dashboard")
    if not lines:
        waiting(win)
        return
    max_y, _ = win.getmaxyx()
    row = 1
    for source, line in lines:
        if row >= max_y - 1:
            break
        tag = f"[{source[:4]}] "
        safe_addstr(win, row, 2, tag, log_colour(source))
        safe_addstr(win, row, 2 + len(tag), line, curses.color_pair(C_DIM))
        row += 1


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
ORCH_H   = 4
WX_H     = 7
FLEET_H  = 10   # 2 rows per scope (name+telemetry, mount+event) + spacing
CAT_H    = 8
PLAN_H   = 4
TOP_H    = max(ORCH_H + WX_H, FLEET_H, CAT_H + PLAN_H)
LOG_TOP  = 1 + TOP_H


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main(stdscr):
    curses.curs_set(0)
    curses.noecho()
    stdscr.nodelay(True)
    stdscr.timeout(1000)
    init_colours()

    last_refresh = 0.0
    last_rows = last_cols = 0
    wins = {}

    def make_wins(rows, cols):
        left_w  = cols // 3
        mid_w   = cols // 3
        right_w = cols - left_w - mid_w
        log_h   = max(4, rows - LOG_TOP - 1)
        return {
            "orch":  curses.newwin(ORCH_H,  left_w,  1,               0),
            "wx":    curses.newwin(WX_H,    left_w,  1 + ORCH_H,      0),
            "fleet": curses.newwin(FLEET_H, mid_w,   1,               left_w),
            "cat":   curses.newwin(CAT_H,   right_w, 1,               left_w + mid_w),
            "plan":  curses.newwin(PLAN_H,  right_w, 1 + CAT_H,       left_w + mid_w),
            "log":   curses.newwin(log_h,   cols,    LOG_TOP,          0),
        }

    while True:
        key = stdscr.getch()
        if key in (ord("q"), ord("Q")):
            break

        now = time.monotonic()
        if now - last_refresh < REFRESH_S:
            continue
        last_refresh = now

        rows, cols = stdscr.getmaxyx()

        if rows < 28 or cols < 100:
            stdscr.erase()
            safe_addstr(stdscr, 0, 0,
                        f"Terminal too small ({cols}x{rows}) — need 100x28 minimum.",
                        curses.A_BOLD)
            stdscr.refresh()
            continue

        if rows != last_rows or cols != last_cols or not wins:
            wins = make_wins(rows, cols)
            last_rows, last_cols = rows, cols

        # Fetch data
        orch    = read_orchestrator()
        weather = read_weather()
        fleet   = read_fleet()
        catalog = read_catalog_stats()
        plan    = read_plan()
        gps     = read_gps()
        logs    = read_log_tail(LOG_LINES)

        # Clear all surfaces
        stdscr.erase()
        for w in wins.values():
            try:
                w.erase()
            except curses.error:
                pass

        # Draw
        draw_header(stdscr, cols, gps)

        footer = f" [q] quit  |  refresh: {REFRESH_S}s  |  seetop v{VERSION} "
        safe_addstr(stdscr, rows - 1, 0, "─" * cols,
                    curses.color_pair(C_BORDER))
        safe_addstr(stdscr, rows - 1, 2, footer,
                    curses.color_pair(C_DIM) | curses.A_DIM)

        try:
            draw_orchestrator(wins["orch"],  orch)
            draw_weather(wins["wx"],         weather)
            draw_fleet(wins["fleet"],        fleet)
            draw_catalog(wins["cat"],        catalog)
            draw_plan(wins["plan"],          plan)
            draw_log_tail(wins["log"],       logs)
        except curses.error:
            pass

        stdscr.noutrefresh()
        for w in wins.values():
            try:
                w.noutrefresh()
            except curses.error:
                pass
        curses.doupdate()


def run():
    curses.wrapper(main)


if __name__ == "__main__":
    run()
