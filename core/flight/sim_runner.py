#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/flight/sim_runner.py
Version: 1.0.0
Objective: Execute a full realtime nightly simulation against tonights_plan.json
           with structured CLI output and live system_state.json for dashboard.
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

SIM_TS  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
SIM_LOG = LOG_DIR / f"sim_{SIM_TS}.log"

# ---------------------------------------------------------------------------
# Dual logging — terminal + structured sim log file
# ---------------------------------------------------------------------------
log = logging.getLogger("SeeVar.Sim")
log.setLevel(logging.DEBUG)

fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(fmt)

fh = logging.FileHandler(SIM_LOG, mode="w")
fh.setFormatter(fmt)

# SeeVar-sim-logging-v2: attach file handler to root logger only.
# Set propagate=False on sim logger to avoid double-writing the banner.
# All other loggers (Orchestrator, Ledger etc) propagate to root → file.
root = logging.getLogger()
root.setLevel(logging.DEBUG)
root.addHandler(fh)
root.addHandler(ch)

# Prevent sim logger from double-firing through root
log.propagate = False

# ---------------------------------------------------------------------------
# Parse optional --targets N argument (default: all)
# ---------------------------------------------------------------------------
MAX_TARGETS = None
for i, arg in enumerate(sys.argv[1:], 1):
    if arg == "--targets" and i < len(sys.argv):
        try:
            MAX_TARGETS = int(sys.argv[i + 1])
        except (IndexError, ValueError):
            pass

# ---------------------------------------------------------------------------
# Inject --simulate into argv for Orchestrator detection
# ---------------------------------------------------------------------------
if "--simulate" not in sys.argv:
    sys.argv.append("--simulate")

# ---------------------------------------------------------------------------
# Trim plan to MAX_TARGETS if requested
# ---------------------------------------------------------------------------
DATA_DIR  = PROJECT_ROOT / "data"
PLAN_FILE = DATA_DIR / "tonights_plan.json"

if MAX_TARGETS is not None:
    try:
        plan = json.loads(PLAN_FILE.read_text())
        changed = False

        if isinstance(plan, list) and len(plan) > MAX_TARGETS:
            plan = plan[:MAX_TARGETS]
            changed = True
        elif isinstance(plan, dict) and isinstance(plan.get("targets"), list) and len(plan["targets"]) > MAX_TARGETS:
            plan["targets"] = plan["targets"][:MAX_TARGETS]
            changed = True

        if changed:
            PLAN_FILE.write_text(json.dumps(plan, indent=2))
            log.info("📋 Plan trimmed to top %d targets for simulation.", MAX_TARGETS)
    except Exception as e:
        log.warning("Plan trim failed: %s — using full plan", e)

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
log.info("=" * 60)
log.info("  SeeVar Federation — Nightly Simulation")
log.info("  Started : %s UTC", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
log.info("  Log     : %s", SIM_LOG)
log.info("  Targets : %s", f"top {MAX_TARGETS}" if MAX_TARGETS else "all from tonights_plan.json")
log.info("  Dashboard reads: data/system_state.json (live during run)")
log.info("=" * 60)

# ---------------------------------------------------------------------------
# Run Orchestrator
# ---------------------------------------------------------------------------
from core.flight.orchestrator import Orchestrator

try:
    orch = Orchestrator()
    orch.run()
except KeyboardInterrupt:
    log.info("Simulation interrupted by user.")
except Exception as e:
    log.exception("Simulation error: %s", e)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
log.info("=" * 60)
log.info("  Simulation complete.")
log.info("  Log saved: %s", SIM_LOG)
log.info("  FITS frames: %s", DATA_DIR / "local_buffer")
log.info("=" * 60)
